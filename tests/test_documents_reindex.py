# -*- coding: utf-8 -*-
"""Регрессии для фоновой переиндексации документов."""

from unittest.mock import MagicMock

import pytest
from werkzeug.security import generate_password_hash


def _login_admin(client) -> None:
    from core.chat_history import get_chat_history

    get_chat_history().create_user(
        username="admin",
        email="admin@example.com",
        password_hash=generate_password_hash("password123"),
        role="admin",
    )
    rv = client.post("/api/auth/login", json={"identifier": "admin", "password": "password123"})
    assert rv.status_code == 200


@pytest.fixture(autouse=True)
def clear_reindex_jobs():
    from api.routes import documents

    with documents._jobs_lock:
        documents._jobs.clear()
    yield
    with documents._jobs_lock:
        documents._jobs.clear()


def test_reindex_rejects_parallel_job(client, monkeypatch):
    from api.routes import documents

    _login_admin(client)

    class FakeThread:
        def __init__(self, target, args=(), daemon=None):
            self.target = target
            self.args = args
            self.daemon = daemon

        def start(self):
            return None

    monkeypatch.setattr(documents.threading, "Thread", FakeThread)

    first = client.post("/api/documents/reindex")
    second = client.post("/api/documents/reindex")

    assert first.status_code == 202
    assert first.get_json()["job"]["status"] == "pending"
    assert second.status_code == 409
    body = second.get_json()
    assert body["error"] == "reindex_already_running"
    assert body["active_job"]["id"] == first.get_json()["job"]["id"]


def test_run_reindex_invokes_callback_on_success(monkeypatch):
    """A6/K2: после успешного job вызывается зарегистрированный callback."""
    from api.routes import documents
    import create_vector_db

    calls: list[str] = []
    documents.set_reindex_callback(lambda: calls.append("ok"))
    monkeypatch.setattr(
        create_vector_db,
        "reindex_vector_db",
        lambda progress_callback=None: {"index_mode": "incremental", "chunks_added": 1},
    )

    documents._set_job("job-1", id="job-1", status="pending", started_at="2026-06-02T00:00:00")
    try:
        documents._run_reindex("job-1")
    finally:
        documents.set_reindex_callback(None)

    with documents._jobs_lock:
        job = documents._jobs["job-1"]
    assert job["status"] == "done"
    assert calls == ["ok"]
    assert job["diagnostics"]["index_mode"] == "incremental"


def test_run_reindex_skips_callback_on_failure(monkeypatch):
    """A6: при падении reindex callback не вызывается."""
    from api.routes import documents
    import create_vector_db

    calls: list[str] = []
    documents.set_reindex_callback(lambda: calls.append("ok"))

    def _boom(progress_callback=None):
        raise RuntimeError("reindex failed")

    monkeypatch.setattr(create_vector_db, "reindex_vector_db", _boom)
    documents._set_job("job-fail", id="job-fail", status="pending", started_at="2026-06-02T00:00:00")
    try:
        documents._run_reindex("job-fail")
    finally:
        documents.set_reindex_callback(None)

    with documents._jobs_lock:
        job = documents._jobs["job-fail"]
    assert job["status"] == "failed"
    assert calls == []


def test_create_vector_db_partial_embeddings_preserves_active_collection(monkeypatch):
    import create_vector_db

    fake_client = MagicMock()
    monkeypatch.setattr(create_vector_db.chromadb, "PersistentClient", lambda path: fake_client)
    monkeypatch.setattr(create_vector_db.settings, "BATCH_SIZE", 10)
    monkeypatch.setattr(create_vector_db.settings, "EMBEDDING_WORKERS", 1)
    monkeypatch.setattr(
        create_vector_db,
        "embed_documents_batch",
        lambda docs: [
            {
                "id": docs[0]["id"],
                "text": docs[0]["text"],
                "metadata": docs[0]["metadata"],
                "embedding": [0.1, 0.2],
            }
        ],
    )

    docs = [
        {"id": "a", "text": "A", "metadata": {}, "embed_text": "A"},
        {"id": "b", "text": "B", "metadata": {}, "embed_text": "B"},
    ]
    with pytest.raises(RuntimeError, match="Получены не все эмбеддинги"):
        create_vector_db.create_vector_db(docs)

    fake_client.delete_collection.assert_not_called()
    fake_client.create_collection.assert_not_called()


