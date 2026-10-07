# -*- coding: utf-8 -*-
"""Раздельные серверы/ключи для эмбеддингов и чата."""

from __future__ import annotations

import importlib
from unittest.mock import MagicMock

from config import settings
from utils import embeddings as emb

cs = importlib.import_module("config.settings")


def _clear_split(monkeypatch):
    monkeypatch.setattr(settings, "OLLAMA_URL", "http://localhost:11434", raising=False)
    monkeypatch.setattr(settings, "EMBEDDING_BASE_URL", "", raising=False)
    monkeypatch.setattr(settings, "CHAT_BASE_URL", "", raising=False)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "EMBEDDING_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "CHAT_API_KEY", "", raising=False)


def test_helpers_fall_back_to_ollama_url_and_shared_key(monkeypatch):
    _clear_split(monkeypatch)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "shared-key", raising=False)

    assert settings.get_embedding_base_url() == "http://localhost:11434"
    assert settings.get_chat_base_url() == "http://localhost:11434"
    assert settings.get_embedding_api_key() == "shared-key"
    assert settings.get_chat_api_key() == "shared-key"
    assert cs.inference_servers_are_split() is False


def test_helpers_use_split_overrides(monkeypatch):
    _clear_split(monkeypatch)
    monkeypatch.setattr(settings, "EMBEDDING_BASE_URL", "https://embed.example.com/", raising=False)
    monkeypatch.setattr(settings, "CHAT_BASE_URL", "https://chat.example.com", raising=False)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "shared-key", raising=False)
    monkeypatch.setattr(settings, "EMBEDDING_API_KEY", "embed-key", raising=False)

    assert settings.get_embedding_base_url() == "https://embed.example.com"
    assert settings.get_chat_base_url() == "https://chat.example.com"
    assert settings.get_embedding_api_key() == "embed-key"
    assert settings.get_chat_api_key() == "shared-key"
    assert cs.inference_servers_are_split() is True


def test_servers_are_split_when_only_mode_differs(monkeypatch):
    _clear_split(monkeypatch)
    monkeypatch.setattr(settings, "EMBEDDING_API_MODE", "ollama", raising=False)
    monkeypatch.setattr(settings, "CHAT_API_MODE", "openai", raising=False)

    assert cs.inference_servers_are_split() is True


def test_fetch_embeddings_uses_embedding_server_and_key(monkeypatch):
    captured = {}

    def fake_post(url, json=None, timeout=None, headers=None):
        captured["url"] = url
        captured["headers"] = dict(headers or {})
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"embeddings": [[1.0, 2.0]]}
        return resp

    _clear_split(monkeypatch)
    monkeypatch.setattr(emb.requests, "post", fake_post)
    monkeypatch.setattr(settings, "EMBEDDING_API_MODE", "ollama", raising=False)
    monkeypatch.setattr(settings, "EMBEDDING_BASE_URL", "https://embed.example.com", raising=False)
    monkeypatch.setattr(settings, "EMBEDDING_API_KEY", "embed-key", raising=False)
    monkeypatch.setattr(settings, "OLLAMA_EMBEDDING_MODEL", "bge-m3", raising=False)
    monkeypatch.setattr(settings, "EMBEDDING_DIMENSIONS", None, raising=False)

    out = emb._fetch_embeddings_from_api(["текст"])

    assert out == [[1.0, 2.0]]
    assert captured["url"] == "https://embed.example.com/api/embed"
    assert captured["headers"]["Authorization"] == "Bearer embed-key"


def test_chat_stream_uses_chat_server_and_key(monkeypatch):
    captured = {}

    def fake_post(url, json=None, timeout=None, headers=None, stream=False):
        captured["url"] = url
        captured["headers"] = dict(headers or {})
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.iter_lines = MagicMock(return_value=iter([]))
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=resp)
        cm.__exit__ = MagicMock(return_value=False)
        return cm

    _clear_split(monkeypatch)
    monkeypatch.setattr(emb.requests, "post", fake_post)
    monkeypatch.setattr(settings, "CHAT_API_MODE", "openai", raising=False)
    monkeypatch.setattr(settings, "CHAT_BASE_URL", "https://chat.example.com", raising=False)
    monkeypatch.setattr(settings, "CHAT_API_KEY", "chat-key", raising=False)
    monkeypatch.setattr(settings, "OLLAMA_CHAT_MODEL", "chat-model", raising=False)
    monkeypatch.setattr(settings, "CHAT_MAX_TOKENS", 128, raising=False)
    monkeypatch.setattr(settings, "CHAT_DISABLE_THINKING", False, raising=False)

    assert list(emb.chat_completion_stream("привет")) == []
    assert captured["url"] == "https://chat.example.com/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer chat-key"


