#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модели для истории чатов
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
import json


class ChatSession:
    """Модель сессии чата"""
    
    def __init__(
        self,
        id: Optional[int] = None,
        user_id: Optional[int] = None,
        title: str = "Новый чат",
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None
    ):
        self.id = id
        self.user_id = user_id
        self.title = title
        self.created_at = created_at or datetime.now()
        self.updated_at = updated_at or datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        """Преобразовать в словарь"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'title': self.title,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ChatSession':
        """Создать из словаря"""
        return cls(
            id=data.get('id'),
            user_id=data.get('user_id'),
            title=data.get('title', 'Новый чат'),
            created_at=datetime.fromisoformat(data['created_at']) if data.get('created_at') else None,
            updated_at=datetime.fromisoformat(data['updated_at']) if data.get('updated_at') else None
        )
    
    @classmethod
    def from_row(cls, row: tuple) -> 'ChatSession':
        """Создать из строки базы данных"""
        return cls(
            id=row[0],
            user_id=row[1],
            title=row[2],
            created_at=datetime.fromisoformat(row[3]) if row[3] else None,
            updated_at=datetime.fromisoformat(row[4]) if row[4] else None
        )


class Message:
    """Модель сообщения в чате"""
    
    def __init__(
        self,
        id: Optional[int] = None,
        session_id: Optional[int] = None,
        role: str = "user",  # "user" или "assistant"
        content: str = "",
        sources: Optional[List[Dict[str, Any]]] = None,
        created_at: Optional[datetime] = None
    ):
        self.id = id
        self.session_id = session_id
        self.role = role
        self.content = content
        self.sources = sources or []
        self.created_at = created_at or datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        """Преобразовать в словарь"""
        return {
            'id': self.id,
            'session_id': self.session_id,
            'role': self.role,
            'content': self.content,
            'sources': self.sources,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Message':
        """Создать из словаря"""
        return cls(
            id=data.get('id'),
            session_id=data.get('session_id'),
            role=data.get('role', 'user'),
            content=data.get('content', ''),
            sources=data.get('sources', []),
            created_at=datetime.fromisoformat(data['created_at']) if data.get('created_at') else None
        )
    
    @classmethod
    def from_row(cls, row: tuple) -> 'Message':
        """Создать из строки базы данных"""
        sources = []
        if row[4]:  # sources_json
            try:
                sources = json.loads(row[4])
            except json.JSONDecodeError:
                pass
        
        return cls(
            id=row[0],
            session_id=row[1],
            role=row[2],
            content=row[3],
            sources=sources,
            created_at=datetime.fromisoformat(row[5]) if row[5] else None
        )
