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

