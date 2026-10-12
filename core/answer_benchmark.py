#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проверка ответов: скоринг, корзина и прогоны. Без UI."""

from __future__ import annotations

import hashlib
import json
import re
import threading
from datetime import datetime, timezone
from typing import Any, Optional

from config import settings
from core.chat_history import get_chat_history
from core.retrieval import bm25_index_path

REFUSAL_PHRASE_VERSION = "1"
REFUSAL_PHRASES = (
    "не нашёл",
    "не нашел",
    "не нашлось",
    "\u043d\u0435 \u043d\u0430\u0448\u0435\u043b\u043e\u0441\u044c",
    "нет информации",
    "нет данных",
    "недостаточно данных",
    "недостаточно информации",
    "не могу ответить",
    "в контексте нет",
    "в базе нет",
)
_STEP_MARKERS = (
    "нажмите",
    "откройте",
    "перейдите",
    "выберите",
    "установите",
    "заполните",
)
_NUMBERED_STEP_RE = re.compile(r"(?m)^\s*\d{1,2}[\.\)]\s+\S")
_SOURCES_BLOCK_RE = re.compile(r"\n\n\*\*Источники:\*\*[\s\S]*$")

SEED_QUESTIONS = (
    "Как сделать рассылку должникам?",
    "Как настроить состояние сертификации?",
    "Инструкция по добавлению пользователя в 1С",
    "Как найти ошибку в журнале регистрации?",
    "Что делать с ошибкой недостаточно прав для работы с таблицей?",
    "В документе количество поэкземплярной продукции не соответствует количеству подобронного товара",
    "Проблема с печатью ТТН",
    "Как добавить ЭЦП и сертификат?",
    "Группа товаров должна быть в архиве",
    "Пустая упаковка при отправке в EDI",
    "Перемещение не подгружается из УПП в ВМС",
    "Ошибка обновления АРМ егаис. Нет вкладки Выпуск продукции",
    "УПП, не хватает остатка ЕГАИС",
    "Как поменять статус у ТТН ЕГАИС?",
    "Как загрузить номенклатуру на кассу в базу УПП?",
    "Что делать с ошибкой конфликт блокировок?",
    "Не проводится документ требование накладная, что делать?",
    "Как активировать лицензии дата мобайл?",
    "Как настраивается АТС переадресации?",
    "Чеклист работы УТМ",
)

ANSWER_LABELS = {
    "substantive": "содержательный",
    "refusal": "отказ",
    "unclear": "неясно",
    "facts_mismatch": "факты не сошлись",
    "abstained_despite_hit": "отказался, хотя документ есть",
    "correct_abstain": "отказался правильно",
    "false_answer": "ответил, хотя ответа нет",
    "infra_error": "ошибка",
    "skipped_before_search": "до поиска",
}
SEARCH_LABELS = {
    "unlabeled": "без эталона",
    "search_hit": "найден",
    "search_miss": "не найден",
    "search_empty": "пусто",
    "search_neighbors": "соседи",
    "skipped_before_search": "до поиска",
    "infra_error": "ошибка",
}

_run_lock = threading.Lock()
_active_run_id: Optional[int] = None


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _loads(raw: Any, default: Any) -> Any:
    if isinstance(raw, (list, dict)):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def _string_list(value: Any, *, limit: int = 20, item_limit: int = 200) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = re.split(r"[\n,]", value)
        value = [part.strip() for part in parts if part.strip()]
    if not isinstance(value, list):
        raise ValueError("ожидается список строк")
    out: list[str] = []
    for item in value[:limit]:
        text = str(item or "").strip()
        if text:
            out.append(text[:item_limit])
    return out


def strip_sources_block(answer: str) -> str:
    return _SOURCES_BLOCK_RE.sub("", answer or "").strip()


def _has_refusal_phrase(text: str) -> bool:
    lowered = (text or "").lower()
    return any(phrase in lowered for phrase in REFUSAL_PHRASES)


def _has_steps(text: str) -> bool:
    lowered = (text or "").lower()
    if _NUMBERED_STEP_RE.search(text or ""):
        return True
    return any(marker in lowered for marker in _STEP_MARKERS)


