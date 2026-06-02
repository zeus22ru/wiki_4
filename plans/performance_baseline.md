# Performance Baseline

Дата: 2026-06-02  
Контекст: Phase 5 из `plans/audit_remediation_plan.md` — наблюдаемость перед оптимизациями Phase 6.

## Что инструментировано

- Retrieval/RAG diagnostics:
  - `query_expansion_ms`;
  - `embedding_ms`;
  - `dense_chroma_ms`;
  - `bm25_load_ms`;
  - `bm25_search_ms`;
  - `rrf_ms`;
  - `chroma_fetch_ms`;
  - `rerank_ms`, если rerank включён;
  - `retrieve_total_ms`;
  - `prompt_ms`;
  - `llm_generation_ms`;
  - `citation_enrich_ms`;
  - `total_ms`.
- Reindex logs:
  - per-file `extraction_ms`, `chunk_ms`, `total_ms`, `chunks`, `skipped`;
  - processing summary: file count, chunk count, skipped/failed files, total processing time;
  - create-vector summary: prepare/embed/Chroma-save/BM25-save/total timings, chunk count, embedding count, skipped embeddings, BM25 file size.
- Admin overview:
  - endpoint-level `diagnostics.timings_ms`;
  - storage sizes for SQLite DB, Chroma directory, BM25 index.

## Local Baseline

Команда измерения: lightweight Python snippet без LLM generation.

```json
{
  "sqlite_db_bytes": 4726784,
  "chroma_dir_bytes": 257227972,
  "bm25_index_bytes": 3118523,
  "bm25_load_ms": 193,
  "bm25_loaded": true,
  "bm25_docs": 1263,
  "chroma_ok": true,
  "chroma_count": 1263,
  "chroma_error": null,
  "chroma_count_ms": 213
}
```

## Verification Baseline

- Focused diagnostics tests: `11 passed`.
- Full suite: `93 passed`, warnings only from external/deprecated dependencies already present (`chromadb`, Pydantic v1 validators).
- IDE lints for edited files: no errors.

## Not Measured

- Live LLM generation latency was not measured in this pass to avoid depending on local model/server state.
- Full reindex wall-clock was not run because it would mutate the active Chroma/BM25 index and can be expensive. The reindex path now logs the required stage timings on the next real run.
- Frontend stream render metrics were left untouched because Phase 4/other workers own stream rendering, and backend stream diagnostics now expose generation/total timings without adding browser noise.

## Phase 6 Recommendation

Prioritize BM25 lifecycle optimization before algorithmic retrieval changes:

- Current baseline loads/builds BM25 in about 193 ms for 1263 chunks. This is already visible on cold retrieval/admin paths and will grow with corpus size.
- `RAGSystem` already has a BM25 bundle cache, so the next useful Phase 6 step is to make cache invalidation/reload explicit around reindex and avoid repeated BM25 rebuilds in any path that bypasses the cache.
- After BM25 load is stable, compare `dense_chroma_ms` and `chroma_fetch_ms` from real query logs before changing RRF/rerank parameters.