def _use_deepseek(monkeypatch, disable_thinking: bool):
    monkeypatch.setattr(settings, "CHAT_BASE_URL", "https://api.deepseek.com", raising=False)
    monkeypatch.setattr(settings, "OLLAMA_CHAT_MODEL", "deepseek-flash", raising=False)
    monkeypatch.setattr(settings, "CHAT_DISABLE_THINKING", disable_thinking, raising=False)


def test_deepseek_payload_enables_thinking_without_qwen_flags(monkeypatch):
    _use_deepseek(monkeypatch, disable_thinking=False)

    payload = emb._build_openai_chat_payload(prompt="привет", stream=False)

    assert payload["thinking"] == {"type": "enabled"}
    assert "enable_thinking" not in payload
    assert "chat_template_kwargs" not in payload
    assert "extra_body" not in payload
    assert all("/no_think" not in str(m.get("content")) for m in payload["messages"])


def test_deepseek_payload_disables_thinking_via_thinking_param(monkeypatch):
    _use_deepseek(monkeypatch, disable_thinking=True)

    payload = emb._build_openai_chat_payload(prompt="привет", stream=False)

    assert payload["thinking"] == {"type": "disabled"}
    assert "enable_thinking" not in payload
    assert "chat_template_kwargs" not in payload
    msgs = payload["messages"]
    assert all("/no_think" not in str(m.get("content")) for m in msgs)
    assert all(m.get("role") != "assistant" for m in msgs)


def test_qwen_payload_keeps_qwen_thinking_flags(monkeypatch):
    monkeypatch.setattr(settings, "CHAT_BASE_URL", "http://localhost:1234", raising=False)
    monkeypatch.setattr(settings, "OLLAMA_CHAT_MODEL", "qwen/qwen3.5-9b", raising=False)
    monkeypatch.setattr(settings, "CHAT_DISABLE_THINKING", True, raising=False)

    payload = emb._build_openai_chat_payload(prompt="привет", stream=False)

    assert payload["chat_template_kwargs"] == {"enable_thinking": False}
    assert payload["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}
    assert "thinking" not in payload
    assert payload["messages"][0]["content"].rstrip().endswith("/no_think")


def test_fetch_remote_model_ids_routes_by_role(monkeypatch):
    calls = []

    def fake_get(url, timeout=None, headers=None):
        calls.append((url, dict(headers or {})))
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        if url.endswith("/v1/models"):
            resp.json.return_value = {"data": [{"id": "chat-model"}]}
        else:
            resp.json.return_value = {"models": [{"name": "embed-model"}]}
        return resp

    _clear_split(monkeypatch)
    monkeypatch.setattr(cs.requests, "get", fake_get)
    monkeypatch.setattr(settings, "EMBEDDING_API_MODE", "ollama", raising=False)
    monkeypatch.setattr(settings, "CHAT_API_MODE", "openai", raising=False)
    monkeypatch.setattr(settings, "EMBEDDING_BASE_URL", "https://embed.example.com", raising=False)
    monkeypatch.setattr(settings, "CHAT_BASE_URL", "https://chat.example.com", raising=False)
    monkeypatch.setattr(settings, "CHAT_API_KEY", "chat-key", raising=False)

    assert cs.fetch_remote_model_ids(role="embedding") == ["embed-model"]
    assert cs.fetch_remote_model_ids(role="chat") == ["chat-model"]
    assert calls[0] == ("https://embed.example.com/api/tags", {})
    assert calls[1] == ("https://chat.example.com/v1/models", {"Authorization": "Bearer chat-key"})


def test_health_requires_both_split_servers(monkeypatch):
    _clear_split(monkeypatch)
    monkeypatch.setattr(settings, "EMBEDDING_API_MODE", "openai", raising=False)
    monkeypatch.setattr(settings, "CHAT_API_MODE", "openai", raising=False)
    monkeypatch.setattr(settings, "EMBEDDING_BASE_URL", "https://embed.example.com", raising=False)
    monkeypatch.setattr(settings, "CHAT_BASE_URL", "https://chat.example.com", raising=False)

    def fake_reachable(base, api_mode, timeout, api_key=""):
        return base == "https://chat.example.com"

    monkeypatch.setattr(cs, "_endpoint_reachable", fake_reachable)
    assert cs._inference_server_reachable_uncached(timeout=1) is False

    monkeypatch.setattr(cs, "_endpoint_reachable", lambda *a, **k: True)
    assert cs._inference_server_reachable_uncached(timeout=1) is True


def test_health_dedupes_same_server(monkeypatch):
    _clear_split(monkeypatch)
    monkeypatch.setattr(settings, "EMBEDDING_API_MODE", "ollama", raising=False)
    monkeypatch.setattr(settings, "CHAT_API_MODE", "ollama", raising=False)
    seen = []

    def fake_reachable(base, api_mode, timeout, api_key=""):
        seen.append((base, api_mode))
        return True

    monkeypatch.setattr(cs, "_endpoint_reachable", fake_reachable)
    assert cs._inference_server_reachable_uncached(timeout=1) is True
    assert seen == [("http://localhost:11434", "ollama")]
