#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import io
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.datastructures import FileStorage

from core.chat_attachments import (
    AttachmentBundle,
    ChatAttachment,
    ChatAttachmentError,
    classify_attachment,
    format_text_excerpts,
    load_attachment,
    load_attachments,
    save_uploaded_file,
)
from core.rag import enrich_query_from_attachments
from web_app import app, _normalize_chat_query


def test_classify_attachment_image_and_text():
    assert classify_attachment("screen.png") == "image"
    assert classify_attachment("log.txt") == "text"


def test_normalize_chat_query_allows_empty_message_with_attachments():
    with app.app_context():
        query, err = _normalize_chat_query({"message": "", "attachment_ids": ["abc"]})
    assert err is None
    assert query["query"] == ""
    assert query["attachment_ids"] == ["abc"]


def test_normalize_chat_query_rejects_empty_without_attachments():
    with app.app_context():
        query, err = _normalize_chat_query({"message": ""})
    assert query is None
    assert err is not None


def test_normalize_chat_query_short_text_with_attachment():
    with app.app_context():
        query, err = _normalize_chat_query({"message": "ok", "attachment_ids": ["x"]})
    assert err is None
    assert query["query"] == "ok"


def test_load_attachment_prefers_data_file_over_meta_json(tmp_path, monkeypatch):
    """glob(id.*) не должен отдавать sidecar .meta.json вместо изображения."""
    monkeypatch.setattr("core.chat_attachments.settings.CHAT_ATTACHMENTS_DIR", str(tmp_path))
    aid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    (tmp_path / f"{aid}.meta.json").write_text(
        '{"filename": "screen.png", "mime": "image/png"}',
        encoding="utf-8",
    )
    (tmp_path / f"{aid}.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    item = load_attachment(aid)
    assert item is not None
    assert item.path.suffix == ".png"
    assert item.kind == "image"


def test_save_and_load_text_attachment(tmp_path, monkeypatch):
    monkeypatch.setattr("core.chat_attachments.settings.CHAT_ATTACHMENTS_DIR", str(tmp_path))
    monkeypatch.setattr("core.chat_attachments.settings.CHAT_ATTACHMENT_MAX_BYTES", 1_000_000)
    monkeypatch.setattr(
        "core.chat_attachments.settings.CHAT_ATTACHMENT_ALLOWED_EXTENSIONS",
        ["txt", "log", "png"],
    )

    storage = io.BytesIO(b"error code 42\nline two")
    file = FileStorage(stream=storage, filename="error.log", content_type="text/plain")

    saved = save_uploaded_file(file)
    assert saved.kind == "text"
    assert "error code 42" in (saved.text_content or "")

    bundle = load_attachments([saved.id])
    assert len(bundle.items) == 1
    assert bundle.items[0].text_content


def test_enrich_query_from_text_attachment_only(tmp_path, monkeypatch):
    monkeypatch.setattr("core.chat_attachments.settings.CHAT_ATTACHMENTS_DIR", str(tmp_path))
    monkeypatch.setattr(
        "core.chat_attachments.settings.CHAT_ATTACHMENT_ALLOWED_EXTENSIONS",
        ["txt", "log"],
    )
    path = tmp_path / "sample.txt"
    path.write_text("ORA-12345 timeout", encoding="utf-8")
    item = ChatAttachment(
        id="11111111-1111-1111-1111-111111111111",
        filename="sample.txt",
        mime="text/plain",
        kind="text",
        path=path,
        size=path.stat().st_size,
        text_content="ORA-12345 timeout",
    )
    bundle = AttachmentBundle(items=[item])

    with patch("core.rag.chat_completion_messages") as mock_mm:
        result = enrich_query_from_attachments("что за ошибка?", bundle)
        mock_mm.assert_not_called()

    assert "ORA-12345" in result["effective_query"]
    assert result["attachment_count"] == 1


@patch("web_app.initialize_database")
@patch("web_app.inference_server_reachable")
def test_api_chat_with_text_attachment(mock_reachable, mock_init, client, tmp_path, monkeypatch):
    from core.rag import RAGResult

    monkeypatch.setattr("core.chat_attachments.settings.CHAT_ATTACHMENTS_DIR", str(tmp_path / "att"))
    monkeypatch.setattr(
        "core.chat_attachments.settings.CHAT_ATTACHMENT_ALLOWED_EXTENSIONS",
        ["txt", "log"],
    )

    upload = client.post(
        "/api/chat/attachments",
        data={"files": (io.BytesIO(b"module X failed"), "fail.log")},
        content_type="multipart/form-data",
    )
    assert upload.status_code == 201
    att_id = upload.get_json()["attachments"][0]["id"]

    mock_reachable.return_value = True
    rag = MagicMock()
    mock_init.return_value = (MagicMock(), rag)
    rag.query.return_value = RAGResult(answer="Ответ", citations=[], sources=[])

    rv = client.post(
        "/api/chat",
        json={"message": "помоги", "attachment_ids": [att_id]},
    )
    assert rv.status_code == 200
    rag.query.assert_called_once()
    assert rag.query.call_args.kwargs.get("attachments") is not None


def test_save_ignores_client_mime_uses_extension(tmp_path, monkeypatch):
    """A3: клиентский text/html для .txt не влияет на сохранённый MIME."""
    monkeypatch.setattr("core.chat_attachments.settings.CHAT_ATTACHMENTS_DIR", str(tmp_path))
    monkeypatch.setattr(
        "core.chat_attachments.settings.CHAT_ATTACHMENT_ALLOWED_EXTENSIONS",
        ["txt", "png"],
    )
    monkeypatch.setattr("core.chat_attachments.settings.CHAT_ATTACHMENT_MAX_BYTES", 1_000_000)
    # Сброс таймера ленивой очистки.
    import core.chat_attachments as ca

    monkeypatch.setattr(ca, "_last_cleanup_monotonic", 0.0)

    storage = io.BytesIO(b"<html>hi</html>")
    file = FileStorage(stream=storage, filename="a.txt", content_type="text/html")
    saved = save_uploaded_file(file)
    assert saved.mime.startswith("text/plain")
    assert "html" not in saved.mime


def test_get_attachment_serves_text_plain_despite_html_upload(client, tmp_path, monkeypatch):
    """A3/приёмка: a.txt с Content-Type text/html отдаётся как text/plain."""
    monkeypatch.setattr("core.chat_attachments.settings.CHAT_ATTACHMENTS_DIR", str(tmp_path / "att"))
    monkeypatch.setattr(
        "core.chat_attachments.settings.CHAT_ATTACHMENT_ALLOWED_EXTENSIONS",
        ["txt", "png", "log"],
    )

    upload = client.post(
        "/api/chat/attachments",
        data={"files": (io.BytesIO(b"<script>x</script>"), "a.txt")},
        content_type="multipart/form-data",
        headers={"Content-Type": "multipart/form-data"},
    )
    # werkzeug test client: передаём content_type файла через кортеж? File via multipart.
    assert upload.status_code == 201
    att_id = upload.get_json()["attachments"][0]["id"]
    assert upload.get_json()["attachments"][0]["mime"].startswith("text/plain")

    rv = client.get(f"/api/chat/attachments/{att_id}")
    assert rv.status_code == 200
    assert "text/plain" in (rv.mimetype or "")
    assert rv.headers.get("X-Content-Type-Options") == "nosniff"
    cd = rv.headers.get("Content-Disposition", "")
    assert "attachment" in cd.lower()


def test_get_image_attachment_inline_disposition(client, tmp_path, monkeypatch):
    """A3: изображения отдаются inline."""
    monkeypatch.setattr("core.chat_attachments.settings.CHAT_ATTACHMENTS_DIR", str(tmp_path / "att"))
    monkeypatch.setattr(
        "core.chat_attachments.settings.CHAT_ATTACHMENT_ALLOWED_EXTENSIONS",
        ["png", "txt"],
    )
    upload = client.post(
        "/api/chat/attachments",
        data={"files": (io.BytesIO(b"\x89PNG\r\n\x1a\n"), "shot.png")},
        content_type="multipart/form-data",
    )
    assert upload.status_code == 201
    att_id = upload.get_json()["attachments"][0]["id"]
    rv = client.get(f"/api/chat/attachments/{att_id}")
    assert rv.status_code == 200
    assert rv.mimetype == "image/png"
    cd = rv.headers.get("Content-Disposition", "")
    assert "inline" in cd.lower() or "attachment" not in cd.lower()


def test_cleanup_old_attachments_removes_stale(tmp_path, monkeypatch):
    """A5: cleanup_old_attachments удаляет файл и .meta.json."""
    import os
    import time

    from core.chat_attachments import cleanup_old_attachments

    monkeypatch.setattr("core.chat_attachments.settings.CHAT_ATTACHMENTS_DIR", str(tmp_path))
    aid = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    data = tmp_path / f"{aid}.txt"
    meta = tmp_path / f"{aid}.meta.json"
    data.write_text("old", encoding="utf-8")
    meta.write_text('{"filename": "old.txt"}', encoding="utf-8")
    old_mtime = time.time() - (80 * 3600)
    os.utime(data, (old_mtime, old_mtime))

    fresh = tmp_path / "cccccccc-cccc-cccc-cccc-cccccccccccc.txt"
    fresh.write_text("new", encoding="utf-8")

    removed = cleanup_old_attachments(72)
    assert removed == 1
    assert not data.exists()
    assert not meta.exists()
    assert fresh.exists()


def test_upload_rejects_too_many_files(client, tmp_path, monkeypatch):
    """A8: число файлов в одном запросе ограничено CHAT_ATTACHMENT_MAX_COUNT."""
    from werkzeug.datastructures import MultiDict

    monkeypatch.setattr("core.chat_attachments.settings.CHAT_ATTACHMENTS_DIR", str(tmp_path / "att"))
    monkeypatch.setattr(
        "core.chat_attachments.settings.CHAT_ATTACHMENT_ALLOWED_EXTENSIONS",
        ["txt"],
    )
    monkeypatch.setattr("core.chat_attachments.settings.CHAT_ATTACHMENT_MAX_COUNT", 2)
    monkeypatch.setattr("api.routes.chat_attachments.settings.CHAT_ATTACHMENT_MAX_COUNT", 2)

    data = MultiDict([
        ("files", (io.BytesIO(b"1"), "a.txt")),
        ("files", (io.BytesIO(b"2"), "b.txt")),
        ("files", (io.BytesIO(b"3"), "c.txt")),
    ])
    upload = client.post(
        "/api/chat/attachments",
        data=data,
        content_type="multipart/form-data",
    )
    assert upload.status_code == 400
    assert "Максимум" in upload.get_json()["error"]


def test_save_cyrillic_attachment_filename(tmp_path, monkeypatch):
    """A1: кириллическое имя вложения сохраняется."""
    monkeypatch.setattr("core.chat_attachments.settings.CHAT_ATTACHMENTS_DIR", str(tmp_path))
    monkeypatch.setattr(
        "core.chat_attachments.settings.CHAT_ATTACHMENT_ALLOWED_EXTENSIONS",
        ["png", "txt"],
    )
    file = FileStorage(
        stream=io.BytesIO(b"\x89PNG\r\n\x1a\n"),
        filename="Снимок экрана.png",
        content_type="image/png",
    )
    saved = save_uploaded_file(file)
    assert "Снимок" in saved.filename
    assert saved.filename.lower().endswith(".png")
