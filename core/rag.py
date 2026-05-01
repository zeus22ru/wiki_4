#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAG (Retrieval-Augmented Generation) с поддержкой цитирования
"""

import chromadb
from chromadb.config import Settings
from typing import List, Dict, Optional, Tuple, Any, Iterator
import re
import json
from dataclasses import dataclass
import time
from pathlib import Path
import logging
import logging.handlers
import requests

from config import settings, get_logger
from utils.embeddings import get_embedding, chat_completion, chat_completion_stream

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
    metadata: Dict[str, Any]
    
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
    #: Код ошибки retrieval: embedding_unavailable | search_error | None при успехе или «нет документов»
    retrieve_error: Optional[str] = None
    diagnostics: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict:
        """Преобразование в словарь"""
        d: Dict[str, Any] = {
            'answer': self.answer,
            'citations': [c.to_dict() for c in self.citations],
            'sources': self.sources,
        }
        if self.retrieve_error is not None:
            d['retrieve_error'] = self.retrieve_error
        if self.diagnostics is not None:
            d['diagnostics'] = self.diagnostics
        return d


def _source_from_metadata(metadata: Optional[Dict[str, Any]]) -> str:
    """Вернуть человекочитаемый источник из доступных метаданных Chroma."""
    metadata = metadata or {}
    for key in ("source", "title", "path"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "Без названия"


def _clip_text(value: str, limit: int) -> str:
    """Обрезать длинный текст для служебных prompt-блоков."""
    value = re.sub(r'\s+', ' ', value or '').strip()
    if len(value) <= limit:
        return value
    return value[:limit - 3].rstrip() + "..."


def _parse_json_object(value: str) -> Dict[str, Any]:
    """Достать JSON-объект из ответа модели, даже если она добавила лишний текст."""
    value = (value or "").strip()
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", value, flags=re.DOTALL)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _format_conversation_history(
    conversation_history: Optional[List[Dict[str, str]]],
    max_messages: int = 10,
    max_chars_per_message: int = 700,
) -> str:
    """Сжать историю чата до компактного блока для LLM."""
    if not conversation_history:
        return ""

    role_labels = {
        "user": "Пользователь",
        "assistant": "Ассистент",
    }
    lines = []
    for message in conversation_history[-max_messages:]:
        role = role_labels.get(str(message.get("role", "")).lower(), "Сообщение")
        content = _clip_text(str(message.get("content", "")), max_chars_per_message)
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


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
        top_k: Optional[int] = None,
        min_score: Optional[float] = None
    ) -> Tuple[List[Dict], Optional[str]]:
        """
        Поиск релевантных документов
        
        Args:
            query: Поисковый запрос
            top_k: Количество документов для возврата (по умолчанию из settings.RAG_TOP_K)
            min_score: Минимальный порог релевантности (по умолчанию из settings.RAG_MIN_SCORE)
            
        Returns:
            (документы, код_ошибки). Код: None при успехе, \"embedding_unavailable\" если не получен
            эмбеддинг запроса, \"search_error\" при сбое Chroma/сети.
        """
        rag_logger.info(f"--- Поиск документов ---")
        rag_logger.debug(f"Запрос: '{query}'")
        
        # Используем значения из настроек по умолчанию
        top_k = top_k if top_k is not None else settings.RAG_TOP_K
        min_score = min_score if min_score is not None else settings.RAG_MIN_SCORE
        
        rag_logger.debug(f"Параметры: top_k={top_k}, min_score={min_score}")
        
        start_time = time.time()
        try:
            # Генерируем эмбеддинг запроса через Ollama API с dimensions=1024
            rag_logger.debug("Генерация эмбеддинга запроса (сервис из .env: OLLAMA_URL / EMBEDDING_API_MODE)...")
            query_embedding = get_embedding(query)
            
            if not query_embedding:
                rag_logger.error("Не удалось получить эмбеддинг запроса")
                return [], "embedding_unavailable"
            
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
                    # Преобразуем косинусное расстояние в оценку релевантности
                    # Для косинусного расстояния: 0 = идентичные векторы, 1 = противоположные
                    # Ограничиваем диапазон [0, 1]
                    relevance_score = max(0.0, min(1.0, 1.0 - score))
                    
                    rag_logger.debug(f"Документ {i+1}: score={score:.4f}, relevance={relevance_score:.4f}")
                    
                    if relevance_score >= min_score:
                        metadata = results['metadatas'][0][i] if results['metadatas'] else {}
                        chunk_id = results['ids'][0][i] if results['ids'] else f"chunk_{i}"
                        source = _source_from_metadata(metadata)
                        
                        rag_logger.debug(f"Документ {i+1} принят (source={source}, chunk_id={chunk_id})")
                        documents.append({
                            'text': doc,
                            'score': relevance_score,
                            'metadata': metadata,
                            'chunk_id': chunk_id
                        })
            
            # Сортируем документы по релевантности (от высокого к низкому)
            documents.sort(key=lambda x: x['score'], reverse=True)
            rag_logger.debug(f"Документы отсортированы по релевантности")
            
            elapsed = time.time() - start_time
            rag_logger.info(f"Поиск завершен за {elapsed:.3f} сек. Найдено документов: {len(documents)}")
            rag_logger.debug(f"Топ документы: {[d['metadata'].get('source', 'N/A') for d in documents]}")
            
            return documents, None
            
        except Exception as e:
            elapsed = time.time() - start_time
            rag_logger.error(f"Ошибка при поиске документов за {elapsed:.3f} сек: {e}", exc_info=True)
            return [], "search_error"
    
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
            source = _source_from_metadata(metadata)
            
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
        max_citations: Optional[int] = None
    ) -> str:
        """
        Форматирование ответа с цитатами
        
        Args:
            answer: Исходный ответ
            citations: Список цитат
            max_citations: Максимальное количество цитат для отображения (по умолчанию из settings.RAG_MAX_CITATIONS)
            
        Returns:
            Отформатированный ответ с цитатами
        """
        rag_logger.info(f"--- Форматирование ответа с цитатами ---")
        rag_logger.debug(f"Исходный ответ: {answer[:100]}...")
        rag_logger.debug(f"Найдено цитат: {len(citations)}, max для отображения: {max_citations}")
        
        # Используем значение из настроек по умолчанию
        max_citations = max_citations if max_citations is not None else settings.RAG_MAX_CITATIONS
        
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
            score = citation.score
            
            rag_logger.debug(f"Цитата {i}: source={source}, score={score:.4f}")
            
            sources_section += f"\n{i}. {source}"
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
        max_context_length: Optional[int] = None,
        answer_mode: str = "default",
        conversation_history: Optional[List[Dict[str, str]]] = None,
        retrieval_query: Optional[str] = None,
    ) -> str:
        """
        Генерация промпта для RAG с контекстом
        
        Args:
            query: Пользовательский запрос
            documents: Список найденных документов
            max_context_length: Максимальная длина контекста (по умолчанию из settings.RAG_MAX_CONTEXT_LENGTH)
            conversation_history: Последние сообщения текущего чата
            retrieval_query: Запрос, который использовался для поиска документов
            
        Returns:
            Сформированный промпт
        """
        rag_logger.info(f"--- Генерация промпта ---")
        rag_logger.debug(f"Запрос: '{query}'")
        rag_logger.debug(f"Документов: {len(documents)}, max_context_length: {max_context_length}")
        
        # Используем значение из настроек по умолчанию
        max_context_length = max_context_length if max_context_length is not None else settings.RAG_MAX_CONTEXT_LENGTH
        
        start_time = time.time()
        
        # Формируем контекст из документов
        context_parts = []
        current_length = 0
        total_text_length = 0
        
        for i, doc in enumerate(documents):
            text = doc['text']
            source = _source_from_metadata(doc.get('metadata'))
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
        
        mode_instructions = {
            "brief": "Дай краткий ответ в 2-4 предложениях, но не теряй ключевые условия.",
            "detailed": "Дай подробный структурированный ответ с шагами и важными оговорками.",
            "sources_only": "Отвечай только тем, что явно следует из контекста. Если данных мало, прямо скажи об этом.",
            "steps": "Дай пошаговое объяснение с нумерованными шагами.",
        }
        extra_instruction = mode_instructions.get(answer_mode, "Дай полезный структурированный ответ.")

        # Формируем промпт
        history_block = _format_conversation_history(conversation_history)
        history_section = f"""
