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
import uuid

from config import settings, get_logger
from utils.embeddings import (
    get_embedding,
    chat_completion,
    chat_completion_stream,
    strip_model_reasoning,
    _filter_reasoning_stream,
)
from core.retrieval import hybrid_retrieve, load_bm25_okapi

logger = get_logger(__name__)

# Настройка отдельного файлового логгера для RAG модуля
rag_log_dir = Path(settings.LOG_DIR) / "rag"
rag_log_dir.mkdir(parents=True, exist_ok=True)
rag_log_file = rag_log_dir / "rag_detailed.log"
deep_retrieval_log_file = rag_log_dir / "deep_retrieval.log"

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
if not any(
    isinstance(h, logging.handlers.RotatingFileHandler)
    and getattr(h, "baseFilename", None) == str(rag_log_file)
    for h in rag_logger.handlers
):
    rag_logger.addHandler(rag_file_handler)

# Отдельный логгер для deep retrieval (в отдельный файл)
deep_retrieval_file_handler = logging.handlers.RotatingFileHandler(
    deep_retrieval_log_file,
    maxBytes=10 * 1024 * 1024,  # 10 MB
    backupCount=5,
    encoding='utf-8',
)
deep_retrieval_file_handler.setLevel(logging.DEBUG)
deep_retrieval_file_handler.setFormatter(rag_file_formatter)

deep_retrieval_logger = logging.getLogger("deep_retrieval")
deep_retrieval_logger.setLevel(logging.DEBUG)
if not any(
    isinstance(h, logging.handlers.RotatingFileHandler)
    and getattr(h, "baseFilename", None) == str(deep_retrieval_log_file)
    for h in deep_retrieval_logger.handlers
):
    deep_retrieval_logger.addHandler(deep_retrieval_file_handler)

# Отдельный логгер: обмен "вопрос ↔ LLM" (JSONL) для анализа качества
llm_log_dir = Path(settings.LOG_DIR) / "llm"
llm_log_dir.mkdir(parents=True, exist_ok=True)
llm_exchange_log_file = llm_log_dir / "llm_exchange.jsonl"

llm_exchange_file_handler = logging.handlers.RotatingFileHandler(
    llm_exchange_log_file,
    maxBytes=20 * 1024 * 1024,  # 20 MB
    backupCount=10,
    encoding="utf-8",
)
llm_exchange_file_handler.setLevel(logging.INFO)
llm_exchange_file_handler.setFormatter(logging.Formatter("%(message)s"))

llm_exchange_logger = logging.getLogger("llm_exchange")
llm_exchange_logger.setLevel(logging.INFO)
if not any(
    isinstance(h, logging.handlers.RotatingFileHandler)
    and getattr(h, "baseFilename", None) == str(llm_exchange_log_file)
    for h in llm_exchange_logger.handlers
):
    llm_exchange_logger.addHandler(llm_exchange_file_handler)


def _clip_for_llm_log(value: str, limit: Optional[int] = None) -> str:
    limit = int(limit or getattr(settings, "LLM_EXCHANGE_LOG_MAX_CHARS", 20000) or 20000)
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def _safe_json_log(payload: Dict[str, Any]) -> None:
    """Записать одну JSONL-строку в llm_exchange, без падений основного потока."""
    if not bool(getattr(settings, "LLM_EXCHANGE_LOG_ENABLED", True)):
        return
    try:
        llm_exchange_logger.info(json.dumps(payload, ensure_ascii=False, default=str))
        for h in llm_exchange_logger.handlers:
            try:
                h.flush()
            except Exception:
                pass
    except Exception:
        # Логирование не должно ломать ответы пользователю.
        pass


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


def _clip_text_keep_newlines(value: str, limit: int) -> str:
    """
    Обрезать длинный текст, сохраняя переводы строк.

    Важно для контента, где переносы строк несут смысл (например, Mermaid/код).
    """
    value = (value or "").strip()
    if len(value) <= limit:
        return value
    return value[:limit - 3].rstrip() + "..."


