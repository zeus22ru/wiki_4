# -*- coding: utf-8 -*-
"""Скорер проверок и admin API без живого LLM и Chroma."""

import json
from unittest.mock import MagicMock, patch

from werkzeug.security import generate_password_hash

from core.answer_benchmark import compare_runs, score_case, summarize
from core.rag import RAGResult


def _obs(answer, sources=None, status=None, error=None):
    return {
        "answer": answer,
        "sources": sources or [],
        "retrieval_status": status,
        "retrieve_error": error,
        "chunk_texts": [],
    }


def _source(title, path, score=0.4):
    return {"title": title, "path": path, "source": title, "score": score, "text": "фрагмент"}


def test_substantive_ignores_sources_block():
    scored = score_case(
        {"label": "answerable", "expected_sources": [], "must_contain_any": [], "must_not_contain": []},
        _obs("Откройте обработку рассылки.\n\n**Источники:**\nнет информации"),
    )
    assert scored["answer_verdict"] == "substantive"
    assert scored["search_verdict"] == "unlabeled"


def test_refusal_and_unclear():
    refusal = score_case(
        {"label": "answerable"},
        _obs("К сожалению, я не нашёл релевантной информации."),
    )
    assert refusal["answer_verdict"] == "refusal"
    unclear = score_case(
        {"label": "answerable"},
        _obs("Не нашёл точной инструкции, но нажмите кнопку проведения."),
    )
    assert unclear["answer_verdict"] == "unclear"
    hard = score_case(
        {"label": "answerable"},
        _obs("К сожалению, я не нашёл релевантной информации.", status="no_documents"),
    )
    assert hard["answer_verdict"] == "refusal"


def test_search_hit_rank_and_facts():
    sources = [_source("Другое", "other.txt"), _source("Рассылка должникам", "docs/debt.txt")]
    scored = score_case(
        {
            "label": "answerable",
            "expected_sources": ["debt.txt"],
            "must_contain_any": ["рассылк"],
            "must_not_contain": [],
        },
        _obs("Откройте рассылку должникам и выберите контрагентов.", sources),
    )
    assert scored["search_verdict"] == "search_hit"
    assert scored["rank"] == 2
    assert scored["answer_verdict"] == "substantive"

    missed = score_case(
        {"label": "answerable", "expected_sources": ["debt.txt"], "must_contain_any": ["егаис"]},
        _obs("Откройте рассылку должникам.", sources),
    )
    assert missed["answer_verdict"] == "facts_mismatch"

    abstained = score_case(
        {"label": "answerable", "expected_sources": ["debt.txt"]},
        _obs("В базе нет такой инструкции.", sources),
    )
    assert abstained["answer_verdict"] == "abstained_despite_hit"
    assert abstained["search_verdict"] == "search_hit"


def test_unanswerable_and_infra():
    refused = score_case(
        {"label": "unanswerable"},
        _obs("Не нашёл релевантной информации.", status="no_documents"),
    )
    assert refused["search_verdict"] == "search_empty"
    assert refused["answer_verdict"] == "correct_abstain"
    invented = score_case(
        {"label": "unanswerable", "expected_sources": []},
        _obs("Откройте справочник и заполните поле.", [_source("Шум", "noise.txt")]),
    )
    assert invented["search_verdict"] == "search_neighbors"
    assert invented["answer_verdict"] == "false_answer"
    broken = score_case(
        {"label": "answerable", "expected_sources": ["a.txt"]},
        _obs("", error="embedding_unavailable"),
    )
    assert broken["search_verdict"] == "infra_error"
    assert broken["answer_verdict"] == "infra_error"


def test_summary_excludes_infra_from_evaluated():
    summary = summarize([
        {"search_verdict": "unlabeled", "answer_verdict": "substantive", "rank": None, "detail": {}},
        {"search_verdict": "infra_error", "answer_verdict": "infra_error", "rank": None, "detail": {}},
        {"search_verdict": "search_hit", "answer_verdict": "substantive", "rank": 1, "detail": {"evidence_hit": True}},
    ])
    assert summary["evaluated"] == 2
    assert summary["answer"]["substantive"] == 2
    assert summary["search"]["hit_at_1"] == 1
    assert summary["search"]["labeled"] == 1
    assert summary["search"]["evidence_hit"] == 1


