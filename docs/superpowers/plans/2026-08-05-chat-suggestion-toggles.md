# Chat Suggestion Toggles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users opt into «Можно уточнить:» and «Что читать дальше:» via two independent toolbar checkboxes (default off, `localStorage`), with related docs available to all roles.

**Architecture:** Frontend gates `loadFollowupSuggestions` / `loadRelatedDocuments` on checkbox prefs restored from `localStorage`. Toolbar markup adds two Lucide-style icon checkboxes after `#answerModeSelect`. Backend exempts `documents.related_documents` from the documents blueprint admin `before_request` (same as `open_document`).

**Tech Stack:** Flask, Jinja `templates/index.html`, vanilla `static/script.js`, `static/css/components.css`, pytest.

## Global Constraints

- Toggle ids: `followupSuggestionsToggle`, `relatedDocsToggle`
- `localStorage` keys: `chatShowFollowups`, `chatShowRelatedDocs` (`"1"` / `"0"`); missing → off
- Both toggles default **unchecked**
- No retroactive chip loading when toggling mid-conversation
- Icons: Lucide/Feather `help-circle` + `book-open`, 16×16, stroke 2, `currentColor`
- Do not add server-side user profile prefs in this plan
- Commit steps: only if the user explicitly asks to commit

---

## File map

| File | Responsibility |
|------|----------------|
| `api/routes/documents.py` | Exempt related endpoint from admin gate |
| `tests/test_web_app.py` | Non-admin can `POST /api/documents/related` |
| `tests/test_frontend_contract.py` | DOM contract for new toggle ids |
| `templates/index.html` | Checkbox + icon markup in toolbar |
| `static/script.js` | Pref helpers, init, gate loaders, drop admin guard |
| `static/css/components.css` | Toolbar checkbox+icon alignment |

---

### Task 1: Open `/api/documents/related` to non-admins

**Files:**
- Modify: `api/routes/documents.py` (before_request ~lines 24–29)
- Modify: `tests/test_web_app.py` (near `test_api_documents_related_uses_only_data_dir`)

**Interfaces:**
- Consumes: Flask `request.endpoint`, `require_admin_access()`
- Produces: `documents.related_documents` reachable without admin role (same exemption style as `documents.open_document`)

- [ ] **Step 1: Write the failing non-admin related test**

Add to `tests/test_web_app.py` after `test_api_documents_related_uses_only_data_dir`:

```python
def test_api_documents_related_allows_non_admin_user(client, tmp_path, monkeypatch):
    client.post(
        "/api/auth/register",
        json={"username": "reader", "email": "reader@example.com", "password": "password123"},
    )
    base = tmp_path / "wiki" / "printer"
    base.mkdir(parents=True)
    (base / "setup.txt").write_text("setup", encoding="utf-8")
    (base / "errors.txt").write_text("errors", encoding="utf-8")
    monkeypatch.setattr("api.routes.documents.settings.DATA_DIR", str(tmp_path))

    rv = client.post("/api/documents/related", json={
        "sources": [{"path": "wiki/printer/setup.txt", "title": "Настройка принтера"}],
    })

    assert rv.status_code == 200
    docs = rv.get_json()["documents"]
    assert docs
    assert docs[0]["path"] == "wiki/printer/errors.txt"
```

- [ ] **Step 2: Run test — expect FAIL (403)**

Run: `pytest tests/test_web_app.py::test_api_documents_related_allows_non_admin_user -v`  
Expected: FAIL with status `403` (admin-only before_request)

- [ ] **Step 3: Exempt related endpoint from admin gate**

In `api/routes/documents.py`, change:

```python
@documents_bp.before_request
def require_admin_role():
    """Управление базой знаний доступно только администраторам."""
    if request.endpoint == "documents.open_document":
        return None
    return require_admin_access()
```

to:

```python
@documents_bp.before_request
def require_admin_role():
    """Управление базой знаний доступно только администраторам."""
    if request.endpoint in {"documents.open_document", "documents.related_documents"}:
        return None
    return require_admin_access()
```

- [ ] **Step 4: Run related + open document tests**

Run: `pytest tests/test_web_app.py -k "documents_related or documents_open" -v`  
Expected: all PASS (including existing admin related test)

- [ ] **Step 5: Commit** (only if user asks)

```bash
git add api/routes/documents.py tests/test_web_app.py
git commit -m "Allow non-admin access to related documents API."
```

