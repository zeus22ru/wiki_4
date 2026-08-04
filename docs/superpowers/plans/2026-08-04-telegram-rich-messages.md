# Telegram Rich Messages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver wiki_4 agent Q&A answers in Telegram as Rich Messages (GFM markdown including tables), stream via `sendRichMessageDraft`, finalize with `sendRichMessage`, and keep classic HTML as fallback.

**Architecture:** Extend `TelegramClient` with rich send/draft methods. When `TELEGRAM_RICH_MESSAGES` is true, `handle_question` uses draft thinking → throttled markdown drafts → final rich message; on failure or flag off, reuse existing placeholder/edit/HTML path. Light sanitization (strip sources, truncate) lives next to the client helpers.

**Tech Stack:** Python 3, `requests`, Telegram Bot API 10.1+ Rich Messages, pytest, existing Flask internal `/api/chat/stream` SSE.

**Spec:** `docs/superpowers/specs/2026-08-04-telegram-rich-messages-design.md`

## Global Constraints

- Content representation for Q&A: `InputRichMessage.markdown` (exactly one of markdown/html/blocks)
- Default `TELEGRAM_RICH_MESSAGES` = `true`
- Default `TELEGRAM_RICH_MAX_CHARS` = `32000` (Bot API limit 32768)
- Commands / linking stay on classic `sendMessage`
- Sources stay classic `sendMessage` when `TELEGRAM_SHOW_SOURCES=true`
- No media/blocks builder / Ephemeral / Communities in this plan
- Commit steps only if the user explicitly asks to commit

---

### Task 1: Settings + rich markdown helpers + TelegramClient rich methods

**Files:**
- Modify: `config/settings.py` (after `TELEGRAM_SHOW_SOURCES`)
- Modify: `.env.example` (Telegram section)
- Modify: `integrations/telegram.py`
- Modify: `tests/test_telegram_integration.py`

**Interfaces:**
- Consumes: Bot API `sendRichMessage`, `sendRichMessageDraft`; existing `_request`
- Produces:
  - `settings.TELEGRAM_RICH_MESSAGES: bool`
  - `settings.TELEGRAM_RICH_MAX_CHARS: int`
  - `validate_rich_message(rich_message: dict) -> dict` (returns same dict or raises `ValueError`)
  - `prepare_rich_markdown(text: str, *, max_chars: int) -> str`
  - `TelegramClient.send_rich_message(chat_id: int, rich_message: dict, *, reply_markup: dict | None = None) -> dict`
  - `TelegramClient.send_rich_message_draft(chat_id: int, draft_id: int, rich_message: dict) -> dict`

- [ ] **Step 1: Write failing tests for helpers and client methods**

Append to `tests/test_telegram_integration.py`:

```python
def test_validate_rich_message_requires_exactly_one_representation():
    from integrations.telegram import validate_rich_message

    assert validate_rich_message({"markdown": "| a | b |\n|---|---|\n| 1 | 2 |"})["markdown"].startswith("| a |")
    with pytest.raises(ValueError):
        validate_rich_message({})
    with pytest.raises(ValueError):
        validate_rich_message({"markdown": "x", "html": "<p>x</p>"})


def test_prepare_rich_markdown_truncates():
    from integrations.telegram import prepare_rich_markdown

    long_text = "я" * 100
    out = prepare_rich_markdown(long_text, max_chars=50)
    assert len(out) <= 50
    assert out.endswith("…") or len(out) == 50


def test_telegram_client_send_rich_message(monkeypatch):
    calls = []

    def mock_request(self, method, *, params=None, json_payload=None):
        calls.append((method, json_payload))
        return {"ok": True, "result": {"message_id": 42}}

    monkeypatch.setattr(TelegramClient, "_request", mock_request)
    client = TelegramClient(bot_token="test-token")
    table = "| A | B |\n|---|---|\n| 1 | 2 |"
    result = client.send_rich_message(987, {"markdown": table})
    assert result["result"]["message_id"] == 42
    assert calls[0][0] == "sendRichMessage"
    assert calls[0][1]["chat_id"] == 987
    assert calls[0][1]["rich_message"]["markdown"] == table


def test_telegram_client_send_rich_message_draft(monkeypatch):
    calls = []

    def mock_request(self, method, *, params=None, json_payload=None):
        calls.append((method, json_payload))
        return {"ok": True, "result": True}

    monkeypatch.setattr(TelegramClient, "_request", mock_request)
    client = TelegramClient(bot_token="test-token")
    client.send_rich_message_draft(
        987,
        draft_id=555,
        rich_message={"html": "<tg-thinking>Думаю...</tg-thinking>"},
    )
    assert calls[0][0] == "sendRichMessageDraft"
    assert calls[0][1]["draft_id"] == 555
    assert "html" in calls[0][1]["rich_message"]
```