def _normalize_mermaid_code(code_text: str) -> str:
    """
    Дешёвая нормализация Mermaid-кода для типовых ошибок LLM.

    Цель: повысить шанс успешного рендера без ещё одного LLM-вызова.
    """
    text = (code_text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return text

    # Нормализация частых HTML-тегов внутри label'ов.
    # `<b>` убираем, а `<br>` унифицируем к `<br/>` (Mermaid любит этот вариант для многострочных подписей).
    text = re.sub(r"(?i)</?b\s*>", "", text)
    text = re.sub(r"(?i)<br\s*/?>", "<br/>", text)

    # Частая ошибка LLM: подписи ребер в кавычках: `A -- "текст" --> B`.
    # Для flowchart более устойчиво: `A -->|текст| B`.
    text = re.sub(r'(?m)(--+)\s*"([^"\n]+)"\s*(--+>)', r"\1>| \2 |\3", text)
    text = re.sub(r'(?m)(-\.+)\s*"([^"\n]+)"\s*(\.+->)', r"\1>| \2 |\3", text)

    # Нормализуем "умные" кавычки.
    text = (
        text.replace("“", '"')
        .replace("”", '"')
        .replace("„", '"')
        .replace("«", '"')
        .replace("»", '"')
        .replace("’", "'")
        .replace("‘", "'")
    )

    # Частая ошибка: `subgraph "Название с пробелами"` (и тем более с вложенными кавычками).
    # Приводим к форме `subgraph sg1["Название ..."]`.
    sg_idx = 0

    def _fix_subgraph_quoted(m: re.Match) -> str:
        nonlocal sg_idx
        sg_idx += 1
        label = (m.group(1) or "").strip()
        # Внутри ["..."] нельзя оставлять двойные кавычки — заменяем на одиночные.
        label = label.replace('"', "'")
        return f'subgraph sg{sg_idx}["{label}"]'

    text = re.sub(
        r'(?mi)^\s*subgraph\s+"([^"\n]*(?:"[^"\n]*)*)"\s*$',
        _fix_subgraph_quoted,
        text,
    )
    text = re.sub(
        r"(?mi)^\s*subgraph\s+'([^'\n]*(?:'[^'\n]*)*)'\s*$",
        _fix_subgraph_quoted,
        text,
    )

    def _sanitize_bracket_labels(line: str) -> str:
        """
        В Mermaid flowchart есть форма `A["text"]` и `subgraph id["label"]`.
        Если внутри text есть двойные кавычки, Mermaid ломается.
        """
        if '["' not in line:
            return line
        out = line
        start = 0
        while True:
            i = out.find('["', start)
            if i < 0:
                break
            j = out.find('"]', i + 2)
            if j < 0:
                break
            inner = out[i + 2 : j]
            # Переводы строк внутри [] ломают парсер Mermaid — заменяем на `<br/>`.
            if "\n" in inner:
                inner = inner.replace("\n", "<br/>")
            if '"' in inner:
                inner = inner.replace('"', "'")
            if r"\"" in inner:
                inner = inner.replace(r"\"", "'")
            out = out[: i + 2] + inner + out[j:]
            start = i + 2 + len(inner) + 2
        return out

    text = "\n".join(_sanitize_bracket_labels(ln) for ln in text.split("\n"))

    return text


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


def _best_score(documents: List[Dict[str, Any]]) -> float:
    scores = []
    for d in documents or []:
        s = d.get("score")
        if isinstance(s, (int, float)):
            scores.append(float(s))
    return max(scores) if scores else 0.0


def _slim_doc_label(doc: Dict[str, Any]) -> str:
    """Короткая подпись для LLM: title / section_path / path."""
    meta = (doc or {}).get("metadata") or {}
    title = str(meta.get("title") or meta.get("source") or meta.get("path") or "Без названия").strip()
    section_path = str(meta.get("section_path") or "").strip()
    path = str(meta.get("path") or "").strip()
    parts = [title]
    if section_path:
        parts.append(section_path)
    if path and path != title:
        parts.append(path)
    return " | ".join([p for p in parts if p])[:220]


def _json_array_parse_candidates(value: str) -> List[str]:
    """Варианты текста для json.loads (в т.ч. после обрезки strip_model_reasoning)."""
    value = (value or "").strip()
    if not value:
        return []
    candidates: List[str] = [value]
    if value.endswith("]") and not value.lstrip().startswith("["):
        candidates.append("[" + value)
        head = value.lstrip()
        if head and not head.startswith(('"', "'")):
            candidates.append('["' + value)
    match = re.search(r"\[.*\]", value, flags=re.DOTALL)
    if match:
        fragment = match.group(0)
        if fragment not in candidates:
            candidates.append(fragment)
    return candidates


def _parse_json_array_of_strings(value: str) -> List[str]:
    value = (value or "").strip()
    if not value:
        return []
    parsed = None
    for candidate in _json_array_parse_candidates(value):
        try:
            parsed = json.loads(candidate)
            break
        except json.JSONDecodeError:
            continue
    if parsed is None:
        quoted = re.findall(r'"((?:[^"\\]|\\.)*)"', value)
        if quoted:
            parsed = quoted
    if not isinstance(parsed, list):
        return []
    out: List[str] = []
    for item in parsed:
        s = re.sub(r"\s+", " ", str(item)).strip()
        if not s or len(s) < 3:
            continue
        if s not in out:
            out.append(s[:500])
    return out


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
        
        self.collection = self._load_collection()
        self._bm25_bundle = None

        elapsed = time.time() - start_time
        rag_logger.info(f"RAG система инициализирована за {elapsed:.3f} сек. Коллекция: {self.collection_name}")
        rag_logger.debug(f"Свойства коллекции: {self.collection.count()} документов")

    def _load_collection(self):
        """Получить актуальный объект коллекции ChromaDB."""
        # Эмбеддинги генерируем вручную через Ollama API, поэтому embedding function не передаём.
        rag_logger.debug(f"Получение коллекции: {self.collection_name}")
        collection = self.client.get_collection(name=self.collection_name)
        rag_logger.debug(f"Коллекция получена. ID: {collection.name}")
        return collection

    def _reload_collection(self):
        """Переподключиться к коллекции после переиндексации."""
        rag_logger.warning("Обновление подключения к коллекции ChromaDB после переиндексации")
        self.collection = self._load_collection()
        return self.collection

    def _get_bm25_bundle(self):
        """Ленивая загрузка BM25 (после переиндексации сбрасывается сбросом процесса)."""
        mode = (settings.RETRIEVAL_MODE or "hybrid").lower()
        if mode not in ("hybrid", "sparse"):
            return None
        if self._bm25_bundle is None:
            self._bm25_bundle = load_bm25_okapi()
        return self._bm25_bundle

    def _llm_standalone_search_query(self, history_block: str, question: str) -> str:
        prompt = f"""История диалога:
{history_block}

Текущая реплика пользователя:
{question}

Сформулируй один самодостаточный поисковый запрос к корпоративной базе знаний на русском языке.
Только текст запроса, без пояснений и без кавычек."""
        text = (chat_completion(prompt, timeout=90) or "").strip()
        return re.sub(r"^[\"']|[\"']$", "", text).strip()

    def _llm_multi_query_variants(self, core_query: str, original: str) -> List[str]:
        prompt = f"""Базовый поисковый запрос: {core_query}
Исходная реплика пользователя: {original}

Сгенерируй 2–3 коротких альтернативных запроса к базе знаний (другие формулировки, синонимы).
Верни только JSON-массив строк на русском."""
        raw = chat_completion(prompt, timeout=90) or ""
        return _parse_json_array_of_strings(raw)[:4]

    def _llm_hyde_passage(self, question: str) -> str:
        prompt = f"""Вопрос пользователя: {question}

Напиши 2–3 предложения гипотетического ответа так, как будто они взяты из внутренней документации компании.
Только связный текст, без заголовков и без «в документации сказано»."""
        return (chat_completion(prompt, timeout=90) or "").strip()

    def _llm_deep_next_queries(
        self,
        question: str,
        conversation_history: Optional[List[Dict[str, str]]],
        previous_queries: List[str],
        top_documents: List[Dict[str, Any]],
        reason: str,
        limit: int,
    ) -> List[str]:
        """Сгенерировать уточняющие/альтернативные поисковые запросы для deep retrieval."""
        history_block = _format_conversation_history(
            conversation_history,
            max_messages=min(settings.RAG_QUERY_EXPANSION_MAX_MESSAGES, 6),
            max_chars_per_message=300,
        )
        doc_hints = []
        for doc in (top_documents or [])[:8]:
            doc_hints.append(_slim_doc_label(doc))
        prompt = f"""Ты помогаешь улучшить поиск по корпоративной базе знаний.

Исходный вопрос пользователя:
{_clip_text(question, 800)}

Причина, почему нужно уточнить поиск:
{reason}

Уже использованные поисковые запросы (не повторяй их):
{json.dumps(previous_queries[:30], ensure_ascii=False)}

Самые релевантные найденные документы (ориентиры по терминам/разделам):
{chr(10).join([f"- {x}" for x in doc_hints]) or "- (пока нет релевантных документов)"}

Короткая история диалога (если есть):
{history_block or "Нет"}

Задача:
- предложи {limit} коротких поисковых запросов на русском, чтобы повысить шанс найти нужную статью;
- используй синонимы, сокращения, варианты терминов, названия модулей/ролей/форм из ориентиров;
- не добавляй пояснений.

Верни только JSON-массив строк."""
        raw = chat_completion(prompt, timeout=90) or ""
        return _parse_json_array_of_strings(raw)[:limit]

    def expand_retrieval_queries(
        self,
        user_query: str,
        conversation_history: Optional[List[Dict[str, str]]],
    ) -> Dict[str, Any]:
        """Переписывание, multi-query и HyDE — списки запросов для dense/BM25."""
        history_block = _format_conversation_history(
            conversation_history,
            max_messages=settings.RAG_QUERY_EXPANSION_MAX_MESSAGES,
            max_chars_per_message=400,
        )
        meta: Dict[str, Any] = {
            "rewritten": user_query.strip(),
            "hyde_snippet": None,
            "multi_variants": [],
            "dense_queries": [user_query.strip()],
            "sparse_queries": [user_query.strip()],
        }
        base = user_query.strip()
        if settings.CONVERSATIONAL_REWRITE_ENABLED and history_block:
            rewritten = self._llm_standalone_search_query(history_block, user_query)
            if rewritten and len(rewritten) > 3:
                meta["rewritten"] = rewritten
                base = rewritten
                meta["dense_queries"] = [rewritten]
                meta["sparse_queries"] = [rewritten]

        if settings.RAG_MULTI_QUERY_ENABLED:
            variants = self._llm_multi_query_variants(base, user_query.strip())
            meta["multi_variants"] = variants
            for v in variants:
                if v:
                    meta["dense_queries"].append(v)
                    meta["sparse_queries"].append(v)

        if settings.RAG_HYDE_ENABLED:
            hyde = self._llm_hyde_passage(base)
            meta["hyde_snippet"] = hyde
            if hyde:
                meta["dense_queries"].append(hyde)

        def _dedupe(seq: List[str]) -> List[str]:
            seen = set()
            out: List[str] = []
            for x in seq:
                x = (x or "").strip()
                if not x or x in seen:
                    continue
                seen.add(x)
                out.append(x)
            return out

        meta["dense_queries"] = _dedupe(meta["dense_queries"])
        meta["sparse_queries"] = _dedupe(meta["sparse_queries"])
        if not meta["dense_queries"]:
            meta["dense_queries"] = [user_query.strip()]
        if not meta["sparse_queries"]:
            meta["sparse_queries"] = [user_query.strip()]
        return meta

    def retrieve_documents_deep(
        self,
        user_query: str,
        top_k: Optional[int] = None,
        min_score: Optional[float] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> Tuple[List[Dict], Optional[str], Dict[str, Any], Dict[str, Any]]:
        """
        Deep retrieval: несколько итераций поиска с дозапросами, дедупом кандидатов и диагностикой.

        Returns:
            (документы, код_ошибки, expansion_meta, diagnostics)
        """
        deep_retrieval_logger.info("--- Deep retrieval: старт ---")
        deep_retrieval_logger.info("Deep retrieval: query='%s'", _clip_text(user_query, 400))
        top_k = top_k if top_k is not None else settings.RAG_TOP_K
        min_score = min_score if min_score is not None else settings.RAG_MIN_SCORE

        max_iters = max(1, int(getattr(settings, "DEEP_RETRIEVAL_MAX_ITERS", 3) or 3))
        new_per_iter = max(0, int(getattr(settings, "DEEP_RETRIEVAL_NEW_QUERIES_PER_ITER", 3) or 3))
        stop_best = float(getattr(settings, "DEEP_RETRIEVAL_MIN_BEST_SCORE", 0.55) or 0.55)
        max_candidates = max(1, int(getattr(settings, "DEEP_RETRIEVAL_MAX_CANDIDATES", 60) or 60))

        started = time.time()
        expansion = self.expand_retrieval_queries(user_query, conversation_history)
        embedding_cache: Dict[str, List[float]] = {}
        deep_retrieval_logger.debug(
            "Deep retrieval: params top_k=%s, min_score=%s, max_iters=%s, new_per_iter=%s, stop_best=%.3f, max_candidates=%s",
            top_k,
            min_score,
            max_iters,
            new_per_iter,
            float(stop_best),
            max_candidates,
        )
        deep_retrieval_logger.debug(
            "Deep retrieval: initial queries dense=%s, sparse=%s",
            (expansion.get("dense_queries") or [])[:20],
            (expansion.get("sparse_queries") or [])[:20],
        )

        deep_diag: Dict[str, Any] = {
            "enabled": True,
            "max_iters": max_iters,
            "new_queries_per_iter": new_per_iter,
            "stop_min_best_score": stop_best,
            "max_candidates": max_candidates,
            "iters": [],
        }

        # Пул кандидатов: chunk_id -> doc (+ происхождение)
        pool: Dict[str, Dict[str, Any]] = {}
        origins: Dict[str, List[str]] = {}

        seen_queries: List[str] = []
        for q in (expansion.get("dense_queries") or []) + (expansion.get("sparse_queries") or []):
            q = (q or "").strip()
            if q and q not in seen_queries:
                seen_queries.append(q)

        last_err: Optional[str] = None
        last_retrieve_diag: Dict[str, Any] = {}

        for iter_idx in range(max_iters):
            iter_started = time.time()
            documents, err, diag = self._retrieve_documents_inner(
                expansion,
                top_k=top_k,
                min_score=min_score,
                embedding_cache=embedding_cache,
            )
            last_err = err
            last_retrieve_diag = dict(diag or {})
            iter_best = _best_score(documents)
            deep_retrieval_logger.info(
                "Deep retrieval итерация %s/%s: документов=%s, best_score=%.3f, ошибка=%s",
                iter_idx + 1,
                max_iters,
                len(documents or []),
                float(iter_best),
                err,
            )

            # Мерджим кандидатов
            added = 0
            for doc in documents or []:
                cid = str(doc.get("chunk_id") or "")
                if not cid:
                    continue
                prev = pool.get(cid)
                if prev is None or float(doc.get("score") or 0.0) > float(prev.get("score") or 0.0):
                    pool[cid] = doc
                if cid not in origins:
                    origins[cid] = []
                # origin: первый dense query (или rewritten)
                origin_label = (expansion.get("rewritten") or user_query).strip()
                if origin_label and origin_label not in origins[cid]:
                    origins[cid].append(origin_label)
                added += 1

            # Ограничиваем пул кандидатов по текущим score
            if len(pool) > max_candidates:
                ordered_ids = sorted(pool.keys(), key=lambda x: float(pool[x].get("score") or 0.0), reverse=True)
                for drop_id in ordered_ids[max_candidates:]:
                    pool.pop(drop_id, None)
                    origins.pop(drop_id, None)

            iter_info: Dict[str, Any] = {
                "iter": iter_idx + 1,
                "latency_ms": int((time.time() - iter_started) * 1000),
                "error": err,
                "doc_count": len(documents or []),
                "best_score": round(float(iter_best), 4),
                "pool_size": len(pool),
                "added_candidates": added,
                "added_queries": [],
                "stop_reason": None,
            }

            # Ошибки, при которых нет смысла продолжать
            if err in {"embedding_unavailable", "search_error"}:
                iter_info["stop_reason"] = f"error:{err}"
                deep_diag["iters"].append(iter_info)
                deep_retrieval_logger.warning("Deep retrieval остановлен из-за ошибки: %s", err)
                break

            # Достаточно хороший результат — стоп
            if iter_best >= stop_best and documents:
                iter_info["stop_reason"] = "good_enough"
                deep_diag["iters"].append(iter_info)
                deep_retrieval_logger.info("Deep retrieval остановлен: good_enough (best_score=%.3f)", float(iter_best))
                break

            # Нет дозапросов или лимит итераций
            if iter_idx >= max_iters - 1 or new_per_iter <= 0:
                iter_info["stop_reason"] = "max_iters" if iter_idx >= max_iters - 1 else "no_budget_for_queries"
                deep_diag["iters"].append(iter_info)
                deep_retrieval_logger.info("Deep retrieval остановлен: %s", iter_info["stop_reason"])
                break

            # Сгенерировать новые запросы
            reason = "нет релевантных документов" if not documents else "низкая релевантность/покрытие"
            proposed = self._llm_deep_next_queries(
                user_query,
                conversation_history,
                previous_queries=seen_queries,
                top_documents=documents,
                reason=reason,
                limit=new_per_iter,
            )
            proposed = [q for q in proposed if q and q not in seen_queries]

            if not proposed:
                iter_info["stop_reason"] = "no_new_queries"
                deep_diag["iters"].append(iter_info)
                deep_retrieval_logger.info("Deep retrieval: новые запросы не предложены, останавливаемся")
                break

            # Добавляем запросы в expansion (и dense, и sparse) для следующей итерации.
            for q in proposed:
                seen_queries.append(q)
                (expansion.setdefault("dense_queries", [])).append(q)
                (expansion.setdefault("sparse_queries", [])).append(q)
            iter_info["added_queries"] = proposed
            deep_diag["iters"].append(iter_info)
            deep_retrieval_logger.info("Deep retrieval: добавлены дозапросы: %s", proposed)

        # Финальный список документов
        final_docs = sorted(pool.values(), key=lambda x: float(x.get("score") or 0.0), reverse=True)
        final_docs = [d for d in final_docs if float(d.get("score") or 0.0) >= float(min_score)]
        final_docs = final_docs[:top_k]

        deep_diag["latency_total_ms"] = int((time.time() - started) * 1000)
        deep_diag["final_count"] = len(final_docs)
        deep_diag["final_best_score"] = round(float(_best_score(final_docs)), 4)
        deep_diag["query_count"] = len(seen_queries)
        deep_retrieval_logger.info(
            "Deep retrieval завершён: iters=%s, final_docs=%s, best_score=%.3f, queries=%s, latency_ms=%s",
            len(deep_diag["iters"]),
            len(final_docs),
            float(deep_diag["final_best_score"]),
            len(seen_queries),
            deep_diag["latency_total_ms"],
        )

        # В diagnostics подмешаем последний diag retrieval, но deep положим отдельно.
        diagnostics = dict(last_retrieve_diag or {})
        diagnostics["deep"] = deep_diag

        # В expansion_meta добавим накопленные запросы (dedupe)
        def _dedupe(seq: List[str]) -> List[str]:
            seen = set()
            out: List[str] = []
            for x in seq:
                x = (x or "").strip()
                if not x or x in seen:
                    continue
                seen.add(x)
                out.append(x)
            return out

        expansion["dense_queries"] = _dedupe(expansion.get("dense_queries") or [])
        expansion["sparse_queries"] = _dedupe(expansion.get("sparse_queries") or [])
        return final_docs, last_err, expansion, diagnostics

    def retrieve_documents_auto(
        self,
        user_query: str,
        top_k: Optional[int] = None,
        min_score: Optional[float] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        deep_override: Optional[bool] = None,
    ) -> Tuple[List[Dict], Optional[str], Dict[str, Any], Dict[str, Any]]:
        """Выбрать обычный или deep retrieval (по настройке или override)."""
        enabled = (
            bool(deep_override)
            if deep_override is not None
            else bool(getattr(settings, "DEEP_RETRIEVAL_ENABLED", False))
        )
        if enabled:
            return self.retrieve_documents_deep(user_query, top_k, min_score, conversation_history)
        return self.retrieve_documents(user_query, top_k, min_score, conversation_history)

    def _retrieve_documents_inner(
        self,
        expansion: Dict[str, Any],
        top_k: int,
        min_score: float,
        embedding_cache: Optional[Dict[str, List[float]]] = None,
    ) -> Tuple[List[Dict], Optional[str], Dict[str, Any]]:
        mode = (settings.RETRIEVAL_MODE or "hybrid").lower()
        bm25_bundle = self._get_bm25_bundle() if mode in ("hybrid", "sparse") else None
        if mode in ("hybrid", "sparse") and bm25_bundle is None:
            rag_logger.debug("BM25-индекс не найден — используем только векторный поиск")
        try:
            documents, err, diag = hybrid_retrieve(
                self.collection,
                expansion.get("dense_queries") or [expansion.get("rewritten", "")],
                expansion.get("sparse_queries") or [expansion.get("rewritten", "")],
                get_embedding,
                top_k,
                min_score,
                self._reload_collection,
                bm25_bundle=bm25_bundle,
                embedding_cache=embedding_cache,
            )
        except Exception as e:
            rag_logger.error("Ошибка гибридного поиска: %s", e, exc_info=True)
            return [], "search_error", {"error": str(e)}
        slim = {
            "retrieval_mode": diag.get("retrieval_mode"),
            "stage": diag.get("stage"),
            "rewritten": expansion.get("rewritten"),
            "hyde_used": bool(expansion.get("hyde_snippet")),
            "multi_variants": expansion.get("multi_variants") or [],
            "dense_queries": expansion.get("dense_queries") or [],
        }
        diag["expansion"] = slim
        return documents, err, diag

    def retrieve_documents(
        self,
        user_query: str,
        top_k: Optional[int] = None,
        min_score: Optional[float] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> Tuple[List[Dict], Optional[str], Dict[str, Any], Dict[str, Any]]:
        """
        Поиск релевантных документов (гибридный RRF + опциональный rerank).

        Returns:
            (документы, код_ошибки, expansion_meta, diagnostics)
        """
        rag_logger.info("--- Поиск документов ---")
        rag_logger.debug("Исходный вопрос: '%s'", user_query)

        top_k = top_k if top_k is not None else settings.RAG_TOP_K
        min_score = min_score if min_score is not None else settings.RAG_MIN_SCORE
        rag_logger.debug("Параметры: top_k=%s, min_score=%s", top_k, min_score)

        start_time = time.time()
        expansion = self.expand_retrieval_queries(user_query, conversation_history)
        rag_logger.debug("Переписанный/расширенный поиск: dense=%s", expansion.get("dense_queries"))

        documents, err, diag = self._retrieve_documents_inner(expansion, top_k, min_score)
        diag = dict(diag or {})
        diag["latency_retrieve_ms"] = int((time.time() - start_time) * 1000)
        rag_logger.info(
            "Поиск завершён за %.3f с, документов: %s, код ошибки: %s",
            time.time() - start_time,
            len(documents),
            err,
        )
        return documents, err, expansion, diag
    
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
            "employee_instruction": (
                "Оформи ответ как рабочую инструкцию для сотрудника: цель, когда применять, "
                "что понадобится, пошаговые действия, частые ошибки, проверка результата и источники."
            ),
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
1. Всегда отвечай на русском языке. Если вопрос или часть контекста на другом языке — переведи и изложи ответ по-русски (термины/названия/цитаты сохраняй как в источнике при необходимости).
2. Ответь на вопрос, используя информацию из контекста.
3. Если в контексте нет информации для ответа, честно скажи об этом.
4. Ссылайся на источники в ответе, используя формат [Источник: название].
5. Не выдумывай информацию, которой нет в контексте.
6. Форматируй ответ с использованием Markdown для лучшей читаемости.
7. Режим ответа: {extra_instruction}
8. Используй историю диалога только для понимания уточнений и местоимений; факты бери из контекста источников.
9. Если история диалога противоречит найденному контексту, опирайся на контекст источников.
10. Если пользователь просит изобразить что-то графически (например: "схема", "диаграмма", "граф", "визуализируй", "изобрази графически"), вместо отказа дай результат в формате Mermaid внутри блока Markdown ```mermaid ... ```. Выбирай подходящий тип диаграммы Mermaid (flowchart/graph, sequenceDiagram, classDiagram) и следи за корректным синтаксисом.
11. Не выводи ход рассуждений, черновики и внутренний анализ. Сразу начинай с финального ответа пользователю на русском.

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

    def _autofix_mermaid_blocks(self, answer: str) -> str:
        """
        Попытаться исключить ошибки Mermaid, перепроверив и (при необходимости) исправив
        Mermaid-код внутри ```mermaid ... ``` блоков.

        Это выполняется отдельным LLM-вызовом только для блоков диаграммы (не для всего ответа),
        чтобы минимально влиять на стиль/текст ответа.
        """
        enabled = getattr(settings, "MERMAID_AUTOFIX_ENABLED", True)
        if not enabled:
            return answer
        log_enabled = getattr(settings, "MERMAID_AUTOFIX_LOG_ENABLED", False)

        text = (answer or "")
        if "```mermaid" not in text:
            return answer

        pattern = re.compile(r"```mermaid\s*([\s\S]*?)\s*```", flags=re.IGNORECASE)
        blocks = list(pattern.finditer(text))
        if not blocks:
            return answer

        fixed = text
        replaced = 0
        for m in reversed(blocks):
            raw = (m.group(1) or "").strip()
            if not raw:
                continue
            raw_norm = _normalize_mermaid_code(raw)
            if log_enabled and raw_norm != raw:
                rag_logger.debug(
                    "Mermaid autofix: нормализация (до LLM)\n--- raw ---\n%s\n--- norm ---\n%s",
                    _clip_text_keep_newlines(raw, 1200),
                    _clip_text_keep_newlines(raw_norm, 1200),
                )
            raw = raw_norm
            # В Mermaid переносы строк критичны для синтаксиса; не схлопываем whitespace.
            raw_clip = _clip_text_keep_newlines(raw, 6000)
            fix_prompt = f"""Ты валидируешь и исправляешь синтаксис Mermaid (совместимость Mermaid 10.x).

Вход: Mermaid-код диаграммы.
Задача:
- исправь ошибки синтаксиса (некорректные идентификаторы, кавычки, скобки, стрелки, лишние символы);
- сохрани смысл и структуру диаграммы;
- НЕ добавляй объяснений и НЕ оборачивай в Markdown;
- верни ТОЛЬКО исправленный Mermaid-код (без ```).

MERMAID:
{raw_clip}
"""
            try:
                candidate = (chat_completion(fix_prompt, timeout=60) or "").strip()
            except Exception:
                candidate = ""

            if not candidate:
                continue

            # Иногда модель возвращает код в ```; аккуратно извлечём содержимое.
            fence_match = re.search(r"```(?:mermaid)?\s*([\s\S]*?)\s*```", candidate, flags=re.IGNORECASE)
            if fence_match:
                candidate = (fence_match.group(1) or "").strip()
            candidate_norm = _normalize_mermaid_code(candidate)
            if log_enabled and candidate_norm != candidate:
                rag_logger.debug(
                    "Mermaid autofix: нормализация (после LLM)\n--- candidate ---\n%s\n--- norm ---\n%s",
                    _clip_text_keep_newlines(candidate, 1200),
                    _clip_text_keep_newlines(candidate_norm, 1200),
                )
            candidate = candidate_norm

            # Минимальная sanity-проверка: должен начинаться с известного типа диаграммы.
            if not looks_like_mermaid(candidate):
                if log_enabled:
                    rag_logger.debug(
                        "Mermaid autofix: пропуск, не похоже на Mermaid (first line=%r)",
                        (candidate.splitlines() or [""])[0][:180],
                    )
                continue

            fixed = fixed[: m.start(1)] + candidate + fixed[m.end(1) :]
            replaced += 1

        if replaced:
            rag_logger.info("Mermaid autofix: исправлено блоков=%s", replaced)
        elif log_enabled:
            rag_logger.debug("Mermaid autofix: блоки найдены=%s, замен не выполнено", len(blocks))
        return fixed

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

        exchange_id = uuid.uuid4().hex
        exchange_started = time.time()
        
        # Используем значения из настроек по умолчанию
        top_k = top_k if top_k is not None else settings.RAG_TOP_K
        min_score = min_score if min_score is not None else settings.RAG_MIN_SCORE
        max_citations = max_citations if max_citations is not None else settings.RAG_MAX_CITATIONS
        
        rag_logger.debug(f"Параметры: top_k={top_k}, min_score={min_score}, include_citations={include_citations}, max_citations={max_citations}")
        
        start_time = time.time()
        
        # 1. Поиск релевантных документов
        rag_logger.debug("Шаг 1: Поиск релевантных документов")
        documents, retrieve_error, expansion, retrieve_diag = self.retrieve_documents_auto(
            query, top_k, min_score, conversation_history
        )
        retrieval_query = expansion.get("rewritten") or query

        _safe_json_log(
            {
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "exchange_id": exchange_id,
                "stage": "retrieve",
                "question": _clip_for_llm_log(query, 4000),
                "retrieval_query": _clip_for_llm_log(retrieval_query, 4000),
                "answer_mode": str(answer_mode or "default"),
                "top_k": int(top_k),
                "min_score": float(min_score),
                "conversation_messages": len(conversation_history or []),
                "retrieve_error": retrieve_error,
                "document_count": len(documents or []),
                "top_docs": [
                    {
                        "label": _slim_doc_label(d),
                        "chunk_id": str(d.get("chunk_id", ""))[:120],
                        "score": float(d.get("score") or 0.0),
                        "source": _source_from_metadata((d or {}).get("metadata")),
                    }
                    for d in (documents or [])[: min(10, int(top_k or 5))]
                ],
                "expansion": {
                    "rewritten": _clip_for_llm_log(expansion.get("rewritten") or "", 2000),
                    "hyde_used": bool(expansion.get("hyde_snippet")),
                    "multi_variants": (expansion.get("multi_variants") or [])[:6],
                    "dense_queries": (expansion.get("dense_queries") or [])[:10],
                    "sparse_queries": (expansion.get("sparse_queries") or [])[:10],
                },
                "retrieve_diag": retrieve_diag or {},
            }
        )
        
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
                diagnostics={
                    "retrieval_status": "embedding_unavailable",
                    "latency_ms": int(elapsed * 1000),
                    "retrieval": retrieve_diag,
                    "expansion": expansion,
                },
            )
        
        if retrieve_error == "search_error":
            elapsed = time.time() - start_time
            rag_logger.warning(f"RAG запрос за {elapsed:.3f} сек: ошибка поиска в Chroma")
            return RAGResult(
                answer="Ошибка при поиске по векторной базе. Проверьте логи и целостность Chroma.",
                citations=[],
                sources=[],
                retrieve_error="search_error",
                diagnostics={
                    "retrieval_status": "search_error",
                    "latency_ms": int(elapsed * 1000),
                    "retrieval": retrieve_diag,
                    "expansion": expansion,
                },
            )
        
        if not documents:
            elapsed = time.time() - start_time
            rag_logger.warning(f"RAG запрос завершен за {elapsed:.3f} сек. Не найдено релевантных документов")
            return RAGResult(
                answer="К сожалению, я не нашёл релевантной информации для ответа на ваш вопрос.",
                citations=[],
                sources=[],
                diagnostics={
                    "retrieval_status": "no_documents",
                    "latency_ms": int(elapsed * 1000),
                    "retrieval": retrieve_diag,
                    "expansion": expansion,
                },
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

        _safe_json_log(
            {
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "exchange_id": exchange_id,
                "stage": "prompt",
                "prompt_chars": len(prompt or ""),
                "prompt": _clip_for_llm_log(prompt),
            }
        )
        
        # 3. Генерация ответа через Ollama
        rag_logger.debug("Шаг 3: Генерация ответа через Ollama")
        gen_started = time.time()
        answer = self._generate_answer(prompt)
        gen_ms = int((time.time() - gen_started) * 1000)
        answer = self._autofix_mermaid_blocks(answer)

        _safe_json_log(
            {
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "exchange_id": exchange_id,
                "stage": "answer",
                "chat_api_mode": str(getattr(settings, "CHAT_API_MODE", "") or ""),
                "model": str(getattr(settings, "OLLAMA_CHAT_MODEL", "") or ""),
                "latency_llm_ms": gen_ms,
                "answer_chars": len(answer or ""),
                "answer": _clip_for_llm_log(answer),
            }
        )
        
        # 4. Обогащение ответа цитатами
        rag_logger.debug("Шаг 4: Обогащение ответа цитатами")
        rag_result = self.enrich_answer_with_citations(answer, documents, max_citations)

        _safe_json_log(
            {
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "exchange_id": exchange_id,
                "stage": "final",
                "citations_count": len(rag_result.citations or []),
                "sources_count": len(rag_result.sources or []),
                "latency_total_ms": int((time.time() - exchange_started) * 1000),
            }
        )
        
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
            "retrieval": retrieve_diag,
            "expansion": {
                "rewritten": expansion.get("rewritten"),
                "dense_queries": expansion.get("dense_queries"),
                "hyde_used": bool(expansion.get("hyde_snippet")),
                "multi_variants": expansion.get("multi_variants"),
            },
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

        exchange_id = uuid.uuid4().hex
        exchange_started = time.time()
        _safe_json_log(
            {
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "exchange_id": exchange_id,
                "stage": "retrieve",
                "stream": True,
                "question": _clip_for_llm_log(query, 4000),
                "retrieval_query": _clip_for_llm_log((retrieval_query or query), 4000),
                "answer_mode": str(answer_mode or "default"),
                "conversation_messages": len(conversation_history or []),
                "document_count": len(documents or []),
                "top_docs": [
                    {
                        "label": _slim_doc_label(d),
                        "chunk_id": str(d.get("chunk_id", ""))[:120],
                        "score": float(d.get("score") or 0.0),
                        "source": _source_from_metadata((d or {}).get("metadata")),
                    }
                    for d in (documents or [])[: min(10, int(settings.RAG_TOP_K or 5))]
                ],
            }
        )

        prompt = self.generate_rag_prompt(
            query,
            documents,
            answer_mode=answer_mode,
            conversation_history=conversation_history,
            retrieval_query=retrieval_query,
        )

        _safe_json_log(
            {
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "exchange_id": exchange_id,
                "stage": "prompt",
                "stream": True,
                "prompt_chars": len(prompt or ""),
                "prompt": _clip_for_llm_log(prompt),
            }
        )

        parts: List[str] = []
        raw_chunks: List[str] = []
        gen_started = time.time()

        def _live_llm_chunks() -> Iterator[str]:
            for fragment in chat_completion_stream(prompt, timeout=120):
                raw_chunks.append(fragment)
                yield fragment

        for fragment in _filter_reasoning_stream(_live_llm_chunks()):
            parts.append(fragment)
            if fragment:
                yield {"type": "delta", "text": fragment}

        raw_answer = "".join(raw_chunks)
        answer = "".join(parts)
        gen_ms = int((time.time() - gen_started) * 1000)
        disable_thinking = bool(getattr(settings, "CHAT_DISABLE_THINKING", True))
        if disable_thinking:
            answer = strip_model_reasoning(answer)
        answer = self._autofix_mermaid_blocks(answer)

        _safe_json_log(
            {
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "exchange_id": exchange_id,
                "stage": "answer",
                "stream": True,
                "chat_api_mode": str(getattr(settings, "CHAT_API_MODE", "") or ""),
                "model": str(getattr(settings, "OLLAMA_CHAT_MODEL", "") or ""),
                "chat_disable_thinking": disable_thinking,
                "latency_llm_ms": gen_ms,
                "answer_raw_chars": len(raw_answer or ""),
                "cot_in_raw": "The user is asking" in (raw_answer or ""),
                "answer_chars": len(answer or ""),
                "answer": _clip_for_llm_log(answer),
            }
        )

        rag_result = self.enrich_answer_with_citations(answer, documents, max_citations)
        rag_result.diagnostics = {
            "retrieval_status": "ok",
            "document_count": len(documents),
            "score_distribution": [round(float(d.get("score", 0)), 4) for d in documents],
            "answer_mode": answer_mode,
            "conversation_messages": len(conversation_history or []),
        }

        _safe_json_log(
            {
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "exchange_id": exchange_id,
                "stage": "final",
                "stream": True,
                "citations_count": len(rag_result.citations or []),
                "sources_count": len(rag_result.sources or []),
                "latency_total_ms": int((time.time() - exchange_started) * 1000),
            }
        )

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
            section_path = meta.get('section_path') or ''
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
                'section_path': section_path,
                'chunk_kind': meta.get('chunk_kind', ''),
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


def looks_like_mermaid(code_text: str) -> bool:
    """Грубая проверка: похоже ли содержимое на Mermaid-диаграмму."""
    text = str(code_text or "").strip()
    if not text:
        return False
    return (
        text.startswith("graph ")
        or text.startswith("flowchart ")
        or text.startswith("sequenceDiagram")
        or text.startswith("classDiagram")
        or text.startswith("stateDiagram")
        or text.startswith("erDiagram")
        or text.startswith("journey")
        or text.startswith("gantt")
        or text.startswith("mindmap")
        or text.startswith("timeline")
        or text.startswith("quadrantChart")
        or text.startswith("sankey-beta")
    )
