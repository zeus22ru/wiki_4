# -*- coding: utf-8 -*-
"""Тесты manifest-основы для будущего incremental reindex."""

from core.index_manifest import (
    build_index_manifest,
    diff_manifest_against_files,
    save_index_manifest,
)


def test_index_manifest_tracks_file_signature_and_chunk_ids(monkeypatch, tmp_path):
    import core.index_manifest as index_manifest

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    source = data_dir / "article.txt"
    source.write_text("alpha", encoding="utf-8")
    manifest_file = tmp_path / "chroma" / "index_manifest.json"

    monkeypatch.setattr(index_manifest.settings, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(index_manifest.settings, "CHROMA_PERSIST_DIR", str(manifest_file.parent))
    monkeypatch.setattr(index_manifest.settings, "CHROMA_COLLECTION_NAME", "wiki_test")

    documents = [
        {
            "id": "chunk-1",
            "metadata": {"path": "article.txt", "title": "Article", "file_type": ".txt"},
        },
        {
            "id": "chunk-2",
            "metadata": {"path": "article.txt", "title": "Article", "file_type": ".txt"},
        },
    ]

    manifest = save_index_manifest(documents, path=manifest_file)
    entry = manifest["files"]["article.txt"]

    assert manifest_file.is_file()
    assert entry["chunk_ids"] == ["chunk-1", "chunk-2"]
    assert entry["size_bytes"] == 5
    assert entry["sha256"]
    assert entry["exists"] is True


def test_index_manifest_diff_reports_changed_and_deleted(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    source = data_dir / "article.txt"
    source.write_text("alpha", encoding="utf-8")
    deleted = data_dir / "deleted.txt"
    deleted.write_text("gone", encoding="utf-8")

    manifest = build_index_manifest(
        [
            {"id": "chunk-1", "metadata": {"path": "article.txt"}},
            {"id": "chunk-2", "metadata": {"path": "deleted.txt"}},
        ],
        data_dir=data_dir,
        generated_at="2026-06-02T00:00:00+00:00",
    )

    source.write_text("alpha changed", encoding="utf-8")
    deleted.unlink()

    diff = diff_manifest_against_files(manifest, data_dir=data_dir)

    assert diff == {"changed": ["article.txt"], "deleted": ["deleted.txt"]}
