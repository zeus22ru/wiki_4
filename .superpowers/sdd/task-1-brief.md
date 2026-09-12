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

