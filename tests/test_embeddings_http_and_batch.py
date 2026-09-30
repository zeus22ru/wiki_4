"""Тесты HTTP-ошибок эмбеддингов/чата и контракта get_embeddings_batch."""

from unittest.mock import MagicMock, patch

import requests

from utils.embeddings import (
    ChatCompletionError,
    _fetch_embeddings_from_api,
    chat_completion_stream,
    get_embeddings_batch,
)


def test_http_error_message_uses_is_not_none():
    """Статус берётся через ``e.response is not None``, не через truthiness."""
    resp = MagicMock()
    resp.status_code = 500
    # response считается «falsy» при `if e.response`, но is not None — True
    resp.__bool__ = lambda self: False
    http_err = requests.exceptions.HTTPError("boom")
    http_err.response = resp

    mock_cm = MagicMock()
    mock_cm.__enter__.side_effect = http_err
    mock_cm.__exit__.return_value = False

    with patch("utils.embeddings.requests.post", return_value=mock_cm):
        with patch("utils.embeddings.settings") as mock_settings:
            mock_settings.OLLAMA_URL = "http://localhost:11434"
            mock_settings.CHAT_API_MODE = "ollama"
            mock_settings.OLLAMA_CHAT_MODEL = "x"
            mock_settings.CHAT_MAX_TOKENS = 100
            try:
                list(chat_completion_stream("hi"))
                raised = None
            except ChatCompletionError as e:
                raised = e
    assert raised is not None
    assert "HTTP 500" in str(raised)


def test_get_embeddings_batch_returns_empty_on_partial_failure(monkeypatch):
    monkeypatch.setattr("utils.embeddings.get_cached_embedding", lambda *a, **k: None)
    monkeypatch.setattr(
        "utils.embeddings._fetch_embeddings_from_api",
        lambda texts: [[0.1, 0.2]],
    )
    monkeypatch.setattr("utils.embeddings.cache_embedding", lambda *a, **k: True)
    assert get_embeddings_batch(["a", "b"]) == []


def test_embedding_dimensions_none_omits_field(monkeypatch):
    captured = {}

    def fake_post(url, json=None, timeout=None, headers=None):
        captured["payload"] = dict(json or {})
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"embeddings": [[0.1, 0.2, 0.3]]}
        return resp

    monkeypatch.setattr("utils.embeddings.requests.post", fake_post)
    monkeypatch.setattr(
        "utils.embeddings.settings",
        MagicMock(
            EMBEDDING_API_MODE="ollama",
            OLLAMA_URL="http://localhost:11434",
            OLLAMA_EMBEDDING_MODEL="bge",
            EMBEDDING_DIMENSIONS=None,
            OPENAI_API_KEY="",
        ),
    )
    out = _fetch_embeddings_from_api(["текст"])
    assert out == [[0.1, 0.2, 0.3]]
    assert "dimensions" not in captured["payload"]


def test_embedding_dimensions_sent_when_set(monkeypatch):
    captured = {}

    def fake_post(url, json=None, timeout=None, headers=None):
        captured["payload"] = dict(json or {})
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"embeddings": [[0.1]]}
        return resp

    monkeypatch.setattr("utils.embeddings.requests.post", fake_post)
    monkeypatch.setattr(
        "utils.embeddings.settings",
        MagicMock(
            EMBEDDING_API_MODE="ollama",
            OLLAMA_URL="http://localhost:11434",
            OLLAMA_EMBEDDING_MODEL="bge",
            EMBEDDING_DIMENSIONS=1024,
            OPENAI_API_KEY="",
        ),
    )
    _fetch_embeddings_from_api(["текст"])
    assert captured["payload"].get("dimensions") == 1024
