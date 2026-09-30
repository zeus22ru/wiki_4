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


def test_telegram_link_schema_migration_drops_unique(tmp_path):
    import sqlite3

    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute('''
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        ''')
        conn.execute('''
            CREATE TABLE telegram_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                code TEXT NOT NULL UNIQUE,
                telegram_user_id INTEGER,
                telegram_username TEXT,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                used_at TEXT
            )
        ''')
        conn.execute(
            "INSERT INTO users (username, email, password_hash, role, is_active, created_at, updated_at) "
            "VALUES ('u', 'u@e.com', 'h', 'user', 1, '2020-01-01', '2020-01-01')"
        )
        conn.execute(
            "INSERT INTO telegram_links (user_id, code, created_at, expires_at, used_at) "
            "VALUES (1, 'USEDCODE1', '2020-01-01', '2020-01-02', '2020-01-01')"
        )
        conn.commit()

    history = ChatHistoryManager(str(db_path))
    with sqlite3.connect(history.db_path) as conn:
        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='telegram_links'"
        ).fetchone()[0]
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert "code TEXT NOT NULL UNIQUE" not in sql
    assert version >= 1


def test_message_belongs_to_session_and_mark_failed(tmp_path):
    history = ChatHistoryManager(str(tmp_path / "history.db"))
    session = history.create_session(title="s")
    other = history.create_session(title="other")
    msg = history.add_message(session.id, "user", "вопрос")

    assert history.message_belongs_to_session(msg.id, session.id) is True
    assert history.message_belongs_to_session(msg.id, other.id) is False
    assert history.mark_message_failed(msg.id, "search_error") is True

    messages = history.get_messages(session.id)
    assert messages[0].metadata.get("failed") is True
    assert messages[0].metadata.get("error") == "search_error"


def test_search_sessions_escapes_like_and_offset(tmp_path):
    history = ChatHistoryManager(str(tmp_path / "history.db"))
    s1 = history.create_session(title="100% готово")
    history.add_message(s1.id, "user", "обычный текст")
    s2 = history.create_session(title="подчёркивание_тест")
    history.add_message(s2.id, "user", "ещё")
    s3 = history.create_session(title="процент готово")
    history.add_message(s3.id, "user", "ещё2")

    # Поиск «100%» не должен матчить «процент» через wildcard
    found = history.search_sessions("100%")
    assert [s.id for s in found] == [s1.id]

    found_under = history.search_sessions("подчёркивание_тест")
    assert [s.id for s in found_under] == [s2.id]

    # offset
    all_found = history.search_sessions("готово", limit=10, offset=0)
    assert len(all_found) >= 2
    paged = history.search_sessions("готово", limit=1, offset=1)
    assert len(paged) == 1
    assert paged[0].id == all_found[1].id


def test_verify_telegram_rejects_second_account(tmp_path):
    from core.chat_history import TelegramAlreadyLinkedError
    from werkzeug.security import generate_password_hash

    history = ChatHistoryManager(str(tmp_path / "history.db"))
    u1 = history.create_user("a", "a@e.com", generate_password_hash("password123"))
    u2 = history.create_user("b", "b@e.com", generate_password_hash("password123"))
    code1 = history.create_telegram_link(u1.id)["code"]
    history.verify_telegram_link(code1, telegram_user_id=777)
    code2 = history.create_telegram_link(u2.id)["code"]
    try:
        history.verify_telegram_link(code2, telegram_user_id=777)
        raise AssertionError("ожидался TelegramAlreadyLinkedError")
    except TelegramAlreadyLinkedError:
        pass

    assert history.unlink_telegram(u1.id) is True
    assert history.get_telegram_link(777) is None
    # После unlink тот же TG можно привязать к другому аккаунту
    assert history.verify_telegram_link(code2, telegram_user_id=777)["user_id"] == u2.id
