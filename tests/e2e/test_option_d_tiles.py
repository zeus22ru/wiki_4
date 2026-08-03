"""Option D browser smoke tests (Playwright). Skipped if playwright is unavailable."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("playwright")

from playwright.sync_api import sync_playwright

BASE_URL = os.environ.get("DEMO_BASE_URL", "http://127.0.0.1:5000").rstrip("/")
REPO = Path(__file__).resolve().parents[2]


def _app_reachable() -> bool:
    try:
        import urllib.request

        with urllib.request.urlopen(f"{BASE_URL}/", timeout=2) as resp:
            return 200 <= resp.status < 500
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _app_reachable(), reason=f"App not reachable at {BASE_URL}")


def test_option_d_empty_tiles_and_shell():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(f"{BASE_URL}/")
        page.wait_for_selector("#emptyTiles")
        assert page.locator("#emptyTiles").is_visible()
        assert page.locator(".main-shell").count() == 1
        assert page.locator(".sidebar-brand").count() == 1
        assert page.locator("#sourcesPanel").count() == 1
        assert page.locator("#sendButton", has_text="Отправить").count() == 1
        page.locator('[data-tile="question"]').click()
        assert page.locator("#messageInput").evaluate("el => document.activeElement === el")
        browser.close()