def test_create_vector_db_logs_performance_summary(monkeypatch, tmp_path):
    import create_vector_db

    fake_collection = MagicMock()
    fake_client = MagicMock()
    fake_client.create_collection.return_value = fake_collection
    monkeypatch.setattr(create_vector_db.chromadb, "PersistentClient", lambda path: fake_client)
    monkeypatch.setattr(create_vector_db.settings, "BATCH_SIZE", 10)
    monkeypatch.setattr(create_vector_db.settings, "EMBEDDING_WORKERS", 1)
    monkeypatch.setattr(create_vector_db.settings, "CHROMA_COLLECTION_NAME", "wiki_test")
    monkeypatch.setattr(create_vector_db.settings, "CHROMA_PERSIST_DIR", str(tmp_path / "chroma"))
    monkeypatch.setattr(
        create_vector_db,
        "embed_documents_batch",
        lambda docs: [
            {
                "id": doc["id"],
                "text": doc["text"],
                "metadata": doc["metadata"],
                "embedding": [0.1, 0.2],
            }
            for doc in docs
        ],
    )

    bm25_path = tmp_path / "bm25_corpus.pkl"

    def fake_save_bm25(ids, texts):
        bm25_path.write_bytes(b"bm25")

    fake_logger = MagicMock()
    monkeypatch.setattr(create_vector_db, "save_bm25_index", fake_save_bm25)
    monkeypatch.setattr(create_vector_db, "bm25_index_path", lambda: bm25_path)
    monkeypatch.setattr(create_vector_db, "invalidate_embedding_cache", lambda: None)
    monkeypatch.setattr(create_vector_db, "logger", fake_logger)

    docs = [
        {"id": "a", "text": "A", "metadata": {}, "embed_text": "A"},
        {"id": "b", "text": "B", "metadata": {}, "embed_text": "B"},
    ]
    create_vector_db.create_vector_db(docs)

    info_messages = [call.args[0] for call in fake_logger.info.call_args_list if call.args]
    assert "Reindex create_vector_db summary: chunks=%s embeddings=%s skipped_embeddings=%s timings_ms=%s bm25_size_bytes=%s" in info_messages
    fake_collection.add.assert_called_once()


