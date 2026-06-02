"""Focused tests for chat history storage and maintenance."""

import sqlite3
from datetime import datetime, timedelta

from core.chat_history import ChatHistoryManager


def _set_session_updated_at(history: ChatHistoryManager, session_id: int, updated_at: str) -> None:
    with history._get_connection() as conn:
        conn.execute(
            "UPDATE chat_sessions SET created_at = ?, updated_at = ? WHERE id = ?",
            (updated_at, updated_at, session_id),
        )


def _set_message_created_at(history: ChatHistoryManager, message_id: int, created_at: str) -> None:
    with history._get_connection() as conn:
        conn.execute(
            "UPDATE messages SET created_at = ? WHERE id = ?",
            (created_at, message_id),
        )


def test_chat_history_indexes_are_created_idempotently(tmp_path):
    history = ChatHistoryManager(str(tmp_path / "history.db"))
    history._create_tables()

    with sqlite3.connect(history.db_path) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        ).fetchall()

    index_names = {row[0] for row in rows}
    assert {
        "idx_messages_created_at",
        "idx_messages_role",
        "idx_messages_session_created_at",
        "idx_messages_role_created_at",
        "idx_feedback_rating",
        "idx_feedback_created_at",
        "idx_feedback_rating_created_at",
        "idx_chat_sessions_updated_at",
    }.issubset(index_names)


def test_cleanup_guest_sessions_supports_dry_run_and_apply(tmp_path):
    history = ChatHistoryManager(str(tmp_path / "history.db"))
    old_at = (datetime.now() - timedelta(days=90)).isoformat()
    recent_at = datetime.now().isoformat()

    old_guest = history.create_session(title="old guest")
    old_answer = history.add_message(old_guest.id, "assistant", "old answer")
    history.add_feedback(old_guest.id, old_answer.id, "down")
    _set_session_updated_at(history, old_guest.id, old_at)

    orphan = history.create_session(user_id=999, title="orphan")
    _set_session_updated_at(history, orphan.id, old_at)

    recent_guest = history.create_session(title="recent guest")
    _set_session_updated_at(history, recent_guest.id, recent_at)

    dry_run = history.cleanup_guest_sessions(retention_days=30, dry_run=True)
    assert dry_run["matched"] == 2
    assert dry_run["deleted"] == 0
    assert history.get_session(old_guest.id) is not None

    applied = history.cleanup_guest_sessions(retention_days=30, dry_run=False)
    assert applied["matched"] == 2
    assert applied["deleted"] == 2
    assert history.get_session(old_guest.id) is None
    assert history.get_session(orphan.id) is None
    assert history.get_session(recent_guest.id) is not None
    assert history.get_feedback(limit=10) == []


def test_get_weak_answers_honors_scan_limit(tmp_path):
    history = ChatHistoryManager(str(tmp_path / "history.db"))
    session = history.create_session(title="quality")
    base = datetime.now() - timedelta(minutes=10)

    old_question = history.add_message(session.id, "user", "old question")
    old_answer = history.add_message(
        session.id,
        "assistant",
        "old weak answer",
        metadata={"retrieval_status": "no_documents"},
    )
    new_question = history.add_message(session.id, "user", "new question")
    new_answer = history.add_message(
        session.id,
        "assistant",
        "new weak answer",
        metadata={"retrieval_status": "no_documents"},
    )

    for offset, message in enumerate([old_question, old_answer, new_question, new_answer]):
        _set_message_created_at(history, message.id, (base + timedelta(minutes=offset)).isoformat())

    weak = history.get_weak_answers(limit=10, scan_limit=2)

    assert [item["answer"] for item in weak] == ["new weak answer"]
    assert weak[0]["question"] == "new question"
