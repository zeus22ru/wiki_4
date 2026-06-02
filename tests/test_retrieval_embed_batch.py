# -*- coding: utf-8 -*-
"""Тесты пакетных эмбеддингов и in-request кэша в hybrid retrieval."""

import pickle
import time
from unittest.mock import MagicMock, patch

from core.retrieval import hybrid_retrieve, resolve_dense_embeddings


def _fake_vector(seed: float) -> list:
    return [seed, seed + 0.1, seed + 0.2]


@patch("core.retrieval.get_embeddings_batch")
def test_resolve_dense_embeddings_single_batch(mock_batch):
    mock_batch.return_value = [_fake_vector(1.0), _fake_vector(2.0)]
    cache: dict = {}
    emb_map, ok = resolve_dense_embeddings(
        ["запрос один", "запрос два"],
        cache,
    )
    assert ok is True
    assert mock_batch.call_count == 1
    assert mock_batch.call_args[0][0] == ["запрос один", "запрос два"]
    assert emb_map["запрос один"] == _fake_vector(1.0)
    assert cache["запрос два"] == _fake_vector(2.0)


@patch("core.retrieval.get_embeddings_batch")
def test_resolve_dense_embeddings_reuses_cache(mock_batch):
    cache = {"старый": _fake_vector(9.0)}
    mock_batch.return_value = [_fake_vector(3.0)]
    emb_map, ok = resolve_dense_embeddings(
        ["старый", "новый"],
        cache,
    )
    assert ok is True
    mock_batch.assert_called_once_with(["новый"])
    assert emb_map["старый"] == _fake_vector(9.0)
    assert emb_map["новый"] == _fake_vector(3.0)


@patch("core.retrieval._dense_rankings_parallel")
@patch("core.retrieval.resolve_dense_embeddings")
def test_hybrid_retrieve_one_embed_resolve(mock_resolve, mock_parallel):
    mock_resolve.return_value = (
        {"q1": _fake_vector(1.0), "q2": _fake_vector(2.0)},
        True,
    )
    mock_parallel.return_value = [["a"], ["b"]]

    collection = MagicMock()
    collection.get.return_value = {
        "ids": ["a", "b"],
        "documents": ["doc a", "doc b"],
        "metadatas": [{}, {}],
    }

    with patch("core.retrieval.settings") as mock_settings:
        mock_settings.RETRIEVAL_MODE = "hybrid"
        mock_settings.RAG_FUSION_CANDIDATES = 10
        mock_settings.RERANK_TOP_N = 10
        mock_settings.RERANK_ENABLED = False
        mock_settings.RRF_K_CONSTANT = 60
        mock_settings.RRF_SCORE_NORMALIZER = 0.15
        mock_settings.RAG_MIN_SCORE = 0.0

        docs, err, _diag = hybrid_retrieve(
            collection,
            ["q1", "q2"],
            ["q1"],
            lambda _q: None,
            top_k=2,
            min_score=0.0,
            reload_collection=lambda: collection,
            bm25_bundle=None,
            embedding_cache={},
        )

    assert err is None
    mock_resolve.assert_called_once()
    mock_parallel.assert_called_once()
    assert len(docs) >= 1


@patch("core.retrieval._dense_rankings_parallel")
@patch("core.retrieval.resolve_dense_embeddings")
def test_hybrid_retrieve_reports_stage_timings(mock_resolve, mock_parallel):
    mock_resolve.return_value = ({"q1": _fake_vector(1.0)}, True)
    mock_parallel.return_value = [["a"]]

    collection = MagicMock()
    collection.get.return_value = {
        "ids": ["a"],
        "documents": ["doc a"],
        "metadatas": [{}],
    }

    with patch("core.retrieval.settings") as mock_settings:
        mock_settings.RETRIEVAL_MODE = "hybrid"
        mock_settings.RAG_FUSION_CANDIDATES = 10
        mock_settings.RERANK_TOP_N = 10
        mock_settings.RERANK_ENABLED = False
        mock_settings.RRF_K_CONSTANT = 60
        mock_settings.RRF_SCORE_NORMALIZER = 0.15

        docs, err, diag = hybrid_retrieve(
            collection,
            ["q1"],
            ["q1"],
            lambda _q: None,
            top_k=1,
            min_score=0.0,
            reload_collection=lambda: collection,
            bm25_bundle=None,
            embedding_cache={},
        )

    assert err is None
    assert docs[0]["chunk_id"] == "a"
    timings = diag["timings_ms"]
    assert {"embedding_ms", "dense_chroma_ms", "rrf_ms", "chroma_fetch_ms", "total_ms"}.issubset(timings)
    assert all(isinstance(timings[key], int) and timings[key] >= 0 for key in timings)


@patch("core.retrieval.resolve_dense_embeddings")
def test_hybrid_retrieve_uses_sparse_fallback_when_dense_fails(mock_resolve):
    mock_resolve.return_value = ({}, False)

    bm25 = MagicMock()
    bm25.get_scores.return_value = [2.0, 1.0]
    collection = MagicMock()
    collection.get.return_value = {
        "ids": ["a"],
        "documents": ["doc a"],
        "metadatas": [{"title": "A"}],
    }

    with patch("core.retrieval.settings") as mock_settings:
        mock_settings.RETRIEVAL_MODE = "hybrid"
        mock_settings.RAG_FUSION_CANDIDATES = 10
        mock_settings.RERANK_TOP_N = 10
        mock_settings.RERANK_ENABLED = False
        mock_settings.RRF_K_CONSTANT = 60
        mock_settings.RRF_SCORE_NORMALIZER = 0.15

        docs, err, diag = hybrid_retrieve(
            collection,
            ["q1"],
            ["q1"],
            lambda _q: None,
            top_k=1,
            min_score=0.0,
            reload_collection=lambda: collection,
            bm25_bundle=(bm25, ["a", "b"]),
            embedding_cache={},
        )

    assert err is None
    assert docs[0]["chunk_id"] == "a"
    assert diag["degraded"] is True
    assert diag["dense_error"] == "embedding_unavailable"
    assert diag["used_sparse_fallback"] is True
    assert diag["stage"] == "sparse_fallback"