ИСТОРИЯ ДИАЛОГА:
{history_block}
""" if history_block else """
ИСТОРИЯ ДИАЛОГА:
Нет предыдущих сообщений.
"""
        retrieval_section = f"""
ПОИСКОВЫЙ ЗАПРОС:
{retrieval_query}
""" if retrieval_query and retrieval_query != query else ""
        prompt = f"""Ты - полезный ассистент, который отвечает на вопросы на основе предоставленного контекста.

КОНТЕКСТ:
{context}
{history_section}{retrieval_section}

ВОПРОС:
{query}

ИНСТРУКЦИИ:
1. Ответь на вопрос, используя информацию из контекста.
2. Если в контексте нет информации для ответа, честно скажи об этом.
3. Ссылайся на источники в ответе, используя формат [Источник: название].
4. Не выдумывай информацию, которой нет в контексте.
5. Форматируй ответ с использованием Markdown для лучшей читаемости.
6. Режим ответа: {extra_instruction}
7. Используй историю диалога только для понимания уточнений и местоимений; факты бери из контекста источников.
8. Если история диалога противоречит найденному контексту, опирайся на контекст источников.

ОТВЕТ:"""
        
        elapsed = time.time() - start_time
        rag_logger.info(f"Генерация промпта завершена за {elapsed:.3f} сек")
        rag_logger.debug(f"Длина промпта: {len(prompt)} символов")
        
        return prompt
    
    def _generate_answer(self, prompt: str) -> str:
        """
        Генерация ответа через Ollama (/api/generate) или OpenAI-совместимый API (/v1/chat/completions).
        """
        mode = getattr(settings, "CHAT_API_MODE", "ollama") or "ollama"
        rag_logger.debug("Генерация ответа (CHAT_API_MODE=%s)...", mode)
        answer = chat_completion(prompt, timeout=120)
        rag_logger.debug(f"Ответ сгенерирован, длина: {len(answer)} символов")
        return answer

    def build_retrieval_query(
        self,
        query: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """Сформировать поисковый запрос с учетом короткой истории текущего чата."""
        history_block = _format_conversation_history(
            conversation_history,
            max_messages=6,
            max_chars_per_message=350,
        )
        if not history_block:
            return query
        return (
            "История диалога:\n"
            f"{history_block}\n\n"
            "Текущий вопрос:\n"
            f"{query}"
        )

    def verify_answer_against_sources(
        self,
        answer: str,
        citations: List[Dict[str, Any]],
        sources: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Проверить, насколько ответ подтверждается сохраненными цитатами."""
        answer = (answer or "").strip()
        sources = sources or []
        evidence_parts = []
        for i, citation in enumerate(citations[:8], start=1):
            text = _clip_text(str(citation.get("text", "")), 1200)
            if not text:
                continue
            source = citation.get("source") or citation.get("chunk_id") or f"Источник {i}"
            evidence_parts.append(f"[{i}] {source}\n{text}")

        if not answer:
            return {
                "status": "error",
                "summary": "Нечего проверять: текст ответа пустой.",
                "details": [],
                "source_count": len(sources),
                "citation_count": len(citations),
            }

        if not evidence_parts:
            return {
                "status": "no_sources",
                "summary": "Проверка невозможна: у ответа нет сохраненных цитат.",
                "details": [],
                "source_count": len(sources),
                "citation_count": len(citations),
            }

        prompt = f"""Ты проверяешь ответ RAG-ассистента по цитатам из базы знаний.

ОТВЕТ:
{_clip_text(answer, 5000)}

ЦИТАТЫ:
{chr(10).join(evidence_parts)}

ЗАДАЧА:
1. Найди ключевые утверждения ответа.
2. Определи, подтверждаются ли они цитатами.
3. Не используй внешние знания.
4. Верни только JSON без Markdown.

Формат JSON:
{{
  "status": "confirmed" | "partial" | "unsupported",
  "summary": "краткий вывод на русском",
  "details": [
    {{"claim": "утверждение", "verdict": "confirmed" | "uncertain" | "unsupported", "evidence": "короткая ссылка на цитату или причина"}}
  ]
}}"""
        raw = self._generate_answer(prompt)
        parsed = _parse_json_object(raw)
        status = parsed.get("status") if isinstance(parsed, dict) else None
        if status not in {"confirmed", "partial", "unsupported"}:
            status = "partial"
        summary = parsed.get("summary") if isinstance(parsed, dict) else None
        details = parsed.get("details") if isinstance(parsed, dict) else None
        if not isinstance(summary, str) or not summary.strip():
            summary = "Модель выполнила проверку, но вернула результат в свободной форме."
        if not isinstance(details, list):
            details = [{"claim": "Проверка", "verdict": "uncertain", "evidence": raw.strip()}]
        return {
            "status": status,
            "summary": summary.strip(),
            "details": details[:8],
            "source_count": len(sources),
            "citation_count": len(citations),
        }

    def suggest_followup_questions(
        self,
        answer: str,
        citations: List[Dict[str, Any]],
        sources: Optional[List[Dict[str, Any]]] = None,
        limit: int = 5,
    ) -> List[str]:
        """Предложить короткие уточняющие вопросы по ответу и его источникам."""
        answer = _clip_text(answer, 3500)
        sources = sources or []
        evidence = []
        for citation in citations[:6]:
            text = _clip_text(str(citation.get("text", "")), 600)
            if text:
                evidence.append(text)
        source_titles = [
            str(source.get("title") or source.get("source") or source.get("path"))
            for source in sources[:6]
            if source.get("title") or source.get("source") or source.get("path")
        ]
        if not answer:
            return []

        prompt = f"""Сгенерируй {limit} полезных уточняющих вопросов для пользователя корпоративной базы знаний.

ОТВЕТ АССИСТЕНТА:
{answer}

ИСТОЧНИКИ:
{chr(10).join(source_titles) or "Нет названий источников"}

ЦИТАТЫ:
{chr(10).join(evidence) or "Нет цитат"}

Требования:
- вопросы должны быть на русском;
- каждый вопрос до 120 символов;
- вопросы должны помогать продолжить рабочий сценарий;
- не добавляй пояснения.

Верни только JSON-массив строк."""
        raw = self._generate_answer(prompt)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\[.*\]", raw, flags=re.DOTALL)
            if not match:
                return []
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError:
                return []
        if not isinstance(parsed, list):
            return []
        questions = []
        for item in parsed:
            question = re.sub(r"\s+", " ", str(item)).strip()
            if question and question not in questions:
                questions.append(question[:120])
            if len(questions) >= limit:
                break
        return questions
    
    def query(
        self,
        query: str,
        top_k: Optional[int] = None,
        min_score: Optional[float] = None,
        include_citations: bool = True,
        max_citations: Optional[int] = None,
        answer_mode: str = "default",
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> RAGResult:
        """
        Выполнение RAG запроса
        
        Args:
            query: Пользовательский запрос
            top_k: Количество документов для поиска (по умолчанию из settings.RAG_TOP_K)
            min_score: Минимальный порог релевантности (по умолчанию из settings.RAG_MIN_SCORE)
            include_citations: Включать ли цитаты в ответ
            max_citations: Максимальное количество цитат (по умолчанию из settings.RAG_MAX_CITATIONS)
            conversation_history: Последние сообщения текущего чата
            
        Returns:
            Результат RAG с ответом и цитатами
        """
        rag_logger.info(f"=== Выполнение RAG запроса ===")
        rag_logger.debug(f"Запрос: '{query}'")
        
        # Используем значения из настроек по умолчанию
        top_k = top_k if top_k is not None else settings.RAG_TOP_K
        min_score = min_score if min_score is not None else settings.RAG_MIN_SCORE
        max_citations = max_citations if max_citations is not None else settings.RAG_MAX_CITATIONS
        
        rag_logger.debug(f"Параметры: top_k={top_k}, min_score={min_score}, include_citations={include_citations}, max_citations={max_citations}")
        
        start_time = time.time()
        
        # 1. Поиск релевантных документов
        rag_logger.debug("Шаг 1: Поиск релевантных документов")
        retrieval_query = self.build_retrieval_query(query, conversation_history)
        documents, retrieve_error = self.retrieve_documents(retrieval_query, top_k, min_score)
        
        if retrieve_error == "embedding_unavailable":
            elapsed = time.time() - start_time
            rag_logger.warning(f"RAG запрос за {elapsed:.3f} сек: эмбеддинг запроса недоступен")
            return RAGResult(
                answer=(
                    "Поиск по базе не выполнен: не удалось получить эмбеддинг для вашего вопроса. "
                    "Индекс в Chroma уже заполнен, но для каждого запроса нужна работающая модель эмбеддингов "
                    "(например, загрузите модель в LM Studio и проверьте OLLAMA_EMBEDDING_MODEL и INFERENCE_BACKEND=lmstudio)."
                ),
                citations=[],
                sources=[],
                retrieve_error="embedding_unavailable",
                diagnostics={"retrieval_status": "embedding_unavailable", "latency_ms": int(elapsed * 1000)},
            )
        
        if retrieve_error == "search_error":
            elapsed = time.time() - start_time
            rag_logger.warning(f"RAG запрос за {elapsed:.3f} сек: ошибка поиска в Chroma")
            return RAGResult(
                answer="Ошибка при поиске по векторной базе. Проверьте логи и целостность Chroma.",
                citations=[],
                sources=[],
                retrieve_error="search_error",
                diagnostics={"retrieval_status": "search_error", "latency_ms": int(elapsed * 1000)},
            )
        
        if not documents:
            elapsed = time.time() - start_time
            rag_logger.warning(f"RAG запрос завершен за {elapsed:.3f} сек. Не найдено релевантных документов")
            return RAGResult(
                answer="К сожалению, я не нашёл релевантной информации для ответа на ваш вопрос.",
                citations=[],
                sources=[],
                diagnostics={"retrieval_status": "no_documents", "latency_ms": int(elapsed * 1000)},
            )
        
        rag_logger.debug(f"Найдено {len(documents)} релевантных документов")
        
        # 2. Генерация промпта с контекстом
        rag_logger.debug("Шаг 2: Генерация промпта с контекстом")
        prompt = self.generate_rag_prompt(
            query,
            documents,
            answer_mode=answer_mode,
            conversation_history=conversation_history,
            retrieval_query=retrieval_query,
        )
        
        # 3. Генерация ответа через Ollama
        rag_logger.debug("Шаг 3: Генерация ответа через Ollama")
        answer = self._generate_answer(prompt)
        
        # 4. Обогащение ответа цитатами
        rag_logger.debug("Шаг 4: Обогащение ответа цитатами")
        rag_result = self.enrich_answer_with_citations(answer, documents, max_citations)
        
        elapsed = time.time() - start_time
        rag_result.diagnostics = {
            "retrieval_status": "ok",
            "document_count": len(documents),
            "score_distribution": [round(float(d.get("score", 0)), 4) for d in documents],
            "top_k": top_k,
            "min_score": min_score,
            "answer_mode": answer_mode,
            "conversation_messages": len(conversation_history or []),
            "latency_ms": int(elapsed * 1000),
        }
        rag_logger.info(f"RAG запрос завершен за {elapsed:.3f} сек")
        rag_logger.debug(f"Результат: {len(documents)} документов, {len(rag_result.citations)} цитат")
        
        return rag_result

    def stream_rag_answer(
        self,
        query: str,
        documents: List[Dict],
        max_citations: Optional[int] = None,
        answer_mode: str = "default",
        conversation_history: Optional[List[Dict[str, str]]] = None,
        retrieval_query: Optional[str] = None,
    ) -> Iterator[Dict[str, Any]]:
        """
        Потоковая генерация ответа по уже найденным документам.

        Yields:
            {\"type\": \"delta\", \"text\": str} — фрагмент текста модели;
            {\"type\": \"done\", \"rag_result\": RAGResult} — итог с цитатами и блоком источников.
        """
        max_citations = max_citations if max_citations is not None else settings.RAG_MAX_CITATIONS
        rag_logger.info("Потоковая генерация RAG-ответа (%s документов)", len(documents))
        prompt = self.generate_rag_prompt(
            query,
            documents,
            answer_mode=answer_mode,
            conversation_history=conversation_history,
            retrieval_query=retrieval_query,
        )
        parts: List[str] = []
        for fragment in chat_completion_stream(prompt, timeout=120):
            parts.append(fragment)
            yield {"type": "delta", "text": fragment}
        answer = "".join(parts)
        rag_result = self.enrich_answer_with_citations(answer, documents, max_citations)
        rag_result.diagnostics = {
            "retrieval_status": "ok",
            "document_count": len(documents),
            "score_distribution": [round(float(d.get("score", 0)), 4) for d in documents],
            "answer_mode": answer_mode,
            "conversation_messages": len(conversation_history or []),
        }
        yield {"type": "done", "rag_result": rag_result}
    
    def enrich_answer_with_citations(
        self,
        answer: str,
        documents: List[Dict],
        max_citations: Optional[int] = None
    ) -> RAGResult:
        """
        Обогащение сгенерированного ответа цитатами
        
        Args:
            answer: Сгенерированный ответ
            documents: Список найденных документов
            max_citations: Максимальное количество цитат (по умолчанию из settings.RAG_MAX_CITATIONS)
            
        Returns:
            RAG результат с цитатами
        """
        rag_logger.info(f"--- Обогащение ответа цитатами ---")
        rag_logger.debug(f"Длина ответа: {len(answer)} символов")
        rag_logger.debug(f"Документов: {len(documents)}, max_citations: {max_citations}")
        
        # Используем значение из настроек по умолчанию
        max_citations = max_citations if max_citations is not None else settings.RAG_MAX_CITATIONS
        
        start_time = time.time()
        
        # Извлекаем цитаты
        rag_logger.debug("Шаг 1: Извлечение цитат")
        citations = self.extract_citations(answer, documents)
        
        # Форматируем ответ с цитатами
        rag_logger.debug("Шаг 2: Форматирование ответа с цитатами")
        formatted_answer = self.format_answer_with_citations(answer, citations, max_citations)
        
        # Формируем источники
        rag_logger.debug("Шаг 3: Формирование источников")
        sources = []
        for doc in documents:
            meta = doc.get('metadata') or {}
            title = meta.get('title') or _source_from_metadata(meta)
            path = meta.get('path', 'N/A')
            score = float(doc['score'])
            sources.append({
                'source': _source_from_metadata(meta),
                'chunk_id': doc['chunk_id'],
                'score': score,
                'text': doc['text'][:200] + "..." if len(doc['text']) > 200 else doc['text'],
                'title': title,
                'path': path,
                'file_type': meta.get('file_type', ''),
                'chunk_index': meta.get('chunk_index'),
                'total_chunks': meta.get('total_chunks'),
                'relevance': round(score, 2),
            })
        
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
