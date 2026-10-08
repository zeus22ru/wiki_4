#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Загрузка ресурсов страниц XWiki (ТЗ §10).

Страница и её ресурсы скачиваются через ту же авторизованную ``requests.Session``.
Скачиваются original attachment images и локальные изображения статьи; сетевые
ресурсы требуют явного allowlist. Сохраняются хэши и локальные ссылки, а также
sidecar-manifest без паролей, cookies и токенов. Только после успешной записи
ресурсов формируется новая версия экспорта.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

_LAZY_ATTRS = ("data-src", "data-original", "data-lazy-src", "data-image", "data-url")
_LOGIN_HINTS = ("j_username", "login", "форм", "авторизац")
_HTML_CONTENT_TYPES = ("text/html", "application/xhtml")

MAX_REDIRECTS = 3


def _resolved_content_type(response: Any) -> str:
    return (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()


def _looks_like_login(response: Any) -> bool:
    ctype = _resolved_content_type(response)
    if any(ctype.startswith(t) for t in _HTML_CONTENT_TYPES):
        body = (response.text or "")[:4000].lower()
        if "j_username" in body or "j_password" in body:
            return True
        final = (response.url or "").lower()
        if "/login" in final or "loginsubmit" in final:
            return True
    return False


def _host_allowed(url: str, page_host: str, allowed_hosts: List[str]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    if host == page_host:
        return True
    return host in {h.lower() for h in allowed_hosts}


def _normalize_url(raw: str, base_url: str) -> Optional[str]:
    """Разрешить URL относительно base без повторного декодирования (ТЗ §10.1)."""
    if not raw:
        return None
    candidate = raw.strip()
    if candidate.startswith("data:"):
        return candidate
    # Protocol-relative //host/path
    if candidate.startswith("//"):
        candidate = urlparse(base_url).scheme + ":" + candidate
    resolved = urljoin(base_url, candidate)
    # Не трогаем %23 (иначе имя страницы распадётся на fragment).
    parts = urlsplit(resolved)
    return urlunsplit(parts)


def _extract_visual_candidates(soup: BeautifulSoup, base_url: str) -> List[Tuple[str, str]]:
    """Вернуть список (url, kind) визуальных ресурсов до очистки HTML."""
    out: List[Tuple[str, str]] = []

    def add(node: Tag) -> None:
        for attr in ("src",) + _LAZY_ATTRS:
            value = node.get(attr)
            if value:
                resolved = _normalize_url(str(value), base_url)
                if resolved:
                    out.append((resolved, "img"))
                return
        srcset = node.get("srcset") or node.get("data-srcset")
        if srcset:
            first = str(srcset).split(",")[0].strip().split(" ")[0]
            resolved = _normalize_url(first, base_url)
            if resolved:
                out.append((resolved, "img"))

    for img in soup.find_all("img"):
        add(img)
    for source in soup.find_all("source"):
        add(source)
    return out


def download_page_assets(
    session: Any,
    page_url: str,
    article_html: str,
    asset_root: Path,
    *,
    page_host: Optional[str] = None,
    allowed_hosts: Optional[List[str]] = None,
    max_bytes: int = 50 * 1024 * 1024,
    timeout: float = 30.0,
    enabled: bool = True,
    download_attachments: bool = False,
) -> Dict[str, Any]:
    """Скачать ресурсы статьи и вернуть результат для sidecar-manifest.

    Возвращает словарь с ``html`` (переписанные локальные ссылки), ``assets``
    (список записей), ``diagnostics`` и ``status``.
    """
    soup = BeautifulSoup(article_html, "html.parser")
    base_url = str(soup.find("base").get("href")) if soup.find("base") else page_url
    page_host = (page_host or urlparse(page_url).hostname or "").lower()
    allowed_hosts = list(allowed_hosts or [])
    result: Dict[str, Any] = {"html": article_html, "assets": [], "diagnostics": [], "status": "success"}
    if not enabled:
        result["status"] = "skipped"
        result["diagnostics"].append({"code": "assets_download_disabled"})
        return result

    asset_root = Path(asset_root)
    asset_root.mkdir(parents=True, exist_ok=True)

    candidates = _extract_visual_candidates(soup, base_url)
    url_to_local: Dict[str, str] = {}
    hashed: Dict[str, str] = {}

    for url, kind in candidates:
        if url.startswith("data:"):
            continue
        if not _host_allowed(url, page_host, allowed_hosts):
            result["diagnostics"].append({"code": "asset_host_not_allowed", "url": url})
            result["status"] = "partial"
            continue
        if url in url_to_local:
            continue
        try:
            response = session.get(url, timeout=timeout, allow_redirects=True, stream=True)
        except Exception as exc:
            result["diagnostics"].append({"code": "asset_download_failed", "url": url, "error": str(exc)})
            result["status"] = "partial"
            continue

        if response.status_code in (401, 403):
            result["diagnostics"].append({"code": "asset_download_login", "url": url,
                                          "http_status": response.status_code})
            result["status"] = "partial"
            continue
        if response.status_code != 200:
            result["diagnostics"].append({"code": "asset_http_error", "url": url,
                                          "http_status": response.status_code})
            result["status"] = "partial"
            continue
        if _looks_like_login(response):
            result["diagnostics"].append({"code": "asset_download_login", "url": url})
            result["status"] = "partial"
            continue

        content_type = _resolved_content_type(response)
        content = response.content
        if len(content) > max_bytes:
            result["diagnostics"].append({"code": "asset_too_large", "url": url, "bytes": len(content)})
            result["status"] = "partial"
            continue
        if not content:
            result["diagnostics"].append({"code": "asset_decode_failed", "url": url})
            result["status"] = "partial"
            continue

        sha = hashlib.sha256(content).hexdigest()
        if sha in hashed:
            url_to_local[url] = hashed[sha]
            continue
        suffix = Path(urlparse(url).path).suffix or _suffix_from_type(content_type)
        local_name = f"{sha[:16]}{suffix}"
        local_path = asset_root / local_name
        if not local_path.exists():
            local_path.write_bytes(content)
        rel = local_path.name
        url_to_local[url] = rel
        hashed[sha] = rel
        result["assets"].append({
            "url": url,
            "local_path": rel,
            "sha256": sha,
            "content_type": content_type,
            "bytes": len(content),
            "final_url": response.url,
        })

    # Переписываем ссылки в HTML на локальные.
    if url_to_local:
        for img in soup.find_all(["img", "source"]):
            for attr in ("src",) + _LAZY_ATTRS:
                value = img.get(attr)
                if value:
                    resolved = _normalize_url(str(value), base_url)
                    if resolved and resolved in url_to_local:
                        img[attr] = url_to_local[resolved]
                        img["data-source-url"] = resolved
                    break
        result["html"] = str(soup)

    result["assets_root"] = str(asset_root.as_posix())
    return result


def write_asset_manifest(asset_root: Path, page_url: str, assets: List[Dict[str, Any]]) -> Path:
    """Записать sidecar-manifest ресурсов страницы (без секретов)."""
    manifest_path = Path(asset_root) / "assets_manifest.json"
    payload = {"page_url": page_url, "assets": assets}
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


def _suffix_from_type(content_type: str) -> str:
    mapping = {
        "image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif",
        "image/webp": ".webp", "image/svg+xml": ".svg", "image/bmp": ".bmp",
        "image/tiff": ".tiff",
    }
    return mapping.get(content_type, ".bin")
