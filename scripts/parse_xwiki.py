#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Выгрузка страниц XWiki в читаемую структуру файлов для дальнейшей индексации.

По умолчанию сохраняет только пользовательские страницы, пропуская служебные
пространства XWiki. Закрытые пространства требуют логина XWiki.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import re
import shutil
import sys
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qsl, quote, unquote_plus, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup


DEFAULT_BASE_URL = "http://wiki.bochkari.local"
DEFAULT_OUTPUT_DIR = Path("data/wiki_pars")
DEFAULT_START_PATHS = ("/bin/view/Main/", "/bin/view/Main/AllDocs")
SYSTEM_SPACES = {
    "Applications",
    "Attachment",
    "Blog",
    "Contributors",
    "Help",
    "Macros",
    "Main",
    "Notifications",
    "Panels",
    "Sandbox",
    "Scheduler",
    "SkinsCode",
    "Templates",
    "WikiManager",
    "XWiki",
}
INVALID_FILENAME_CHARS = '<>:"/\\|?*\0'
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


@dataclass(frozen=True)
class PageCandidate:
    url: str
    source: str


def normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/")


def normalize_view_url(base_url: str, href: str) -> str | None:
    """Вернуть канонический URL просмотра XWiki без query/fragment."""
    if not href:
        return None

    absolute = urljoin(base_url + "/", href)
    parsed = urlparse(absolute)
    base = urlparse(base_url)

    if parsed.netloc and parsed.netloc.lower() != base.netloc.lower():
        return None
    if not parsed.path.startswith("/bin/view/"):
        return None

    path = re.sub(r"/+", "/", parsed.path)
    return urlunparse((base.scheme, base.netloc, path, "", "", ""))


def is_login_url(url: str) -> bool:
    path = urlparse(url).path
    return "/bin/login/" in path or "/bin/loginsubmit/" in path


def root_space_from_url(url: str) -> str:
    path = urlparse(url).path
    prefix = "/bin/view/"
    if not path.startswith(prefix):
        return ""
    remainder = path[len(prefix) :].strip("/")
    if not remainder:
        return ""
    return unquote_plus(remainder.split("/", 1)[0])


def clean_component(value: str, fallback: str, max_len: int = 90) -> str:
    value = unquote_plus(value or "").strip()
    value = re.sub(r"\s+", " ", value)
    value = "".join("_" if ch in INVALID_FILENAME_CHARS or ord(ch) < 32 else ch for ch in value)
    value = value.strip(" .")
    if not value:
        value = fallback

    if value.upper() in WINDOWS_RESERVED_NAMES:
        value = f"{value}_"

    if len(value) > max_len:
        digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]
        value = f"{value[: max_len - 9].rstrip()}-{digest}"

    return value


def title_from_soup(soup: BeautifulSoup, fallback: str) -> str:
    selectors = [
        "#document-title h1",
        ".document-title h1",
        "#xwikicontent h1",
        "h1",
    ]
    for selector in selectors:
        tag = soup.select_one(selector)
        if tag:
            text = tag.get_text(" ", strip=True)
            if text:
                return strip_xwiki_suffix(text)

    if soup.title:
        text = soup.title.get_text(" ", strip=True)
        if text:
            return strip_xwiki_suffix(text)

    return fallback


def strip_xwiki_suffix(title: str) -> str:
    title = re.sub(r"\s+-\s+XWiki\s*$", "", title).strip()
    return title or "Без названия"


def readable_output_path(output_dir: Path, url: str, title: str, used_paths: set[Path]) -> Path:
    path = urlparse(url).path
    parts = [part for part in path.removeprefix("/bin/view/").split("/") if part]
    decoded = [clean_component(part, "Раздел") for part in parts]

    if not decoded:
        decoded = ["Main"]

    # Для WebHome и страниц-разделов имя файла берём из заголовка, чтобы не плодить WebHome.html.
    filename_source = title or decoded[-1]
    if decoded[-1].lower() == "webhome":
        folders = decoded[:-1]
    else:
        folders = decoded[:-1]

    filename = clean_component(filename_source, decoded[-1]) + ".html"
    candidate = output_dir.joinpath(*folders, filename)

    if len(str(candidate)) > 230:
        short_folders = [clean_component(part, "Раздел", max_len=48) for part in folders]
        short_filename = clean_component(filename_source, decoded[-1], max_len=64) + ".html"
        candidate = output_dir.joinpath(*short_folders, short_filename)

    if candidate not in used_paths:
        used_paths.add(candidate)
        return candidate

    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
    candidate = candidate.with_name(f"{candidate.stem}-{digest}{candidate.suffix}")
    used_paths.add(candidate)
    return candidate


def clean_article_html(soup: BeautifulSoup) -> str:
    content = soup.select_one("#xwikicontent") or soup.select_one(".xwikicontent") or soup.body or soup
    content = BeautifulSoup(str(content), "html.parser")

    for tag in content.select(
        "script, style, noscript, nav, header, footer, form, iframe, "
        ".xwikitabbar, .xwiki-async, .hidden, .comment, .comments, .metadata"
    ):
        tag.decompose()

    for tag in content.find_all(True):
        attrs = dict(tag.attrs)
        for attr in attrs:
            if attr.startswith("on"):
                del tag.attrs[attr]

    return str(content)