Ensure `pytest` is imported at top of the test file (add if missing).

- [ ] **Step 2: Run tests — expect FAIL**

Run: `pytest tests/test_telegram_integration.py::test_validate_rich_message_requires_exactly_one_representation tests/test_telegram_integration.py::test_prepare_rich_markdown_truncates tests/test_telegram_integration.py::test_telegram_client_send_rich_message tests/test_telegram_integration.py::test_telegram_client_send_rich_message_draft -v`

Expected: FAIL (ImportError / AttributeError — symbols missing)

- [ ] **Step 3: Implement settings, helpers, client methods**

In `config/settings.py` after `TELEGRAM_SHOW_SOURCES`:

```python
    TELEGRAM_RICH_MESSAGES: bool = os.getenv("TELEGRAM_RICH_MESSAGES", "true").lower() == "true"
    TELEGRAM_RICH_MAX_CHARS: int = int(os.getenv("TELEGRAM_RICH_MAX_CHARS", "32000"))
```

In `.env.example` after `TELEGRAM_SHOW_SOURCES`:

```env
#TELEGRAM_RICH_MESSAGES=true
#TELEGRAM_RICH_MAX_CHARS=32000
```

In `integrations/telegram.py` add (near other helpers, before `TelegramError`):

```python
def validate_rich_message(rich_message: dict[str, Any]) -> dict[str, Any]:
    """Require exactly one of markdown / html / blocks per Bot API InputRichMessage."""
    if not isinstance(rich_message, dict):
        raise ValueError("rich_message must be a dict")
    present = [k for k in ("markdown", "html", "blocks") if k in rich_message and rich_message[k] is not None]
    if len(present) != 1:
        raise ValueError("rich_message must contain exactly one of markdown, html, blocks")
    return rich_message


def prepare_rich_markdown(text: str, *, max_chars: int) -> str:
    """Truncate markdown for Rich Message limits."""
    text = text or ""
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    if max_chars == 1:
        return "…"
    return text[: max_chars - 1] + "…"
```

On `TelegramClient`:

```python
    def send_rich_message(
        self,
        chat_id: int,
        rich_message: dict[str, Any],
        *,
        reply_markup: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "rich_message": validate_rich_message(rich_message),
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return self._request("sendRichMessage", json_payload=payload)

    def send_rich_message_draft(
        self,
        chat_id: int,
        draft_id: int,
        rich_message: dict[str, Any],
    ) -> dict[str, Any]:
        if not draft_id:
            raise ValueError("draft_id must be a non-zero integer")
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "draft_id": int(draft_id),
            "rich_message": validate_rich_message(rich_message),
        }
        return self._request("sendRichMessageDraft", json_payload=payload)
```

Export new helpers from test imports if the file imports symbols explicitly — update:

```python
from integrations.telegram import (
    TelegramClient,
    ...
    prepare_rich_markdown,
    validate_rich_message,
)
```

(or keep local imports inside the new tests as shown).

- [ ] **Step 4: Run tests — expect PASS**

Run: same pytest command as Step 2  
Expected: all four PASS

- [ ] **Step 5: Commit** (only if user asks)

