# Task 1 Report: Open `/api/documents/related` to non-admins

## Status

**DONE**

## What Was Implemented

Exempted the `documents.related_documents` endpoint from the documents blueprint admin `before_request` gate, using the same pattern already applied to `documents.open_document`. Non-admin registered users can now call `POST /api/documents/related` and receive related document suggestions without a 403.

### Code change (`api/routes/documents.py`)

```python
@documents_bp.before_request
def require_admin_role():
    """Управление базой знаний доступно только администраторам."""
    if request.endpoint in {"documents.open_document", "documents.related_documents"}:
        return None
    return require_admin_access()
```

### Test added (`tests/test_web_app.py`)

`test_api_documents_related_allows_non_admin_user` — registers a non-admin user (`reader`), sets up fixture files under a temp `DATA_DIR`, posts to `/api/documents/related`, and asserts HTTP 200 with the expected related document path.

## TDD Evidence

### RED (Step 2)

Command:
```
.\.venv\Scripts\python.exe -m pytest tests/test_web_app.py::test_api_documents_related_allows_non_admin_user -v
```

Result: **FAILED** — `assert 403 == 200` (admin-only `before_request` blocked the request as expected).

### GREEN (Step 4)

Command:
```
.\.venv\Scripts\python.exe -m pytest tests/test_web_app.py -k "documents_related or documents_open" -v
```

Result: **4 passed** (24 deselected):
- `test_api_documents_related_uses_only_data_dir` — existing admin test, still passes
- `test_api_documents_related_allows_non_admin_user` — new non-admin test, passes
- `test_api_documents_open_serves_file_inside_data_dir` — regression check on sibling exemption
- `test_api_documents_open_rejects_path_outside_data_dir` — regression check on sibling exemption

## Files Changed

| File | Change |
|------|--------|
| `api/routes/documents.py` | Added `documents.related_documents` to admin `before_request` exemption set |
| `tests/test_web_app.py` | Added `test_api_documents_related_allows_non_admin_user` after existing related test |

## Self-Review

- **Scope:** Minimal, focused diff — only the exemption line and one test; no unrelated changes.
- **Pattern consistency:** Matches existing `open_document` exemption style (`request.endpoint in {...}`).
- **Regression:** Existing admin related test and both open-document tests still pass.
- **Security posture:** Unchanged for all other documents blueprint routes (upload, delete, indexing, etc. remain admin-only). Per spec, unauthenticated callers can also hit related (same as `open_document`); product gating is deferred to Task 2/3 UI toggles.
- **Commit:** Skipped per global constraint (user did not request commit).

## Concerns

None blocking. Note for downstream tasks: the endpoint is now reachable without admin role (and without login, mirroring `open_document`). Task 2/3 will add client-side toggles; no server-side auth middleware was added, which is intentional per the design spec.