def classify_tone(answer: str, retrieval_status: Optional[str]) -> str:
    """refusal | unclear | substantive. Пустой текст без статуса — отказ."""
    body = strip_sources_block(answer)
    if retrieval_status == "no_documents":
        return "refusal"
    phrase = _has_refusal_phrase(body)
    if phrase and _has_steps(body):
        return "unclear"
    if phrase or not body:
        return "refusal"
    return "substantive"


def _source_haystack(source: dict) -> str:
    parts = [
        str(source.get("path") or ""),
        str(source.get("title") or ""),
        str(source.get("source") or ""),
    ]
    return " ".join(parts).lower()


def _match_rank(sources: list[dict], expected: list[str]) -> Optional[int]:
    needles = [item.lower() for item in expected if item.strip()]
    if not needles:
        return None
    for index, source in enumerate(sources, start=1):
        haystack = _source_haystack(source)
        if any(needle in haystack for needle in needles):
            return index
    return None


def _contains_any(text: str, needles: list[str]) -> bool:
    lowered = (text or "").lower()
    return any(needle.lower() in lowered for needle in needles if needle.strip())


def score_case(case: dict, observed: dict) -> dict:
    """Вердикты одного вопроса. observed не ходит в LLM."""
    label = case.get("label") or "answerable"
    expected = _string_list(case.get("expected_sources"))
    must_any = _string_list(case.get("must_contain_any"))
    must_not = _string_list(case.get("must_not_contain"))
    evidence = str(case.get("evidence_contains") or "").strip()
    sources = list(observed.get("sources") or [])
    status = observed.get("retrieval_status")
    retrieve_error = observed.get("retrieve_error")
    answer = str(observed.get("answer") or "")
    body = strip_sources_block(answer)

    detail: dict[str, Any] = {
        "retrieval_status": status,
        "retrieve_error": retrieve_error,
        "refusal_phrase_version": REFUSAL_PHRASE_VERSION,
        "evidence_hit": None,
    }

    if retrieve_error in {"embedding_unavailable", "search_error"} or observed.get("failed"):
        return _item(
            "infra_error",
            "infra_error",
            None,
            answer,
            sources,
            detail,
            reason=str(observed.get("error") or retrieve_error or "ошибка вопроса"),
        )

    if status in {"chitchat", "off_topic"}:
        search = "search_miss" if label == "answerable" else "skipped_before_search"
        if label == "answerable":
            detail["reason"] = "skipped_before_search"
        return _item(search, "skipped_before_search", None, answer, sources, detail, reason="skipped_before_search")

    if label == "unanswerable":
        search = "search_empty" if not sources or status == "no_documents" else "search_neighbors"
        rank = None
    elif not expected:
        search = "unlabeled"
        rank = None
    else:
        rank = _match_rank(sources, expected)
        search = "search_hit" if rank else "search_miss"

    if evidence:
        chunks = list(observed.get("chunk_texts") or [])
        blob = "\n".join(chunks) if chunks else "\n".join(str(s.get("text") or "") for s in sources)
        detail["evidence_hit"] = evidence.lower() in blob.lower()

    tone = classify_tone(answer, status if status != "no_documents" else "no_documents")
    if status == "no_documents":
        tone = "refusal"

    if label == "unanswerable":
        if tone == "unclear":
            answer_verdict = "unclear"
        elif tone == "refusal":
            answer_verdict = "correct_abstain"
        else:
            answer_verdict = "false_answer"
    elif tone == "unclear":
        answer_verdict = "unclear"
    elif tone == "refusal":
        answer_verdict = "abstained_despite_hit" if search == "search_hit" else "refusal"
    elif must_any or must_not:
        ok_any = (not must_any) or _contains_any(body, must_any)
        clean = not _contains_any(body, must_not)
        answer_verdict = "substantive" if ok_any and clean else "facts_mismatch"
    else:
        answer_verdict = "substantive"

    top = _public_sources(sources[:3])
    if rank:
        detail["matched_source"] = _public_sources(sources[rank - 1:rank])[0]
    return _item(search, answer_verdict, rank, answer, top, detail)


def _item(search: str, answer: str, rank: Optional[int], text: str, sources: list, detail: dict, reason: str = "") -> dict:
    if reason:
        detail["reason"] = reason
    return {
        "search_verdict": search,
        "answer_verdict": answer,
        "rank": rank,
        "answer_excerpt": text or "",
        "sources": _public_sources(sources[:3]),
        "detail": detail,
    }


