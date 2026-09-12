# Task 3 Report: Wire prefs in `script.js` and gate loaders

## Status

**DONE**

## What Was Implemented

Wired toolbar suggestion toggles in `static/script.js` to persist preferences in `localStorage` and gate deferred post-answer loaders. Removed the admin-only guard from `loadRelatedDocuments` so related docs are available to all roles when the toggle is enabled.

### Element refs + storage keys (`static/script.js`)

Added after `answerModeSelect`:

```javascript
const followupSuggestionsToggle = document.getElementById('followupSuggestionsToggle');
const relatedDocsToggle = document.getElementById('relatedDocsToggle');
const CHAT_SHOW_FOLLOWUPS_KEY = 'chatShowFollowups';
const CHAT_SHOW_RELATED_DOCS_KEY = 'chatShowRelatedDocs';
```

### Helpers (`static/script.js`)

Added above `loadFollowupSuggestions`:

- `readLocalFlag(key)` — reads `localStorage`; returns `true` only when value is `'1'`, otherwise `false` (missing key → off)
- `writeLocalFlag(key, enabled)` — writes `'1'` / `'0'`; swallows quota/private-mode errors
- `isFollowupSuggestionsEnabled()` — `Boolean(followupSuggestionsToggle?.checked)`
- `isRelatedDocsEnabled()` — `Boolean(relatedDocsToggle?.checked)`
- `initChatSuggestionToggles()` — restores checkbox state from storage on load; change handlers only persist (no retroactive loading)

### DOMContentLoaded init

After `syncRagToolbarDefaults();`:

```javascript
    initChatSuggestionToggles();
```

### Loader gating

**`loadFollowupSuggestions`** — after existing early-return for missing message/answer/duplicate:

```javascript
    if (!isFollowupSuggestionsEnabled()) {
        return;
    }
```

**`loadRelatedDocuments`** — replaced admin guard:

```javascript
    if (!isRelatedDocsEnabled()) {
        return;
    }
```

`schedulePostAnswerEnhancements` left unchanged; both loaders are still scheduled but no-op cheaply when toggles are off.

## Test Evidence

Command:
```
.\.venv\Scripts\python.exe -m pytest tests/test_frontend_contract.py tests/test_web_app.py -k "documents_related or required or frontend" -v
```

Result: **84 passed**, 26 deselected in 2.95s, including:

- `test_required_ids_present[followupSuggestionsToggle]` — PASSED
- `test_required_ids_present[relatedDocsToggle]` — PASSED
- `test_api_documents_related_uses_only_data_dir` — PASSED
- `test_api_documents_related_allows_non_admin_user` — PASSED

## Files Changed

| File | Change |
|------|--------|
| `static/script.js` | Element refs, storage helpers, `initChatSuggestionToggles`, gated loaders, removed admin guard on related docs |

## Spec Coverage

| Requirement | Status |
|-------------|--------|
| `localStorage` keys `chatShowFollowups` / `chatShowRelatedDocs`, default off | Done |
| Gate `loadFollowupSuggestions` / `loadRelatedDocuments` on toggles | Done |
| No retroactive loading on toggle change | Done (handlers only write storage) |
| Related for all roles (drop JS admin guard) | Done |
| `schedulePostAnswerEnhancements` unchanged | Done |

## Manual Smoke (not run in CI)

Recommended checks from brief:

1. Hard refresh → both unchecked → answer → no «Можно уточнить:» / «Что читать дальше:»
2. Enable «Уточнения» only → next answer → follow-ups only
3. Enable «Читать дальше» as non-admin → related chips; chip opens `/api/documents/open`
4. Reload → checkbox states restored from `localStorage`

## Self-Review

- **Keys:** Exact `chatShowFollowups`, `chatShowRelatedDocs` with `'1'`/`'0'` encoding.
- **Default:** Missing storage → `readLocalFlag` returns `false` → unchecked.
- **No retroactive load:** Change listeners call `writeLocalFlag` only.
- **Admin guard removed:** Only from `loadRelatedDocuments`; other admin checks elsewhere unchanged.
- **Commit:** Skipped per task override.

## Concerns

None blocking. Manual smoke not executed in this session; automated contract + related API tests pass.

## Final-review fixes

### Changes

1. **`tests/test_web_app.py`**
   - Added `test_api_documents_related_allows_guest_without_auth` — no login/register; same `tmp_path` + `DATA_DIR` monkeypatch pattern; asserts `POST /api/documents/related` returns 200 with non-empty documents and expected `wiki/printer/errors.txt` path.
   - Hardened `test_api_documents_related_allows_non_admin_user` — assert registration returns 201 before calling related.

2. **`static/css/components.css`**
   - Moved checkbox gap to `.rag-toolbar .rag-toolbar-check { gap: 0.4rem; }` so it wins over `.rag-toolbar .field--inline { gap: 0.65rem; }`.
   - Left `.rag-toolbar-check .field__label { margin: 0 }` (label is used in markup).

### Commands run

```
.\.venv\Scripts\python.exe -m pytest tests/test_web_app.py -k "documents_related or documents_open" -v
.\.venv\Scripts\python.exe -m pytest tests/test_frontend_contract.py -q
```

### Results

- `test_web_app.py` (related/open filter): **5 passed**, 24 deselected, 2 warnings, 2.95s
  - `test_api_documents_related_uses_only_data_dir` — PASSED
  - `test_api_documents_related_allows_guest_without_auth` — PASSED
  - `test_api_documents_related_allows_non_admin_user` — PASSED
  - `test_api_documents_open_serves_file_inside_data_dir` — PASSED
  - `test_api_documents_open_rejects_path_outside_data_dir` — PASSED
- `test_frontend_contract.py`: **82 passed** in 0.42s
