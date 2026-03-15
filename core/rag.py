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
import time
from pathlib import Path
import logging
import logging.handlers

from config import settings, get_logger
from utils.embeddings import get_embedding

logger = get_logger(__name__)

# Настройка отдельного файлового логгера для RAG модуля
rag_log_dir = Path(settings.LOG_DIR) / "rag"
rag_log_dir.mkdir(parents=True, exist_ok=True)
rag_log_file = rag_log_dir / "rag_detailed.log"

rag_file_handler = logging.handlers.RotatingFileHandler(
    rag_log_file,
    maxBytes=10 * 1024 * 1024,  # 10 MB
    backupCount=5,
    encoding='utf-8'
)
rag_file_handler.setLevel(logging.DEBUG)
rag_file_formatter = logging.Formatter(
    '%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
rag_file_handler.setFormatter(rag_file_formatter)

# Добавляем файловый обработчик к RAG логгеру
rag_logger = logging.getLogger('rag')
rag_logger.setLevel(logging.DEBUG)
rag_logger.addHandler(rag_file_handler)


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
        rag_logger.info(f"=== Инициализация RAG системы ===")
        rag_logger.debug(f"Входные параметры: collection_name={collection_name}")
        
        start_time = time.time()
        self.collection_name = collection_name or settings.CHROMA_COLLECTION_NAME
        rag_logger.debug(f"Имя коллекции: {self.collection_name}")
        
        rag_logger.debug(f"Подключение к ChromaDB: {settings.CHROMA_PERSIST_DIR}")
        self.client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
        rag_logger.debug("Клиент ChromaDB создан")
        
        # Получаем коллекцию без кастомной функции эмбеддингов
        # Эмбеддинги генерируем вручную через Ollama API
        rag_logger.debug(f"Получение коллекции: {self.collection_name}")
        self.collection = self.client.get_collection(name=self.collection_name)
        rag_logger.debug(f"Коллекция получена. ID: {self.collection.name}")
        
        elapsed = time.time() - start_time
        rag_logger.info(f"RAG система инициализирована за {elapsed:.3f} сек. Коллекция: {self.collection_name}")
        rag_logger.debug(f"Свойства коллекции: {self.collection.count()} документов")
    
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
        rag_logger.info(f"--- Поиск документов ---")
        rag_logger.debug(f"Запрос: '{query}'")
        rag_logger.debug(f"Параметры: top_k={top_k}, min_score={min_score}")
        
        start_time = time.time()
        try:
            # Генерируем эмбеддинг запроса через Ollama API с dimensions=1024
            rag_logger.debug("Генерация эмбеддинга запроса через Ollama API...")
            query_embedding = get_embedding(query)
            
            if not query_embedding:
                rag_logger.error("Не удалось получить эмбеддинг запроса")
                return []
            
            rag_logger.debug(f"Эмбеддинг получен. Размер: {len(query_embedding)}")
            
            # Используем query_embeddings вместо query_texts
            rag_logger.debug(f"Выполнение запроса к ChromaDB (n_results={top_k})")
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k
            )
            
            rag_logger.debug(f"Результаты от ChromaDB получены")
            
            documents = []
            if results['documents'] and results['documents'][0]:
                rag_logger.debug(f"Обработка {len(results['documents'][0])} найденных документов")
                for i, doc in enumerate(results['documents'][0]):
                    score = results['distances'][0][i] if results['distances'] else 0.0
                    # Преобразуем расстояние в оценку релевантности (чем меньше расстояние, тем выше релевантность)
                    relevance_score = 1.0 - min(score, 1.0)
                    
                    rag_logger.debug(f"Документ {i+1}: score={score:.4f}, relevance={relevance_score:.4f}")
                    
                    if relevance_score >= min_score:
                        metadata = results['metadatas'][0][i] if results['metadatas'] else {}
                        chunk_id = results['ids'][0][i] if results['ids'] else f"chunk_{i}"
                        source = metadata.get('source', 'Неизвестный источник')
                        
                        rag_logger.debug(f"Документ {i+1} принят (source={source}, chunk_id={chunk_id})")
                        documents.append({
                            'text': doc,
                            'score': relevance_score,
                            'metadata': metadata,
                            'chunk_id': chunk_id
                        })
            
            elapsed = time.time() - start_time
            rag_logger.info(f"Поиск завершен за {elapsed:.3f} сек. Найдено документов: {len(documents)}")
            rag_logger.debug(f"Топ документы: {[d['metadata'].get('source', 'N/A') for d in documents]}")
            
            return documents
            
        except Exception as e:
            elapsed = time.time() - start_time
            rag_logger.error(f"Ошибка при поиске документов за {elapsed:.3f} сек: {e}", exc_info=True)
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
        rag_logger.info(f"--- Извлечение цитат ---")
        rag_logger.debug(f"Длина ответа: {len(answer)} символов")
        rag_logger.debug(f"Количество документов для анализа: {len(documents)}")
        
        start_time = time.time()
        citations = []
        
        for i, doc in enumerate(documents):
            text = doc['text']
            metadata = doc['metadata']
            chunk_id = doc['chunk_id']
            score = doc['score']
            
            # Получаем источник из метаданных
            source = metadata.get('source', 'Неизвестный источник')
            
            rag_logger.debug(f"Анализ документа {i+1}: source={source}, chunk_id={chunk_id}, score={score:.4f}")
            rag_logger.debug(f"Текст документа (первые 100 символов): {text[:100]}...")
            
            # Проверяем, содержится ли текст документа в ответе
            # Ищем пересечения текста
            citation_text = self._find_citation_in_answer(answer, text)
            
            if citation_text:
                rag_logger.debug(f"Найдена цитата: {citation_text[:50]}...")
                citation = Citation(
                    text=citation_text,
                    source=source,
                    chunk_id=chunk_id,
                    score=score,
                    metadata=metadata
                )
                citations.append(citation)
            else:
                rag_logger.debug(f"Цитата не найдена в ответе")
        
        elapsed = time.time() - start_time
        rag_logger.info(f"Извлечение цитат завершено за {elapsed:.3f} сек. Найдено цитат: {len(citations)}")
        rag_logger.debug(f"Список источников: {[c.source for c in citations]}")
        
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
        rag_logger.debug(f"Поиск цитаты в ответе. Длина документа: {len(document_text)}")
        
        # Разбиваем документ на предложения
        sentences = re.split(r'[.!?]+', document_text)
        sentences = [s.strip() for s in sentences if s.strip()]
        
        rag_logger.debug(f"Разбито предложений: {len(sentences)}")
        
        # Ищем предложения, которые содержатся в ответе
        found_count = 0
        for sentence in sentences:
            # Проверяем, содержится ли предложение в ответе (с небольшими изменениями)
            if len(sentence) > 20:  # Игнорируем слишком короткие предложения
                # Нормализуем текст для сравнения
                normalized_sentence = re.sub(r'\s+', ' ', sentence.lower())
                normalized_answer = re.sub(r'\s+', ' ', answer.lower())
                
                if normalized_sentence in normalized_answer:
                    rag_logger.debug(f"Найдено предложение: {sentence[:50]}...")
                    found_count += 1
                    return sentence
        
        rag_logger.debug(f"Цитаты не найдено. Проверено предложений: {found_count}/{len(sentences)}")
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
        rag_logger.info(f"--- Форматирование ответа с цитатами ---")
        rag_logger.debug(f"Исходный ответ: {answer[:100]}...")
        rag_logger.debug(f"Найдено цитат: {len(citations)}, max для отображения: {max_citations}")
        
        start_time = time.time()
        
        if not citations:
            rag_logger.debug("Цитаты отсутствуют, возврат исходного ответа")
            return answer
        
        # Ограничиваем количество цитат
        citations_to_show = citations[:max_citations]
        rag_logger.debug(f"Будут отображены цитаты: {len(citations_to_show)}")
        
        # Добавляем секцию с источниками
        sources_section = "\n\n**Источники:**\n"
        
        for i, citation in enumerate(citations_to_show, 1):
            source = citation.source
            chunk_id = citation.chunk_id
            score = citation.score
            
            rag_logger.debug(f"Цитата {i}: source={source}, score={score:.4f}")
            
            sources_section += f"\n{i}. {source}"
            if chunk_id:
                sources_section += f" (ID: {chunk_id})"
            sources_section += f" [релевантность: {score:.2%}]"
        
        formatted_answer = answer + sources_section
        elapsed = time.time() - start_time
        
        rag_logger.info(f"Форматирование завершено за {elapsed:.3f} сек")
        rag_logger.debug(f"Длина итогового ответа: {len(formatted_answer)} символов")
        
        return formatted_answer
    
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
        rag_logger.info(f"--- Генерация промпта ---")
        rag_logger.debug(f"Запрос: '{query}'")
        rag_logger.debug(f"Документов: {len(documents)}, max_context_length: {max_context_length}")
        
        start_time = time.time()
        
        # Формируем контекст из документов
        context_parts = []
        current_length = 0
        total_text_length = 0
        
        for i, doc in enumerate(documents):
            text = doc['text']
            source = doc['metadata'].get('source', 'Неизвестный источник')
            text_length = len(text)
            total_text_length += text_length
            
            rag_logger.debug(f"Документ {i+1}: source={source}, length={text_length}")
            
            # Добавляем источник к тексту
            doc_text = f"[Источник: {source}]\n{text}\n"
            doc_text_length = len(doc_text)
            
            # Проверяем длину
            if current_length + doc_text_length > max_context_length:
                rag_logger.debug(f"Превышен лимит длины контекста. Обрезка документа {i+1}")
                # Обрезаем последний документ если нужно
                remaining = max_context_length - current_length
                if remaining > 50:  # Минимальная длина для полезного контента
                    doc_text = doc_text[:remaining] + "..."
                    context_parts.append(doc_text)
                break
            
            context_parts.append(doc_text)
            current_length += doc_text_length
        
        rag_logger.debug(f"Сформирован контекст из {len(context_parts)} документов")
        rag_logger.debug(f"Общая длина контекста: {current_length} символов")
        
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
        
        elapsed = time.time() - start_time
        rag_logger.info(f"Генерация промпта завершена за {elapsed:.3f} сек")
        rag_logger.debug(f"Длина промпта: {len(prompt)} символов")
        
        return prompt
    
    def query(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.0,
        include_citations: bool = True,
        max_citations: int = 5
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
        rag_logger.info(f"=== Выполнение RAG запроса ===")
        rag_logger.debug(f"Запрос: '{query}'")
        rag_logger.debug(f"Параметры: top_k={top_k}, min_score={min_score}, include_citations={include_citations}, max_citations={max_citations}")
        
        start_time = time.time()
        
        # 1. Поиск релевантных документов
        rag_logger.debug("Шаг 1: Поиск релевантных документов")
        documents = self.retrieve_documents(query, top_k, min_score)
        
        if not documents:
            elapsed = time.time() - start_time
            rag_logger.warning(f"RAG запрос завершен за {elapsed:.3f} сек. Не найдено релевантных документов")
            return RAGResult(
                answer="К сожалению, я не нашёл релевантной информации для ответа на ваш вопрос.",
                citations=[],
                sources=[]
            )
        
        rag_logger.debug(f"Найдено {len(documents)} релевантных документов")
        
        # 2. Генерация промпта с контекстом
        rag_logger.debug("Шаг 2: Генерация промпта с контекстом")
        prompt = self.generate_rag_prompt(query, documents)
        
        # 3. Генерация ответа (будет выполняться в qa_system.py)
        # Здесь мы возвращаем промпт и документы для дальнейшей обработки
        rag_logger.debug("Шаг 3: Формирование источников")
        sources = [
            {
                'source': doc['metadata'].get('source', 'Неизвестный источник'),
                'chunk_id': doc['chunk_id'],
                'score': doc['score'],
                'text': doc['text'][:200] + "..." if len(doc['text']) > 200 else doc['text']
            }
            for doc in documents
        ]
        
        rag_logger.debug(f"Сформировано источников: {len(sources)}")
        
        # Возвращаем результат (ответ будет сгенерирован позже)
        elapsed = time.time() - start_time
        rag_logger.info(f"RAG запрос завершен за {elapsed:.3f} сек")
        rag_logger.debug(f"Результат: {len(documents)} документов, {len(sources)} источников")
        
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
        rag_logger.info(f"--- Обогащение ответа цитатами ---")
        rag_logger.debug(f"Длина ответа: {len(answer)} символов")
        rag_logger.debug(f"Документов: {len(documents)}, max_citations: {max_citations}")
        
        start_time = time.time()
        
        # Извлекаем цитаты
        rag_logger.debug("Шаг 1: Извлечение цитат")
        citations = self.extract_citations(answer, documents)
        
        # Форматируем ответ с цитатами
        rag_logger.debug("Шаг 2: Форматирование ответа с цитатами")
        formatted_answer = self.format_answer_with_citations(answer, citations, max_citations)
        
        # Формируем источники
        rag_logger.debug("Шаг 3: Формирование источников")
        sources = [
            {
                'source': doc['metadata'].get('source', 'Неизвестный источник'),
                'chunk_id': doc['chunk_id'],
                'score': doc['score'],
                'text': doc['text'][:200] + "..." if len(doc['text']) > 200 else doc['text']
            }
            for doc in documents
        ]
        
        elapsed = time.time() - start_time
        rag_logger.info(f"Обогащение завершено за {elapsed:.3f} сек")
        rag_logger.debug(f"Найдено цитат: {len(citations)}, источников: {len(sources)}")
        
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
    rag_logger.info(f"Создание RAG системы. collection_name={collection_name}")
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
    rag_logger.debug(f"Подсветка цитат в тексте. Длина текста: {len(text)}, цитат: {len(citations)}")
    
    highlighted_text = text
    replacement_count = 0
    
    for citation in citations:
        citation_text = citation.text
        # Заменяем цитату на подсвеченную версию
        if citation_text in highlighted_text:
            highlighted_text = highlighted_text.replace(
                citation_text,
                f"<mark class='citation'>{citation_text}</mark>"
            )
            replacement_count += 1
            rag_logger.debug(f"Заменена цитата: {citation_text[:50]}...")
    
    rag_logger.debug(f"Выполнено замен: {replacement_count}")
    return highlighted_text