```bash
git add config/settings.py .env.example integrations/telegram.py tests/test_telegram_integration.py
git commit -m "$(cat <<'EOF'
feat(telegram): add Rich Message client helpers

EOF
)"
```

---

### Task 2: Rich streaming path in `handle_question`

**Files:**
- Modify: `scripts/telegram_bot_worker.py`
- Modify: `tests/test_telegram_integration.py`

**Interfaces:**
- Consumes: `TelegramClient.send_rich_message`, `send_rich_message_draft`, `prepare_rich_markdown`, `settings.TELEGRAM_RICH_MESSAGES`, `settings.TELEGRAM_RICH_MAX_CHARS`, existing `_strip_sources_section`, `_send_full_answer`
- Produces:
  - `make_rich_draft_id(update: dict[str, Any], tg_user_id: int) -> int`
  - Rich branch inside `handle_question` when flag is on

- [ ] **Step 1: Write failing tests for draft_id and rich handle_question flow**

```python
def test_make_rich_draft_id_uses_update_id():
    from scripts.telegram_bot_worker import make_rich_draft_id

    assert make_rich_draft_id({"update_id": 42}, tg_user_id=1) == 42
    draft = make_rich_draft_id({}, tg_user_id=7)
    assert isinstance(draft, int) and draft != 0


def test_handle_question_rich_messages_draft_then_final(monkeypatch):
    from scripts.telegram_bot_worker import TelegramSession, _sessions, handle_question

    _sessions.clear()
    monkeypatch.setattr(
        "scripts.telegram_bot_worker.settings.TELEGRAM_RICH_MESSAGES", True
    )
    monkeypatch.setattr(
        "scripts.telegram_bot_worker.settings.TELEGRAM_SHOW_SOURCES", False
    )
    monkeypatch.setattr(
        "scripts.telegram_bot_worker.settings.TELEGRAM_STREAM_EDIT_INTERVAL_MS", 0
    )
    monkeypatch.setattr(
        "scripts.telegram_bot_worker.settings.TELEGRAM_RICH_MAX_CHARS", 32000
    )
    monkeypatch.setattr(
        "scripts.telegram_bot_worker.settings.TELEGRAM_INTERNAL_API_URL",
        "http://127.0.0.1:5000",
    )
    monkeypatch.setattr(
        "scripts.telegram_bot_worker.settings.TELEGRAM_INTERNAL_API_KEY",
        "secret",
    )
    monkeypatch.setattr(
        "scripts.telegram_bot_worker.hydrate_session",
        lambda session, tg_user_id: setattr(session, "user_id", 1) or True,
    )

    calls: list[tuple] = []

    class FakeClient:
        def send_chat_action(self, *a, **k):
            return {"ok": True}

        def send_rich_message_draft(self, chat_id, draft_id, rich_message):
            calls.append(("draft", chat_id, draft_id, rich_message))
            return {"ok": True, "result": True}

        def send_rich_message(self, chat_id, rich_message, reply_markup=None):
            calls.append(("final", chat_id, rich_message))
            return {"ok": True, "result": {"message_id": 9}}

        def send_message(self, *a, **k):
            raise AssertionError("classic send_message should not be used on success")

        def edit_message_text(self, *a, **k):
            raise AssertionError("classic edit should not be used on success")

    sse = (
        'data: {"type":"delta","text":"| A | B |\\n"}\n\n'
        'data: {"type":"delta","text":"|---|---|\\n"}\n\n'
        'data: {"type":"delta","text":"| 1 | 2 |"}\n\n'
        'data: {"type":"done","answer":"| A | B |\\n|---|---|\\n| 1 | 2 |","chat_id":"c1","sources":[],"citations":[]}\n\n'
        "data: [DONE]\n\n"
    )

    class FakeResp:
        def raise_for_status(self):
            return None

        def iter_lines(self, decode_unicode=True):
            for line in sse.splitlines():
                yield line

    monkeypatch.setattr(
        "scripts.telegram_bot_worker.requests.post",
        lambda *a, **k: FakeResp(),
    )

    update = {
        "update_id": 1001,
        "message": {
            "chat": {"id": 55},
            "from": {"id": 77},
            "text": "покажи таблицу",
        },
    }
    handle_question(update, TelegramSession(), FakeClient(), text="покажи таблицу")

    assert calls[0][0] == "draft"
    assert calls[0][2] == 1001
    assert "tg-thinking" in calls[0][3].get("html", "")
    assert any(c[0] == "draft" and "markdown" in c[3] for c in calls)
    finals = [c for c in calls if c[0] == "final"]
    assert len(finals) == 1
    assert "| A | B |" in finals[0][2]["markdown"]


def test_handle_question_rich_failure_falls_back(monkeypatch):
    from scripts.telegram_bot_worker import TelegramSession, _sessions, handle_question
    from integrations.telegram import TelegramError

    _sessions.clear()
    monkeypatch.setattr(
        "scripts.telegram_bot_worker.settings.TELEGRAM_RICH_MESSAGES", True
    )
    monkeypatch.setattr(
        "scripts.telegram_bot_worker.settings.TELEGRAM_SHOW_SOURCES", False
    )
    monkeypatch.setattr(
        "scripts.telegram_bot_worker.settings.TELEGRAM_STREAM_EDIT_INTERVAL_MS", 0
    )
    monkeypatch.setattr(
        "scripts.telegram_bot_worker.settings.TELEGRAM_INTERNAL_API_URL",
        "http://127.0.0.1:5000",
    )
    monkeypatch.setattr(
        "scripts.telegram_bot_worker.settings.TELEGRAM_INTERNAL_API_KEY",
        "secret",
    )
    monkeypatch.setattr(
        "scripts.telegram_bot_worker.hydrate_session",
        lambda session, tg_user_id: setattr(session, "user_id", 1) or True,
    )

    legacy = []

    def fake_send_full(client, chat_id, message_id, markdown_text):
        legacy.append((chat_id, message_id, markdown_text))

    monkeypatch.setattr(
        "scripts.telegram_bot_worker._send_full_answer", fake_send_full
    )

    class FakeClient:
        def send_chat_action(self, *a, **k):
            return {"ok": True}

        def send_rich_message_draft(self, *a, **k):
            return {"ok": True}

        def send_rich_message(self, *a, **k):
            raise TelegramError("rich failed")

        def send_message(self, chat_id, text, **k):
            legacy.append(("placeholder", chat_id, text))
            return {"ok": True, "result": {"message_id": 1}}

        def edit_message_text(self, *a, **k):
            return {"ok": True}

    class FakeResp:
        def raise_for_status(self):
            return None

        def iter_lines(self, decode_unicode=True):
            yield 'data: {"type":"done","answer":"**ok**","chat_id":"c1","sources":[],"citations":[]}'
            yield "data: [DONE]"

    monkeypatch.setattr(
        "scripts.telegram_bot_worker.requests.post",
        lambda *a, **k: FakeResp(),
    )

    update = {
        "update_id": 2,
        "message": {"chat": {"id": 1}, "from": {"id": 2}, "text": "q"},
    }
    handle_question(update, TelegramSession(), FakeClient(), text="q")
    assert legacy
    assert any("**ok**" in str(item) for item in legacy)
```

