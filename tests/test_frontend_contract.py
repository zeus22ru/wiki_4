"""DOM contract guards for templates/index.html (Option D redesign).

Asserts JS-bound IDs/classes stay present across markup refactors.
Uses stdlib html.parser — no browser runtime.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "templates" / "index.html"
THEME_CSS = ROOT / "static" / "css" / "theme.css"

REQUIRED_IDS = (
    "chatList",
    "sidebarNewChatBtn",
    "chatSearchInput",
    "clearChatsBtn",
    "messageForm",
    "messageInput",
    "sendButton",
    "attachButton",
    "attachmentFileInput",
    "attachmentPreview",
    "sourcesPanel",
    "sourcesList",
    "sourcesEmpty",
    "closeSources",
    "chatPanel",
    "documentsPanel",
    "adminPanel",
    "messages",
    "exportChatBtn",
    "answerModeSelect",
    "followupSuggestionsToggle",
    "relatedDocsToggle",
    "topKInput",
    "minScoreInput",
    "ragAdvancedToggle",
    "ragAdvancedPanel",
    "statusDot",
    "statusText",
    "authWidget",
    "authStatus",
    "authOpenBtn",
    "logoutBtn",
    "themeToggle",
    "authModal",
    "issueModal",
    "telegramLinkBtn",
    "uploadForm",
    "documentFileInput",
    "refreshDocumentsBtn",
    "previewDocumentBtn",
    "reindexBtn",
    "documentsList",
    "refreshAdminBtn",
    "adminOverview",
    "adminSettings",
)

REQUIRED_CLASSES = (
    "app-container",
    "workspace-sidebar",
    "chat-container",
    "workspace-toolbar",
    "workspace-tabs",
    "header-actions",
    "tab-btn",
    "admin-only",
    "sources-panel",
    "empty-tiles",
    "main-shell",
    "sidebar-brand",
)

PANEL_TARGETS = ("chatPanel", "documentsPanel", "adminPanel")


class _DomIndex(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.classes: set[str] = set()
        self.id_to_tag: dict[str, str] = {}
        self.id_to_classes: dict[str, set[str]] = {}
        self.tab_panels: list[str] = []
        self.parent_stack: list[str | None] = []
        self.id_parent: dict[str, str | None] = {}
        self.class_children: dict[str, list[str]] = {}
        self.self_closing = {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        el_id = attr.get("id")
        class_names = {c for c in (attr.get("class") or "").split() if c}
        parent_id = self.parent_stack[-1] if self.parent_stack else None

        if el_id:
            self.ids.add(el_id)
            self.id_to_tag[el_id] = tag
            self.id_to_classes[el_id] = class_names
            self.id_parent[el_id] = parent_id

        for cls in class_names:
            self.classes.add(cls)
            if parent_id:
                self.class_children.setdefault(parent_id, []).append(cls)

        panel = attr.get("data-panel")
        if panel and "tab-btn" in class_names:
            self.tab_panels.append(panel)

        if tag not in self.self_closing:
            self.parent_stack.append(el_id if el_id else parent_id)

    def handle_endtag(self, tag: str) -> None:
        if tag in self.self_closing:
            return
        if self.parent_stack:
            self.parent_stack.pop()


def _parse_index() -> _DomIndex:
    raw = INDEX_HTML.read_text(encoding="utf-8")
    # Strip Jinja so the HTML parser sees stable markup.
    cleaned = re.sub(r"\{\{.*?\}\}", "x", raw, flags=re.DOTALL)
    cleaned = re.sub(r"\{%.*?%\}", "", cleaned, flags=re.DOTALL)
    parser = _DomIndex()
    parser.feed(cleaned)
    return parser


@pytest.fixture(scope="module")
def dom() -> _DomIndex:
    assert INDEX_HTML.is_file(), f"missing {INDEX_HTML}"
    return _parse_index()


@pytest.mark.parametrize("element_id", REQUIRED_IDS)
def test_required_ids_present(dom: _DomIndex, element_id: str) -> None:
    assert element_id in dom.ids, f"missing id=#{element_id}"


@pytest.mark.parametrize("class_name", REQUIRED_CLASSES)
def test_required_classes_present(dom: _DomIndex, class_name: str) -> None:
    assert class_name in dom.classes, f"missing class.{class_name}"


def test_workspace_tab_panel_targets(dom: _DomIndex) -> None:
    for panel in PANEL_TARGETS:
        assert panel in dom.tab_panels, f"missing tab data-panel={panel}"
        assert panel in dom.ids, f"missing panel #{panel}"


def test_sources_panel_hooks(dom: _DomIndex) -> None:
    assert "sourcesPanel" in dom.ids
    assert "sourcesList" in dom.ids
    assert "sourcesEmpty" in dom.ids
    assert "closeSources" in dom.ids
    assert "sources-panel" in dom.id_to_classes.get("sourcesPanel", set())


def test_sources_empty_state_in_html_not_css() -> None:
    """Empty sources copy must live in UTF-8 HTML/JS — never CSS content:."""
    raw = INDEX_HTML.read_text(encoding="utf-8")
    assert 'id="sourcesEmpty"' in raw
    assert "Источники появятся после ответа" in raw
    empty = re.search(
        r'id="sourcesEmpty"[^>]*>([^<]+)<',
        raw,
    )
    assert empty is not None
    assert "?" not in empty.group(1)
    assert "Источники" in empty.group(1)

    style = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
    components = (ROOT / "static" / "css" / "components.css").read_text(encoding="utf-8")
    for css in (style, components):
        assert "sources-list:empty::before" not in css
        assert not re.search(
            r"sources-list[^{]*:empty::before\s*\{[^}]*content\s*:",
            css,
            flags=re.DOTALL,
        )
        # No CSS-generated Russian (or mojibake) empty-state near sources-list.
        assert not re.search(
            r"\.sources-list[^{]*::before\s*\{[^}]*content\s*:\s*[\"'][^\"']*[\"']",
            css,
            flags=re.DOTALL,
        )

    script = (ROOT / "static" / "script.js").read_text(encoding="utf-8")
    assert "SOURCES_EMPTY_IDLE" in script
    assert "Источники появятся после ответа" in script
    assert "showSourcesEmpty" in script
    assert "?" not in "Источники появятся после ответа"

def test_message_content_class_for_clipboard(dom: _DomIndex) -> None:
    # ClipboardManager observes .message-content; class is emitted by addMessage().
    script = (ROOT / "static" / "script.js").read_text(encoding="utf-8")
    assert "message-content" in script
    assert "className = 'message-content'" in script or 'className = "message-content"' in script or "className = `message-content`" in script or ".message-content" in script


def test_attachment_and_auth_nodes(dom: _DomIndex) -> None:
    for element_id in (
        "attachmentPreview",
        "attachmentFileInput",
        "attachButton",
        "authModal",
        "authOpenBtn",
        "logoutBtn",
        "authStatus",
    ):
        assert element_id in dom.ids


def test_admin_only_class_on_restricted_tabs(dom: _DomIndex) -> None:
    # Documents and admin tabs must stay role-gated via .admin-only
    assert "admin-only" in dom.classes


def test_option_d_shell_structure(dom: _DomIndex) -> None:
    """Canonical Option D shell: sidebar + main-shell; sources sibling of chat."""
    assert "main-shell" in dom.classes
    assert "sidebar-brand" in dom.classes
    assert "empty-tiles" in dom.classes
    assert "emptyTiles" in dom.ids

    from bs4 import BeautifulSoup

    raw = INDEX_HTML.read_text(encoding="utf-8")
    cleaned = re.sub(r"\{\{.*?\}\}", "x", raw, flags=re.DOTALL)
    cleaned = re.sub(r"\{%.*?%\}", "", cleaned, flags=re.DOTALL)
    soup = BeautifulSoup(cleaned, "html.parser")
    app = soup.select_one(".app-container")
    assert app is not None
    children = [c for c in app.find_all(recursive=False) if getattr(c, "name", None)]
    assert any("workspace-sidebar" in (c.get("class") or []) for c in children)
    shell = next(c for c in children if "main-shell" in (c.get("class") or []))
    shell_kids = [c for c in shell.find_all(recursive=False) if getattr(c, "name", None)]
    assert any("chat-container" in (c.get("class") or []) for c in shell_kids)
    assert any(c.get("id") == "sourcesPanel" for c in shell_kids)
    chat_panel = soup.select_one("#chatPanel")
    assert chat_panel is not None
    assert chat_panel.select_one("#sourcesPanel") is None


def test_option_d_toolbar_layout() -> None:
    """Title/chat-header removed; tabs left, status + auth right (space-between)."""
    from bs4 import BeautifulSoup

    raw = INDEX_HTML.read_text(encoding="utf-8")
    cleaned = re.sub(r"\{\{.*?\}\}", "x", raw, flags=re.DOTALL)
    cleaned = re.sub(r"\{%.*?%\}", "", cleaned, flags=re.DOTALL)
    soup = BeautifulSoup(cleaned, "html.parser")

    assert soup.select_one(".chat-header") is None
    assert soup.select_one(".workspace-title") is None
    assert "Рабочее пространство" not in raw

    toolbar = soup.select_one(".workspace-toolbar")
    assert toolbar is not None
    tabs = toolbar.select_one(".workspace-tabs")
    actions = toolbar.select_one(".header-actions")
    assert tabs is not None
    assert actions is not None
    children = [c for c in toolbar.find_all(recursive=False) if getattr(c, "name", None)]
    assert children[0] is tabs
    assert children[1] is actions
    assert actions.select_one("#serviceStatus") is not None
    assert actions.select_one("#authWidget") is not None
    assert actions.select_one("#logoutBtn") is not None
    assert actions.select_one("#telegramLinkBtn") is not None
    assert actions.select_one("#themeToggle") is not None
    assert tabs.select_one('[data-panel="chatPanel"]') is not None
    assert tabs.select_one('[data-panel="documentsPanel"]') is not None
    assert tabs.select_one('[data-panel="adminPanel"]') is not None

    chat = soup.select_one(".chat-container")
    assert chat is not None
    first = next(c for c in chat.find_all(recursive=False) if getattr(c, "name", None))
    assert "workspace-toolbar" in (first.get("class") or [])

    style = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
    components = (ROOT / "static" / "css" / "components.css").read_text(encoding="utf-8")
    for css in (style, components):
        assert re.search(
            r"\.workspace-toolbar\s*\{[^}]*justify-content:\s*space-between",
            css,
            flags=re.DOTALL,
        ), "workspace-toolbar must use space-between (tabs left, actions right)"
        assert not re.search(
            r"\.workspace-toolbar\s*\{[^}]*justify-content:\s*flex-end",
            css,
            flags=re.DOTALL,
        ), "workspace-toolbar must not cluster tabs+actions with flex-end"


OPTION_D_TOKENS = (
    "--primary-color",
    "--accent-sand",
    "--accent-mint",
    "--workspace-canvas",
    "--text-color",
    "--secondary-text",
    "--border-color",
    "--radius",
    "--text-xs",
    "--on-primary",
    "--status-ok",
    "--status-down",
)


def _theme_blocks() -> tuple[str, str]:
    css = THEME_CSS.read_text(encoding="utf-8")
    root_match = re.search(r":root\s*\{(.*?)\n\}", css, flags=re.DOTALL)
    dark_match = re.search(r'\[data-theme="dark"\]\s*\{(.*?)\n\}', css, flags=re.DOTALL)
    assert root_match, ":root block missing in theme.css"
    assert dark_match, '[data-theme="dark"] block missing in theme.css'
    return root_match.group(1), dark_match.group(1)


@pytest.mark.parametrize("token", OPTION_D_TOKENS)
def test_option_d_tokens_in_light_and_dark(token: str) -> None:
    root, dark = _theme_blocks()
    assert token in root, f"light theme missing {token}"
    assert token in dark, f"dark theme missing {token}"


def test_option_d_brand_palette_values() -> None:
    root, _ = _theme_blocks()
    assert re.search(r"--primary-color:\s*#A88656", root, re.I)
    assert re.search(r"--accent-sand:\s*#D6BC8A", root, re.I)
    assert re.search(r"--accent-mint:\s*#D9F2EB", root, re.I)
    assert re.search(r"--workspace-canvas:\s*#F4F5F6", root, re.I)
    assert re.search(r"--text-color:\s*#212529", root, re.I)
    assert re.search(r"--secondary-text:\s*#68717B", root, re.I)
    assert re.search(r"--border-color:\s*#DDE1E5", root, re.I)
    assert re.search(r"--radius:\s*4px", root, re.I)


def test_send_button_has_visible_label(dom: _DomIndex) -> None:
    raw = INDEX_HTML.read_text(encoding="utf-8")
    assert 'id="sendButton"' in raw
    assert "Отправить" in raw
    assert 'aria-label="Отправить"' in raw


def test_empty_tiles_actions_present() -> None:
    raw = INDEX_HTML.read_text(encoding="utf-8")
    for action in ("question", "source", "continue", "library"):
        assert f'data-tile="{action}"' in raw


def test_option_d_message_avatars_use_marks_not_legacy_art() -> None:
    """Avatars must be Option D Lucide stroke marks — not letter/star/robot art."""
    script = (ROOT / "static" / "script.js").read_text(encoding="utf-8")
    components = (ROOT / "static" / "css" / "components.css").read_text(encoding="utf-8")

    assert "createMessageAvatar" in script
    assert "message-avatar--bot" in script
    assert "message-avatar--user" in script
    assert "message-avatar__glyph" in script
    assert "USER_AVATAR_GLYPH" in script
    assert "BOT_AVATAR_GLYPH" in script
    assert 'stroke="currentColor"' in script
    assert "assistant-avatar.svg" not in script
    assert "assistantAvatarSrc" not in script
    assert "avatar.textContent = 'Вы'" not in script
    assert "message-avatar__initial" not in script
    assert "textContent = 'В'" not in script
    # No filled sparkle / star mark
    assert "L12 3l2.4 6.6L21 12" not in script

    assert "message-avatar--bot" in components
    assert re.search(r"border-radius:\s*4px", components)
    assert "stroke: currentColor" in components
    assert re.search(
        r"\.message-avatar\s+img\s*\{[^}]*display:\s*none",
        components,
        flags=re.DOTALL,
    )
    assert not re.search(
        r"\.message-avatar[^{]*\{[^}]*border-radius:\s*50%",
        components,
        flags=re.DOTALL,
    )


def test_admin_model_select_wired_in_frontend() -> None:
    """Chat/embedding model settings use /api/admin/models dropdown helpers."""
    script = (ROOT / "static" / "script.js").read_text(encoding="utf-8")
    style = (ROOT / "static" / "style.css").read_text(encoding="utf-8")

    assert "ADMIN_MODEL_SETTING_KEYS" in script
    assert "OLLAMA_CHAT_MODEL" in script
    assert "OLLAMA_EMBEDDING_MODEL" in script
    assert "/api/admin/models" in script
    assert "enhanceAdminModelSelects" in script
    assert "data-setting-models-refresh" in script
    assert "setting-model-picker" in style
    assert "setting-select" in style
