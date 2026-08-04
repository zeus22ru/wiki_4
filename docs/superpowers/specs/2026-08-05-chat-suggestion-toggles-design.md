# Chat suggestion toggles: follow-ups and related reading

**Date:** 2026-08-05  
**Status:** Draft for review  
**Scope:** Gate «Можно уточнить:» and «Что читать дальше:» behind two independent user toggles in the RAG toolbar, with Lucide-style icons, `localStorage` persistence, and related-docs access for all authenticated roles.

## Goal

- User can independently enable/disable:
  - **Уточнения** → block «Можно уточнить:» (follow-up question chips)
  - **Читать дальше** → block «Что читать дальше:» (related document chips)
- Controls live in `rag-toolbar-primary`, immediately to the right of `#answerModeSelect`, before «Скачать диалог».
- Default for a clean browser: **both off**.
- Preference applies only to **new** assistant answers (already rendered messages are not retroactively updated).
- «Читать дальше» is available to **all roles** when enabled (not admin-only).

## Non-goals

- Server-side user profile sync (deferred; `localStorage` now, profile later).
- Changing suggestion/related ranking algorithms or API payloads beyond auth.
- Retroactive loading for messages already on screen when a toggle turns on.
- Telegram / CLI surfaces — web chat UI only.

## Current behavior

- After an answer, frontend always calls `loadFollowupSuggestions` → `/api/chat/suggestions` and renders «Можно уточнить:».
- `loadRelatedDocuments` calls `/api/documents/related` but **returns early** unless `currentAuth.role === 'admin'`.
- Entire `documents` blueprint (except `open_document`) requires admin via `before_request`, so even without the JS guard non-admins cannot use related docs.
- Answer mode lives in `#answerModeSelect`; no existing pattern for these two prefs.

## Approach

**Two inline checkboxes with icons (chosen option 1)** in the same `field field--inline` toolbar pattern.

### UI

```
[Стиль ответа ▾]  [help-circle] Уточнения  [book-open] Читать дальше  |  Скачать диалог
```

| Control | Element id | Icon (Lucide/Feather 24×24, stroke 2, currentColor) | Label |
|---------|------------|------------------------------------------------------|-------|
| Follow-ups | `followupSuggestionsToggle` | `help-circle` | Уточнения |
| Related docs | `relatedDocsToggle` | `book-open` | Читать дальше |

Icons: inline SVG `width="16" height="16"`, same attributes as other toolbar/nav icons (`fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"`).

### Persistence

| Key | Values | Default if missing |
|-----|--------|--------------------|
| `chatShowFollowups` | `"1"` / `"0"` | off (`false`) |
| `chatShowRelatedDocs` | `"1"` / `"0"` | off (`false`) |

On page load: restore checkbox checked state from `localStorage`. On `change`: write immediately.

### Runtime gating

- Call `loadFollowupSuggestions` only when follow-ups toggle is on.
- Call `loadRelatedDocuments` only when related-docs toggle is on.
- Remove the `currentAuth.role !== 'admin'` early return in `loadRelatedDocuments`.
- Toggling does not add/remove chips on existing message DOM nodes.

### Backend auth

In `api/routes/documents.py` `require_admin_role` before_request, also skip admin check for endpoint `documents.related_documents` (same pattern as `documents.open_document`: return `None` for that endpoint). No new login middleware on this route; the chat UI only calls it when the user is already in the chat session. Non-admins can receive related chips when their toggle is on.

`/api/chat/suggestions` unchanged; frontend simply skips the request when the toggle is off.

## Data flow

```
Page load
  → read localStorage → set checkbox states

User toggles checkbox
  → write localStorage (no effect on existing messages)

New assistant answer finishes
  → if chatShowFollowups: POST /api/chat/suggestions → render chips
  → if chatShowRelatedDocs: POST /api/documents/related → render chips
  → click related chip → /api/documents/open?path=… (already non-admin)
```

## Files

| File | Change |
|------|--------|
| `templates/index.html` | Two checkbox fields + SVG icons after `#answerModeSelect` |
| `static/script.js` | Pref helpers, gate loaders, drop admin-only related guard |
| `static/css/components.css` | Minimal alignment for checkbox+icon labels in toolbar |
| `api/routes/documents.py` | Exempt `related_documents` from admin before_request |
| `tests/test_frontend_contract.py` | Require new toggle ids |
| `tests/test_web_app.py` (or auth/docs test) | Related API OK for non-admin authenticated user |

## Testing

- Frontend contract: `followupSuggestionsToggle` and `relatedDocsToggle` present in `index.html`.
- API: logged-in non-admin `POST /api/documents/related` returns 200 (not 403); unauthenticated still denied per existing auth rules for exempt document routes (match `open_document` behavior).
- Manual: both default off → no chips; enable each → only corresponding block on next answer; disable → no new chips; existing chips stay until new chat/answer.

## Out of scope / explicit decisions

- **Independent toggles** (not one combined control).
- **Both off by default** (opt-in).
- **localStorage only** for v1; server profile later without changing control ids/keys if possible.
- **No retroactive fetch** when enabling mid-conversation.
- **Icons:** `help-circle` + `book-open` from the existing Lucide/Feather inline set.