def _public_sources(sources: list) -> list[dict]:
    out = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        out.append({
            "title": str(source.get("title") or source.get("source") or "")[:300],
            "path": str(source.get("path") or "")[:300],
            "score": source.get("score"),
        })
    return out


def summarize(items: list[dict]) -> dict:
    answer_counts: dict[str, int] = {key: 0 for key in ANSWER_LABELS}
    search_counts: dict[str, int] = {key: 0 for key in SEARCH_LABELS}
    labeled = hit1 = hitk = evidence_of = evidence_hit = 0
    for item in items:
        answer_counts[item["answer_verdict"]] = answer_counts.get(item["answer_verdict"], 0) + 1
        search_counts[item["search_verdict"]] = search_counts.get(item["search_verdict"], 0) + 1
        detail = item.get("detail") or {}
        if item["search_verdict"] in {"search_hit", "search_miss"}:
            labeled += 1
            if item["search_verdict"] == "search_hit":
                hitk += 1
                if item.get("rank") == 1:
                    hit1 += 1
        if detail.get("evidence_hit") is not None:
            evidence_of += 1
            if detail.get("evidence_hit"):
                evidence_hit += 1
    skipped = answer_counts.get("skipped_before_search", 0) + answer_counts.get("infra_error", 0)
    evaluated = max(0, len(items) - skipped)
    return {
        "total": len(items),
        "evaluated": evaluated,
        "answer": answer_counts,
        "search": {
            "counts": search_counts,
            "labeled": labeled,
            "unlabeled": search_counts.get("unlabeled", 0),
            "hit_at_1": hit1,
            "hit_at_k": hitk,
            "evidence_of": evidence_of,
            "evidence_hit": evidence_hit,
        },
        "refusal_phrase_version": REFUSAL_PHRASE_VERSION,
    }


def params_snapshot() -> dict:
    multi = bool(getattr(settings, "RAG_MULTI_QUERY_ENABLED", False))
    hyde = bool(getattr(settings, "RAG_HYDE_ENABLED", False))
    deep = bool(getattr(settings, "DEEP_RETRIEVAL_ENABLED", False))
    return {
        "OLLAMA_CHAT_MODEL": settings.OLLAMA_CHAT_MODEL,
        "OLLAMA_EMBEDDING_MODEL": settings.OLLAMA_EMBEDDING_MODEL,
        "CHAT_API_MODE": settings.CHAT_API_MODE,
        "INFERENCE_BACKEND": settings.INFERENCE_BACKEND,
        "CHAT_DISABLE_THINKING": bool(settings.CHAT_DISABLE_THINKING),
        "CHUNK_SIZE": settings.CHUNK_SIZE,
        "CHUNK_OVERLAP": settings.CHUNK_OVERLAP,
        "STRUCTURAL_CHUNKING_ENABLED": bool(settings.STRUCTURAL_CHUNKING_ENABLED),
        "STRUCTURAL_CHUNK_MAX_CHARS": settings.STRUCTURAL_CHUNK_MAX_CHARS,
        "STRUCTURAL_CHUNK_MIN_CHARS": settings.STRUCTURAL_CHUNK_MIN_CHARS,
        "CONTEXTUAL_RETRIEVAL_ENABLED": bool(settings.CONTEXTUAL_RETRIEVAL_ENABLED),
        "RETRIEVAL_MODE": settings.RETRIEVAL_MODE,
        "RERANK_ENABLED": bool(settings.RERANK_ENABLED),
        "RERANK_MODEL": settings.RERANK_MODEL,
        "RAG_MULTI_QUERY_ENABLED": multi,
        "RAG_HYDE_ENABLED": hyde,
        "DEEP_RETRIEVAL_ENABLED": deep,
        "RAG_TOP_K": settings.RAG_TOP_K,
        "RAG_MIN_SCORE": settings.RAG_MIN_SCORE,
        "RAG_MAX_CITATIONS": settings.RAG_MAX_CITATIONS,
        "CHROMA_COLLECTION_NAME": settings.CHROMA_COLLECTION_NAME,
        "nondeterministic": multi or hyde or deep,
    }


