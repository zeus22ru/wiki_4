# Task 2 Report: Toolbar markup + frontend contract ids

## Status

**DONE**

## What Was Implemented

Added two toolbar checkboxes to the RAG toolbar in `templates/index.html` and corresponding styles in `static/css/components.css`. Extended `REQUIRED_IDS` in `tests/test_frontend_contract.py` so the DOM contract guards the new element ids for Task 3 JS wiring.

### Contract ids (`tests/test_frontend_contract.py`)

Appended after `answerModeSelect`:

```python
    "followupSuggestionsToggle",
    "relatedDocsToggle",
```

### Toolbar markup (`templates/index.html`)

Inserted inside `.rag-toolbar-primary`, after the answer-mode field closing `</div>` and before `.rag-toolbar-actions`:

- `#followupSuggestionsToggle` — label «Уточнения», help-circle SVG icon, unchecked by default
- `#relatedDocsToggle` — label «Читать дальше», book-open SVG icon, unchecked by default

Both use `label.field.field--inline.rag-toolbar-check` with `input.rag-toolbar-check__input`.

### Styles (`static/css/components.css`)

Added after `.rag-toolbar .field--inline` block:

- `.rag-toolbar-check` — gap, cursor, user-select, secondary text color
- `.rag-toolbar-check__input` — size, margin, accent-color, cursor
- `.rag-toolbar-check svg` — flex-shrink
- `.rag-toolbar-check .field__label` — margin reset

## TDD Evidence

### RED (Step 2)

After extending `REQUIRED_IDS` without markup, parametrized tests `test_required_ids_present[followupSuggestionsToggle]` and `test_required_ids_present[relatedDocsToggle]` fail with `missing id=#followupSuggestionsToggle` / `missing id=#relatedDocsToggle`.

### GREEN (Step 4)

Command:
```
.\.venv\Scripts\python.exe -m pytest tests/test_frontend_contract.py -v
```

Result: **82 passed** in 0.58s, including:
- `test_required_ids_present[followupSuggestionsToggle]` — PASSED
- `test_required_ids_present[relatedDocsToggle]` — PASSED

## Files Changed

| File | Change |
|------|--------|
| `tests/test_frontend_contract.py` | Added `followupSuggestionsToggle`, `relatedDocsToggle` to `REQUIRED_IDS` |
| `templates/index.html` | Inserted two toolbar checkbox labels with SVG icons |
| `static/css/components.css` | Added `.rag-toolbar-check` styles |

## Out of Scope (per brief)

- `api/routes/documents.py` — not modified (Task 1)
- `static/script.js` — not modified (Task 3)

## Self-Review

- **Ids:** Exact contract ids `followupSuggestionsToggle`, `relatedDocsToggle` on checkbox inputs.
- **Default state:** No `checked` attributes — toggles default off.
- **Placement:** Between answer-mode field and `.rag-toolbar-actions` as specified.
- **Icons:** help-circle and book-open Lucide stroke SVGs verbatim from brief.
- **Commit:** Skipped per global constraint.

## Concerns

None blocking. Toggles are present in DOM but inert until Task 3 wires `script.js` behavior and persistence.
