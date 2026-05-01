#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Управление историей чатов в SQLite базе данных
"""

import sqlite3
import json
from pathlib import Path
from typing import List, Optional
from datetime import datetime

from config import settings, get_logger
from models import ChatSession, Message

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
                CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_id 
                ON chat_sessions(user_id)
            ''')
            
            conn.commit()
            logger.info("Таблицы истории чатов созданы или уже существуют")

    def _ensure_column(self, cursor: sqlite3.Cursor, table: str, column: str, ddl: str) -> None:
        """Добавить колонку при мягкой миграции SQLite."""
        cursor.execute(f"PRAGMA table_info({table})")
        columns = {row[1] for row in cursor.fetchall()}
        if column not in columns:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
    
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

    def delete_all_sessions(self) -> int:
        """Удалить все сессии чатов и связанные данные."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM chat_sessions')
            conn.commit()

            deleted_count = cursor.rowcount

            if deleted_count:
                logger.info(f"Удалены все сессии чатов: {deleted_count}")

            return deleted_count
    
    # ========== Методы для работы с сообщениями ==========
    
    def add_message(
        self,
        session_id: int,
        role: str,
        content: str,
        sources: Optional[List[dict]] = None,
        citations: Optional[List[dict]] = None,
        metadata: Optional[dict] = None
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
                    session_id, role, content, sources_json, citations_json, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (session_id, role, content, sources_json, citations_json, metadata_json, now))
            
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
                created_at=datetime.fromisoformat(now)
            )
    
    def get_messages(self, session_id: int) -> List[Message]:
        """Получить все сообщения сессии"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, session_id, role, content, sources_json, created_at, citations_json, metadata_json
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
                SELECT id, session_id, role, content, sources_json, created_at, citations_json, metadata_json
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

    def search_sessions(self, query: str, limit: int = 20) -> List[ChatSession]:
        """Найти сессии по заголовку или тексту сообщений."""
        like = f"%{query}%"
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT DISTINCT s.id, s.user_id, s.title, s.created_at, s.updated_at
                FROM chat_sessions s
                LEFT JOIN messages m ON m.session_id = s.id
                WHERE s.title LIKE ? OR m.content LIKE ?
                ORDER BY s.updated_at DESC
                LIMIT ?
            ''', (like, like, limit))
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

    def get_feedback_summary(self) -> dict:
        """Сводка оценок ответов."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT rating, COUNT(*) AS count FROM feedback GROUP BY rating')
            counts = {row['rating']: row['count'] for row in cursor.fetchall()}
            return {
                "up": counts.get("up", 0),
                "down": counts.get("down", 0),
                "total": sum(counts.values()),
            }

    def get_top_sources(self, limit: int = 10) -> List[dict]:
        """Самые часто используемые источники в ответах."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT sources_json
                FROM messages
                WHERE role = 'assistant' AND sources_json IS NOT NULL
            ''')
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


# Глобальный экземпляр менеджера
_chat_history_manager: Optional[ChatHistoryManager] = None


def get_chat_history() -> ChatHistoryManager:
    """Получить глобальный экземпляр менеджера истории чатов"""
    global _chat_history_manager
    if _chat_history_manager is None:
        _chat_history_manager = ChatHistoryManager()
    return _chat_history_manager