def index_fingerprint() -> dict:
    chunk_count = None
    try:
        import web_app as web_app_module

        coll = getattr(web_app_module, "collection", None)
        if coll is not None:
            chunk_count = int(coll.count())
    except Exception:
        chunk_count = None
    path = bm25_index_path()
    mtime = size = None
    if path.exists():
        stat = path.stat()
        mtime = stat.st_mtime
        size = stat.st_size
    return {
        "collection": settings.CHROMA_COLLECTION_NAME,
        "chunk_count": chunk_count,
        "bm25_mtime": mtime,
        "bm25_size": size,
    }


def dataset_hash(cases: list[dict]) -> str:
    payload = []
    for case in sorted(cases, key=lambda item: item.get("external_id") or ""):
        payload.append({
            "external_id": case.get("external_id"),
            "question": case.get("question"),
            "label": case.get("label"),
            "expected_sources": case.get("expected_sources") or [],
            "evidence_contains": case.get("evidence_contains") or "",
            "must_contain_any": case.get("must_contain_any") or [],
            "must_not_contain": case.get("must_not_contain") or [],
            "active": 1 if case.get("active", True) else 0,
        })
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _row_case(row) -> dict:
    return {
        "id": row["id"],
        "external_id": row["external_id"],
        "question": row["question"],
        "label": row["label"],
        "expected_sources": _loads(row["expected_sources_json"], []),
        "evidence_contains": row["evidence_contains"] or "",
        "must_contain_any": _loads(row["must_contain_any_json"], []),
        "must_not_contain": _loads(row["must_not_contain_json"], []),
        "notes": row["notes"] or "",
        "active": bool(row["active"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def ensure_seed() -> None:
    history = get_chat_history()
    with history._get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) AS n FROM eval_cases").fetchone()["n"]
        if count:
            return
        now = utc_now()
        for index, question in enumerate(SEED_QUESTIONS, start=1):
            conn.execute(
                '''
                INSERT INTO eval_cases (
                    external_id, question, label, expected_sources_json,
                    evidence_contains, must_contain_any_json, must_not_contain_json,
                    notes, active, created_at, updated_at
                ) VALUES (?, ?, 'answerable', '[]', '', '[]', '[]', '', 1, ?, ?)
                ''',
                (f"q{index:02d}", question, now, now),
            )
        conn.commit()


def list_cases() -> list[dict]:
    ensure_seed()
    history = get_chat_history()
    with history._get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM eval_cases ORDER BY external_id COLLATE NOCASE"
        ).fetchall()
    return [_row_case(row) for row in rows]


def _validate_case_fields(data: dict, *, partial: bool) -> dict:
    out: dict[str, Any] = {}
    if not partial or "question" in data:
        question = str(data.get("question") or "").strip()
        if not question:
            raise ValueError("Нужен текст вопроса")
        if len(question) > 4000:
            raise ValueError("Вопрос длиннее 4000 символов")
        out["question"] = question
    if not partial or "label" in data:
        label = str(data.get("label") or "answerable").strip()
        if label not in {"answerable", "unanswerable"}:
            raise ValueError("Метка должна быть answerable или unanswerable")
        out["label"] = label
    if not partial or "expected_sources" in data:
        out["expected_sources"] = _string_list(data.get("expected_sources"))
    if not partial or "evidence_contains" in data:
        out["evidence_contains"] = str(data.get("evidence_contains") or "").strip()[:500]
    if not partial or "must_contain_any" in data:
        out["must_contain_any"] = _string_list(data.get("must_contain_any"))
    if not partial or "must_not_contain" in data:
        out["must_not_contain"] = _string_list(data.get("must_not_contain"))
    if not partial or "notes" in data:
        notes = str(data.get("notes") or "").strip()
        if len(notes) > 2000:
            raise ValueError("Заметка длиннее 2000 символов")
        out["notes"] = notes
    if not partial or "active" in data:
        out["active"] = bool(data.get("active", True))
    if not partial or "external_id" in data:
        external_id = str(data.get("external_id") or "").strip()
        if external_id:
            if len(external_id) > 80 or not re.fullmatch(r"[A-Za-z0-9_-]+", external_id):
                raise ValueError("id: латиница, цифры, _ и -")
            out["external_id"] = external_id
    return out


def create_case(data: dict) -> dict:
    fields = _validate_case_fields(data, partial=False)
    history = get_chat_history()
    now = utc_now()
    external_id = fields.get("external_id")
    with history._get_connection() as conn:
        if not external_id:
            row = conn.execute("SELECT COUNT(*) AS n FROM eval_cases").fetchone()
            external_id = f"q{int(row['n']) + 1:02d}"
            while conn.execute(
                "SELECT 1 FROM eval_cases WHERE external_id = ?", (external_id,)
            ).fetchone():
                external_id = f"c{int(row['n']) + 1}-{external_id}"
        try:
            cur = conn.execute(
                '''
                INSERT INTO eval_cases (
                    external_id, question, label, expected_sources_json,
                    evidence_contains, must_contain_any_json, must_not_contain_json,
                    notes, active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    external_id,
                    fields["question"],
                    fields["label"],
                    json.dumps(fields["expected_sources"], ensure_ascii=False),
                    fields["evidence_contains"],
                    json.dumps(fields["must_contain_any"], ensure_ascii=False),
                    json.dumps(fields["must_not_contain"], ensure_ascii=False),
                    fields["notes"],
                    1 if fields["active"] else 0,
                    now,
                    now,
                ),
            )
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                raise ValueError("Такой id уже есть") from exc
            raise
        conn.commit()
        case_id = cur.lastrowid
        row = conn.execute("SELECT * FROM eval_cases WHERE id = ?", (case_id,)).fetchone()
    return _row_case(row)


def update_case(case_id: int, data: dict) -> dict:
    fields = _validate_case_fields(data, partial=True)
    if not fields:
        raise ValueError("Нет полей для обновления")
    history = get_chat_history()
    now = utc_now()
    assignments = ["updated_at = ?"]
    params: list[Any] = [now]
    mapping = {
        "question": "question",
        "label": "label",
        "evidence_contains": "evidence_contains",
        "notes": "notes",
    }
    for key, column in mapping.items():
        if key in fields:
            assignments.append(f"{column} = ?")
            params.append(fields[key])
    if "expected_sources" in fields:
        assignments.append("expected_sources_json = ?")
        params.append(json.dumps(fields["expected_sources"], ensure_ascii=False))
    if "must_contain_any" in fields:
        assignments.append("must_contain_any_json = ?")
        params.append(json.dumps(fields["must_contain_any"], ensure_ascii=False))
    if "must_not_contain" in fields:
        assignments.append("must_not_contain_json = ?")
        params.append(json.dumps(fields["must_not_contain"], ensure_ascii=False))
    if "active" in fields:
        assignments.append("active = ?")
        params.append(1 if fields["active"] else 0)
    params.append(case_id)
    with history._get_connection() as conn:
        exists = conn.execute("SELECT id FROM eval_cases WHERE id = ?", (case_id,)).fetchone()
        if not exists:
            raise LookupError("Вопрос не найден")
        conn.execute(
            f"UPDATE eval_cases SET {', '.join(assignments)} WHERE id = ?",
            params,
        )
        conn.commit()
        row = conn.execute("SELECT * FROM eval_cases WHERE id = ?", (case_id,)).fetchone()
    return _row_case(row)


def import_jsonl(text: str) -> dict:
    created = updated = 0
    errors = []
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if not lines:
        raise ValueError("Файл пустой")
    if len(lines) > 500:
        raise ValueError("Не больше 500 строк за один импорт")
    for index, line in enumerate(lines, start=1):
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            errors.append({"line": index, "error": "не JSON"})
            continue
        if not isinstance(obj, dict):
            errors.append({"line": index, "error": "нужен объект"})
            continue
        external_id = str(obj.get("id") or obj.get("external_id") or "").strip()
        payload = {
            "external_id": external_id,
            "question": obj.get("question"),
            "label": obj.get("label") or "answerable",
            "expected_sources": obj.get("expected_sources") or [],
            "evidence_contains": obj.get("evidence_contains") or "",
            "must_contain_any": obj.get("must_contain_any") or [],
            "must_not_contain": obj.get("must_not_contain") or [],
            "notes": obj.get("notes") or "",
            "active": obj.get("active", True),
        }
        try:
            if external_id:
                existing = _case_by_external_id(external_id)
                if existing:
                    update_case(existing["id"], payload)
                    updated += 1
                    continue
            create_case(payload)
            created += 1
        except ValueError as exc:
            errors.append({"line": index, "error": str(exc)})
    return {"created": created, "updated": updated, "errors": errors}


def _case_by_external_id(external_id: str) -> Optional[dict]:
    history = get_chat_history()
    with history._get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM eval_cases WHERE external_id = ?", (external_id,)
        ).fetchone()
    return _row_case(row) if row else None


def _heal_orphaned_runs() -> None:
    """Прогон, оставшийся running после остановки процесса, не блокирует новый."""
    global _active_run_id
    history = get_chat_history()
    with history._get_connection() as conn:
        rows = conn.execute(
            "SELECT id FROM eval_runs WHERE status IN ('queued', 'running')"
        ).fetchall()
        now = utc_now()
        for row in rows:
            if row["id"] == _active_run_id:
                continue
            conn.execute(
                '''
                UPDATE eval_runs
                SET status = 'failed', finished_at = ?, error = ?
                WHERE id = ? AND status IN ('queued', 'running')
                ''',
                (now, "Прогон не завершился: процесс был перезапущен", row["id"]),
            )
        conn.commit()


def start_run(user_id: Optional[int]) -> tuple[dict, bool]:
    """Вернуть (run, already_running)."""
    global _active_run_id
    ensure_seed()
    with _run_lock:
        _heal_orphaned_runs()
        if _active_run_id is not None:
            active = get_run(_active_run_id)
            return active or {"id": _active_run_id, "status": "running"}, True
        cases = [case for case in list_cases() if case["active"]]
        if not cases:
            raise ValueError("Нет активных вопросов")
        history = get_chat_history()
        now = utc_now()
        with history._get_connection() as conn:
            cur = conn.execute(
                '''
                INSERT INTO eval_runs (
                    status, started_by, started_at, dataset_hash,
                    params_json, index_json, summary_json,
                    progress_done, progress_total
                ) VALUES ('queued', ?, ?, ?, '{}', '{}', '{}', 0, ?)
                ''',
                (user_id, now, dataset_hash(cases), len(cases)),
            )
            conn.commit()
            run_id = int(cur.lastrowid)
        _active_run_id = run_id
    thread = threading.Thread(target=execute_run, args=(run_id,), daemon=True)
    thread.start()
    return get_run(run_id), False


def execute_run(run_id: int) -> None:
    global _active_run_id
    history = get_chat_history()
    try:
        _mark_running(run_id)
        params = params_snapshot()
        fingerprint = index_fingerprint()
        with history._get_connection() as conn:
            conn.execute(
                "UPDATE eval_runs SET params_json = ?, index_json = ? WHERE id = ?",
                (
                    json.dumps(params, ensure_ascii=False),
                    json.dumps(fingerprint, ensure_ascii=False),
                    run_id,
                ),
            )
            conn.commit()
            rows = conn.execute(
                "SELECT * FROM eval_cases WHERE active = 1 ORDER BY external_id COLLATE NOCASE"
            ).fetchall()
        cases = [_row_case(row) for row in rows]
        items = []
        for case in cases:
            observed = _ask(case)
            scored = score_case(case, observed)
            _insert_item(run_id, case, scored)
            items.append(scored)
            _set_progress(run_id, len(items), len(cases))
        summary = summarize(items)
        summary["nondeterministic"] = bool(params.get("nondeterministic"))
        with history._get_connection() as conn:
            conn.execute(
                '''
                UPDATE eval_runs
                SET status = 'done', finished_at = ?, summary_json = ?, error = NULL
                WHERE id = ?
                ''',
                (utc_now(), json.dumps(summary, ensure_ascii=False), run_id),
            )
            conn.commit()
    except Exception as exc:
        with history._get_connection() as conn:
            conn.execute(
                '''
                UPDATE eval_runs
                SET status = 'failed', finished_at = ?, error = ?
                WHERE id = ?
                ''',
                (utc_now(), str(exc)[:2000], run_id),
            )
            conn.commit()
    finally:
        with _run_lock:
            if _active_run_id == run_id:
                _active_run_id = None


def _ask(case: dict) -> dict:
    try:
        from core.rag import RAGSystem

        rag = RAGSystem(settings.CHROMA_COLLECTION_NAME)
        result = rag.query(case["question"])
    except Exception as exc:
        return {"failed": True, "error": str(exc), "answer": "", "sources": []}
    diagnostics = result.diagnostics or {}
    sources = []
    for source in result.sources or []:
        sources.append({
            "title": source.get("title") or "",
            "path": source.get("path") or "",
            "source": source.get("source") or "",
            "score": source.get("score"),
            "text": source.get("text") or "",
        })
    observed = {
        "answer": result.answer or "",
        "sources": sources,
        "retrieval_status": diagnostics.get("retrieval_status"),
        "retrieve_error": result.retrieve_error,
        "chunk_texts": [],
    }
    evidence = str(case.get("evidence_contains") or "").strip()
    if evidence and not result.retrieve_error:
        try:
            documents, _err, _expansion, _diag = rag.retrieve_documents_auto(
                case["question"],
                conversation_history=None,
            )
            observed["chunk_texts"] = [
                str(doc.get("text") or "") for doc in (documents or [])
            ]
        except Exception:
            observed["chunk_texts"] = []
    return observed


def _mark_running(run_id: int) -> None:
    history = get_chat_history()
    with history._get_connection() as conn:
        conn.execute("UPDATE eval_runs SET status = 'running' WHERE id = ?", (run_id,))
        conn.commit()


def _set_progress(run_id: int, done: int, total: int) -> None:
    history = get_chat_history()
    with history._get_connection() as conn:
        conn.execute(
            "UPDATE eval_runs SET progress_done = ?, progress_total = ? WHERE id = ?",
            (done, total, run_id),
        )
        conn.commit()


def _insert_item(run_id: int, case: dict, scored: dict) -> None:
    history = get_chat_history()
    with history._get_connection() as conn:
        conn.execute(
            '''
            INSERT INTO eval_run_items (
                run_id, case_id, external_id, question, label,
                search_verdict, answer_verdict, rank, answer_excerpt,
                sources_json, detail_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                run_id,
                case.get("id"),
                case.get("external_id"),
                case.get("question"),
                case.get("label"),
                scored["search_verdict"],
                scored["answer_verdict"],
                scored.get("rank"),
                scored.get("answer_excerpt") or "",
                json.dumps(scored.get("sources") or [], ensure_ascii=False),
                json.dumps(scored.get("detail") or {}, ensure_ascii=False),
            ),
        )
        conn.commit()


def _run_row(row, *, with_items: bool = False) -> dict:
    params = _loads(row["params_json"], {})
    summary = _loads(row["summary_json"], {})
    data = {
        "id": row["id"],
        "status": row["status"],
        "started_by": row["started_by"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "dataset_hash": row["dataset_hash"],
        "params": params,
        "index": _loads(row["index_json"], {}),
        "summary": summary,
        "progress_done": row["progress_done"],
        "progress_total": row["progress_total"],
        "error": row["error"],
        "headline": _headline(summary, row["progress_done"], row["progress_total"], row["status"]),
    }
    if with_items:
        history = get_chat_history()
        with history._get_connection() as conn:
            items = conn.execute(
                "SELECT * FROM eval_run_items WHERE run_id = ? ORDER BY id",
                (row["id"],),
            ).fetchall()
        data["items"] = [_item_row(item) for item in items]
    return data


def _item_row(row) -> dict:
    return {
        "id": row["id"],
        "external_id": row["external_id"],
        "question": row["question"],
        "label": row["label"],
        "search_verdict": row["search_verdict"],
        "answer_verdict": row["answer_verdict"],
        "search_label": _search_label(row["search_verdict"], row["rank"]),
        "answer_label": ANSWER_LABELS.get(row["answer_verdict"], row["answer_verdict"]),
        "rank": row["rank"],
        "answer_excerpt": row["answer_excerpt"],
        "sources": _loads(row["sources_json"], []),
        "detail": _loads(row["detail_json"], {}),
    }


def _search_label(verdict: str, rank: Optional[int]) -> str:
    if verdict == "search_hit" and rank:
        return f"найден, место {rank}"
    return SEARCH_LABELS.get(verdict, verdict)


def _headline(summary: dict, done: int, total: int, status: str) -> dict:
    answer = (summary or {}).get("answer") or {}
    search = (summary or {}).get("search") or {}
    evaluated = (summary or {}).get("evaluated")
    substantive = answer.get("substantive", 0)
    labeled = search.get("labeled") or 0
    return {
        "status": status,
        "progress": f"{done}/{total}" if total else "",
        "answer": f"{substantive}/{evaluated}" if evaluated else "",
        "search": f"{search.get('hit_at_k', 0)}/{labeled}" if labeled else "",
    }


def list_runs(limit: int = 30) -> list[dict]:
    history = get_chat_history()
    with history._get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM eval_runs ORDER BY id DESC LIMIT ?",
            (max(1, min(int(limit), 100)),),
        ).fetchall()
    return [_run_row(row) for row in rows]


def get_run(run_id: int) -> Optional[dict]:
    history = get_chat_history()
    with history._get_connection() as conn:
        row = conn.execute("SELECT * FROM eval_runs WHERE id = ?", (run_id,)).fetchone()
    if not row:
        return None
    return _run_row(row, with_items=True)


def compare_runs(before_id: int, after_id: int) -> dict:
    before = get_run(before_id)
    after = get_run(after_id)
    if not before or not after:
        raise LookupError("Прогон не найден")
    warnings = []
    if before.get("dataset_hash") and after.get("dataset_hash") and before["dataset_hash"] != after["dataset_hash"]:
        warnings.append("dataset_changed")
    if _index_unchanged_despite_settings(before, after):
        warnings.append("index_unchanged")
    before_items = {item["external_id"]: item for item in before.get("items") or []}
    after_items = {item["external_id"]: item for item in after.get("items") or []}
    changed = []
    for external_id in sorted(set(before_items) | set(after_items)):
        left = before_items.get(external_id)
        right = after_items.get(external_id)
        if not left or not right:
            changed.append({
                "external_id": external_id,
                "question": (right or left)["question"],
                "search_before": left["search_label"] if left else "не было",
                "search_after": right["search_label"] if right else "не было",
                "answer_before": left["answer_label"] if left else "не было",
                "answer_after": right["answer_label"] if right else "не было",
            })
            continue
        if left["search_verdict"] != right["search_verdict"] or left["answer_verdict"] != right["answer_verdict"] or left.get("rank") != right.get("rank"):
            changed.append({
                "external_id": external_id,
                "question": right["question"],
                "search_before": left["search_label"],
                "search_after": right["search_label"],
                "answer_before": left["answer_label"],
                "answer_after": right["answer_label"],
            })
    b_eval = (before.get("summary") or {}).get("evaluated") or 0
    a_eval = (after.get("summary") or {}).get("evaluated") or 0
    b_sub = ((before.get("summary") or {}).get("answer") or {}).get("substantive", 0)
    a_sub = ((after.get("summary") or {}).get("answer") or {}).get("substantive", 0)
    n = a_eval or b_eval
    if n and b_eval == a_eval and 0 < abs(a_sub - b_sub) <= 1:
        warnings.append("delta_within_one")
    return {
        "before": _compare_side(before),
        "after": _compare_side(after),
        "warnings": warnings,
        "changed": changed,
        "substantive": {"before": f"{b_sub}/{b_eval}" if b_eval else "—", "after": f"{a_sub}/{a_eval}" if a_eval else "—"},
    }


def _compare_side(run: dict) -> dict:
    params = run.get("params") or {}
    return {
        "id": run["id"],
        "started_at": run["started_at"],
        "status": run["status"],
        "model": params.get("OLLAMA_CHAT_MODEL"),
        "embedding_model": params.get("OLLAMA_EMBEDDING_MODEL"),
        "chunk_size": params.get("CHUNK_SIZE"),
        "summary": run.get("summary") or {},
        "headline": run.get("headline") or {},
    }


def _index_unchanged_despite_settings(before: dict, after: dict) -> bool:
    bp = before.get("params") or {}
    ap = after.get("params") or {}
    settings_differ = (
        bp.get("CHUNK_SIZE") != ap.get("CHUNK_SIZE")
        or bp.get("OLLAMA_EMBEDDING_MODEL") != ap.get("OLLAMA_EMBEDDING_MODEL")
    )
    if not settings_differ:
        return False
    bi = before.get("index") or {}
    ai = after.get("index") or {}
    keys = ("chunk_count", "bm25_mtime", "bm25_size")
    if any(bi.get(key) is None and ai.get(key) is None for key in keys):
        if all(bi.get(key) is None and ai.get(key) is None for key in keys):
            return False
    return all(bi.get(key) == ai.get(key) for key in keys)
