# -*- coding: utf-8 -*-
"""Регрессии для фоновой переиндексации документов."""

import sys
import threading
from types import SimpleNamespace
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


def test_run_reindex_resets_long_lived_rag_state(monkeypatch):
    from api.routes import documents
    import create_vector_db

    rag = SimpleNamespace(_bm25_bundle=("old", []))
    fake_web_app = SimpleNamespace(
        init_lock=threading.Lock(),
        collection=object(),
        rag_system=rag,
        db_initialized=True,
    )
    monkeypatch.setitem(sys.modules, "web_app", fake_web_app)
    monkeypatch.setattr(
        create_vector_db,
        "reindex_vector_db",
        lambda progress_callback=None: {"index_mode": "incremental", "chunks_added": 1},
    )

    documents._set_job("job-1", id="job-1", status="pending", started_at="2026-06-02T00:00:00")
    documents._run_reindex("job-1")

    with documents._jobs_lock:
        job = documents._jobs["job-1"]
    assert job["status"] == "done"
    assert fake_web_app.collection is None
    assert fake_web_app.rag_system is None
    assert fake_web_app.db_initialized is False
    assert rag._bm25_bundle is None
    assert job["diagnostics"]["index_mode"] == "incremental"


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
