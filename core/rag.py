#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAG (Retrieval-Augmented Generation) с поддержкой цитирования
"""

import chromadb
from chromadb.config import Settings
from typing import List, Dict, Optional, Tuple
import re
from dataclasses import dataclass

from config import settings, get_logger
from utils.embeddings import get_embedding

logger = get_logger(__name__)


@dataclass
class Citation:
    """Класс для хранения информации о цитате"""
    text: str
    source: str
    chunk_id: str
    score: float
    metadata: Dict[str, any]
    
    def to_dict(self) -> Dict:
        """Преобразование в словарь"""
        return {
            'text': self.text,
            'source': self.source,
            'chunk_id': self.chunk_id,
            'score': self.score,
            'metadata': self.metadata
        }


@dataclass
class RAGResult:
    """Результат RAG с цитатами"""
    answer: str
    citations: List[Citation]
    sources: List[Dict]
    
    def to_dict(self) -> Dict:
        """Преобразование в словарь"""
        return {
            'answer': self.answer,
            'citations': [c.to_dict() for c in self.citations],
            'sources': self.sources
        }


class RAGSystem:
    """Система RAG с поддержкой цитирования"""
    
    def __init__(self, collection_name: Optional[str] = None):
        """
        Инициализация RAG системы
        
        Args:
            collection_name: Имя коллекции ChromaDB
        """
        self.collection_name = collection_name or settings.CHROMA_COLLECTION_NAME
        self.client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
        
        # Получаем коллекцию без кастомной функции эмбеддингов
        # Эмбеддинги генерируем вручную через Ollama API
        self.collection = self.client.get_collection(name=self.collection_name)
        logger.info(f"RAG система инициализирована с коллекцией: {self.collection_name}")
    
    def retrieve_documents(
        self,
        query: str,
        top_k: int = 3,
        min_score: float = 0.0
    ) -> List[Dict]:
        """
        Поиск релевантных документов
        
        Args:
            query: Поисковый запрос
            top_k: Количество документов для возврата
            min_score: Минимальный порог релевантности
            
        Returns:
            Список релевантных документов с метаданными
        """
        try:
            # Генерируем эмбеддинг запроса через Ollama API с dimensions=1024
            query_embedding = get_embedding(query)
            
            if not query_embedding:
                logger.error("Не удалось получить эмбеддинг запроса")
                return []
            
            # Используем query_embeddings вместо query_texts
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k
            )
            
            documents = []
            if results['documents'] and results['documents'][0]:
                for i, doc in enumerate(results['documents'][0]):
                    score = results['distances'][0][i] if results['distances'] else 0.0
                    # Преобразуем расстояние в оценку релевантности (чем меньше расстояние, тем выше релевантность)
                    relevance_score = 1.0 - min(score, 1.0)
                    
                    if relevance_score >= min_score:
                        metadata = results['metadatas'][0][i] if results['metadatas'] else {}
                        documents.append({
                            'text': doc,
                            'score': relevance_score,
                            'metadata': metadata,
                            'chunk_id': results['ids'][0][i] if results['ids'] else f"chunk_{i}"
                        })
            
            logger.info(f"Найдено {len(documents)} документов для запроса: '{query}'")
            return documents
            
        except Exception as e:
            logger.error(f"Ошибка при поиске документов: {e}")
            return []
    
    def extract_citations(
        self,
        answer: str,
        documents: List[Dict]
    ) -> List[Citation]:
        """
        Извлечение цитат из ответа на основе найденных документов
        
        Args:
            answer: Сгенерированный ответ
            documents: Список найденных документов
            
        Returns:
            Список цитат
        """
        citations = []
        
        for doc in documents:
            text = doc['text']
            metadata = doc['metadata']
            chunk_id = doc['chunk_id']
            score = doc['score']
            
            # Получаем источник из метаданных
            source = metadata.get('source', 'Неизвестный источник')
            
            # Проверяем, содержится ли текст документа в ответе
            # Ищем пересечения текста
            citation_text = self._find_citation_in_answer(answer, text)
            
            if citation_text:
                citation = Citation(
                    text=citation_text,
                    source=source,
                    chunk_id=chunk_id,
                    score=score,
                    metadata=metadata
                )
                citations.append(citation)
        
        logger.info(f"Извлечено {len(citations)} цитат из ответа")
        return citations
    
    def _find_citation_in_answer(self, answer: str, document_text: str) -> Optional[str]:
        """
        Поиск цитаты в ответе
        
        Args:
            answer: Сгенерированный ответ
            document_text: Текст документа
            
        Returns:
            Текст цитаты или None
        """
        # Разбиваем документ на предложения
        sentences = re.split(r'[.!?]+', document_text)
        sentences = [s.strip() for s in sentences if s.strip()]
        
        # Ищем предложения, которые содержатся в ответе
        for sentence in sentences:
            # Проверяем, содержится ли предложение в ответе (с небольшими изменениями)
            if len(sentence) > 20:  # Игнорируем слишком короткие предложения
                # Нормализуем текст для сравнения
                normalized_sentence = re.sub(r'\s+', ' ', sentence.lower())
                normalized_answer = re.sub(r'\s+', ' ', answer.lower())
                
                if normalized_sentence in normalized_answer:
                    return sentence
        
        return None
    
    def format_answer_with_citations(
        self,
        answer: str,
        citations: List[Citation],
        max_citations: int = 3
    ) -> str:
        """
        Форматирование ответа с цитатами
        
        Args:
            answer: Исходный ответ
            citations: Список цитат
            max_citations: Максимальное количество цитат для отображения
            
        Returns:
            Отформатированный ответ с цитатами
        """
        if not citations:
            return answer
        
        # Ограничиваем количество цитат
        citations_to_show = citations[:max_citations]
        
        # Добавляем секцию с источниками
        sources_section = "\n\n**Источники:**\n"
        
        for i, citation in enumerate(citations_to_show, 1):
            source = citation.source
            chunk_id = citation.chunk_id
            score = citation.score
            
            sources_section += f"\n{i}. {source}"
            if chunk_id:
                sources_section += f" (ID: {chunk_id})"
            sources_section += f" [релевантность: {score:.2%}]"
        
        return answer + sources_section
    
    def generate_rag_prompt(
        self,
        query: str,
        documents: List[Dict],
        max_context_length: int = 3000
    ) -> str:
        """
        Генерация промпта для RAG с контекстом
        
        Args:
            query: Пользовательский запрос
            documents: Список найденных документов
            max_context_length: Максимальная длина контекста
            
        Returns:
            Сформированный промпт
        """
        # Формируем контекст из документов
        context_parts = []
        current_length = 0
        
        for doc in documents:
            text = doc['text']
            source = doc['metadata'].get('source', 'Неизвестный источник')
            
            # Добавляем источник к тексту
            doc_text = f"[Источник: {source}]\n{text}\n"
            
            # Проверяем длину
            if current_length + len(doc_text) > max_context_length:
                # Обрезаем последний документ если нужно
                remaining = max_context_length - current_length
                if remaining > 50:  # Минимальная длина для полезного контента
                    doc_text = doc_text[:remaining] + "..."
                    context_parts.append(doc_text)
                break
            
            context_parts.append(doc_text)
            current_length += len(doc_text)
        
        context = "\n---\n".join(context_parts)
        
        # Формируем промпт
        prompt = f"""Ты - полезный ассистент, который отвечает на вопросы на основе предоставленного контекста.

