# Admin model select for chat & embedding

**Date:** 2026-08-04  
**Status:** Draft for review  
**Scope:** Replace text inputs for `OLLAMA_CHAT_MODEL` and `OLLAMA_EMBEDDING_MODEL` in Admin → Settings with dropdowns populated from the inference server (LM Studio `/v1/models` or Ollama `/api/tags`).

## Goal

Admin picks model ids from what the server actually exposes, instead of typing them by hand (and mistyping LM Studio ids).

## Non-goals

- No new inference backends
- No filtering chat vs embedding models by capability (LM Studio does not reliably expose that)
- No auto-load / unload of models in LM Studio
- No change to how settings are persisted (still draft → Apply → `.env`)

## Approach

**Frontend-only enhancement over existing list API** (chosen option 1).

Backend already has:

- `fetch_remote_model_ids()` in `config/settings.py` (Ollama names / LM Studio ids)
- `GET /api/models` in `web_app.py`
- Admin overview also embeds `models.available`

### Auth note

`GET /api/models` sits outside the admin blueprint and may require `X-API-Key` when `API_KEY` is set. Admin UI uses session cookies for `/api/admin/*`.

**Resolution:** use a thin admin endpoint `GET /api/admin/models` that wraps `fetch_remote_model_ids()` and inherits existing admin session auth. Response shape matches `/api/models`: `{ "models": ["id", ...] }` or `{ "error": "..." }`. No duplicate fetch logic.

This keeps the “reuse existing fetch” spirit of option 1 while making the admin UI reliable.

## UX

1. After `renderAdminSettings`, for keys `OLLAMA_CHAT_MODEL` and `OLLAMA_EMBEDDING_MODEL`, replace the text control with a select wrapper:
   - `<select class="setting-text" data-setting-input="...">` populated from the models list
   - Small «Обновить» button that re-fetches the list
2. While loading: select disabled, single placeholder option «Загрузка моделей…»
3. Current saved/draft value always present as an option (even if missing from server list), and selected
4. On fetch failure: keep a text input with the current value; show a short error under the control («Не удалось получить список моделей»)
5. Change on select updates the same draft/dirty pipeline as other settings (`updateAdminSettingsDraftFromInput`)
6. Re-render (search / collapse / discard) must re-attach selects and re-apply cached model list when available (avoid refetch on every keystroke in search; refetch on panel open and on «Обновить»)

## Data flow

```
loadAdminSettings
  → GET /api/admin/settings/schema
  → renderAdminSettings
  → ensureModelSelects()
       → GET /api/admin/models  (or use in-memory cache from last successful fetch)
       → swap text → select for the two keys
select change → draft/dirty → Apply unchanged
```

## CSS

Reuse `.setting-text` on `<select>` where possible; add minimal rules if native select height/padding differs from inputs. Refresh button: compact, next to the control, consistent with existing admin button styles.

## Testing

- Contract/unit: admin models route returns list from mocked `fetch_remote_model_ids`
- Frontend contract (if present): DOM for the two keys can be select after enhance, or document expected `data-setting-input` still present
- Manual: LM Studio running → both dropdowns list ids; select → dirty → save; stop LM Studio → fallback text + error; refresh button recovers when server is back

## Files likely touched

- `api/routes/admin.py` — `GET /models`
- `static/script.js` — enhance controls after render, cache, refresh
- `static/style.css` (and/or `static/css/components.css`) — select + refresh layout
- `tests/` — route or frontend contract coverage as fits existing patterns
