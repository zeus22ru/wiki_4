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
