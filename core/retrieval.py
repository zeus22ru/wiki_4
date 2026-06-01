#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Гибридный поиск: плотный (Chroma) + BM25, слияние RRF, опциональный cross-encoder rerank.
"""

from __future__ import annotations

import math
import pickle
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, DefaultDict, Dict, List, MutableMapping, Optional, Sequence, Tuple

from utils.embeddings import get_embeddings_batch

from chromadb.errors import NotFoundError

from config import settings, get_logger

logger = get_logger(__name__)

# BM25 (лёгкая зависимость)
try:
    from rank_bm25 import BM25Okapi

    _BM25_AVAILABLE = True
except ImportError:
    BM25Okapi = None  # type: ignore
    _BM25_AVAILABLE = False
    logger.warning(
        "Пакет rank-bm25 не найден (pip: «rank-bm25»). BM25 и гибридный поиск отключены до установки: "
        "pip install rank-bm25  или  pip install -r requirements.txt"
    )

# Cross-encoder (тяжёлая зависимость, подгружается лениво)
_cross_encoder_model = None
_cross_encoder_name: Optional[str] = None


def _tokenize_bm25(text: str) -> List[str]:
    if not text:
        return []
    return re.findall(r"[\w\d]+", text.lower(), flags=re.UNICODE)


def bm25_index_path() -> Path:
    base = Path(settings.CHROMA_PERSIST_DIR)
    return base / settings.BM25_INDEX_FILENAME


def save_bm25_index(ids: List[str], texts: List[str]) -> None:
    """Сохранить корпус для BM25 (тот же порядок id, что в Chroma)."""
    if not _BM25_AVAILABLE:
        logger.warning(
            "Индекс BM25 не сохранён: установите пакет rank-bm25 "
            "(pip install rank-bm25 или pip install -r requirements.txt)"
        )
        return
    if len(ids) != len(texts):
        raise ValueError("ids и texts должны совпадать по длине")
    path = bm25_index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "collection": settings.CHROMA_COLLECTION_NAME,
        "ids": ids,
        "texts": texts,
    }
    with open(path, "wb") as f:
        pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
    logger.info("Сохранён BM25-индекс: %s (%s документов)", path, len(ids))


def load_bm25_corpus() -> Optional[Tuple[List[str], List[str]]]:
    """Загрузить (ids, texts) или None, если файла нет."""
    path = bm25_index_path()
    if not path.is_file():
        return None
    try:
        with open(path, "rb") as f:
            payload = pickle.load(f)
    except Exception as e:
        logger.warning("Не удалось прочитать BM25-индекс: %s", e)
        return None
    ids = payload.get("ids") or []
    texts = payload.get("texts") or []
    if len(ids) != len(texts) or not ids:
        return None
    return ids, texts


def build_bm25_okapi(ids: List[str], texts: List[str]) -> Any:
    if not _BM25_AVAILABLE:
        raise RuntimeError(
            "Пакет rank-bm25 не установлен. Выполните: pip install rank-bm25"
        )
    tokenized = [_tokenize_bm25(t) for t in texts]
    return BM25Okapi(tokenized), ids


def load_bm25_okapi() -> Optional[Tuple[Any, List[str]]]:
    corpus = load_bm25_corpus()
    if not corpus:
        return None
    ids, texts = corpus
    try:
        bm25, aligned_ids = build_bm25_okapi(ids, texts)
    except Exception as e:
        logger.warning("Ошибка построения BM25: %s", e)
        return None
    return bm25, aligned_ids


def reciprocal_rank_fusion(
    rankings: List[List[str]],
    k: int = 60,
) -> List[Tuple[str, float]]:
    """RRF: список ранжирований по chunk_id, возвращает (id, score) по убыванию score."""
    scores: DefaultDict[str, float] = defaultdict(float)
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking):
            scores[str(doc_id)] += 1.0 / (k + rank + 1)
    ordered = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return ordered


def _get_cross_encoder():
    global _cross_encoder_model, _cross_encoder_name
    if not settings.RERANK_ENABLED:
        return None
    name = (settings.RERANK_MODEL or "").strip()
    if not name:
        return None
    try:
        from sentence_transformers import CrossEncoder
    except ImportError:
        logger.warning("sentence-transformers не установлен — rerank отключён")
        return None
    if _cross_encoder_model is None or _cross_encoder_name != name:
        logger.info("Загрузка cross-encoder: %s", name)
        try:
            _cross_encoder_model = CrossEncoder(name)
            _cross_encoder_name = name
        except Exception as e:
            logger.warning(
                "Не удалось загрузить cross-encoder %s — rerank пропущен, поиск продолжается без него: %s",
                name,
                e,
            )
            return None
    return _cross_encoder_model


def _sigmoid(x: float) -> float:
    try:
        return 1.0 / (1.0 + math.exp(-x))
    except OverflowError:
        return 1.0 if x > 0 else 0.0


def rerank_cross_encoder(
    query: str,
    documents: List[Dict[str, Any]],
    top_n: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Переранжировать документы cross-encoder; score заменяется на sigmoid(logit)."""
    model = _get_cross_encoder()
    if model is None or not documents:
        return documents
    limit = top_n if top_n is not None else len(documents)
    chunk = documents[:limit]
    pairs = [[query, d.get("text") or ""] for d in chunk]
    try:
        raw_scores = model.predict(pairs, show_progress_bar=False)
    except Exception as e:
        logger.warning("Ошибка cross-encoder rerank: %s", e)
        return documents
    scored = []
    for doc, s in zip(chunk, raw_scores):
        d = dict(doc)
        try:
            fv = float(s)
        except (TypeError, ValueError):
            fv = 0.0
        d["score"] = _sigmoid(fv)
        d["rerank_score_raw"] = fv
        scored.append(d)
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored + documents[limit:]