---

### Task 2: Toolbar markup + frontend contract ids

**Files:**
- Modify: `tests/test_frontend_contract.py` (`REQUIRED_IDS`)
- Modify: `templates/index.html` (inside `.rag-toolbar-primary`, after answer-mode field, before `.rag-toolbar-actions`)
- Modify: `static/css/components.css` (toolbar checkbox styles)

**Interfaces:**
- Consumes: existing `.field.field--inline`, `.rag-toolbar-primary` layout
- Produces: DOM ids `followupSuggestionsToggle`, `relatedDocsToggle` (checkbox inputs)

- [ ] **Step 1: Add failing contract ids**

In `tests/test_frontend_contract.py`, extend `REQUIRED_IDS` to include (keep alphabetical-ish placement near `exportChatBtn` / `answerModeSelect` is fine — append after `answerModeSelect`):

```python
    "answerModeSelect",
    "followupSuggestionsToggle",
    "relatedDocsToggle",
```

- [ ] **Step 2: Run contract test — expect FAIL**

Run: `pytest tests/test_frontend_contract.py -k "required_ids or ids" -v`  
If the suite uses a single test for all ids, run: `pytest tests/test_frontend_contract.py -v`  
Expected: FAIL missing `followupSuggestionsToggle` / `relatedDocsToggle`

- [ ] **Step 3: Insert toolbar checkboxes + CSS**

In `templates/index.html`, between the closing `</div>` of the answer-mode field and `<div class="rag-toolbar-actions">`, insert:

```html
                            <label class="field field--inline rag-toolbar-check" for="followupSuggestionsToggle">
                                <input type="checkbox" id="followupSuggestionsToggle" class="rag-toolbar-check__input">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                                    <circle cx="12" cy="12" r="10"/>
                                    <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/>
                                    <line x1="12" y1="17" x2="12.01" y2="17"/>
                                </svg>
                                <span class="field__label">Уточнения</span>
                            </label>
                            <label class="field field--inline rag-toolbar-check" for="relatedDocsToggle">
                                <input type="checkbox" id="relatedDocsToggle" class="rag-toolbar-check__input">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                                    <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/>
                                    <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>
                                </svg>
                                <span class="field__label">Читать дальше</span>
                            </label>
```

Do **not** set `checked` attributes (default off).

In `static/css/components.css`, after `.rag-toolbar .field--inline` block (~line 426), add:

```css
.rag-toolbar-check {
    gap: 0.4rem;
    cursor: pointer;
    user-select: none;
    color: var(--secondary-text);
}

.rag-toolbar-check__input {
    width: 1rem;
    height: 1rem;
    margin: 0;
    accent-color: var(--primary-color);
    cursor: pointer;
}

.rag-toolbar-check svg {
    flex-shrink: 0;
}

.rag-toolbar-check .field__label {
    margin: 0;
}
```

- [ ] **Step 4: Run frontend contract tests**

Run: `pytest tests/test_frontend_contract.py -v`  
Expected: PASS

- [ ] **Step 5: Commit** (only if user asks)

```bash
git add templates/index.html static/css/components.css tests/test_frontend_contract.py
git commit -m "Add toolbar toggles for follow-ups and related reading."
```

---

### Task 3: Wire prefs in `script.js` and gate loaders

**Files:**
- Modify: `static/script.js` (element consts near `answerModeSelect`; helpers; `DOMContentLoaded`; `loadFollowupSuggestions`; `loadRelatedDocuments`)

**Interfaces:**
- Consumes: `#followupSuggestionsToggle`, `#relatedDocsToggle`, `localStorage`
- Produces:
  - `isFollowupSuggestionsEnabled(): boolean`
  - `isRelatedDocsEnabled(): boolean`
  - `initChatSuggestionToggles(): void`
  - Gated calls from `schedulePostAnswerEnhancements` / loaders

- [ ] **Step 1: Add element refs + storage helpers**

Near `const answerModeSelect = ...` add:

```javascript
const followupSuggestionsToggle = document.getElementById('followupSuggestionsToggle');
const relatedDocsToggle = document.getElementById('relatedDocsToggle');
const CHAT_SHOW_FOLLOWUPS_KEY = 'chatShowFollowups';
const CHAT_SHOW_RELATED_DOCS_KEY = 'chatShowRelatedDocs';
```

