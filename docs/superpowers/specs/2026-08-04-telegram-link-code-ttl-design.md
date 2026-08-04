# Telegram link code: 24h TTL and reuse

**Date:** 2026-08-04  
**Status:** Draft for review  
**Scope:** Increase Telegram account-link code lifetime to 24 hours and return the same active code on repeated requests so it is not lost across app restarts or reopening the link modal.

## Goal

- Unused link codes remain valid for **24 hours**.
- Opening the «Привязать Telegram» modal again (or restarting the app) does **not** invalidate a still-valid unused code; the same `code` and `expires_at` are returned.

## Non-goals

- No change to post-verify permanent binding behavior.
- No new API routes or UI changes.
- No change to code format (6 digits) or verify/worker flow.
- No bulk migration of already-issued codes (existing rows keep their stored `expires_at`).

## Current behavior

- Codes are stored in SQLite `telegram_links` (`create_telegram_link` in `core/chat_history.py`) — they already survive process restart.
- Default TTL is `TELEGRAM_LINK_CODE_TTL_SECONDS=600` (10 minutes).
- Every `POST /api/telegram/link` always inserts a new code and expires any previous unused codes for that user — so reopening the modal looks like the code was “lost”.

## Approach

**Reuse active code inside `create_telegram_link`** (chosen option A).

1. Look up an unused, non-expired row for `user_id` (`used_at IS NULL` AND `expires_at > now`).
2. If found → return `{ "code", "expires_at" }` without inserting or invalidating.
3. If not found → keep current create path (invalidate leftover actives, insert new code with TTL from settings).

API contract (`POST /api/telegram/link`) and frontend (`openTelegramLinkModal`) stay unchanged.

## Config / docs

| Location | Change |
|----------|--------|
| `config/settings.py` | Default `TELEGRAM_LINK_CODE_TTL_SECONDS` → `86400` |
| `.env.example` | Comment/example → `86400` |
| `docs/telegram_bot_setup.md` | Document 24h default instead of 10 minutes |

Env override still works: set `TELEGRAM_LINK_CODE_TTL_SECONDS` in `.env` if a different TTL is needed.

## Data flow

```
POST /api/telegram/link
  → create_telegram_link(user_id)
       → SELECT active unused code for user
       → if present: return same code/expires_at
       → else: invalidate leftovers, INSERT new, return new code/expires_at
verify / worker: unchanged (expires_at check on unused codes only)
```

## Testing

- Existing tests keep using monkeypatched short TTL where needed.
- Add/adjust: second `create_telegram_link` for the same user returns the **same** `code` and `expires_at` while the first is still valid.
- Optional: assert default setting is `86400` (or document-only if env-dependent in tests).

## Out of scope / explicit decisions

- **Forced regenerate:** not required for v1; user waits for expiry or uses the shown code. (Can add a “новый код” button later.)
- **Extending TTL on reuse:** do not refresh `expires_at` when returning an existing code; lifetime stays from original creation.