def login_admin(client):
    from core.chat_history import get_chat_history

    get_chat_history().create_user(
        username="admin",
        email="admin@example.com",
        password_hash=generate_password_hash("password123"),
        role="admin",
    )
    rv = client.post("/api/auth/login", json={"identifier": "admin", "password": "password123"})
    assert rv.status_code == 200


def test_evals_require_admin(client):
    rv = client.get("/api/admin/evals/cases")
    assert rv.status_code == 401


def test_seed_import_and_parallel_start(client, monkeypatch):
    import core.answer_benchmark as bench

    login_admin(client)
    listed = client.get("/api/admin/evals/cases")
    assert listed.status_code == 200
    cases = listed.get_json()["cases"]
    assert len(cases) == 20
    assert cases[0]["question"].startswith("Как сделать рассылку")
    assert cases[0]["expected_sources"] == []

    imported = client.post(
        "/api/admin/evals/cases/import",
        json={"jsonl": json.dumps({
            "id": "q01",
            "question": "Как сделать рассылку должникам?",
            "label": "answerable",
            "expected_sources": ["debt.txt"],
        }, ensure_ascii=False)},
    )
    assert imported.status_code == 200
    body = imported.get_json()
    assert body["updated"] == 1
    assert body["created"] == 0

    monkeypatch.setattr(bench.threading, "Thread", lambda *args, **kwargs: MagicMock())
    first = client.post("/api/admin/evals/runs")
    assert first.status_code == 202
    second = client.post("/api/admin/evals/runs")
    assert second.status_code == 409
    assert second.get_json()["error"] == "eval_already_running"
    bench._active_run_id = None


def test_run_records_params_and_compare_warns_same_index(client, monkeypatch):
    import core.answer_benchmark as bench
    from core.chat_history import get_chat_history

    login_admin(client)

    class ImmediateThread:
        def __init__(self, target, args=(), daemon=None):
            self._target = target
            self._args = args

        def start(self):
            self._target(*self._args)

    monkeypatch.setattr(bench.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(bench, "index_fingerprint", lambda: {
        "collection": "wiki", "chunk_count": 10, "bm25_mtime": 1.0, "bm25_size": 5,
    })

    rag = MagicMock()
    rag.query.return_value = RAGResult(
        answer="Откройте обработку рассылки должникам.",
        citations=[],
        sources=[{"title": "Должники", "path": "debt.txt", "source": "Должники", "score": 0.8, "text": "текст"}],
        diagnostics={"retrieval_status": "ok"},
    )
    rag.retrieve_documents_auto.return_value = ([], None, {}, {})

    with patch("core.rag.RAGSystem", return_value=rag):
        started = client.post("/api/admin/evals/runs")
    assert started.status_code == 202
    run_id = started.get_json()["run"]["id"]
    detail = client.get(f"/api/admin/evals/runs/{run_id}")
    run = detail.get_json()["run"]
    assert run["status"] == "done"
    assert run["params"]["OLLAMA_CHAT_MODEL"]
    assert run["summary"]["answer"]["substantive"] == 20
    assert run["summary"]["search"]["unlabeled"] == 20
    assert len(run["items"]) == 20

    history = get_chat_history()
    with history._get_connection() as conn:
        first = conn.execute("SELECT * FROM eval_runs WHERE id = ?", (run_id,)).fetchone()
        conn.execute(
            '''
            INSERT INTO eval_runs (
                status, started_by, started_at, finished_at, dataset_hash,
                params_json, index_json, summary_json, progress_done, progress_total
            ) VALUES ('done', ?, ?, ?, ?, ?, ?, ?, 20, 20)
            ''',
            (
                first["started_by"],
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:01:00+00:00",
                first["dataset_hash"],
                json.dumps({**json.loads(first["params_json"]), "CHUNK_SIZE": 999}),
                first["index_json"],
                first["summary_json"],
            ),
        )
        conn.commit()
        second_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        conn.execute(
            '''
            INSERT INTO eval_run_items (
                run_id, case_id, external_id, question, label,
                search_verdict, answer_verdict, rank, answer_excerpt, sources_json, detail_json
            )
            SELECT ?, case_id, external_id, question, label,
                   'search_miss', 'refusal', NULL, '', '[]', '{}'
            FROM eval_run_items WHERE run_id = ?
            ''',
            (second_id, run_id),
        )
        conn.commit()

    report = compare_runs(run_id, second_id)
    assert "index_unchanged" in report["warnings"]
    assert report["changed"]
    assert report["changed"][0]["answer_before"] == "содержательный"
    assert report["changed"][0]["answer_after"] == "отказ"