def _chroma_query_dense(
    collection,
    query_embedding: List[float],
    n_results: int,
    reload_collection: Callable[[], Any],
) -> Tuple[List[str], List[float], List[Optional[Dict]], List[str]]:
    try:
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
        )
    except NotFoundError:
        results = reload_collection().query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
        )
    ids = (results.get("ids") or [[]])[0]
    dists = (results.get("distances") or [[]])[0]
    metas = (results.get("metadatas") or [[]])[0]
    docs = (results.get("documents") or [[]])[0]
    return ids, dists, metas, docs


def _documents_from_chroma_ids(
    collection,
    chunk_ids: Sequence[str],
    reload_collection: Callable[[], Any],
) -> Dict[str, Dict[str, Any]]:
    chunk_ids = [str(i) for i in chunk_ids if i]
    if not chunk_ids:
        return {}
    try:
        got = collection.get(ids=list(chunk_ids), include=["documents", "metadatas"])
    except NotFoundError:
        got = reload_collection().get(ids=list(chunk_ids), include=["documents", "metadatas"])
    out: Dict[str, Dict[str, Any]] = {}
    for i, cid in enumerate(got.get("ids") or []):
        doc_text = (got.get("documents") or [""])[i] if got.get("documents") else ""
        meta = (got.get("metadatas") or [None])[i]
        out[str(cid)] = {"text": doc_text or "", "metadata": meta or {}, "chunk_id": str(cid)}
    return out


def bm25_ranking(bm25: Any, id_list: List[str], query: str, top_n: int) -> List[str]:
    tokens = _tokenize_bm25(query)
    if not tokens:
        return []
    scores = bm25.get_scores(tokens)
    ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    return [id_list[i] for i in ranked[:top_n]]


