#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Снимает 6 скриншотов веб-интерфейса БочкарИИ для документации и презентации.

Перед запуском должны быть:
    1. Запущено основное приложение (например, `python web_app.py`).
    2. Запущен сервер инференса (Ollama / LM Studio) — нужен для сценария
       «ответ с источниками», иначе на этом шаге скрипт пропустит реальный
       ответ и оставит чат пустым.
    3. Создан админ-пользователь (`python scripts/create_admin.py ...`).
    4. Установлены dev-зависимости и браузер Playwright:

        pip install -r requirements-dev.txt
        python -m playwright install chromium

Запуск (PowerShell):

    $env:DEMO_USER = "admin@example.com"
    $env:DEMO_PASSWORD = "********"
    python scripts/capture_screenshots.py

Полезные ключи:
    --base-url URL        Адрес приложения (default: http://localhost:5000)
    --headed              Показать окно браузера (по умолчанию headless)
    --scenario NAME       Снять только один сценарий из списка SCENARIOS
    --keep-data           Не удалять созданные demo-чаты после съёмки
    --slow-mo MS          Замедлить действия (отладка), напр. --slow-mo 250
    --output DIR          Куда сохранять PNG (default: docs/images)

Скрипт идемпотентен: повторный запуск переиспользует уже созданные demo-чаты
(находит их по заголовку), не плодит дубли. Файлы 01-login.png … 06-admin-overview.png
перезаписываются.
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

try:
    from playwright.sync_api import (
        APIRequestContext,
        BrowserContext,
        Page,
        Playwright,
        TimeoutError as PlaywrightTimeoutError,
        sync_playwright,
    )
except ImportError as exc:  # pragma: no cover
    sys.stderr.write(
        "Не найден пакет playwright. Установите dev-зависимости:\n"
        "    pip install -r requirements-dev.txt\n"
        "    python -m playwright install chromium\n"
    )
    raise SystemExit(1) from exc


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = REPO_ROOT / "docs" / "images"
DEFAULT_BASE_URL = os.environ.get("DEMO_BASE_URL", "http://localhost:5000")

DEMO_QUESTIONS: list[tuple[str, str]] = [
    ("Рассылка должникам", "Как сделать рассылку должникам?"),
    ("Состояние сертификации", "Как настроить состояние сертификации?"),
    ("Добавление пользователя в 1С", "Инструкция по добавлению пользователя в 1С"),
    ("Ошибка в журнале регистрации", "Как найти ошибку в журнале регистрации?"),
    (
        "Недостаточно прав для работы с таблицей",
        "Что делать с ошибкой 'недостаточно прав для работы с таблицей'?",
    ),
    (
        "Расхождение количества подобранного товара",
        "В документе количество поэкземплярной продукции не соответствует "
        "количеству подобранного товара — что делать?",
    ),
]

ANSWER_TARGET_TITLE = "Недостаточно прав для работы с таблицей"

VIEWPORT = {"width": 1440, "height": 900}
DEVICE_SCALE_FACTOR = 2


@dataclass
class Config:
    base_url: str
    user: str
    password: str
    output_dir: Path
    headed: bool
    slow_mo: int
    keep_data: bool
    scenarios: list[str]


SCENARIOS = ["login", "new-chat", "answer-sources", "chat-list", "documents", "admin"]
SCENARIO_FILES = {
    "login": "01-login.png",
    "new-chat": "02-new-chat.png",
    "answer-sources": "03-answer-sources.png",
    "chat-list": "04-chat-list.png",
    "documents": "05-documents-admin.png",
    "admin": "06-admin-overview.png",
}


def parse_args() -> Config:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"default: {DEFAULT_BASE_URL}")
    parser.add_argument("--user", default=os.environ.get("DEMO_USER", ""), help="email/username admin (или DEMO_USER)")
    parser.add_argument("--password", default=os.environ.get("DEMO_PASSWORD", ""), help="пароль admin (или DEMO_PASSWORD)")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_DIR), help=f"default: {DEFAULT_OUTPUT_DIR}")
    parser.add_argument("--headed", action="store_true", help="показывать окно браузера")
    parser.add_argument("--slow-mo", type=int, default=0, help="мс на действие (отладка)")
    parser.add_argument("--keep-data", action="store_true", help="не удалять demo-чаты")
    parser.add_argument(
        "--scenario",
        choices=SCENARIOS,
        action="append",
        help="снять только указанный сценарий (можно несколько раз)",
    )
    args = parser.parse_args()

    if not args.user or not args.password:
        parser.error("Не задан логин/пароль. Передайте --user/--password или DEMO_USER/DEMO_PASSWORD.")

    return Config(
        base_url=args.base_url.rstrip("/"),
        user=args.user,
        password=args.password,
        output_dir=Path(args.output).resolve(),
        headed=args.headed,
        slow_mo=args.slow_mo,
        keep_data=args.keep_data,
        scenarios=args.scenario or SCENARIOS,
    )