Add helpers (near other small preference/storage helpers, or just above `loadFollowupSuggestions`):

```javascript
function readLocalFlag(key) {
    try {
        return localStorage.getItem(key) === '1';
    } catch (_) {
        return false;
    }
}

function writeLocalFlag(key, enabled) {
    try {
        localStorage.setItem(key, enabled ? '1' : '0');
    } catch (_) {
        /* ignore quota / private mode */
    }
}

function isFollowupSuggestionsEnabled() {
    return Boolean(followupSuggestionsToggle?.checked);
}

function isRelatedDocsEnabled() {
    return Boolean(relatedDocsToggle?.checked);
}

function initChatSuggestionToggles() {
    if (followupSuggestionsToggle) {
        followupSuggestionsToggle.checked = readLocalFlag(CHAT_SHOW_FOLLOWUPS_KEY);
        followupSuggestionsToggle.addEventListener('change', () => {
            writeLocalFlag(CHAT_SHOW_FOLLOWUPS_KEY, followupSuggestionsToggle.checked);
        });
    }
    if (relatedDocsToggle) {
        relatedDocsToggle.checked = readLocalFlag(CHAT_SHOW_RELATED_DOCS_KEY);
        relatedDocsToggle.addEventListener('change', () => {
            writeLocalFlag(CHAT_SHOW_RELATED_DOCS_KEY, relatedDocsToggle.checked);
        });
    }
}
```

- [ ] **Step 2: Call init on DOMContentLoaded**

Inside the existing `DOMContentLoaded` handler, after `syncRagToolbarDefaults();`, add:

```javascript
    initChatSuggestionToggles();
```

- [ ] **Step 3: Gate loaders; remove admin-only related guard**

At the top of `loadFollowupSuggestions`, after the existing early-return for missing message/answer/duplicate, add:

```javascript
    if (!isFollowupSuggestionsEnabled()) {
        return;
    }
```

Replace the start of `loadRelatedDocuments`:

```javascript
async function loadRelatedDocuments(messageEl, sources = []) {
    if (currentAuth.role !== 'admin') {
        return;
    }
    if (!messageEl || !sources.length || messageEl.querySelector('.related-documents')) {
        return;
    }
```

with:

```javascript
async function loadRelatedDocuments(messageEl, sources = []) {
    if (!isRelatedDocsEnabled()) {
        return;
    }
    if (!messageEl || !sources.length || messageEl.querySelector('.related-documents')) {
        return;
    }
```

Leave `schedulePostAnswerEnhancements` as-is (always schedules both); the loaders no-op when toggles are off so deferred work stays cheap.

- [ ] **Step 4: Sanity-check with contract + related API tests**

Run: `pytest tests/test_frontend_contract.py tests/test_web_app.py -k "documents_related or required or frontend" -v`  
Expected: PASS for related + frontend contract tests involved

Manual smoke (optional but recommended):
1. Hard refresh chat → both checkboxes unchecked → answer → no «Можно уточнить:» / «Что читать дальше:»
2. Enable «Уточнения» only → next answer → only follow-ups
3. Enable «Читать дальше» as non-admin → next answer → related chips; chip opens `/api/documents/open`
4. Reload page → checkbox states restored from `localStorage`

- [ ] **Step 5: Commit** (only if user asks)

```bash
git add static/script.js
git commit -m "Persist and gate chat suggestion toggles in the toolbar."
```

---

## Spec coverage self-review

| Spec requirement | Task |
|------------------|------|
| Two independent toggles after answer mode | Task 2 |
| Icons help-circle + book-open | Task 2 |
| `localStorage` keys + default off | Task 3 |
| Gate follow-ups / related on toggles | Task 3 |
| No retroactive update | Task 3 (change handlers only write storage) |
| Related for all roles (drop JS admin guard) | Task 3 |
| Exempt related API from admin before_request | Task 1 |
| Frontend contract ids | Task 2 |
| Non-admin related API test | Task 1 |
| Server profile deferred | Out of scope (no task) |

**Note on spec testing line about “unauthenticated denied”:** `open_document` is public after exemption; related follows the same pattern, so guests may also call related. Product gate is the UI toggle + chat flow. Do **not** add a new login middleware unless a follow-up spec requires it.

**Placeholder scan:** none.  
**Name consistency:** ids/keys match spec exactly.
