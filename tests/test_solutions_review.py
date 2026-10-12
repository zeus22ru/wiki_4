"""Independent regression checks for solutions authorization and races."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading

import pytest


@pytest.fixture
def solution_case(client, tmp_path, monkeypatch):
    from config import settings
    from core.chat_history import get_chat_history
    from core import solutions

    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path / "corpus"))
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path / "corpus" / "uploads"))
    monkeypatch.setattr(solutions, "chat_completion", lambda *_a, **_k: "{}")
    history = get_chat_history()
    owner = history.create_user("solution-owner", "owner@example.invalid", "unused")
    admin = history.create_user("solution-admin", "admin@example.invalid", "unused", role="admin")
    chat = history.create_session(user_id=owner.id, title="Печать")
    history.add_message(chat.id, "user", "Не печатает принтер склада")
    answer = history.add_message(chat.id, "assistant", "Перезапустите службу печати")
    with client.session_transaction() as session:
        session["user_id"] = owner.id
    rv = client.post("/api/solutions", json={"session_id": chat.id, "message_id": answer.id})
    assert rv.status_code == 201, rv.get_json()
    return {
        "id": rv.get_json()["solution"]["id"], "chat": chat, "answer": answer,
        "history": history, "owner": owner, "admin": admin, "root": tmp_path / "corpus",
    }


def _draft(client, case, kind="modified", clarification="Сначала очистил очередь печати"):
    rv = client.post(f"/api/solutions/{case['id']}/draft", json={
        "kind": kind, "clarification": clarification,
    })
    assert rv.status_code == 200, rv.get_json()
    return rv.get_json()["solution"]


def _pending(client, case):
    draft = _draft(client, case)
    rv = client.patch(f"/api/solutions/{case['id']}", json={
        "version": draft["version"], "fields": {
            "title": "Восстановление печати", "problem": "Не печатает принтер",
            "solution": "Очистить очередь, затем перезапустить службу",
        },
    })
    assert rv.status_code == 200, rv.get_json()
    rv = client.post(f"/api/solutions/{case['id']}/submit", json={"version": rv.json["solution"]["version"]})
    assert rv.status_code == 200, rv.get_json()
    return rv.json["solution"]


def _as_admin(client, case):
    with client.session_transaction() as session:
        session["user_id"] = case["admin"].id


def test_fallback_preserves_modification(client, solution_case):
    draft = _draft(client, solution_case)
    assert "очередь" in draft["solution"].lower()
    assert "перезапуст" in draft["solution"].lower()
    assert draft["problem"].strip()


def test_other_fallback_excludes_failed_advice(client, solution_case):
    draft = _draft(client, solution_case, "other", "Заменил неисправный USB-кабель")
    assert "USB-кабель" in draft["solution"]
    assert "Перезапустите" not in draft["solution"]


def test_stale_publish_does_not_write_any_article(client, solution_case):
    item = _pending(client, solution_case)
    _as_admin(client, solution_case)
    rv = client.post(f"/api/solutions/{item['id']}/review", json={
        "version": item["version"] - 1, "action": "publish",
    })
    assert rv.status_code == 409
    assert not list(solution_case["root"].rglob("solution-*.txt"))
    assert client.get(f"/api/solutions/{item['id']}").json["solution"]["status"] == "pending"


@pytest.mark.parametrize("status", ["draft", "resolved"])
def test_review_list_cannot_expose_private_unsubmitted_work(client, solution_case, status):
    if status == "draft":
        _draft(client, solution_case)
    _as_admin(client, solution_case)
    rv = client.get(f"/api/solutions/review?status={status}")
    assert rv.status_code in {400, 403} or rv.json.get("solutions") == []
    assert client.get(f"/api/solutions/{solution_case['id']}").status_code in {403, 404}


def test_deleted_chat_revokes_owner_access_to_draft(client, solution_case):
    draft = _draft(client, solution_case)
    assert client.delete(f"/api/chats/{solution_case['chat'].id}").status_code == 200
    assert client.get(f"/api/solutions/{draft['id']}").status_code in {403, 404}
    assert client.patch(f"/api/solutions/{draft['id']}", json={
        "version": draft["version"], "fields": {"title": "Изменить после удаления"},
    }).status_code in {403, 404}


def test_snapshot_cleans_source_text_and_russian_secret_labels(client, solution_case):
    case = solution_case
    answer = case["history"].add_message(case["chat"].id, "assistant", "пароль: qwerty-review-secret", sources=[{
        "title": "Тест owner.private@example.invalid", "path": "uploads/test.txt",
        "text": "token=review-token-secret; пароль: another-review-secret",
    }])
    rv = client.post("/api/solutions", json={"session_id": case["chat"].id, "message_id": answer.id})
    case = {**case, "id": rv.json["solution"]["id"]}
    item = _pending(client, case)
    _as_admin(client, case)
    text = client.get(f"/api/solutions/{item['id']}").get_data(as_text=True)
    for secret in ("review-token-secret", "qwerty-review-secret", "another-review-secret", "owner.private@example.invalid"):
        assert secret not in text


def test_two_admins_publish_exactly_one_file(client, solution_case):
    from core.solutions import SolutionError, SolutionService

    item = _pending(client, solution_case)
    barrier = threading.Barrier(2)

    def publish():
        service = SolutionService(solution_case["history"])
        barrier.wait(timeout=10)
        try:
            service.review(item["id"], item["version"], "publish", {}, solution_case["admin"].id)
            return 200
        except SolutionError as exc:
            return exc.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: publish(), range(2)))
    assert sorted(outcomes) == [200, 409]
    assert len(list(solution_case["root"].rglob("solution-*.txt"))) == 1


def test_delayed_generation_cannot_overwrite_submitted_draft(client, solution_case, monkeypatch):
    from core import solutions

    case = solution_case
    service = solutions.SolutionService(case["history"])

    def concurrent_completion(*_a, **_k):
        monkeypatch.setattr(solutions, "chat_completion", lambda *_a, **_k: "{}")
        draft, _notice = service.prepare_draft(case["id"], "other", "Решение в другой вкладке", case["owner"].id, None)
        draft = service.update_draft(case["id"], {"title": "Другая вкладка", "problem": "Печать", "solution": "Проверенное решение"}, draft["version"], case["owner"].id, None)
        service.submit(case["id"], draft["version"], case["owner"].id, None)
        return '{}'

    monkeypatch.setattr(solutions, "chat_completion", concurrent_completion)
    rv = client.post(f"/api/solutions/{case['id']}/draft", json={"kind": "other", "clarification": "Задержавшийся запрос"})
    assert rv.status_code in {200, 409}
    item = client.get(f"/api/solutions/{case['id']}").json["solution"]
    assert item["status"] == "pending"
    assert item["solution"] == "Проверенное решение"


@pytest.mark.parametrize("body", [[], None, True, 3, {"session_id": True, "message_id": 1}, {"session_id": 1, "message_id": []}])
def test_bad_confirm_json_is_client_error(client, body):
    import json
    rv = client.post("/api/solutions", data=json.dumps(body), content_type="application/json")
    assert rv.status_code == 400


def test_fallback_uses_latest_question_and_respects_field_limits(client, solution_case):
    case = solution_case
    case["history"].add_message(case["chat"].id, "user", "Теперь другая проблема: пропал звук")
    answer = case["history"].add_message(case["chat"].id, "assistant", "Проверить динамики. " * 900)
    rv = client.post("/api/solutions", json={"session_id": case["chat"].id, "message_id": answer.id})
    case = {**case, "id": rv.json["solution"]["id"]}
    draft = _draft(client, case, "modified", "Подключил кабель колонок")
    assert "пропал звук" in draft["problem"]
    assert "Подключил кабель" in draft["solution"]
    assert len(draft["solution"]) <= 8000
    assert client.patch(f"/api/solutions/{draft['id']}", json={
        "version": draft["version"], "fields": {"title": "Пропал звук", "solution": draft["solution"], "problem": draft["problem"]},
    }).status_code == 200


def test_link_requires_supported_document_not_internal_database(client, solution_case):
    case = solution_case
    item = _pending(client, case)
    case["root"].mkdir(parents=True, exist_ok=True)
    (case["root"] / "internal.db").write_bytes(b"not a knowledge article")
    _as_admin(client, case)
    rv = client.post(f"/api/solutions/{item['id']}/review", json={
        "version": item["version"], "action": "link", "document_path": "internal.db",
    })
    assert rv.status_code == 400
