#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Утилита для "корзинок" coverage (как в DeepResearch-подходе):
- export: собрать вопросы из слабых ответов (SQLite history) в JSONL
- run: прогнать JSONL и сравнить метрики retrieval (hit-rate, best-score, latency)

Примеры:
  python scripts/eval_coverage_basket.py export --out data/evals/coverage_basket.jsonl --limit 200
  python scripts/eval_coverage_basket.py run --in data/evals/coverage_basket.jsonl --out data/evals/report_deep.json --deep true
  python scripts/eval_coverage_basket.py run --in data/evals/coverage_basket.jsonl --out data/evals/report_base.json --deep false
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from config import settings, get_logger, inference_server_reachable
from core.chat_history import get_chat_history
from core.rag import RAGSystem

logger = get_logger(__name__)


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> int:
    _ensure_parent(path)
    n = 0
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    return n


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                out.append(obj)
    return out


def export_basket(out_path: Path, limit: int) -> None:
    chat_history = get_chat_history()
    weak = chat_history.get_weak_answers(limit=limit)
    rows = []
    for item in weak:
        q = (item.get("question") or "").strip()
        if not q:
            continue
        rows.append({
            "question": q,
            "reason": item.get("reason"),
            "created_at": item.get("created_at"),
            "session_id": item.get("session_id"),
            "message_id": item.get("message_id"),
        })
    n = _write_jsonl(out_path, rows)
    logger.info("Export корзинки coverage: %s вопросов -> %s", n, out_path)


@dataclass
class RunMetrics:
    total: int = 0
    hits: int = 0
    no_docs: int = 0
    embedding_unavailable: int = 0
    search_error: int = 0
    avg_best_score: float = 0.0
    avg_latency_ms: float = 0.0


def _best_score(documents: List[Dict[str, Any]]) -> float:
    best = 0.0
    for d in documents or []:
        s = d.get("score")
        if isinstance(s, (int, float)) and float(s) > best:
            best = float(s)
    return best


def run_basket(in_path: Path, out_path: Path, deep: bool, top_k: Optional[int], min_score: Optional[float]) -> None:
    if not inference_server_reachable():
        logger.warning(
            "Сервер инференса недоступен по OLLAMA_URL (%s). "
            "Deep retrieval и query expansion могут требовать LLM.",
            settings.OLLAMA_URL,
        )

    basket = _read_jsonl(in_path)
    rag = RAGSystem(settings.CHROMA_COLLECTION_NAME)

    metrics = RunMetrics()
    details = []
    total_best = 0.0
    total_latency = 0.0

    for idx, row in enumerate(basket, start=1):
        question = (row.get("question") or "").strip()
        if not question:
            continue
        started = time.time()
        documents, err, expansion, diagnostics = rag.retrieve_documents_auto(
            question,
            top_k=top_k,
            min_score=min_score,
            conversation_history=None,
            deep_override=deep,
        )
        latency_ms = int((time.time() - started) * 1000)
        best = _best_score(documents)
        hit = bool(documents)

        metrics.total += 1
        metrics.hits += 1 if hit else 0
        metrics.no_docs += 1 if (not hit and err is None) else 0
        metrics.embedding_unavailable += 1 if err == "embedding_unavailable" else 0
        metrics.search_error += 1 if err == "search_error" else 0

        total_best += best
        total_latency += latency_ms

        details.append({
            "idx": idx,
            "question": question,
            "hit": hit,
            "best_score": round(float(best), 4),
            "latency_ms": latency_ms,
            "error": err,
            "rewritten": expansion.get("rewritten"),
            "deep": (diagnostics or {}).get("deep"),
        })

    if metrics.total:
        metrics.avg_best_score = total_best / metrics.total
        metrics.avg_latency_ms = total_latency / metrics.total

    report = {
        "mode": "deep" if deep else "base",
        "input": str(in_path),
        "top_k": top_k,
        "min_score": min_score,
        "metrics": {
            "total": metrics.total,
            "hits": metrics.hits,
            "hit_rate": round(metrics.hits / metrics.total, 4) if metrics.total else 0.0,
            "no_docs": metrics.no_docs,
            "embedding_unavailable": metrics.embedding_unavailable,
            "search_error": metrics.search_error,
            "avg_best_score": round(metrics.avg_best_score, 4),
            "avg_latency_ms": round(metrics.avg_latency_ms, 2),
        },
        "details": details[:500],
    }
    _ensure_parent(out_path)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Report сохранён: %s", out_path)
    logger.info("Итого: total=%s hit_rate=%.2f avg_best=%.3f avg_latency=%.1fms",
                report["metrics"]["total"],
                report["metrics"]["hit_rate"],
                report["metrics"]["avg_best_score"],
                report["metrics"]["avg_latency_ms"])


def _parse_bool(value: str) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "on", "y")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_export = sub.add_parser("export", help="Экспорт coverage-корзинки из слабых ответов")
    p_export.add_argument("--out", required=True, help="Путь JSONL для записи")
    p_export.add_argument("--limit", type=int, default=200, help="Сколько вопросов выгрузить")

    p_run = sub.add_parser("run", help="Прогон корзинки и сбор метрик retrieval")
    p_run.add_argument("--in", dest="inp", required=True, help="Путь JSONL корзинки")
    p_run.add_argument("--out", required=True, help="Путь JSON отчёта")
    p_run.add_argument("--deep", default="false", help="true/false — включить deep retrieval")
    p_run.add_argument("--top-k", type=int, default=None, help="Override top_k (иначе из settings)")
    p_run.add_argument("--min-score", type=float, default=None, help="Override min_score (иначе из settings)")

    args = parser.parse_args()

    if args.cmd == "export":
        export_basket(Path(args.out), limit=int(args.limit))
        return

    if args.cmd == "run":
        run_basket(
            Path(args.inp),
            Path(args.out),
            deep=_parse_bool(args.deep),
            top_k=args.top_k,
            min_score=args.min_score,
        )
        return


if __name__ == "__main__":
    main()