- [ ] **Step 2: Run new worker tests — expect FAIL**

Run: `pytest tests/test_telegram_integration.py::test_make_rich_draft_id_uses_update_id tests/test_telegram_integration.py::test_handle_question_rich_messages_draft_then_final tests/test_telegram_integration.py::test_handle_question_rich_failure_falls_back -v`

Expected: FAIL (`make_rich_draft_id` missing / rich path not implemented)

- [ ] **Step 3: Implement worker helpers and branch `handle_question`**

Add imports in `scripts/telegram_bot_worker.py`:

```python
from integrations.telegram import (
    ...
    prepare_rich_markdown,
)
```

Add helpers near `_strip_sources_section`:

```python
def make_rich_draft_id(update: dict[str, Any], tg_user_id: int) -> int:
    update_id = update.get("update_id")
    if isinstance(update_id, int) and update_id != 0:
        return update_id
    mixed = (int(tg_user_id) ^ int(time.time() * 1000)) & 0x7FFFFFFF
    return mixed or 1


def _prepare_answer_markdown(markdown_text: str) -> str:
    text = markdown_text if markdown_text else "(пустой ответ)"
    if not settings.TELEGRAM_SHOW_SOURCES:
        text = _strip_sources_section(text)
    return prepare_rich_markdown(text, max_chars=settings.TELEGRAM_RICH_MAX_CHARS)
```

