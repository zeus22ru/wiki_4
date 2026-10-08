#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Тесты загрузки ресурсов XWiki (ТЗ §22.3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.xwiki_assets import download_page_assets


class _FakeResponse:
    def __init__(self, url, status_code=200, headers=None, content=b"", text=None):
        self.url = url
        self.status_code = status_code
        self.headers = headers or {}
        self.content = content
        self.text = text if text is not None else content.decode("utf-8", "replace")


class _FakeSession:
    def __init__(self, routes):
        self.routes = routes
        self.requested = []

    def get(self, url, **kwargs):
        self.requested.append(url)
        for prefix, response in self.routes.items():
            if url.startswith(prefix):
                return response(url) if callable(response) else response
        return _FakeResponse(url, status_code=404)


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50


def test_download_relative_image_and_rewrite(tmp_path: Path) -> None:
    session = _FakeSession({
        "http://wiki.local/bin/download/": _FakeResponse(
            "http://wiki.local/bin/download/img.png", headers={"Content-Type": "image/png"}, content=PNG,
        ),
    })
    html = '<article><img src="/bin/download/img.png" alt="x"></article>'
    result = download_page_assets(
        session, "http://wiki.local/bin/view/1c/instr/Page", html, tmp_path / "assets",
    )
    assert result["status"] == "success"
    assert len(result["assets"]) == 1
    assert result["assets"][0]["sha256"]
    assert "bin/download/img.png" in result["html"]  # data-source-url сохранён
    assert (tmp_path / "assets" / result["assets"][0]["local_path"]).is_file()


def test_login_page_detected_as_error(tmp_path: Path) -> None:
    session = _FakeSession({
        "http://wiki.local/": _FakeResponse(
            "http://wiki.local/bin/login", headers={"Content-Type": "text/html"},
            content=b'<form><input name="j_username"></form>',
        ),
    })
    html = '<article><img src="/bin/download/x.png"></article>'
    result = download_page_assets(session, "http://wiki.local/bin/view/Page", html, tmp_path / "a")
    assert result["status"] == "partial"
    assert any(d["code"] == "asset_download_login" for d in result["diagnostics"])
    assert result["assets"] == []


def test_other_host_requires_allowlist(tmp_path: Path) -> None:
    session = _FakeSession({})
    html = '<article><img src="http://evil.example/x.png"></article>'
    result = download_page_assets(session, "http://wiki.local/bin/view/Page", html, tmp_path / "a")
    assert any(d["code"] == "asset_host_not_allowed" for d in result["diagnostics"])
    assert session.requested == []  # не ходим на чужой host


def test_allowed_host_downloads(tmp_path: Path) -> None:
    session = _FakeSession({
        "http://cdn.local/": _FakeResponse(
            "http://cdn.local/x.png", headers={"Content-Type": "image/png"}, content=PNG,
        ),
    })
    html = '<article><img src="http://cdn.local/x.png"></article>'
    result = download_page_assets(
        session, "http://wiki.local/bin/view/P", html, tmp_path / "a",
        allowed_hosts=["cdn.local"],
    )
    assert len(result["assets"]) == 1


def test_oversized_asset_skipped(tmp_path: Path) -> None:
    session = _FakeSession({
        "http://wiki.local/": _FakeResponse(
            "http://wiki.local/big.png", headers={"Content-Type": "image/png"}, content=b"0" * 1000,
        ),
    })
    html = '<article><img src="/big.png"></article>'
    result = download_page_assets(
        session, "http://wiki.local/view", html, tmp_path / "a", max_bytes=100,
    )
    assert any(d["code"] == "asset_too_large" for d in result["diagnostics"])
    assert result["status"] == "partial"


def test_same_image_two_places_single_file(tmp_path: Path) -> None:
    session = _FakeSession({
        "http://wiki.local/": _FakeResponse(
            "http://wiki.local/img.png", headers={"Content-Type": "image/png"}, content=PNG,
        ),
    })
    html = '<article><img src="/img.png"><img src="/img.png"></article>'
    result = download_page_assets(session, "http://wiki.local/view", html, tmp_path / "a")
    assert len(result["assets"]) == 1
    assert len(list((tmp_path / "a").glob("*.png"))) == 1


def test_disabled_returns_skipped(tmp_path: Path) -> None:
    session = _FakeSession({})
    result = download_page_assets(
        session, "http://wiki.local/view", "<img src='/x.png'>", tmp_path / "a", enabled=False,
    )
    assert result["status"] == "skipped"
    assert session.requested == []


def test_percent23_not_decoded(tmp_path: Path) -> None:
    session = _FakeSession({
        "http://wiki.local/bin/download/": _FakeResponse(
            "http://wiki.local/bin/download/a%23b.png",
            headers={"Content-Type": "image/png"}, content=PNG,
        ),
    })
    html = '<article><img src="/bin/download/a%23b.png"></article>'
    result = download_page_assets(session, "http://wiki.local/view/Page", html, tmp_path / "a")
    assert "%23" in session.requested[0]
    assert len(result["assets"]) == 1
