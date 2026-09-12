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