Refactor `handle_question` after attachment handling:

1. Keep typing `send_chat_action`.
2. If `settings.TELEGRAM_RICH_MESSAGES`:
   - `draft_id = make_rich_draft_id(update, tg_user_id)`
   - Try thinking draft: `client.send_rich_message_draft(chat_id, draft_id, {"html": "<tg-thinking>Думаю...</tg-thinking>"})` (log and continue on `TelegramError`).
   - Stream SSE as today; on throttled deltas call `send_rich_message_draft(..., {"markdown": prepare_rich_markdown(accumulated, max_chars=...)})` (ignore draft errors).
   - After stream: `answer = _prepare_answer_markdown(accumulated)`; try `client.send_rich_message(chat_id, {"markdown": answer})`; on `TelegramError` call `_send_full_answer(client, chat_id, message_id=None-path)`.
3. Else: keep existing placeholder + edit + `_send_full_answer` path unchanged.

For fallback when rich final fails and there was never a classic `message_id`, extend `_send_full_answer` to accept `message_id: int | None = None` and when `None`, send all parts via `_send_html_or_plain` without edit (index 0 also uses `message_id=None`). Update the existing call site to keep passing the placeholder id.

Concrete signature change:

```python
def _send_full_answer(
    client: TelegramClient,
    chat_id: int,
    message_id: int | None,
    markdown_text: str,
) -> None:
```

In the rich-success path, do **not** call `_send_full_answer`. Sources block after the answer stays as today (classic `send_message`).

Extract the SSE loop into a shared inner flow or duplicate carefully so both rich and legacy share accumulation/`session.chat_id` updates — prefer one loop with different preview callbacks to avoid drift:

```python
def _stream_chat_answer(...) -> tuple[str, list, list, bool]:
    # returns accumulated, sources, citations, stream_ok
```

Only extract if it keeps the diff readable; otherwise inline two clear branches after the POST.

Recommended structure inside `handle_question`:

```python
    use_rich = settings.TELEGRAM_RICH_MESSAGES
    draft_id = make_rich_draft_id(update, tg_user_id) if use_rich else 0
    message_id: int | None = None

    try:
        client.send_chat_action(chat_id, "typing")
    except TelegramError:
        pass

    if use_rich:
        try:
            client.send_rich_message_draft(
                chat_id,
                draft_id,
                {"html": "<tg-thinking>Думаю...</tg-thinking>"},
            )
        except TelegramError:
            logger.exception("Rich thinking draft failed")
    else:
        try:
            placeholder = client.send_message(chat_id, "⏳ Думаю...")
            message_id = placeholder["result"]["message_id"]
        except TelegramError:
            logger.exception("Не удалось отправить placeholder для chat_id=%s", chat_id)
            return

    # ... same POST + SSE loop ...
    # in delta throttle:
    if use_rich and accumulated:
        try:
            client.send_rich_message_draft(
                chat_id,
                draft_id,
                {
                    "markdown": prepare_rich_markdown(
                        accumulated, max_chars=settings.TELEGRAM_RICH_MAX_CHARS
                    )
                },
            )
        except TelegramError:
            pass
    elif message_id is not None and accumulated:
        _edit_streaming_preview(...)

    # final:
    answer_text = accumulated
    if not settings.TELEGRAM_SHOW_SOURCES:
        answer_text = _strip_sources_section(answer_text)
    if use_rich:
        rich_body = prepare_rich_markdown(
            answer_text if answer_text else "(пустой ответ)",
            max_chars=settings.TELEGRAM_RICH_MAX_CHARS,
        )
        try:
            client.send_rich_message(chat_id, {"markdown": rich_body})
        except TelegramError:
            logger.exception("Rich final failed; falling back to HTML")
            _send_full_answer(client, chat_id, message_id, answer_text)
    else:
        _send_full_answer(client, chat_id, message_id, answer_text)
```