@patch("core.retrieval.get_embeddings_batch")
def test_deep_iteration_skips_cached_queries(mock_batch):
    """Вторая итерация deep: batch только для новых строк."""
    cache: dict = {}
    mock_batch.side_effect = [
        [_fake_vector(1.0), _fake_vector(2.0)],
        [_fake_vector(3.0)],
    ]

    _, ok1 = resolve_dense_embeddings(["a", "b"], cache)
    assert ok1 is True
    assert mock_batch.call_count == 1

    _, ok2 = resolve_dense_embeddings(["a", "b", "c"], cache)
    assert ok2 is True
    assert mock_batch.call_count == 2
    assert mock_batch.call_args_list[1][0][0] == ["c"]
    assert "a" in cache and "b" in cache and "c" in cache


def test_load_bm25_okapi_reuses_cache_and_invalidates(monkeypatch, tmp_path):
    import core.retrieval as retrieval

    monkeypatch.setattr(retrieval.settings, "CHROMA_PERSIST_DIR", str(tmp_path))
    monkeypatch.setattr(retrieval.settings, "BM25_INDEX_FILENAME", "bm25.pkl")
    monkeypatch.setattr(retrieval.settings, "CHROMA_COLLECTION_NAME", "wiki_test")
    monkeypatch.setattr(retrieval, "_BM25_AVAILABLE", True)
    retrieval.invalidate_bm25_cache()

    path = tmp_path / "bm25.pkl"
    path.write_bytes(pickle.dumps({"ids": ["a"], "texts": ["alpha"]}))
    build = MagicMock(side_effect=lambda ids, texts: (f"bm25-{len(build.mock_calls)}", ids))
    monkeypatch.setattr(retrieval, "build_bm25_okapi", build)

    first = retrieval.load_bm25_okapi()
    second = retrieval.load_bm25_okapi()

    assert first == second
    assert build.call_count == 1

    retrieval.save_bm25_index(["b"], ["beta"])
    third = retrieval.load_bm25_okapi()

    assert third[1] == ["b"]
    assert build.call_count == 2
    retrieval.invalidate_bm25_cache()


def test_dense_rankings_use_single_chroma_batch_query():
    import core.retrieval as retrieval

    collection = MagicMock()
    collection.query.return_value = {
        "ids": [["a"], ["b"]],
        "distances": [[0.1], [0.2]],
        "metadatas": [[{}], [{}]],
        "documents": [["doc a"], ["doc b"]],
    }

    rankings = retrieval._dense_rankings_parallel(
        collection,
        [("q1", [0.1, 0.2]), ("q2", [0.3, 0.4])],
        3,
        reload_collection=lambda: collection,
    )

    assert rankings == [["a"], ["b"]]
    collection.query.assert_called_once()
    assert collection.query.call_args.kwargs["query_embeddings"] == [[0.1, 0.2], [0.3, 0.4]]


def test_rerank_cross_encoder_caps_text(monkeypatch):
    import core.retrieval as retrieval

    seen_pairs = []

    class FakeModel:
        def predict(self, pairs, show_progress_bar=False):
            seen_pairs.extend(pairs)
            return [0.0]

    monkeypatch.setattr(retrieval.settings, "RERANK_ENABLED", True)
    monkeypatch.setattr(retrieval.settings, "RERANK_MODEL", "fake-model")
    monkeypatch.setattr(retrieval.settings, "RERANK_MAX_TEXT_CHARS", 5)
    monkeypatch.setattr(retrieval.settings, "RERANK_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr(retrieval, "_cross_encoder_model", FakeModel())
    monkeypatch.setattr(retrieval, "_cross_encoder_name", "fake-model")

    docs = [{"text": "123456789", "score": 0.1, "metadata": {}, "chunk_id": "a"}]
    out = retrieval.rerank_cross_encoder("query", docs)

    assert out[0]["chunk_id"] == "a"
    assert seen_pairs == [["query", "12345"]]


def test_rerank_cross_encoder_timeout_falls_back(monkeypatch):
    import core.retrieval as retrieval

    class SlowModel:
        def predict(self, pairs, show_progress_bar=False):
            time.sleep(0.05)
            return [10.0]

    monkeypatch.setattr(retrieval.settings, "RERANK_ENABLED", True)
    monkeypatch.setattr(retrieval.settings, "RERANK_MODEL", "slow-model")
    monkeypatch.setattr(retrieval.settings, "RERANK_MAX_TEXT_CHARS", 4000)
    monkeypatch.setattr(retrieval.settings, "RERANK_TIMEOUT_SECONDS", 0.001)
    monkeypatch.setattr(retrieval, "_cross_encoder_model", SlowModel())
    monkeypatch.setattr(retrieval, "_cross_encoder_name", "slow-model")

    docs = [{"text": "doc", "score": 0.1, "metadata": {}, "chunk_id": "a"}]

    assert retrieval.rerank_cross_encoder("query", docs) == docs