def test_incremental_reindex_updates_changed_document_only(monkeypatch, tmp_path):
    import create_vector_db
    from core.index_manifest import build_index_manifest

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    source = data_dir / "article.txt"
    keep = data_dir / "keep.txt"
    source.write_text("old article", encoding="utf-8")
    keep.write_text("keep", encoding="utf-8")

    manifest = build_index_manifest(
        [
            {"id": "article-0", "metadata": {"path": "article.txt", "title": "Article", "file_type": ".txt"}},
            {"id": "article-stale", "metadata": {"path": "article.txt", "title": "Article", "file_type": ".txt"}},
            {"id": "keep-0", "metadata": {"path": "keep.txt", "title": "Keep", "file_type": ".txt"}},
        ],
        data_dir=data_dir,
    )
    manifest["collection"] = "wiki_test"
    source.write_text("new article", encoding="utf-8")

    fake_collection = MagicMock()
    fake_client = MagicMock()
    fake_client.get_collection.return_value = fake_collection
    saved_bm25 = {}

    monkeypatch.setattr(create_vector_db.settings, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(create_vector_db.settings, "CHROMA_PERSIST_DIR", str(tmp_path / "chroma"))
    monkeypatch.setattr(create_vector_db.settings, "CHROMA_COLLECTION_NAME", "wiki_test")
    monkeypatch.setattr(create_vector_db.settings, "BATCH_SIZE", 10)
    monkeypatch.setattr(create_vector_db.settings, "EMBEDDING_WORKERS", 1)
    monkeypatch.setattr(create_vector_db, "load_index_manifest", lambda: manifest)
    monkeypatch.setattr(create_vector_db.chromadb, "PersistentClient", lambda path: fake_client)
    monkeypatch.setattr(create_vector_db, "load_bm25_corpus", lambda: (["article-0", "article-stale", "keep-0"], ["old", "stale", "keep"]))
    monkeypatch.setattr(create_vector_db, "save_bm25_index", lambda ids, texts: saved_bm25.update({"ids": ids, "texts": texts}))
    monkeypatch.setattr(create_vector_db, "invalidate_embedding_cache", lambda: None)
    monkeypatch.setattr(
        create_vector_db,
        "process_files",
        lambda files: [
            {
                "id": "article-0",
                "text": "new",
                "embed_text": "new embed",
                "metadata": {"path": "article.txt", "title": "Article", "file_type": ".txt"},
            }
        ],
    )
    monkeypatch.setattr(
        create_vector_db,
        "embed_documents_batch",
        lambda docs: [{**doc, "embedding": [0.1, 0.2]} for doc in docs],
    )

    diagnostics = create_vector_db.reindex_vector_db()

    assert diagnostics["index_mode"] == "incremental"
    assert diagnostics["changed_files"] == 1
    fake_collection.upsert.assert_called_once()
    assert fake_collection.upsert.call_args.kwargs["ids"] == ["article-0"]
    fake_collection.delete.assert_called_once_with(ids=["article-stale"])
    assert saved_bm25["ids"] == ["keep-0", "article-0"]
    assert saved_bm25["texts"] == ["keep", "new embed"]


def test_incremental_reindex_removes_deleted_document(monkeypatch, tmp_path):
    import create_vector_db
    from core.index_manifest import build_index_manifest, load_index_manifest

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    keep = data_dir / "keep.txt"
    deleted = data_dir / "deleted.txt"
    keep.write_text("keep", encoding="utf-8")
    deleted.write_text("gone", encoding="utf-8")

    manifest = build_index_manifest(
        [
            {"id": "keep-0", "metadata": {"path": "keep.txt", "title": "Keep", "file_type": ".txt"}},
            {"id": "deleted-0", "metadata": {"path": "deleted.txt", "title": "Deleted", "file_type": ".txt"}},
        ],
        data_dir=data_dir,
    )
    manifest["collection"] = "wiki_test"
    deleted.unlink()

    fake_collection = MagicMock()
    fake_client = MagicMock()
    fake_client.get_collection.return_value = fake_collection
    saved_bm25 = {}

    monkeypatch.setattr(create_vector_db.settings, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(create_vector_db.settings, "CHROMA_PERSIST_DIR", str(tmp_path / "chroma"))
    monkeypatch.setattr(create_vector_db.settings, "CHROMA_COLLECTION_NAME", "wiki_test")
    monkeypatch.setattr(create_vector_db, "load_index_manifest", lambda: manifest)
    monkeypatch.setattr(create_vector_db.chromadb, "PersistentClient", lambda path: fake_client)
    monkeypatch.setattr(create_vector_db, "load_bm25_corpus", lambda: (["keep-0", "deleted-0"], ["keep", "gone"]))
    monkeypatch.setattr(create_vector_db, "save_bm25_index", lambda ids, texts: saved_bm25.update({"ids": ids, "texts": texts}))
    monkeypatch.setattr(create_vector_db, "invalidate_embedding_cache", lambda: None)
    monkeypatch.setattr(create_vector_db, "process_files", lambda files: [])

    diagnostics = create_vector_db.reindex_vector_db()

    assert diagnostics["deleted_files"] == 1
    fake_collection.upsert.assert_not_called()
    fake_collection.delete.assert_called_once_with(ids=["deleted-0"])
    assert saved_bm25 == {"ids": ["keep-0"], "texts": ["keep"]}

    saved_manifest = load_index_manifest(tmp_path / "chroma" / "index_manifest.json")
    assert list(saved_manifest["files"].keys()) == ["keep.txt"]


# --- Тесты роутов потока A (не индексатора) ---


def test_upload_conflict_returns_409_without_overwrite(client, tmp_path, monkeypatch):
    """A2: повторная загрузка без overwrite -> 409 с existing."""
    from api.routes import documents

    _login_admin(client)
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    existing = uploads / "note.txt"
    existing.write_text("old", encoding="utf-8")
    monkeypatch.setattr(documents.settings, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(documents.settings, "UPLOAD_DIR", str(uploads))
    documents._invalidate_documents_cache()

    import io

    rv = client.post(
        "/api/documents/upload",
        data={"file": (io.BytesIO(b"new"), "note.txt")},
        content_type="multipart/form-data",
    )
    assert rv.status_code == 409
    body = rv.get_json()
    assert body["error"] == "exists"
    assert body["existing"]["filename"] == "note.txt"
    assert existing.read_text(encoding="utf-8") == "old"


def test_upload_overwrite_true_replaces_file(client, tmp_path, monkeypatch):
    """A2: overwrite=true перезаписывает файл."""
    from api.routes import documents

    _login_admin(client)
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    existing = uploads / "note.txt"
    existing.write_text("old", encoding="utf-8")
    monkeypatch.setattr(documents.settings, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(documents.settings, "UPLOAD_DIR", str(uploads))
    documents._invalidate_documents_cache()

    import io

    rv = client.post(
        "/api/documents/upload?overwrite=true",
        data={"file": (io.BytesIO(b"new-content"), "note.txt")},
        content_type="multipart/form-data",
    )
    assert rv.status_code == 201
    assert existing.read_bytes() == b"new-content"


def test_upload_cyrillic_filename_returns_201(client, tmp_path, monkeypatch):
    """A1: кириллическое имя документа сохраняется при загрузке в KB."""
    from api.routes import documents

    _login_admin(client)
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    monkeypatch.setattr(documents.settings, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(documents.settings, "UPLOAD_DIR", str(uploads))
    documents._invalidate_documents_cache()

    import io

    name = "Снимок экрана.txt"
    rv = client.post(
        "/api/documents/upload",
        data={"file": (io.BytesIO(b"hello"), name)},
        content_type="multipart/form-data",
    )
    assert rv.status_code == 201
    doc = rv.get_json()["document"]
    assert "Снимок" in doc["filename"]
    assert doc["filename"].endswith(".txt")
    assert (uploads / doc["filename"]).is_file()


def test_upload_screenshot_png_via_chat_attachments(client, tmp_path, monkeypatch):
    """Приёмка A: загрузка «Снимок экрана.png» в chat attachments -> 201."""
    monkeypatch.setattr("core.chat_attachments.settings.CHAT_ATTACHMENTS_DIR", str(tmp_path / "att"))
    monkeypatch.setattr(
        "core.chat_attachments.settings.CHAT_ATTACHMENT_ALLOWED_EXTENSIONS",
        ["png", "jpg", "txt"],
    )
    import io

    rv = client.post(
        "/api/chat/attachments",
        data={"files": (io.BytesIO(b"\x89PNG\r\n\x1a\n"), "Снимок экрана.png")},
        content_type="multipart/form-data",
    )
    assert rv.status_code == 201
    att = rv.get_json()["attachments"][0]
    assert "Снимок" in att["filename"]
    assert att["mime"] == "image/png"

def test_open_html_served_as_text_plain_attachment(client, tmp_path, monkeypatch):
    """A4: .html отдаётся как text/plain + attachment + nosniff."""
    from api.routes import documents

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    html_path = data_dir / "page.html"
    html_path.write_text("<script>alert(1)</script>", encoding="utf-8")
    monkeypatch.setattr(documents.settings, "DATA_DIR", str(data_dir))
    documents._invalidate_documents_cache()

    rv = client.get("/api/documents/open", query_string={"path": "page.html"})
    assert rv.status_code == 200
    assert "text/plain" in (rv.mimetype or "")
    assert rv.headers.get("X-Content-Type-Options") == "nosniff"
    cd = rv.headers.get("Content-Disposition", "")
    assert "attachment" in cd.lower()


def test_open_rejects_chat_attachments_dir(client, tmp_path, monkeypatch):
    """A7: open не отдаёт файлы из каталога вложений."""
    from api.routes import documents

    data_dir = tmp_path / "data"
    att_dir = data_dir / "chat_attachments"
    att_dir.mkdir(parents=True)
    secret = att_dir / "secret.txt"
    secret.write_text("private", encoding="utf-8")
    monkeypatch.setattr(documents.settings, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(documents.settings, "CHAT_ATTACHMENTS_DIR", str(att_dir))
    monkeypatch.setattr(documents.settings, "UPLOAD_DIR", str(data_dir / "uploads"))
    documents._invalidate_documents_cache()

    rv = client.get("/api/documents/open", query_string={"path": "chat_attachments/secret.txt"})
    assert rv.status_code == 404


def test_scan_documents_skips_attachments_dir(tmp_path, monkeypatch):
    """A7: _scan_documents пропускает CHAT_ATTACHMENTS_DIR."""
    from api.routes import documents

    data_dir = tmp_path / "data"
    kb = data_dir / "kb"
    att = data_dir / "chat_attachments"
    kb.mkdir(parents=True)
    att.mkdir(parents=True)
    (kb / "public.txt").write_text("pub", encoding="utf-8")
    (att / "private.txt").write_text("priv", encoding="utf-8")

    monkeypatch.setattr(documents.settings, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(documents.settings, "CHAT_ATTACHMENTS_DIR", str(att))
    monkeypatch.setattr(documents.settings, "UPLOAD_DIR", str(data_dir / "uploads"))
    documents._invalidate_documents_cache()

    docs = documents._scan_documents()
    paths = {d["path"] for d in docs}
    assert any("public.txt" in p for p in paths)
    assert not any("private.txt" in p for p in paths)


def test_documents_cache_used_by_related(tmp_path, monkeypatch):
    """A7: related использует кэш и не сканирует диск каждый раз."""
    from api.routes import documents

    data_dir = tmp_path / "data"
    base = data_dir / "wiki"
    base.mkdir(parents=True)
    (base / "a.txt").write_text("a", encoding="utf-8")
    (base / "b.txt").write_text("b", encoding="utf-8")
    monkeypatch.setattr(documents.settings, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(documents.settings, "CHAT_ATTACHMENTS_DIR", str(tmp_path / "att"))
    documents._invalidate_documents_cache()

    calls = {"n": 0}
    real_scan = documents._scan_documents

    def counting_scan():
        calls["n"] += 1
        return real_scan()

    monkeypatch.setattr(documents, "_scan_documents", counting_scan)
    documents._find_related_documents([{"path": "wiki/a.txt", "title": "A"}])
    documents._find_related_documents([{"path": "wiki/a.txt", "title": "A"}])
    assert calls["n"] == 1