КОНТЕКСТ:
{context}

ВОПРОС:
{query}

ИНСТРУКЦИИ:
1. Ответь на вопрос, используя информацию из контекста.
2. Если в контексте нет информации для ответа, честно скажи об этом.
3. Ссылайся на источники в ответе, используя формат [Источник: название].
4. Не выдумывай информацию, которой нет в контексте.
5. Форматируй ответ с использованием Markdown для лучшей читаемости.

ОТВЕТ:"""
        
        return prompt
    
    def query(
        self,
        query: str,
        top_k: int = 3,
        min_score: float = 0.0,
        include_citations: bool = True,
        max_citations: int = 3
    ) -> RAGResult:
        """
        Выполнение RAG запроса
        
        Args:
            query: Пользовательский запрос
            top_k: Количество документов для поиска
            min_score: Минимальный порог релевантности
            include_citations: Включать ли цитаты в ответ
            max_citations: Максимальное количество цитат
            
        Returns:
            Результат RAG с ответом и цитатами
        """
        logger.info(f"Выполнение RAG запроса: '{query}'")
        
        # 1. Поиск релевантных документов
        documents = self.retrieve_documents(query, top_k, min_score)
        
        if not documents:
            logger.warning("Не найдено релевантных документов")
            return RAGResult(
                answer="К сожалению, я не нашёл релевантной информации для ответа на ваш вопрос.",
                citations=[],
                sources=[]
            )
        
        # 2. Генерация промпта с контекстом
        prompt = self.generate_rag_prompt(query, documents)
        
        # 3. Генерация ответа (будет выполняться в qa_system.py)
        # Здесь мы возвращаем промпт и документы для дальнейшей обработки
        sources = [
            {
                'source': doc['metadata'].get('source', 'Неизвестный источник'),
                'chunk_id': doc['chunk_id'],
                'score': doc['score'],
                'text': doc['text'][:200] + "..." if len(doc['text']) > 200 else doc['text']
            }
            for doc in documents
        ]
        
        # Возвращаем результат (ответ будет сгенерирован позже)
        return RAGResult(
            answer="",  # Будет заполнен после генерации
            citations=[],
            sources=sources
        )
    
    def enrich_answer_with_citations(
        self,
        answer: str,
        documents: List[Dict],
        max_citations: int = 3
    ) -> RAGResult:
        """
        Обогащение сгенерированного ответа цитатами
        
        Args:
            answer: Сгенерированный ответ
            documents: Список найденных документов
            max_citations: Максимальное количество цитат
            
        Returns:
            RAG результат с цитатами
        """
        # Извлекаем цитаты
        citations = self.extract_citations(answer, documents)
        
        # Форматируем ответ с цитатами
        formatted_answer = self.format_answer_with_citations(answer, citations, max_citations)
        
        # Формируем источники
        sources = [
            {
                'source': doc['metadata'].get('source', 'Неизвестный источник'),
                'chunk_id': doc['chunk_id'],
                'score': doc['score'],
                'text': doc['text'][:200] + "..." if len(doc['text']) > 200 else doc['text']
            }
            for doc in documents
        ]
        
        return RAGResult(
            answer=formatted_answer,
            citations=citations,
            sources=sources
        )


# ============================================
# Функции-помощники
# ============================================

def create_rag_system(collection_name: Optional[str] = None) -> RAGSystem:
    """
    Создание экземпляра RAG системы
    
    Args:
        collection_name: Имя коллекции ChromaDB
        
    Returns:
        Экземпляр RAGSystem
    """
    return RAGSystem(collection_name)


def highlight_citations_in_text(text: str, citations: List[Citation]) -> str:
    """
    Подсветка цитат в тексте
    
    Args:
        text: Исходный текст
        citations: Список цитат
        
    Returns:
        Текст с подсветкой цитат
    """
    highlighted_text = text
    
    for citation in citations:
        citation_text = citation.text
        # Заменяем цитату на подсвеченную версию
        highlighted_text = highlighted_text.replace(
            citation_text,
            f"<mark class='citation'>{citation_text}</mark>"
        )
    
    return highlighted_text