def log(msg: str) -> None:
    print(f"[capture] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Подготовка demo-данных (через API, унаследует cookies от UI-логина)
# ---------------------------------------------------------------------------


def login_via_ui(page: Page, base_url: str, user: str, password: str) -> None:
    log(f"Открываю {base_url}/ и логинюсь как {user}")
    page.goto(f"{base_url}/")
    page.wait_for_selector("#authOpenBtn", state="visible")
    auth_status = page.locator("#authStatus").text_content() or ""
    if "Гость" not in auth_status and auth_status.strip():
        log(f"Уже авторизован как «{auth_status.strip()}», пропускаю UI-логин")
        return

    page.click("#authOpenBtn")
    page.wait_for_selector("#authModal:not([hidden])", timeout=5_000)
    page.fill("#loginIdentifier", user)
    page.fill("#loginPassword", password)
    page.locator("#loginForm button[type=submit]").click()
    page.wait_for_function(
        "() => document.getElementById('authStatus') && !/^\\s*Гость\\s*$/.test(document.getElementById('authStatus').textContent || '')",
        timeout=10_000,
    )
    log(f"Залогинились: {page.locator('#authStatus').text_content()}")


def _list_chats(api: APIRequestContext) -> list[dict]:
    resp = api.get("/api/chats?limit=200")
    if not resp.ok:
        raise RuntimeError(f"GET /api/chats — HTTP {resp.status}: {resp.text()}")
    return resp.json().get("chats", [])


def ensure_demo_chats(api: APIRequestContext) -> dict[str, int]:
    """Создаёт demo-чаты с заголовками из DEMO_QUESTIONS, если их ещё нет."""
    existing = {chat["title"]: chat["id"] for chat in _list_chats(api)}
    chat_ids: dict[str, int] = {}
    for title, _question in DEMO_QUESTIONS:
        if title in existing:
            chat_ids[title] = existing[title]
            continue
        resp = api.post("/api/chats", data={"title": title})
        if not resp.ok:
            raise RuntimeError(f"POST /api/chats — HTTP {resp.status}: {resp.text()}")
        chat_ids[title] = resp.json()["id"]
        log(f"Создан demo-чат: «{title}» (id={chat_ids[title]})")
    return chat_ids


def populate_answer_chat(api: APIRequestContext, chat_id: int, question: str) -> bool:
    """Прогоняет один вопрос через /api/chat — наполняет чат реальным ответом с источниками."""
    log(f"Прогоняю вопрос через /api/chat для чата id={chat_id} (это может занять ~30-60 сек)")
    resp = api.post(
        "/api/chat",
        data={"message": question, "chat_id": chat_id, "answer_mode": "default"},
        timeout=180_000,
    )
    if not resp.ok:
        log(f"  ! /api/chat вернул HTTP {resp.status}: {resp.text()[:300]}")
        return False
    payload = resp.json()
    n_sources = len(payload.get("sources") or [])
    n_cites = len(payload.get("citations") or [])
    log(f"  Ответ получен: {len(payload.get('answer', ''))} символов, {n_sources} источников, {n_cites} цитат")
    return True


def cleanup_demo_chats(api: APIRequestContext, chat_ids: dict[str, int]) -> None:
    log("Удаляю demo-чаты")
    for title, chat_id in chat_ids.items():
        resp = api.delete(f"/api/chats/{chat_id}")
        if not resp.ok:
            log(f"  ! не удалось удалить чат «{title}» (HTTP {resp.status})")


# ---------------------------------------------------------------------------
# Сценарии съёмки
# ---------------------------------------------------------------------------


def force_light_theme(page: Page) -> None:
    page.evaluate(
        "() => { try { localStorage.setItem('theme', 'light'); "
        "document.documentElement.setAttribute('data-theme', 'light'); } catch (e) {} }"
    )


def click_chat_by_title(page: Page, title: str) -> None:
    """Клик по чату в сайдбаре по точному видимому заголовку."""
    item = page.locator(".chat-list-item", has_text=title).first
    item.wait_for(state="visible", timeout=10_000)
    item.click()


def wait_overlays_gone(page: Page) -> None:
    """Ждёт пока скроются индикаторы загрузки и тосты."""
    for selector in ["#typingIndicator", ".toast", ".inline-error"]:
        try:
            page.wait_for_selector(selector, state="hidden", timeout=2_000)
        except PlaywrightTimeoutError:
            pass


def wait_for_admin_tabs_visible(page: Page, timeout: int = 20_000) -> None:
    """Ждёт /api/auth/me: вкладки admin-only снимают hidden только после applyAuthState."""
    page.wait_for_function(
        """() => {
            const tab = document.querySelector('[data-panel="documentsPanel"]');
            return tab && !tab.hidden;
        }""",
        timeout=timeout,
    )


def wait_for_logged_in_ui(page: Page, timeout: int = 20_000) -> None:
    """Кнопка «Выйти» видна только при активной сессии — ждём до applyAuthState после загрузки."""
    page.wait_for_selector("#logoutBtn:not([hidden])", state="visible", timeout=timeout)


def screenshot_to(page: Page, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(path), full_page=False)
    log(f"  Сохранено: {path.relative_to(REPO_ROOT)}")


def scenario_login(page: Page, cfg: Config, _chat_ids: dict[str, int]) -> None:
    log("[01-login] Logout, открываю модалку входа")
    page.request.post(f"{cfg.base_url}/api/auth/logout")
    page.goto(f"{cfg.base_url}/")
    force_light_theme(page)
    page.wait_for_selector("#authOpenBtn", state="visible")
    page.click("#authOpenBtn")
    page.wait_for_selector("#authModal:not([hidden])", timeout=5_000)
    page.fill("#loginIdentifier", cfg.user)
    page.fill("#loginPassword", "demopassword")
    wait_overlays_gone(page)
    screenshot_to(page, cfg.output_dir / SCENARIO_FILES["login"])
    page.evaluate("() => document.getElementById('authCloseBtn')?.click()")
    login_via_ui(page, cfg.base_url, cfg.user, cfg.password)


def scenario_new_chat(page: Page, cfg: Config, chat_ids: dict[str, int]) -> None:
    log("[02-new-chat] Активный чат с введённым (но не отправленным) вопросом")
    target_title, target_question = DEMO_QUESTIONS[2]
    page.goto(f"{cfg.base_url}/")
    force_light_theme(page)
    page.wait_for_selector("#chatList .chat-list-item", timeout=10_000)
    click_chat_by_title(page, target_title)
    page.wait_for_selector(".message", timeout=10_000)
    page.fill("#messageInput", target_question)
    wait_overlays_gone(page)
    screenshot_to(page, cfg.output_dir / SCENARIO_FILES["new-chat"])


def scenario_answer_sources(page: Page, cfg: Config, chat_ids: dict[str, int]) -> None:
    log("[03-answer-sources] Открытый чат с ответом, развёрнута панель источников")
    page.goto(f"{cfg.base_url}/")
    force_light_theme(page)
    wait_for_logged_in_ui(page)
    page.wait_for_selector("#chatList .chat-list-item", timeout=10_000)
    click_chat_by_title(page, ANSWER_TARGET_TITLE)
    try:
        page.wait_for_selector(".bot-message", timeout=15_000)
    except PlaywrightTimeoutError:
        log("  ! не найдено ответа ассистента в чате — снимаю что есть")
    try:
        page.wait_for_selector(".show-sources-btn", state="visible", timeout=15_000)
    except PlaywrightTimeoutError:
        log("  ! кнопка «Источники» не появилась — снимаю без открытой панели")
    show_btn = page.locator(".show-sources-btn").first
    if show_btn.is_visible():
        show_btn.click()
        page.wait_for_selector("#sourcesPanel.open", timeout=8_000)
    else:
        log("  ! кнопка «Источники» не найдена — снимаю без открытой панели")
    wait_overlays_gone(page)
    screenshot_to(page, cfg.output_dir / SCENARIO_FILES["answer-sources"])


def scenario_chat_list(page: Page, cfg: Config, chat_ids: dict[str, int]) -> None:
    log("[04-chat-list] Сайдбар с несколькими чатами, рабочая область пустая")
    page.goto(f"{cfg.base_url}/")
    force_light_theme(page)
    page.wait_for_selector("#chatList .chat-list-item", timeout=10_000)
    page.evaluate(
        "() => { const inp = document.getElementById('messageInput'); if (inp) inp.value = ''; }"
    )
    page.evaluate("() => window.scrollTo(0, 0)")
    wait_overlays_gone(page)
    screenshot_to(page, cfg.output_dir / SCENARIO_FILES["chat-list"])


def scenario_documents(page: Page, cfg: Config, _chat_ids: dict[str, int]) -> None:
    log("[05-documents-admin] Раздел «База знаний»")
    page.goto(f"{cfg.base_url}/")
    force_light_theme(page)
    wait_for_logged_in_ui(page)
    wait_for_admin_tabs_visible(page)
    page.get_by_role("button", name="База знаний").click()
    page.wait_for_function(
        "() => document.getElementById('documentsPanel').classList.contains('active')",
        timeout=15_000,
    )
    try:
        page.wait_for_selector("#documentsList .data-card, #documentsList .empty-state", timeout=10_000)
    except PlaywrightTimeoutError:
        pass
    wait_overlays_gone(page)
    screenshot_to(page, cfg.output_dir / SCENARIO_FILES["documents"])


def scenario_admin(page: Page, cfg: Config, _chat_ids: dict[str, int]) -> None:
    log("[06-admin-overview] Админ-консоль с диагностикой")
    page.goto(f"{cfg.base_url}/")
    force_light_theme(page)
    wait_for_logged_in_ui(page)
    wait_for_admin_tabs_visible(page)
    page.get_by_role("button", name="Админка").click()
    page.wait_for_function(
        "() => document.getElementById('adminPanel').classList.contains('active')",
        timeout=15_000,
    )
    refresh_btn = page.locator("#refreshAdminBtn")
    if refresh_btn.is_visible():
        refresh_btn.click()
    try:
        page.wait_for_selector("#adminOverview .admin-card, #adminOverview .empty-state", timeout=15_000)
    except PlaywrightTimeoutError:
        pass
    wait_overlays_gone(page)
    screenshot_to(page, cfg.output_dir / SCENARIO_FILES["admin"])


SCENARIO_FUNCS = {
    "login": scenario_login,
    "new-chat": scenario_new_chat,
    "answer-sources": scenario_answer_sources,
    "chat-list": scenario_chat_list,
    "documents": scenario_documents,
    "admin": scenario_admin,
}


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------


def run(cfg: Config) -> int:
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    log(f"Скриншоты: {cfg.output_dir}")
    log(f"Сценарии:  {', '.join(cfg.scenarios)}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not cfg.headed, slow_mo=cfg.slow_mo)
        context = browser.new_context(
            viewport=VIEWPORT,
            device_scale_factor=DEVICE_SCALE_FACTOR,
            base_url=cfg.base_url,
            locale="ru-RU",
        )
        page = context.new_page()
        try:
            login_via_ui(page, cfg.base_url, cfg.user, cfg.password)
            chat_ids = ensure_demo_chats(context.request)

            answer_chat_id = chat_ids.get(ANSWER_TARGET_TITLE)
            answer_question = next(q for t, q in DEMO_QUESTIONS if t == ANSWER_TARGET_TITLE)
            if answer_chat_id and "answer-sources" in cfg.scenarios:
                resp = context.request.get(f"/api/chats/{answer_chat_id}")
                msgs = resp.json().get("messages", []) if resp.ok else []
                has_assistant = any(m.get("role") == "assistant" for m in msgs)
                if not has_assistant:
                    populate_answer_chat(context.request, answer_chat_id, answer_question)
                else:
                    log(f"Чат «{ANSWER_TARGET_TITLE}» уже содержит ответ ассистента, пропускаю /api/chat")

            failed: list[str] = []
            for name in cfg.scenarios:
                func = SCENARIO_FUNCS[name]
                try:
                    func(page, cfg, chat_ids)
                except Exception as exc:  # noqa: BLE001
                    failed.append(name)
                    log(f"  !! сценарий {name} упал: {exc}")

            if not cfg.keep_data:
                cleanup_demo_chats(context.request, chat_ids)
            else:
                log("--keep-data: demo-чаты оставлены в БД")

            if failed:
                log(f"Готово. Сбойные сценарии: {', '.join(failed)}")
                return 1
            log("Готово. Все сценарии сняты.")
            return 0
        finally:
            context.close()
            browser.close()


def main(argv: Iterable[str] | None = None) -> int:
    cfg = parse_args()
    return run(cfg)


if __name__ == "__main__":
    raise SystemExit(main())