def _unique_nonempty_queries(queries: Sequence[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for raw in queries:
        q = (raw or "").strip()
        if not q or q in seen:
            continue
        seen.add(q)
        out.append(q)
    return out


def resolve_dense_embeddings(
    queries: Sequence[str],
    embedding_cache: Optional[MutableMapping[str, List[float]]] = None,
) -> Tuple[Dict[str, List[float]], bool]:
    """
    Эмбеддинги для списка запросов одним batch-вызовом; пополняет embedding_cache.

    Returns:
        (query -> vector, all_ok)
    """
    cache: MutableMapping[str, List[float]] = (
        embedding_cache if embedding_cache is not None else {}
    )
    unique = _unique_nonempty_queries(queries)
    missing = [q for q in unique if not cache.get(q)]
    if missing:
        batch = get_embeddings_batch(missing)
        if len(batch) != len(missing):
            logger.error(
                "Пакет эмбеддингов для retrieval: ожидалось %s, получено %s",
                len(missing),
                len(batch),
            )
            return dict(cache), False
        for q, emb in zip(missing, batch):
            if not emb:
                return dict(cache), False
            cache[q] = emb
    return dict(cache), True


def _dense_rankings_parallel(
    collection,
    query_embeddings: List[Tuple[str, List[float]]],
    pool: int,
    reload_collection: Callable[[], Any],
) -> List[List[str]]:
    """Параллельные dense-запросы к Chroma (порядок как у query_embeddings)."""
    if not query_embeddings:
        return []
    if len(query_embeddings) == 1:
        _q, emb = query_embeddings[0]
        ids, _, _, _ = _chroma_query_dense(collection, emb, pool, reload_collection)
        return [[str(x) for x in ids]]

    max_workers = min(4, len(query_embeddings))
    results: List[Optional[List[str]]] = [None] * len(query_embeddings)

    def _one(idx: int, emb: List[float]) -> Tuple[int, List[str]]:
        ids, _, _, _ = _chroma_query_dense(collection, emb, pool, reload_collection)
        return idx, [str(x) for x in ids]

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(_one, i, emb)
            for i, (_q, emb) in enumerate(query_embeddings)
        ]
        for fut in as_completed(futures):
            idx, ranking = fut.result()
            results[idx] = ranking

    return [r if r is not None else [] for r in results]


def hybrid_retrieve(
    collection,
    query_strings_for_dense: List[str],
    query_strings_for_sparse: List[str],
    get_embedding_fn: Callable[[str], Optional[List[float]]],
    top_k: int,
    min_score: float,
    reload_collection: Callable[[], Any],
    bm25_bundle: Optional[Tuple[Any, List[str]]] = None,
    embedding_cache: Optional[MutableMapping[str, List[float]]] = None,
) -> Tuple[List[Dict[str, Any]], Optional[str], Dict[str, Any]]:
    """
    Гибридный поиск с RRF и опциональным rerank.

    Returns:
        (documents, error_code, diagnostics)
    """
    diagnostics: Dict[str, Any] = {
        "retrieval_mode": settings.RETRIEVAL_MODE,
        "queries_dense": list(query_strings_for_dense),
        "queries_sparse": list(query_strings_for_sparse),
    }
    mode = (settings.RETRIEVAL_MODE or "hybrid").lower()
    pool = max(top_k, settings.RAG_FUSION_CANDIDATES, settings.RERANK_TOP_N)

    # --- только dense ---
    if mode == "dense":
        primary_q = query_strings_for_dense[0] if query_strings_for_dense else ""
        primary_q = (primary_q or "").strip()
        emb_map, ok = resolve_dense_embeddings([primary_q], embedding_cache)
        if not ok or not primary_q:
            return [], "embedding_unavailable", diagnostics
        emb = emb_map.get(primary_q)
        if not emb:
            return [], "embedding_unavailable", diagnostics
        ids, dists, metas, docs = _chroma_query_dense(collection, emb, pool, reload_collection)
        documents = []
        for i, cid in enumerate(ids):
            score = dists[i] if i < len(dists) else 0.0
            relevance = max(0.0, min(1.0, 1.0 - float(score)))
            if relevance >= min_score:
                documents.append({
                    "text": docs[i] if i < len(docs) else "",
                    "score": relevance,
                    "metadata": metas[i] if i < len(metas) else {},
                    "chunk_id": str(cid),
                })
        documents.sort(key=lambda x: x["score"], reverse=True)
        documents = documents[:top_k]
        if settings.RERANK_ENABLED and documents:
            documents = rerank_cross_encoder(primary_q, documents, top_n=settings.RERANK_TOP_N)
            documents = [d for d in documents[:top_k] if d.get("score", 0) >= min_score]
        diagnostics["stage"] = "dense_only"
        return documents, None, diagnostics

    # --- гибрид / sparse-only ветка ---
    dense_rankings: List[List[str]] = []
    all_embeddings_ok = True
    if mode != "sparse" and query_strings_for_dense:
        emb_map, all_embeddings_ok = resolve_dense_embeddings(
            query_strings_for_dense, embedding_cache
        )
        if all_embeddings_ok:
            pairs: List[Tuple[str, List[float]]] = []
            for q in query_strings_for_dense:
                qn = (q or "").strip()
                if not qn:
                    continue
                vec = emb_map.get(qn)
                if not vec:
                    all_embeddings_ok = False
                    break
                pairs.append((qn, vec))
            if all_embeddings_ok and pairs:
                dense_rankings = _dense_rankings_parallel(
                    collection, pairs, pool, reload_collection
                )

    if mode != "sparse" and not all_embeddings_ok:
        return [], "embedding_unavailable", diagnostics

    sparse_rankings: List[List[str]] = []
    bm25 = None
    bm25_ids: List[str] = []
    if bm25_bundle:
        bm25, bm25_ids = bm25_bundle
    elif _BM25_AVAILABLE:
        loaded = load_bm25_okapi()
        if loaded:
            bm25, bm25_ids = loaded

    if bm25 is not None:
        for q in query_strings_for_sparse:
            sparse_rankings.append(bm25_ranking(bm25, bm25_ids, q, pool))

    if mode == "sparse":
        if not sparse_rankings or not any(sparse_rankings):
            diagnostics["stage"] = "sparse_empty"
            return [], None, diagnostics
        fused = reciprocal_rank_fusion(sparse_rankings, k=settings.RRF_K_CONSTANT)
    else:
        rankings_for_rrf: List[List[str]] = []
        rankings_for_rrf.extend(dense_rankings)
        rankings_for_rrf.extend(sparse_rankings)
        if not rankings_for_rrf:
            return [], "search_error", diagnostics
        fused = reciprocal_rank_fusion(rankings_for_rrf, k=settings.RRF_K_CONSTANT)

    diagnostics["rrf_fused_count"] = len(fused)
    candidate_ids = [fid for fid, _ in fused[: max(pool, settings.RERANK_TOP_N)]]
    id_to_rrf = {fid: sc for fid, sc in fused}

    chroma_map = _documents_from_chroma_ids(collection, candidate_ids, reload_collection)
    documents = []
    for cid in candidate_ids:
        if cid not in chroma_map:
            continue
        base = chroma_map[cid]
        rrf_score = id_to_rrf.get(cid, 0.0)
        # нормируем RRF для отображения (до rerank)
        documents.append({
            "text": base["text"],
            "metadata": base["metadata"],
            "chunk_id": base["chunk_id"],
            "score": min(1.0, rrf_score / settings.RRF_SCORE_NORMALIZER),
            "rrf_score": rrf_score,
        })

    if not documents:
        diagnostics["stage"] = "no_hits"
        return [], None, diagnostics

    primary_sparse_q = query_strings_for_sparse[0] if query_strings_for_sparse else ""
    primary_dense_q = query_strings_for_dense[0] if query_strings_for_dense else primary_sparse_q

    if settings.RERANK_ENABLED:
        documents = rerank_cross_encoder(primary_dense_q, documents, top_n=settings.RERANK_TOP_N)
    else:
        documents.sort(key=lambda x: x.get("score", 0), reverse=True)

    documents = [d for d in documents if d.get("score", 0) >= min_score]
    documents = documents[:top_k]
    diagnostics["stage"] = "hybrid" if mode == "hybrid" else mode
    diagnostics["final_count"] = len(documents)
    return documents, None, diagnostics
