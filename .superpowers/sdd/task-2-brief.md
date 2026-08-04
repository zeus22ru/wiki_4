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

