#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модель пользователя для аутентификации
"""

from datetime import datetime
from typing import Optional, Dict, Any


class User:
    """Модель пользователя"""
    
    def __init__(
        self,
        id: Optional[int] = None,
        username: str = "",
        password_hash: Optional[str] = None,
        email: Optional[str] = None,
        role: str = "user",  # "user" или "admin"
        created_at: Optional[datetime] = None
    ):
        self.id = id
        self.username = username
        self.password_hash = password_hash
        self.email = email
        self.role = role
        self.created_at = created_at or datetime.now()
    
    def to_dict(self, include_password: bool = False) -> Dict[str, Any]:
        """Преобразовать в словарь"""
        data = {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'role': self.role,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
        if include_password:
            data['password_hash'] = self.password_hash
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'User':
        """Создать из словаря"""
        return cls(
            id=data.get('id'),
            username=data.get('username', ''),
            password_hash=data.get('password_hash'),
            email=data.get('email'),
            role=data.get('role', 'user'),
            created_at=datetime.fromisoformat(data['created_at']) if data.get('created_at') else None
        )
    
    @classmethod
    def from_row(cls, row: tuple) -> 'User':
        """Создать из строки базы данных"""
        return cls(
            id=row[0],
            username=row[1],
            password_hash=row[2],
            email=row[3],
            role=row[4],
            created_at=datetime.fromisoformat(row[5]) if row[5] else None
        )
    
    def set_password(self, password_hash: str) -> None:
        """Установить хеш пароля"""
        self.password_hash = password_hash
    
    def check_password(self, password_hash: str) -> bool:
        """Проверить хеш пароля"""
        return self.password_hash == password_hash
    
    def is_admin(self) -> bool:
        """Проверить, является ли пользователь администратором"""
        return self.role == "admin"