Also add a quick test that `TELEGRAM_RICH_MESSAGES=false` still creates classic placeholder (optional but recommended):

```python
def test_handle_question_legacy_when_rich_disabled(monkeypatch):
    # monkeypatch TELEGRAM_RICH_MESSAGES=False
    # FakeClient tracks send_message("⏳ Думаю...") and edit/final via _send_full_answer mock
    # assert no send_rich_message*
```

- [ ] **Step 4: Run telegram integration tests**

Run: `pytest tests/test_telegram_integration.py -v`  
Expected: all PASS

- [ ] **Step 5: Commit** (only if user asks)

```bash
git add scripts/telegram_bot_worker.py tests/test_telegram_integration.py
git commit -m "$(cat <<'EOF'
feat(telegram): stream Q&A answers as Rich Messages

EOF
)"
```

---

### Task 3: Documentation

**Files:**
- Modify: `docs/telegram_bot_setup.md`
- Modify: `docs/superpowers/specs/2026-08-04-telegram-rich-messages-design.md` (Status → Accepted)

**Interfaces:**
- Consumes: settings names from Task 1
- Produces: operator-facing docs matching behavior

- [ ] **Step 1: Update setup doc section 2 env list and section 7 limits**

In `docs/telegram_bot_setup.md` additional settings block, add:

```env
# Rich Messages (Bot API 10.1+): таблицы и GFM в ответах агента
TELEGRAM_RICH_MESSAGES=true
TELEGRAM_RICH_MAX_CHARS=32000
```

Replace/extend «Ограничения» to state:

- Successful rich answers: up to ~32000 characters; GFM tables/headings/lists supported via `sendRichMessage`.
- Streaming uses `sendRichMessageDraft` (ephemeral preview); final message is always `sendRichMessage`.
- If rich fails or `TELEGRAM_RICH_MESSAGES=false`, legacy HTML path applies with `TELEGRAM_MAX_MESSAGE_LENGTH` (4096) and optional «Часть N/M» split.

- [ ] **Step 2: Mark spec Accepted**

Change header `**Status:** Draft for review` → `**Status:** Accepted`.

- [ ] **Step 3: No automated test** — docs-only; skim that env names match `config/settings.py`.

- [ ] **Step 4: Commit** (only if user asks)

```bash
git add docs/telegram_bot_setup.md docs/superpowers/specs/2026-08-04-telegram-rich-messages-design.md
git commit -m "$(cat <<'EOF'
docs(telegram): document Rich Messages for agent replies

EOF
)"
```

---

## Spec coverage checklist

| Spec requirement | Task |
|------------------|------|
| `sendRichMessage` / draft client methods | Task 1 |
| Markdown-first Q&A | Task 2 |
| Thinking `<tg-thinking>` draft | Task 2 |
| Throttled markdown drafts | Task 2 |
| Final `sendRichMessage` | Task 2 |
| Flag off → legacy path | Task 2 |
| Rich failure → `_send_full_answer` | Task 2 |
| Truncate `TELEGRAM_RICH_MAX_CHARS` | Task 1–2 |
| Strip sources when hidden | Task 2 |
| Sources still classic message | Task 2 (unchanged block) |
| Settings + `.env.example` | Task 1 |
| Setup docs | Task 3 |
| Commands unchanged | (no code change) |
