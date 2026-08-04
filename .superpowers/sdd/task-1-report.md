# Task 1 Report: Settings + Rich Markdown Helpers + TelegramClient Rich Methods

**Date:** 2026-08-04  
**Status:** DONE  
**Scope:** Task 1 of Telegram Rich Messages — settings, `validate_rich_message`, `prepare_rich_markdown`, `TelegramClient.send_rich_message` / `send_rich_message_draft`

## Summary

Implemented the foundation layer for Telegram Rich Messages per the task brief. Added two config settings, two helper functions, and two new `TelegramClient` methods. Did not modify `scripts/telegram_bot_worker.py` (Task 2). No commit per global constraint.

## Files Changed

| File | Change |
|------|--------|
| `config/settings.py` | Added `TELEGRAM_RICH_MESSAGES` (default `true`), `TELEGRAM_RICH_MAX_CHARS` (default `32000`) after `TELEGRAM_SHOW_SOURCES` |
| `.env.example` | Documented both new settings (commented) |
| `integrations/telegram.py` | Added `validate_rich_message`, `prepare_rich_markdown`, `send_rich_message`, `send_rich_message_draft` |
| `tests/test_telegram_integration.py` | Appended four unit tests |

## TDD Evidence

### Step 1 — Write failing tests

Appended four tests to `tests/test_telegram_integration.py`:

- `test_validate_rich_message_requires_exactly_one_representation`
- `test_prepare_rich_markdown_truncates`
- `test_telegram_client_send_rich_message`
- `test_telegram_client_send_rich_message_draft`

`pytest` was already imported at the top of the test file.

### Step 2 — RED (expect FAIL)

```text
Command:
.venv\Scripts\python.exe -m pytest \
  tests/test_telegram_integration.py::test_validate_rich_message_requires_exactly_one_representation \
  tests/test_telegram_integration.py::test_prepare_rich_markdown_truncates \
  tests/test_telegram_integration.py::test_telegram_client_send_rich_message \
  tests/test_telegram_integration.py::test_telegram_client_send_rich_message_draft -v

Result: 4 failed

Failures:
- test_validate_rich_message_requires_exactly_one_representation
  ImportError: cannot import name 'validate_rich_message' from 'integrations.telegram'
- test_prepare_rich_markdown_truncates
  ImportError: cannot import name 'prepare_rich_markdown' from 'integrations.telegram'
- test_telegram_client_send_rich_message
  AttributeError: 'TelegramClient' object has no attribute 'send_rich_message'
- test_telegram_client_send_rich_message_draft
  AttributeError: 'TelegramClient' object has no attribute 'send_rich_message_draft'
```

### Step 3 — Implementation

**`config/settings.py`** (after `TELEGRAM_SHOW_SOURCES`):

```python
TELEGRAM_RICH_MESSAGES: bool = os.getenv("TELEGRAM_RICH_MESSAGES", "true").lower() == "true"
TELEGRAM_RICH_MAX_CHARS: int = int(os.getenv("TELEGRAM_RICH_MAX_CHARS", "32000"))
```

**`.env.example`** (after `TELEGRAM_SHOW_SOURCES`):

```env
#TELEGRAM_RICH_MESSAGES=true
#TELEGRAM_RICH_MAX_CHARS=32000
```

**`integrations/telegram.py`** — helpers placed before `TelegramError`; client methods after `send_message`:

- `validate_rich_message(rich_message)` — requires exactly one of `markdown`, `html`, `blocks`; raises `ValueError` otherwise
- `prepare_rich_markdown(text, *, max_chars)` — truncates with ellipsis (`…`) when over limit
- `TelegramClient.send_rich_message(chat_id, rich_message, *, reply_markup=None)` → `_request("sendRichMessage", ...)`
- `TelegramClient.send_rich_message_draft(chat_id, draft_id, rich_message)` → `_request("sendRichMessageDraft", ...)`; rejects zero `draft_id`

### Step 4 — GREEN (expect PASS)

```text
Command: (same as Step 2)

Result: 4 passed in 1.38s

tests/test_telegram_integration.py::test_validate_rich_message_requires_exactly_one_representation PASSED
tests/test_telegram_integration.py::test_prepare_rich_markdown_truncates PASSED
tests/test_telegram_integration.py::test_telegram_client_send_rich_message PASSED
tests/test_telegram_integration.py::test_telegram_client_send_rich_message_draft PASSED
```

### Step 5 — Commit

Skipped per global constraint (commit only when user asks).

## Self-Review

| Check | Result |
|-------|--------|
| Matches brief verbatim (settings values, helper logic, method signatures) | Yes |
| `telegram_bot_worker.py` untouched | Yes |
| Helpers validate exactly one representation key | Yes |
| `prepare_rich_markdown` handles `max_chars <= 0`, `max_chars == 1`, and ellipsis truncation | Yes |
| `send_rich_message` passes validated `rich_message` and optional `reply_markup` | Yes |
| `send_rich_message_draft` requires non-zero `draft_id` | Yes |
| Linter errors on changed files | None |
| Existing test file imports unchanged (local imports in new tests per brief) | Yes |

## Concerns

None. Settings are not covered by dedicated unit tests in this task (brief only specified the four helper/client tests). Task 2 will wire these into the worker.

## Next Steps (Task 2)

- Integrate rich draft/final send path in `scripts/telegram_bot_worker.py`
- Use `settings.TELEGRAM_RICH_MESSAGES` flag and `prepare_rich_markdown` with `TELEGRAM_RICH_MAX_CHARS`
- Fallback to legacy HTML path on failure or when flag is off
