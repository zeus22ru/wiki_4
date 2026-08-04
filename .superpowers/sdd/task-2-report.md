# Task 2 Report: Rich streaming path in `handle_question`

**Date:** 2026-08-04  
**Status:** DONE  
**Scope:** Task 2 of Telegram Rich Messages — wire `scripts/telegram_bot_worker.py` to use rich drafts during streaming and rich final delivery, with legacy fallback.

## Summary

Implemented the rich-message branch in `handle_question` behind `settings.TELEGRAM_RICH_MESSAGES`. The worker now sends a thinking draft, streams markdown draft updates, sends a final rich message on success, and falls back to the legacy HTML/plain path when rich final delivery fails. Added the required tests for draft id generation and rich success/fallback flows. No commit was created.

## Files Changed

| File | Change |
|------|--------|
| `scripts/telegram_bot_worker.py` | Added `make_rich_draft_id`, `_prepare_answer_markdown`, rich draft/final flow in `handle_question`, and `message_id: int | None` support in `_send_full_answer` |
| `tests/test_telegram_integration.py` | Added three worker tests for draft id, rich success flow, and rich failure fallback |

## TDD Evidence

### Step 1 — Write failing tests

Added these tests first in `tests/test_telegram_integration.py`:

- `test_make_rich_draft_id_uses_update_id`
- `test_handle_question_rich_messages_draft_then_final`
- `test_handle_question_rich_failure_falls_back`

### Step 2 — RED (expect FAIL)

```text
Command:
.venv\Scripts\python.exe -m pytest tests/test_telegram_integration.py::test_make_rich_draft_id_uses_update_id tests/test_telegram_integration.py::test_handle_question_rich_messages_draft_then_final tests/test_telegram_integration.py::test_handle_question_rich_failure_falls_back -v

Result: FAIL during collection

Failure:
ImportError: cannot import name 'make_rich_draft_id' from 'scripts.telegram_bot_worker'
```

This was the expected red state from the brief: the helper was missing and the rich worker path was not yet implemented.

### Step 3 — Implementation

Implemented the brief’s worker changes in `scripts/telegram_bot_worker.py`:

- Imported `prepare_rich_markdown`
- Added `make_rich_draft_id(update, tg_user_id)`
- Added `_prepare_answer_markdown(markdown_text)`
- Changed `_send_full_answer(..., message_id: int | None, ...)`
- In `handle_question`:
  - keep `send_chat_action("typing")`
  - when rich mode is enabled, send `<tg-thinking>Думаю...</tg-thinking>` draft
  - during SSE streaming, send throttled `send_rich_message_draft(..., {"markdown": ...})`
  - on completion, send `send_rich_message(..., {"markdown": ...})`
  - on rich final failure, fall back to `_send_full_answer(...)`
  - when rich mode is disabled, preserve the legacy placeholder/edit/final path

### Step 4 — GREEN (targeted tests)

```text
Command: same as Step 2

Result: 3 passed in 1.34s
```

### Step 5 — Full verification

```text
Command:
.venv\Scripts\python.exe -m pytest tests/test_telegram_integration.py -v

Result: 44 passed in 6.57s
```

## Self-Review

| Check | Result |
|-------|--------|
| Rich branch guarded by `TELEGRAM_RICH_MESSAGES` | Yes |
| Draft id uses `update_id` when available, else positive fallback | Yes |
| Thinking draft uses rich HTML `<tg-thinking>` | Yes |
| Streaming deltas update rich drafts with markdown | Yes |
| Final rich send uses `prepare_rich_markdown` and rich max length | Yes |
| Rich final failure falls back to legacy `_send_full_answer` | Yes |
| Legacy placeholder/edit flow remains for `TELEGRAM_RICH_MESSAGES=false` | Yes |
| Full `tests/test_telegram_integration.py` suite passes | Yes |
| Linter errors on changed files | None |

## Concerns

No blocking concerns. Test output still includes two pre-existing Pydantic deprecation warnings in `utils/validators.py`, unrelated to this task.

## Review Fix (2026-08-04)

**Finding:** When `TELEGRAM_SHOW_SOURCES=false`, rich final failure fell back to `_send_full_answer` with unstripped `answer_text`, leaking `**Источники:**` into the classic message.

**Fix:** Pass `rich_body` (from `_prepare_answer_markdown`) to `_send_full_answer` on rich final `TelegramError`, so fallback uses the same stripped markdown as the rich send.

**Test:** Updated `test_handle_question_rich_failure_falls_back` — answer includes `**Источники:**`, rich final raises `TelegramError`, asserts fallback markdown contains `**ok**` but not `**Источники:**`.

**Verification:**

```text
Command: .venv\Scripts\python.exe -m pytest tests/test_telegram_integration.py -v
Result: 44 passed in 6.55s
```

No commit created.

## Final Review Fix (2026-08-04)

**Finding:** `_prepare_answer_markdown` both stripped sources and truncated to `TELEGRAM_RICH_MAX_CHARS`. On rich final failure, fallback passed that truncated `rich_body` to `_send_full_answer`, so long answers lost content the legacy splitter could deliver.

**Fix:** Split helpers — `_sanitize_answer_markdown` (strip sources, no truncation) and `_prepare_answer_markdown` (sanitize + truncate for rich send). Rich fallback now calls `_send_full_answer` with `_sanitize_answer_markdown(answer_text)` so the full stripped answer is delivered via HTML/split.

**Test:** Added `test_handle_question_rich_failure_fallback_not_truncated` — 250-char answer, `TELEGRAM_RICH_MAX_CHARS=100`, `SHOW_SOURCES=false`, rich final raises `TelegramError`; asserts fallback length > rich max, equals full stripped body, sources not present. Existing `test_handle_question_rich_failure_falls_back` still passes.

**Verification:**

```text
Command: .venv\Scripts\python.exe -m pytest tests/test_telegram_integration.py -v
Result: 45 passed in 6.62s
```

No commit created.
