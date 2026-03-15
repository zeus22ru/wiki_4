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
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES chat_sessions (id) ON DELETE CASCADE
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
    
    # ========== Методы для работы с сообщениями ==========
    
    def add_message(
        self,
        session_id: int,
        role: str,
        content: str,
        sources: Optional[List[dict]] = None
    ) -> Message:
        """Добавить сообщение в сессию"""
        now = datetime.now().isoformat()
        sources_json = json.dumps(sources) if sources else None
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO messages (session_id, role, content, sources_json, created_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (session_id, role, content, sources_json, now))
            
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
                created_at=datetime.fromisoformat(now)
            )
    
    def get_messages(self, session_id: int) -> List[Message]:
        """Получить все сообщения сессии"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, session_id, role, content, sources_json, created_at
                FROM messages
                WHERE session_id = ?
                ORDER BY created_at ASC
            ''', (session_id,))
            
            return [Message.from_row(row) for row in cursor.fetchall()]
    
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


# Глобальный экземпляр менеджера
_chat_history_manager: Optional[ChatHistoryManager] = None


def get_chat_history() -> ChatHistoryManager:
    """Получить глобальный экземпляр менеджера истории чатов"""
    global _chat_history_manager
    if _chat_history_manager is None:
        _chat_history_manager = ChatHistoryManager()
    return _chat_history_manager
