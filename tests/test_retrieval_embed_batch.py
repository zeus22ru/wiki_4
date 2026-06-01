# -*- coding: utf-8 -*-
"""Тесты пакетных эмбеддингов и in-request кэша в hybrid retrieval."""

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