def render_exported_html(title: str, source_url: str, full_name: str, article_html: str) -> str:
    metadata = f"""
<p class="xwiki-export-meta">
  <strong>Источник:</strong> <a href="{source_url}">{source_url}</a><br>
  <strong>XWiki page:</strong> {full_name}
</p>""".strip()

    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
</head>
<body>
<article data-source-url="{source_url}" data-xwiki-page="{full_name}">
  <h1>{title}</h1>
  {metadata}
  {article_html}
</article>
</body>
</html>
"""


def get_form_token(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    token = soup.find("input", {"name": "form_token"})
    return token.get("value", "") if token else ""


def login(session: requests.Session, base_url: str, username: str, password: str, timeout: int) -> None:
    login_url = f"{base_url}/bin/login/XWiki/XWikiLogin"
    response = session.get(login_url, timeout=timeout)
    token = get_form_token(response.text)

    payload = {
        "j_username": username,
        "j_password": password,
        "j_rememberme": "true",
        "form_token": token,
        "xredirect": "/bin/view/Main/",
    }
    result = session.post(
        f"{base_url}/bin/loginsubmit/XWiki/XWikiLogin",
        data=payload,
        timeout=timeout,
        allow_redirects=True,
    )

    if result.status_code in {401, 403} or "j_username" in result.text:
        raise RuntimeError("Не удалось войти в XWiki. Проверьте логин и пароль.")


def get_json(session: requests.Session, url: str, timeout: int, params: list[tuple[str, object]] | None = None) -> dict:
    response = session.get(url, params=params, timeout=timeout, headers={"Accept": "application/json"})
    response.raise_for_status()
    return response.json()


def discover_livedata_pages(session: requests.Session, base_url: str, timeout: int, limit: int) -> list[PageCandidate]:
    candidates: list[PageCandidate] = []
    offset = 0
    page_size = 100

    while True:
        params: list[tuple[str, object]] = [
            ("properties", "doc.title"),
            ("properties", "doc.location"),
            ("properties", "doc.url"),
            ("properties", "doc.fullName"),
            ("properties", "doc.viewable"),
            ("offset", offset),
            ("limit", page_size),
            ("sort", "doc.location"),
            ("descending", "false"),
            ("sourceParams.translationPrefix", "platform.index."),
            ("sourceParams.queryFilters", "currentlanguage,hidden"),
            ("timestamp", int(time.time() * 1000)),
            ("namespace", "wiki:xwiki"),
        ]
        data = get_json(session, f"{base_url}/rest/liveData/sources/liveTable/entries", timeout, params)
        entries = data.get("entries", [])
        if not entries:
            break

        for entry in entries:
            values = entry.get("values", {})
            if values.get("doc.viewable") is False:
                continue
            url = values.get("doc.url")
            if not url:
                continue
            normalized = normalize_view_url(base_url, str(url))
            if normalized:
                candidates.append(PageCandidate(normalized, "livedata"))

        offset += len(entries)
        if limit and len(candidates) >= limit:
            break
        count = data.get("count")
        if isinstance(count, int) and offset >= count:
            break

    return candidates


def extract_links_from_page(base_url: str, html: str) -> list[PageCandidate]:
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for link in soup.find_all("a", href=True):
        normalized = normalize_view_url(base_url, link["href"])
        if normalized:
            links.append(PageCandidate(normalized, "crawl"))
    return links


def discover_rest_pages(session: requests.Session, base_url: str, timeout: int) -> list[PageCandidate]:
    candidates: list[PageCandidate] = []
    try:
        spaces_data = get_json(session, f"{base_url}/rest/wikis/xwiki/spaces", timeout, [("media", "json")])
    except Exception as exc:
        print(f"REST discovery skipped: {exc}")
        return candidates

    for space in spaces_data.get("spaces", []):
        pages_link = next(
            (link.get("href") for link in space.get("links", []) if str(link.get("rel", "")).endswith("/pages")),
            None,
        )
        if not pages_link:
            name = space.get("name")
            if not name:
                continue
            pages_link = f"{base_url}/rest/wikis/xwiki/spaces/{quote(str(name), safe='')}/pages"

        try:
            pages_data = get_json(session, pages_link, timeout, [("media", "json")])
        except Exception:
            continue

        for page in pages_data.get("pageSummaries", []):
            url = page.get("xwikiAbsoluteUrl") or page.get("xwikiRelativeUrl")
            normalized = normalize_view_url(base_url, str(url)) if url else None
            if normalized:
                candidates.append(PageCandidate(normalized, "rest"))

    return candidates


def should_skip_space(url: str, include_system: bool, include_spaces: set[str], exclude_spaces: set[str]) -> bool:
    space = root_space_from_url(url)
    if include_spaces and space not in include_spaces:
        return True
    if space in exclude_spaces:
        return True
    if not include_system and space in SYSTEM_SPACES:
        return True
    return False


def fetch_page(session: requests.Session, url: str, timeout: int) -> tuple[str, BeautifulSoup] | None:
    response = session.get(url, timeout=timeout, allow_redirects=True)
    if response.status_code in {401, 403, 404} or is_login_url(response.url):
        return None
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    html_tag = soup.find("html")
    if html_tag and html_tag.get("data-xwiki-isnew") == "true":
        return None
    return response.text, soup


def save_page(output_dir: Path, url: str, soup: BeautifulSoup, used_paths: set[Path]) -> dict:
    fallback = root_space_from_url(url) or "Страница"
    title = title_from_soup(soup, fallback)
    html_tag = soup.find("html")
    full_name = html_tag.get("data-xwiki-document", "") if html_tag else ""
    article_html = clean_article_html(soup)
    output_path = readable_output_path(output_dir, url, title, used_paths)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_exported_html(title, url, full_name, article_html), encoding="utf-8")
    return {
        "title": title,
        "url": url,
        "xwiki_page": full_name,
        "path": str(output_path.as_posix()),
    }


def unique_candidates(candidates: Iterable[PageCandidate]) -> list[PageCandidate]:
    seen: set[str] = set()
    result: list[PageCandidate] = []
    for candidate in candidates:
        if candidate.url in seen:
            continue
        seen.add(candidate.url)
        result.append(candidate)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Выгрузить страницы XWiki в data/wiki_pars.")
    parser.add_argument("--base-url", default=os.getenv("XWIKI_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--output", type=Path, default=Path(os.getenv("XWIKI_OUTPUT_DIR", DEFAULT_OUTPUT_DIR)))
    parser.add_argument("--username", default=os.getenv("XWIKI_USERNAME", ""))
    parser.add_argument("--password", default=os.getenv("XWIKI_PASSWORD", ""))
    parser.add_argument("--include-space", action="append", default=[], help="Выгружать только указанное корневое пространство.")
    parser.add_argument("--exclude-space", action="append", default=[], help="Исключить корневое пространство.")
    parser.add_argument("--include-system", action="store_true", help="Не пропускать служебные пространства XWiki.")
    parser.add_argument("--start-url", action="append", default=[], help="Дополнительная стартовая страница для обхода.")
    parser.add_argument("--clean", action="store_true", help="Очистить папку назначения перед выгрузкой.")
    parser.add_argument("--max-pages", type=int, default=0, help="Ограничить число сохранённых страниц.")
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--delay", type=float, default=0.0, help="Пауза между запросами страниц.")
    parser.add_argument("--no-crawl", action="store_true", help="Не добавлять ссылки со скачанных страниц в очередь.")
    return parser.parse_args()


def main() -> int:
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    args = parse_args()
    base_url = normalize_base_url(args.base_url)
    include_spaces = set(args.include_space)
    exclude_spaces = set(args.exclude_space)

    session = requests.Session()
    session.headers.update({"User-Agent": "wiki_4-xwiki-exporter/1.0"})

    if args.username:
        password = args.password or getpass.getpass("XWiki password: ")
        print(f"Вход в XWiki как {args.username}...")
        login(session, base_url, args.username, password, args.timeout)

    if args.clean and args.output.exists():
        shutil.rmtree(args.output)
    args.output.mkdir(parents=True, exist_ok=True)

    print("Получение списка страниц...")
    candidates = []
    candidates.extend(discover_livedata_pages(session, base_url, args.timeout, args.max_pages))
    candidates.extend(discover_rest_pages(session, base_url, args.timeout))

    start_paths = list(DEFAULT_START_PATHS) + args.start_url
    candidates.extend(
        PageCandidate(normalize_view_url(base_url, start) or "", "start")
        for start in start_paths
    )
    queue = deque(candidate for candidate in unique_candidates(candidates) if candidate.url)
    queued = {candidate.url for candidate in queue}
    visited: set[str] = set()
    used_paths: set[Path] = set()
    manifest: list[dict] = []
    skipped = 0

    while queue:
        candidate = queue.popleft()
        if candidate.url in visited:
            continue
        visited.add(candidate.url)

        if should_skip_space(candidate.url, args.include_system, include_spaces, exclude_spaces):
            skipped += 1
            continue

        fetched = fetch_page(session, candidate.url, args.timeout)
        if not fetched:
            skipped += 1
            continue

        html, soup = fetched
        saved = save_page(args.output, candidate.url, soup, used_paths)
        saved["discovered_by"] = candidate.source
        manifest.append(saved)

        if len(manifest) % 20 == 0:
            print(f"Сохранено страниц: {len(manifest)}")

        if args.max_pages and len(manifest) >= args.max_pages:
            break

        if not args.no_crawl:
            for link in extract_links_from_page(base_url, html):
                if link.url not in queued and link.url not in visited:
                    queue.append(link)
                    queued.add(link.url)

        if args.delay:
            time.sleep(args.delay)

    manifest_path = args.output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Готово. Сохранено страниц: {len(manifest)}")
    print(f"Пропущено/недоступно: {skipped}")
    print(f"Manifest: {manifest_path}")
    if not manifest:
        print("Страницы не сохранены. Для закрытых пространств укажите XWIKI_USERNAME/XWIKI_PASSWORD или --username/--password.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
