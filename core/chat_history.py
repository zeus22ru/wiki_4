#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Управление историей чатов в SQLite базе данных
"""

import sqlite3
import json
import re
import secrets
from pathlib import Path
from typing import List, Optional
from datetime import datetime, timedelta

from config import settings, get_logger
from models import ChatSession, Message, User

logger = get_logger(__name__)


class ChatHistoryManager:
    """Менеджер истории чатов"""
    
    def __init__(self, db_path: Optional[str] = None):
        """Инициализация менеджера истории чатов"""
        self.db_path = db_path or settings.DATABASE_PATH
        self._ensure_database_exists()
        self._create_tables()
    
    def _get_connection(self) -> sqlite3.Connection:
        """Получить соединение с базой данных"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn
    
    def _ensure_database_exists(self) -> None:
        """Убедиться, что директория базы данных существует"""
        db_path = Path(self.db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
    
    def _create_tables(self) -> None:
        """Создать таблицы в базе данных"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Таблица сессий чата
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_users_role
                ON users(role)
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    title TEXT NOT NULL DEFAULT 'Новый чат',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            ''')
            
            # Таблица сообщений
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    sources_json TEXT,
                    citations_json TEXT,
                    metadata_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES chat_sessions (id) ON DELETE CASCADE
                )
            ''')

            self._ensure_column(cursor, 'messages', 'citations_json', 'TEXT')
            self._ensure_column(cursor, 'messages', 'metadata_json', 'TEXT')
            self._ensure_column(cursor, 'messages', 'retrieval_query_text', 'TEXT')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id INTEGER,
                    session_id INTEGER,
                    rating TEXT NOT NULL,
                    comment TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (message_id) REFERENCES messages (id) ON DELETE SET NULL,
                    FOREIGN KEY (session_id) REFERENCES chat_sessions (id) ON DELETE CASCADE
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT NOT NULL UNIQUE,
                    filename TEXT NOT NULL,
                    file_type TEXT,
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    modified_at TEXT,
                    indexed_at TEXT,
                    status TEXT NOT NULL DEFAULT 'known',
                    error TEXT
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS index_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    status TEXT NOT NULL,
                    message TEXT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT
                )
            ''')
            
            # Индексы для быстрого поиска
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_messages_session_id 
                ON messages(session_id)
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_messages_created_at
                ON messages(created_at)
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_messages_role
                ON messages(role)
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_messages_session_created_at
                ON messages(session_id, created_at)
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_messages_role_created_at
                ON messages(role, created_at)
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_id 
                ON chat_sessions(user_id)
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_chat_sessions_updated_at
                ON chat_sessions(updated_at)
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_feedback_rating
                ON feedback(rating)
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_feedback_created_at
                ON feedback(created_at)
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_feedback_rating_created_at
                ON feedback(rating, created_at)
            ''')

            # Таблица привязки Telegram-аккаунтов
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS telegram_links (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    code TEXT NOT NULL UNIQUE,
                    telegram_user_id INTEGER,
                    telegram_username TEXT,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used_at TEXT,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
                )
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_telegram_links_code
                ON telegram_links(code)
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_telegram_links_tg_user
                ON telegram_links(telegram_user_id)
            ''')

            conn.commit()
            logger.info("Таблицы истории чатов созданы или уже существуют")

    def _ensure_column(self, cursor: sqlite3.Cursor, table: str, column: str, ddl: str) -> None:
        """Добавить колонку при мягкой миграции SQLite."""
        cursor.execute(f"PRAGMA table_info({table})")
        columns = {row[1] for row in cursor.fetchall()}
        if column not in columns:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    # ========== Методы для работы с пользователями ==========

    def create_user(
        self,
        username: str,
        email: str,
        password_hash: str,
        role: str = "user",
        is_active: bool = True,
    ) -> User:
        """Создать пользователя приложения."""
        now = datetime.now().isoformat()
        normalized_email = email.strip().lower()
        normalized_username = username.strip()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO users (username, email, password_hash, role, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                normalized_username,
                normalized_email,
                password_hash,
                role,
                1 if is_active else 0,
                now,
                now,
            ))
            conn.commit()
            return User(
                id=cursor.lastrowid,
                username=normalized_username,
                email=normalized_email,
                password_hash=password_hash,
                role=role,
                is_active=is_active,
                created_at=datetime.fromisoformat(now),
                updated_at=datetime.fromisoformat(now),
            )

    def get_user(self, user_id: int) -> Optional[User]:
        """Получить пользователя по ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, username, email, password_hash, role, is_active, created_at, updated_at
                FROM users
                WHERE id = ?
            ''', (user_id,))
            row = cursor.fetchone()
            return User.from_row(row) if row else None

    def get_user_by_identifier(self, identifier: str) -> Optional[User]:
        """Найти пользователя по email или username."""
        value = (identifier or "").strip()
        if not value:
            return None
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, username, email, password_hash, role, is_active, created_at, updated_at
                FROM users
                WHERE email = ? COLLATE NOCASE OR username = ? COLLATE NOCASE
            ''', (value.lower(), value))
            row = cursor.fetchone()
            return User.from_row(row) if row else None

    def update_user_role(self, user_id: int, role: str) -> bool:
        """Изменить роль пользователя."""
        now = datetime.now().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE users
                SET role = ?, updated_at = ?
                WHERE id = ?
            ''', (role, now, user_id))
            conn.commit()
            return cursor.rowcount > 0

    # ========== Методы для привязки Telegram ==========

    def create_telegram_link(self, user_id: int) -> dict:
        """Вернуть активный код привязки Telegram или создать новый (6 цифр)."""
        now = datetime.now()
        now_iso = now.isoformat()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT code, expires_at
                FROM telegram_links
                WHERE user_id = ?
                  AND used_at IS NULL
                  AND expires_at > ?
                ORDER BY created_at DESC
                LIMIT 1
            ''', (user_id, now_iso))
            existing = cursor.fetchone()
            if existing:
                return {"code": existing["code"], "expires_at": existing["expires_at"]}

            expires_at = now + timedelta(seconds=settings.TELEGRAM_LINK_CODE_TTL_SECONDS)
            code = f"{secrets.randbelow(1_000_000):06d}"

            # Инвалидировать просроченные/остаточные активные коды этого пользователя
            cursor.execute('''
                UPDATE telegram_links
                SET expires_at = ?
                WHERE user_id = ?
                  AND used_at IS NULL
                  AND expires_at > ?
            ''', (now_iso, user_id, now_iso))

            cursor.execute('''
                INSERT INTO telegram_links (user_id, code, telegram_user_id, telegram_username, created_at, expires_at, used_at)
                VALUES (?, ?, NULL, NULL, ?, ?, NULL)
            ''', (user_id, code, now_iso, expires_at.isoformat()))
            conn.commit()

        logger.info(f"Создан код привязки Telegram для user_id={user_id}")
        return {"code": code, "expires_at": expires_at.isoformat()}

    def verify_telegram_link(self, code: str, telegram_user_id: int, telegram_username: Optional[str] = None) -> Optional[dict]:
        """Проверить код привязки и активировать связь с Telegram."""
        now = datetime.now().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, user_id
                FROM telegram_links
                WHERE code = ?
                  AND used_at IS NULL
                  AND expires_at > ?
            ''', (code, now))
            row = cursor.fetchone()
            if not row:
                return None

            link_id = row["id"]
            user_id = row["user_id"]

            cursor.execute('''
                UPDATE telegram_links
                SET used_at = ?, telegram_user_id = ?, telegram_username = ?
                WHERE id = ?
            ''', (now, telegram_user_id, telegram_username, link_id))

            # Получить роль пользователя
            cursor.execute('SELECT role FROM users WHERE id = ?', (user_id,))
            user_row = cursor.fetchone()
            conn.commit()

        role = user_row["role"] if user_row else "user"
        logger.info(f"Привязан Telegram user_id={telegram_user_id} к пользователю {user_id}")
        return {"user_id": user_id, "role": role}

    def get_telegram_link(self, telegram_user_id: int) -> Optional[dict]:
        """Получить активную привязку по Telegram user_id.

        expires_at относится только к неиспользованному коду; после verify привязка постоянная.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT l.user_id, l.telegram_username, l.used_at, u.role
                FROM telegram_links l
                JOIN users u ON u.id = l.user_id
                WHERE l.telegram_user_id = ?
                  AND l.used_at IS NOT NULL
                ORDER BY l.used_at DESC
                LIMIT 1
            ''', (telegram_user_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "user_id": row["user_id"],
                "role": row["role"],
                "telegram_username": row["telegram_username"],
                "used_at": row["used_at"],
            }

    # ========== Методы для работы с сессиями ==========
    
    def create_session(
        self,
        user_id: Optional[int] = None,
        title: str = "Новый чат"
    ) -> ChatSession:
        """Создать новую сессию чата"""
        now = datetime.now().isoformat()
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO chat_sessions (user_id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?)
            ''', (user_id, title, now, now))
            
            session_id = cursor.lastrowid
            conn.commit()
            
            logger.info(f"Создана новая сессия чата: {session_id}")
            return ChatSession(
                id=session_id,
                user_id=user_id,
                title=title,
                created_at=datetime.fromisoformat(now),
                updated_at=datetime.fromisoformat(now)
            )
    
    def get_session(self, session_id: int) -> Optional[ChatSession]:
        """Получить сессию по ID"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, user_id, title, created_at, updated_at
                FROM chat_sessions
                WHERE id = ?
            ''', (session_id,))
            
            row = cursor.fetchone()
            if row:
                return ChatSession.from_row(row)
            return None
    
    def get_sessions(
        self,
        user_id: Optional[int] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[ChatSession]:
        """Получить список сессий"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            if user_id is not None:
                cursor.execute('''
                    SELECT id, user_id, title, created_at, updated_at
                    FROM chat_sessions
                    WHERE user_id = ?
                    ORDER BY updated_at DESC
                    LIMIT ? OFFSET ?
                ''', (user_id, limit, offset))
            else:
                cursor.execute('''
                    SELECT id, user_id, title, created_at, updated_at
                    FROM chat_sessions
                    ORDER BY updated_at DESC
                    LIMIT ? OFFSET ?
                ''', (limit, offset))
            
            return [ChatSession.from_row(row) for row in cursor.fetchall()]
    
    def update_session(self, session_id: int, title: Optional[str] = None) -> bool:
        """Обновить сессию"""
        now = datetime.now().isoformat()
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            if title is not None:
                cursor.execute('''
                    UPDATE chat_sessions
                    SET title = ?, updated_at = ?
                    WHERE id = ?
                ''', (title, now, session_id))
            else:
                cursor.execute('''
                    UPDATE chat_sessions
                    SET updated_at = ?
                    WHERE id = ?
                ''', (now, session_id))
            
            conn.commit()
            updated = cursor.rowcount > 0
            
            if updated:
                logger.info(f"Сессия {session_id} обновлена")
            
            return updated
    
    def delete_session(self, session_id: int) -> bool:
        """Удалить сессию и все её сообщения"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM chat_sessions WHERE id = ?', (session_id,))
            conn.commit()
            
            deleted = cursor.rowcount > 0
            
            if deleted:
                logger.info(f"Сессия {session_id} удалена")
            
            return deleted

    def delete_all_sessions(self, user_id: Optional[int] = None) -> int:
        """Удалить все сессии чатов и связанные данные."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if user_id is None:
                cursor.execute('DELETE FROM chat_sessions')
            else:
                cursor.execute('DELETE FROM chat_sessions WHERE user_id = ?', (user_id,))
            conn.commit()

            deleted_count = cursor.rowcount

            if deleted_count:
                logger.info(f"Удалены все сессии чатов: {deleted_count}")

            return deleted_count

    def cleanup_guest_sessions(
        self,
        retention_days: int = 30,
        dry_run: bool = True,
        limit: int = 1000,
        vacuum: bool = False,
    ) -> dict:
        """Удалить старые guest/orphan-сессии с безопасным dry-run режимом."""
        retention_days = max(1, int(retention_days))
        limit = max(1, min(int(limit), 10000))
        cutoff = (datetime.now() - timedelta(days=retention_days)).isoformat()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT s.id
                FROM chat_sessions s
                LEFT JOIN users u ON u.id = s.user_id
                WHERE (s.user_id IS NULL OR u.id IS NULL)
                  AND s.updated_at < ?
                ORDER BY s.updated_at ASC
                LIMIT ?
            ''', (cutoff, limit))
            session_ids = [row[0] for row in cursor.fetchall()]

            deleted_count = 0
            if session_ids and not dry_run:
                placeholders = ",".join("?" for _ in session_ids)
                cursor.execute(f"DELETE FROM chat_sessions WHERE id IN ({placeholders})", session_ids)
                deleted_count = cursor.rowcount
                conn.commit()

        vacuumed = False
        if vacuum and deleted_count:
            self.vacuum()
            vacuumed = True

        return {
            "dry_run": dry_run,
            "retention_days": retention_days,
            "cutoff": cutoff,
            "matched": len(session_ids),
            "deleted": deleted_count,
            "limit": limit,
            "vacuumed": vacuumed,
            "session_ids": session_ids,
        }

    def vacuum(self) -> None:
        """Запустить VACUUM отдельным соединением после cleanup."""
        with self._get_connection() as conn:
            conn.execute("VACUUM")
    
    # ========== Методы для работы с сообщениями ==========
    
    def add_message(
        self,
        session_id: int,
        role: str,
        content: str,
        sources: Optional[List[dict]] = None,
        citations: Optional[List[dict]] = None,
        metadata: Optional[dict] = None,
        retrieval_query_text: Optional[str] = None,
    ) -> Message:
        """Добавить сообщение в сессию"""
        now = datetime.now().isoformat()
        sources_json = json.dumps(sources) if sources else None
        citations_json = json.dumps(citations) if citations else None
        metadata_json = json.dumps(metadata) if metadata else None
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO messages (
                    session_id, role, content, sources_json, citations_json, metadata_json,
                    retrieval_query_text, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                session_id, role, content, sources_json, citations_json, metadata_json,
                retrieval_query_text,
                now,
            ))
            
            message_id = cursor.lastrowid
            conn.commit()
            
            # Обновляем время последнего изменения сессии
            self.update_session(session_id)
            
            logger.debug(f"Добавлено сообщение {message_id} в сессию {session_id}")
            
            return Message(
                id=message_id,
                session_id=session_id,
                role=role,
                content=content,
                sources=sources or [],
                citations=citations or [],
                metadata=metadata or {},
                created_at=datetime.fromisoformat(now),
                retrieval_query_text=retrieval_query_text,
            )
    
    def get_messages(self, session_id: int) -> List[Message]:
        """Получить все сообщения сессии"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, session_id, role, content, sources_json, created_at, citations_json, metadata_json,
                       retrieval_query_text
                FROM messages
                WHERE session_id = ?
                ORDER BY created_at ASC
            ''', (session_id,))
            
            return [Message.from_row(row) for row in cursor.fetchall()]

    def get_recent_messages(self, session_id: int, limit: int = 10) -> List[Message]:
        """Получить последние сообщения сессии в хронологическом порядке."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, session_id, role, content, sources_json, created_at, citations_json, metadata_json,
                       retrieval_query_text
                FROM messages
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            ''', (session_id, limit))

            messages = [Message.from_row(row) for row in cursor.fetchall()]
            return list(reversed(messages))
    
    def delete_messages(self, session_id: int) -> bool:
        """Удалить все сообщения сессии"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM messages WHERE session_id = ?', (session_id,))
            conn.commit()
            
            deleted = cursor.rowcount > 0
            
            if deleted:
                logger.info(f"Удалены сообщения сессии {session_id}")
            
            return deleted
    
    # ========== Статистика ==========
    
    def get_session_count(self, user_id: Optional[int] = None) -> int:
        """Получить количество сессий"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            if user_id is not None:
                cursor.execute('SELECT COUNT(*) FROM chat_sessions WHERE user_id = ?', (user_id,))
            else:
                cursor.execute('SELECT COUNT(*) FROM chat_sessions')
            
            return cursor.fetchone()[0]
    
    def get_message_count(self, session_id: int) -> int:
        """Получить количество сообщений в сессии"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM messages WHERE session_id = ?', (session_id,))
            return cursor.fetchone()[0]

    def get_total_message_count(self) -> int:
        """Получить общее количество сообщений."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM messages')
            return cursor.fetchone()[0]

    def search_sessions(
        self,
        query: str,
        limit: int = 20,
        user_id: Optional[int] = None
    ) -> List[ChatSession]:
        """Найти сессии по заголовку или тексту сообщений."""
        like = f"%{query}%"
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if user_id is None:
                cursor.execute('''
                    SELECT DISTINCT s.id, s.user_id, s.title, s.created_at, s.updated_at
                    FROM chat_sessions s
                    LEFT JOIN messages m ON m.session_id = s.id
                    WHERE s.title LIKE ? OR m.content LIKE ?
                    ORDER BY s.updated_at DESC
                    LIMIT ?
                ''', (like, like, limit))
            else:
                cursor.execute('''
                    SELECT DISTINCT s.id, s.user_id, s.title, s.created_at, s.updated_at
                    FROM chat_sessions s
                    LEFT JOIN messages m ON m.session_id = s.id
                    WHERE s.user_id = ? AND (s.title LIKE ? OR m.content LIKE ?)
                    ORDER BY s.updated_at DESC
                    LIMIT ?
                ''', (user_id, like, like, limit))
            return [ChatSession.from_row(row) for row in cursor.fetchall()]

    def add_feedback(
        self,
        session_id: Optional[int],
        message_id: Optional[int],
        rating: str,
        comment: Optional[str] = None
    ) -> dict:
        """Сохранить пользовательскую оценку ответа."""
        now = datetime.now().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO feedback (message_id, session_id, rating, comment, created_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (message_id, session_id, rating, comment, now))
            conn.commit()
            return {
                "id": cursor.lastrowid,
                "message_id": message_id,
                "session_id": session_id,
                "rating": rating,
                "comment": comment,
                "created_at": now,
            }

    def get_feedback(self, limit: int = 50) -> List[dict]:
        """Последние оценки ответов для анализа качества."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, message_id, session_id, rating, comment, created_at
                FROM feedback
                ORDER BY created_at DESC
                LIMIT ?
            ''', (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def get_feedback_summary(self, created_after: Optional[str] = None) -> dict:
        """Сводка оценок ответов."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if created_after:
                cursor.execute('''
                    SELECT rating, COUNT(*) AS count
                    FROM feedback
                    WHERE created_at >= ?
                    GROUP BY rating
                ''', (created_after,))
            else:
                cursor.execute('SELECT rating, COUNT(*) AS count FROM feedback GROUP BY rating')
            counts = {row['rating']: row['count'] for row in cursor.fetchall()}
            return {
                "up": counts.get("up", 0),
                "down": counts.get("down", 0),
                "total": sum(counts.values()),
            }

    def get_top_sources(
        self,
        limit: int = 10,
        created_after: Optional[str] = None,
        scan_limit: int = 2000,
    ) -> List[dict]:
        """Самые часто используемые источники в ответах."""
        scan_limit = max(1, min(int(scan_limit), 10000))
        with self._get_connection() as conn:
            cursor = conn.cursor()
            params: list[object] = []
            created_filter = ""
            if created_after:
                created_filter = "AND created_at >= ?"
                params.append(created_after)
            params.append(scan_limit)
            cursor.execute(f'''
                SELECT sources_json
                FROM messages
                WHERE role = 'assistant' AND sources_json IS NOT NULL
                {created_filter}
                ORDER BY created_at DESC
                LIMIT ?
            ''', params)
            counts: dict[str, dict] = {}
            for row in cursor.fetchall():
                try:
                    sources = json.loads(row['sources_json'] or '[]')
                except json.JSONDecodeError:
                    continue
                for source in sources:
                    key = source.get('path') or source.get('title') or source.get('source') or 'N/A'
                    item = counts.setdefault(key, {
                        "title": source.get('title') or source.get('source') or key,
                        "path": source.get('path') or key,
                        "count": 0,
                    })
                    item["count"] += 1
            return sorted(counts.values(), key=lambda item: item["count"], reverse=True)[:limit]

    def get_negative_feedback_context(self, limit: int = 5) -> List[dict]:
        """Последние дизлайки с текстом сообщения для админского анализа."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT f.id, f.message_id, f.session_id, f.comment, f.created_at,
                       m.content AS answer, s.title AS chat_title
                FROM feedback f
                LEFT JOIN messages m ON m.id = f.message_id
                LEFT JOIN chat_sessions s ON s.id = f.session_id
                WHERE f.rating = 'down'
                ORDER BY f.created_at DESC
                LIMIT ?
            ''', (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def get_source_feedback(
        self,
        limit: int = 10,
        created_after: Optional[str] = None,
        scan_limit: int = 1000,
    ) -> List[dict]:
        """Источники, чаще всего встречающиеся в ответах с негативной оценкой."""
        scan_limit = max(1, min(int(scan_limit), 10000))
        with self._get_connection() as conn:
            cursor = conn.cursor()
            params: list[object] = []
            created_filter = ""
            if created_after:
                created_filter = "AND f.created_at >= ?"
                params.append(created_after)
            params.append(scan_limit)
            cursor.execute(f'''
                SELECT m.sources_json
                FROM feedback f
                JOIN messages m ON m.id = f.message_id
                WHERE f.rating = 'down' AND m.sources_json IS NOT NULL
                {created_filter}
                ORDER BY f.created_at DESC
                LIMIT ?
            ''', params)
            counts: dict[str, dict] = {}
            for row in cursor.fetchall():
                try:
                    sources = json.loads(row['sources_json'] or '[]')
                except json.JSONDecodeError:
                    continue
                for source in sources:
                    key = source.get('path') or source.get('title') or source.get('source') or 'N/A'
                    item = counts.setdefault(key, {
                        "title": source.get('title') or source.get('source') or key,
                        "path": source.get('path') or key,
                        "negative_count": 0,
                    })
                    item["negative_count"] += 1
            return sorted(counts.values(), key=lambda item: item["negative_count"], reverse=True)[:limit]

    @staticmethod
    def _message_quality_reason(message: Message) -> Optional[str]:
        diagnostics = message.metadata.get("diagnostics") if isinstance(message.metadata, dict) else {}
        diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
        retrieve_error = message.metadata.get("retrieve_error") if isinstance(message.metadata, dict) else None
        retrieval_status = diagnostics.get("retrieval_status") or retrieve_error or message.metadata.get("retrieval_status")
        scores = diagnostics.get("score_distribution") or []
        source_count = len(message.sources or [])

        if retrieve_error:
            return f"Ошибка retrieval: {retrieve_error}"
        if retrieval_status in {"no_documents", "embedding_unavailable", "search_error"}:
            return f"Статус поиска: {retrieval_status}"
        if source_count == 0:
            return "Ответ без источников"
        if isinstance(scores, list) and scores:
            numeric_scores = [float(score) for score in scores if isinstance(score, (int, float))]
            if numeric_scores:
                best_score = max(numeric_scores)
                if best_score < 0.35:
                    return f"Низкая максимальная релевантность: {best_score:.2f}"
        return None

    def get_weak_answers(
        self,
        limit: int = 10,
        created_after: Optional[str] = None,
        scan_limit: int = 1000,
    ) -> List[dict]:
        """Ответы, которые стоит проверить редактору базы знаний."""
        scan_limit = max(1, min(int(scan_limit), 10000))
        with self._get_connection() as conn:
            cursor = conn.cursor()
            params: list[object] = []
            created_filter = ""
            if created_after:
                created_filter = "AND created_at >= ?"
                params.append(created_after)
            params.append(scan_limit)
            cursor.execute(f'''
                SELECT id, session_id, role, content, sources_json, created_at, citations_json, metadata_json,
                       retrieval_query_text
                FROM messages
                WHERE role IN ('user', 'assistant')
                {created_filter}
                ORDER BY created_at DESC
                LIMIT ?
            ''', params)
            messages = list(reversed([Message.from_row(row) for row in cursor.fetchall()]))

        previous_user_by_session: dict[int, Message] = {}
        weak = []
        for message in messages:
            if message.role == "user":
                previous_user_by_session[message.session_id] = message
                continue
            if message.role != "assistant":
                continue
            reason = self._message_quality_reason(message)
            if not reason:
                continue
            question = previous_user_by_session.get(message.session_id)
            weak.append({
                "message_id": message.id,
                "session_id": message.session_id,
                "question": question.content if question else "",
                "answer": message.content,
                "reason": reason,
                "source_count": len(message.sources or []),
                "created_at": message.created_at.isoformat() if message.created_at else None,
            })
        return list(reversed(weak))[:limit]

    @staticmethod
    def _gap_key(question: str) -> str:
        words = re.findall(r"[A-Za-zА-Яа-я0-9]{4,}", (question or "").lower())
        stop_words = {"как", "что", "где", "когда", "если", "почему", "нужно", "можно", "надо", "какой", "какая"}
        useful = [word for word in words if word not in stop_words]
        return " ".join(useful[:5]) or (question or "Без вопроса")[:80]

    def get_knowledge_gaps(
        self,
        limit: int = 10,
        created_after: Optional[str] = None,
        scan_limit: int = 2000,
    ) -> List[dict]:
        """Сгруппировать слабые ответы в темы для пополнения базы знаний."""
        groups: dict[str, dict] = {}
        weak_limit = max(200, limit * 20)
        for item in self.get_weak_answers(
            limit=weak_limit,
            created_after=created_after,
            scan_limit=scan_limit,
        ):
            key = self._gap_key(item.get("question", ""))
            group = groups.setdefault(key, {
                "topic": key,
                "count": 0,
                "reasons": {},
                "last_question": "",
                "last_seen_at": None,
                "recommended_action": "Добавить или обновить документ по этой теме",
            })
            group["count"] += 1
            reason = item.get("reason") or "Слабый ответ"
            group["reasons"][reason] = group["reasons"].get(reason, 0) + 1
            group["last_question"] = item.get("question") or group["last_question"]
            group["last_seen_at"] = item.get("created_at") or group["last_seen_at"]

        result = []
        for group in groups.values():
            top_reason = max(group["reasons"].items(), key=lambda item: item[1])[0] if group["reasons"] else "Слабый ответ"
            result.append({
                "topic": group["topic"],
                "count": group["count"],
                "reason": top_reason,
                "last_question": group["last_question"],
                "last_seen_at": group["last_seen_at"],
                "recommended_action": group["recommended_action"],
            })
        return sorted(result, key=lambda item: (item["count"], item["last_seen_at"] or ""), reverse=True)[:limit]


# Глобальный экземпляр менеджера
_chat_history_manager: Optional[ChatHistoryManager] = None


def get_chat_history() -> ChatHistoryManager:
    """Получить глобальный экземпляр менеджера истории чатов"""
    global _chat_history_manager
    if _chat_history_manager is None:
        _chat_history_manager = ChatHistoryManager()
    return _chat_history_manager
