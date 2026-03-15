#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Основные модули приложения
"""

from .rag import (
    RAGSystem,
    Citation,
    RAGResult,
    create_rag_system,
    highlight_citations_in_text
)

from .chat_history import (
    ChatHistoryManager,
    Message
)

__all__ = [
    # RAG
    'RAGSystem',
    'Citation',
    'RAGResult',
    'create_rag_system',
    'highlight_citations_in_text',
    # Chat History
    'ChatHistoryManager',
    'Message'
]
