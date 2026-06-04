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
