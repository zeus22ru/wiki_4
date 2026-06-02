"""Регрессии для инвариантов настроек чанкинга."""

from types import SimpleNamespace

import pytest
from werkzeug.security import generate_password_hash

from config import settings
from config.runtime_overrides import apply_overrides
from core.chunking import chunk_text_fixed_size


def _login_admin(client) -> None:
    from core.chat_history import get_chat_history

    get_chat_history().create_user(
        username="admin",
        email="admin@example.com",
        password_hash=generate_password_hash("password123"),
        role="admin",
    )
    rv = client.post("/api/auth/login", json={"identifier": "admin", "password": "password123"})
    assert rv.status_code == 200


@pytest.mark.parametrize("overlap", [100, 120])
def test_chunk_text_rejects_overlap_not_smaller_than_chunk_size(overlap):
    with pytest.raises(ValueError, match="CHUNK_OVERLAP должен быть меньше CHUNK_SIZE"):
        chunk_text_fixed_size("x" * 300, chunk_size=100, overlap=overlap)


def test_runtime_overrides_reject_invalid_chunk_overlap_atomically():
    settings_obj = SimpleNamespace(CHUNK_SIZE=100, CHUNK_OVERLAP=20)

    with pytest.raises(ValueError, match="CHUNK_OVERLAP должен быть меньше CHUNK_SIZE"):
        apply_overrides(settings_obj, {"CHUNK_OVERLAP": 100})

    assert settings_obj.CHUNK_SIZE == 100
    assert settings_obj.CHUNK_OVERLAP == 20


def test_admin_settings_reject_invalid_chunk_overlap(client, monkeypatch, tmp_path):
    _login_admin(client)
    overrides_path = tmp_path / "settings_overrides.json"
    monkeypatch.setenv("SETTINGS_OVERRIDES_PATH", str(overrides_path))
    monkeypatch.setattr(settings, "CHUNK_SIZE", 100)
    monkeypatch.setattr(settings, "CHUNK_OVERLAP", 20)

    rv = client.post("/api/admin/settings", json={"key": "CHUNK_OVERLAP", "value": 100})

    assert rv.status_code == 400
    assert "CHUNK_OVERLAP должен быть меньше CHUNK_SIZE" in rv.get_json()["error"]
    assert not overrides_path.exists()
    assert settings.CHUNK_OVERLAP == 20
