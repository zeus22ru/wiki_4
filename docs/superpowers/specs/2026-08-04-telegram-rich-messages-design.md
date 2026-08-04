# Telegram Rich Messages for agent replies

**Date:** 2026-08-04  
**Status:** Accepted  
**Scope:** Send wiki_4 Q&A answers via Telegram Bot API Rich Messages (Markdown-first), with draft streaming and legacy HTML fallback.

## Goal

- Agent answers in Telegram render as **Rich Messages**: GFM tables, headings, lists, code blocks, blockquotes, and other rich markdown supported by Bot API 10.1+.
- While the answer streams, the user sees a native draft preview (`sendRichMessageDraft`), then a persisted final message (`sendRichMessage`).
- If rich delivery fails, the bot falls back to the existing `sendMessage` / `editMessageText` HTML path so users still get an answer.

## Non-goals

- No change to account linking (`/start <code>`), `/help`, `/mode`, `/reset`, `/history`, or reply keyboards (those stay on classic `sendMessage`).
- No Rich Message media, collage, slideshow, or map blocks in v1.
- No Ephemeral Messages or Communities (Bot API 10.2) in v1.
- No structured `blocks` builder and no expansion of `markdown_to_telegram_html` into full Rich HTML.
- No LLM prompt changes specifically for Telegram formatting (only light output sanitization).

## Current behavior

- [`scripts/telegram_bot_worker.py`](../../../scripts/telegram_bot_worker.py) `handle_question` posts to `/api/chat/stream`, shows `⏳ Думаю...`, periodically `editMessageText` with plain preview, then formats the final answer via `markdown_to_telegram_html` and `sendMessage`/`editMessageText` (`parse_mode=HTML`).
- [`integrations/telegram.py`](../../../integrations/telegram.py) converts a subset of markdown (bold, headers→`<b>`, links, code/pre, bullets). **Tables and most GFM are not rendered.**
- Message length capped at `TELEGRAM_MAX_MESSAGE_LENGTH` (default 4096) with manual split into «Часть N/M».

## Approach

**Markdown-first Rich Messages** (chosen).

1. Pass the LLM answer (after light sanitization) as `InputRichMessage.markdown` — Telegram parses GFM-compatible rich markdown, including tables.
2. Stream with `sendRichMessageDraft` using a stable non-zero `draft_id` per answer; finalize with `sendRichMessage` (draft is ephemeral ~30s and does not persist by itself).
3. Keep classic HTML path as **fallback** when `TELEGRAM_RICH_MESSAGES=false` or when a rich API call fails.

### Data flow

```
User message
  → hydrate / bind check (unchanged)
  → sendRichMessageDraft(draft_id, html="<tg-thinking>…")
  → POST /api/chat/stream (SSE)
  → on delta (throttled): sendRichMessageDraft(draft_id, markdown=accumulated)
  → on done: sanitize answer
  → sendRichMessage(markdown=final)
  → on rich failure: legacy _send_full_answer (HTML/split)
  → optional sources via classic sendMessage if TELEGRAM_SHOW_SOURCES
```

### draft_id

- Must be a non-zero integer; updates with the same `draft_id` animate in the client.
- Derive from the Telegram `update_id` when available; otherwise a positive hash of `(telegram_user_id, wall_time_ms)`.

### Thinking placeholder

- First draft uses Rich HTML field with `<tg-thinking>Думаю...</tg-thinking>` (thinking block is draft-only per Bot API).
- After the first non-empty delta, drafts use `{ "markdown": accumulated }`.

### Sanitization

- Strip the sources section from the answer body when `TELEGRAM_SHOW_SOURCES` is false (existing `_strip_sources_section`).
- Truncate markdown to `TELEGRAM_RICH_MAX_CHARS` (default 32000; Bot API limit 32768).
- Do not manually rewrite tables or headings.

### Fallback rules

| Condition | Behavior |
|-----------|----------|
| `TELEGRAM_RICH_MESSAGES=false` | Entire Q&A path uses current placeholder + edit + HTML final |
| `sendRichMessage` / draft returns API error | Log; send final answer via existing `_send_full_answer` / `_edit_streaming_preview` path (may start a new classic message if no placeholder `message_id`) |
| Empty answer | Send `(пустой ответ)` via classic or rich plain text |

Commands and errors that already use `send_bot_message` stay unchanged.

## Config / docs

| Location | Change |
|----------|--------|
| `config/settings.py` | Add `TELEGRAM_RICH_MESSAGES` (default `true`), `TELEGRAM_RICH_MAX_CHARS` (default `32000`) |
| `.env.example` | Document both settings |
| `docs/telegram_bot_setup.md` | Document Rich Messages, GFM tables, 32k limit, draft streaming; keep 4096 as legacy/fallback note |

Existing: `TELEGRAM_STREAM_EDIT_INTERVAL_MS` still throttles draft updates. `TELEGRAM_MAX_MESSAGE_LENGTH` applies only to legacy/fallback.

## API surface (client)

In `TelegramClient` (`integrations/telegram.py`):

- `send_rich_message(chat_id, rich_message: dict, reply_markup=None) -> dict` → Bot API `sendRichMessage`
- `send_rich_message_draft(chat_id, draft_id: int, rich_message: dict) -> dict` → Bot API `sendRichMessageDraft`

`rich_message` must contain exactly one of `markdown`, `html`, or `blocks`. Optional: `skip_entity_detection`.

No new Flask routes.

## Testing

- Client unit tests: payloads for `sendRichMessage` / `sendRichMessageDraft` include markdown with a GFM table.
- Worker/integration with mocks: thinking draft → partial markdown draft → final `sendRichMessage`.
- Flag off: legacy path still used (placeholder + edit + HTML).
- Rich failure: fallback invokes legacy final send.
- Truncation: content longer than `TELEGRAM_RICH_MAX_CHARS` is cut before send.

## Out of scope / explicit decisions

- **Sources:** remain a separate classic `sendMessage` when enabled; not embedded as rich `<details>` in v1.
- **Split «Часть N/M»:** not used for successful rich sends (32k limit); still used only on HTML fallback.
- **Status SSE chunks:** still ignored in v1 (optional later: update thinking text).
- **Forced regenerate / session persistence:** unrelated; tracked separately from this spec.
