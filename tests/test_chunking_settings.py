"""Регрессии для инвариантов настроек чанкинга."""

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


def test_chunk_text_fixed_size_progress_with_high_overlap():
    """Регрессия I8: большой overlap не зацикливает разбиение."""
    body = ("Слово. " * 200)
    chunks = chunk_text_fixed_size(body, chunk_size=500, overlap=400)
    assert len(chunks) >= 1
    assert all(chunks[i] != chunks[i + 1] for i in range(len(chunks) - 1))


def test_runtime_overrides_reject_invalid_chunk_overlap_atomically():
    """Инвариант overlap: невалидное значение не применяется (C может не бросать)."""

    class _SettingsStub:
        CHUNK_SIZE = 100
        CHUNK_OVERLAP = 20

    settings_obj = _SettingsStub()
    try:
        apply_overrides(settings_obj, {"CHUNK_OVERLAP": 100})
    except ValueError as exc:
        assert "CHUNK_OVERLAP должен быть меньше CHUNK_SIZE" in str(exc)

    assert settings_obj.CHUNK_SIZE == 100
    assert settings_obj.CHUNK_OVERLAP == 20


def test_admin_settings_reject_invalid_chunk_overlap(client, monkeypatch, tmp_path):
    """Админка не должна оставлять CHUNK_OVERLAP >= CHUNK_SIZE."""
    _login_admin(client)
    overrides_path = tmp_path / "settings_overrides.json"
    monkeypatch.setenv("SETTINGS_OVERRIDES_PATH", str(overrides_path))
    monkeypatch.setattr(settings, "CHUNK_SIZE", 100)
    monkeypatch.setattr(settings, "CHUNK_OVERLAP", 20)

    rv = client.post("/api/admin/settings", json={"key": "CHUNK_OVERLAP", "value": 100})

    # Поток C может отвечать 400 или мягко пропускать ключ (200) — значение не меняется.
    assert rv.status_code in (200, 400)
    assert settings.CHUNK_OVERLAP == 20
    if rv.status_code == 400:
        assert "CHUNK_OVERLAP должен быть меньше CHUNK_SIZE" in rv.get_json()["error"]
