#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Общие функции для работы с эмбеддингами

Этот модуль содержит функции для получения эмбеддингов, поиска документов
и генерации ответов, которые используются в разных частях проекта.
"""

import requests
from typing import List, Dict, Optional
from config import settings, get_logger

# Импорт кэширования (опционально)
try:
    from utils.cache import get_cached_embedding, cache_embedding, invalidate_embedding_cache
    USE_CACHE = True
except ImportError:
    USE_CACHE = False

# Импорт ChromaDB для кастомной функции эмбеддингов
try:
    import chromadb
    from chromadb import Documents, EmbeddingFunction, Embeddings
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False

logger = get_logger(__name__)


def _embedding_headers() -> dict:
    h = {"Content-Type": "application/json"}
    if getattr(settings, "OPENAI_API_KEY", ""):
        h["Authorization"] = f"Bearer {settings.OPENAI_API_KEY}"
    return h


def _parse_ollama_embedding_response(result: dict) -> List[List[float]]:
    if "embeddings" in result:
        return result["embeddings"]
    if "embedding" in result:
        return [result["embedding"]]
    return []


def _parse_openai_embedding_response(result: dict) -> List[List[float]]:
    data = result.get("data") or []
    ordered = sorted(data, key=lambda x: x.get("index", 0))
    out = []
    for item in ordered:
        emb = item.get("embedding")
        if emb:
            out.append(emb)
    return out


def _fetch_embeddings_from_api(texts: List[str]) -> List[List[float]]:
    """
    Запрос эмбеддингов к Ollama (/api/embed) или OpenAI-совместимому (/v1/embeddings).
    """
    if not texts:
        return []

    base = settings.OLLAMA_URL.rstrip("/")
    mode = getattr(settings, "EMBEDDING_API_MODE", "ollama") or "ollama"

    if mode == "openai":
        url = f"{base}/v1/embeddings"
        payload = {
            "model": settings.OLLAMA_EMBEDDING_MODEL,
            "input": texts if len(texts) > 1 else texts[0],
        }
        try:
            response = requests.post(
                url, json=payload, timeout=120, headers=_embedding_headers()
            )
            response.raise_for_status()
            return _parse_openai_embedding_response(response.json())
        except requests.exceptions.HTTPError as e:
            body = e.response.text[:800] if e.response is not None else ""
            logger.error(
                "Ошибка HTTP при эмбеддинге (openai %s): %s %s",
                url,
                e.response.status_code if e.response else "?",
                body,
            )
            return []
        except requests.exceptions.RequestException as e:
            logger.error("Ошибка запроса эмбеддинга (openai %s): %s", url, e)
            return []

    # Ollama
    url = f"{base}/api/embed"
    for use_dimensions in (True, False):
        payload = {"model": settings.OLLAMA_EMBEDDING_MODEL, "input": texts}
        if use_dimensions:
            payload["dimensions"] = 1024
        try:
            response = requests.post(
                url, json=payload, timeout=120, headers=_embedding_headers()
            )
            response.raise_for_status()
            parsed = _parse_ollama_embedding_response(response.json())
            if parsed:
                return parsed
        except requests.exceptions.HTTPError as e:
            if (
                use_dimensions
                and e.response is not None
                and e.response.status_code == 400
            ):
                logger.warning(
                    "Ollama /api/embed с dimensions=1024 отклонён (400), повтор без dimensions"
                )
                continue
            body = e.response.text[:800] if e.response is not None else ""
            logger.error(
                "Ошибка HTTP при эмбеддинге (ollama %s): %s %s",
                url,
                e.response.status_code if e.response else "?",
                body,
            )
            return []
        except requests.exceptions.RequestException as e:
            logger.error("Ошибка запроса эмбеддинга (ollama %s): %s", url, e)
            return []

    return []


def chat_completion(prompt: str, timeout: int = 120) -> str:
    """
    Генерация ответа по одному текстовому промпту.

    - CHAT_API_MODE=ollama: POST /api/generate
    - CHAT_API_MODE=openai: POST /v1/chat/completions (LM Studio и др.)
    """
    base = settings.OLLAMA_URL.rstrip("/")
    mode = getattr(settings, "CHAT_API_MODE", "ollama") or "ollama"

    if mode == "openai":
        try:
            response = requests.post(
                f"{base}/v1/chat/completions",
                json={
                    "model": settings.OLLAMA_CHAT_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "top_p": 0.9,
                    "max_tokens": 500,
                    "stream": False,
                },
                timeout=timeout,
                headers=_embedding_headers(),
            )
            response.raise_for_status()
            result = response.json()
            choices = result.get("choices") or []
            if not choices:
                logger.warning("chat/completions: пустой choices в ответе")
                return ""
            msg = choices[0].get("message") or {}
            return (msg.get("content") or "").strip()
        except requests.exceptions.HTTPError as e:
            body = e.response.text[:800] if e.response is not None else ""
            code = e.response.status_code if e.response else "?"
            logger.error("HTTP ошибка chat/completions: %s %s", code, body)
            return f"Произошла ошибка при генерации ответа: HTTP {code}"
        except requests.exceptions.Timeout:
            logger.error("Таймаут при генерации ответа (chat/completions)")
            return "Произошла ошибка при генерации ответа: Превышено время ожидания"
        except requests.exceptions.ConnectionError:
            logger.error("Ошибка подключения к серверу LLM (chat/completions)")
            return "Произошла ошибка при генерации ответа: Не удалось подключиться к серверу LLM"
        except Exception as e:
            logger.error("Ошибка при генерации ответа: %s", e)
            return f"Произошла ошибка при генерации ответа: {str(e)}"

    try:
        response = requests.post(
            f"{base}/api/generate",
            json={
                "model": settings.OLLAMA_CHAT_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.3,
                    "top_p": 0.9,
                    "num_predict": 500,
                },
            },
            timeout=timeout,
        )
        response.raise_for_status()
        result = response.json()
        return (result.get("response") or "").strip()
    except requests.exceptions.HTTPError as e:
        logger.error(
            "HTTP ошибка при генерации ответа: %s",
            e.response.status_code if hasattr(e, "response") and e.response else "Unknown",
        )
        return f"Произошла ошибка при генерации ответа: HTTP {e.response.status_code if hasattr(e, 'response') and e.response else 'Unknown'}"
    except requests.exceptions.Timeout:
        logger.error("Таймаут при генерации ответа")
        return "Произошла ошибка при генерации ответа: Превышено время ожидания"
    except requests.exceptions.ConnectionError:
        logger.error("Ошибка подключения к Ollama")
        return "Произошла ошибка при генерации ответа: Не удалось подключиться к Ollama"
    except Exception as e:
        logger.error("Ошибка при генерации ответа: %s", e)
        return f"Произошла ошибка при генерации ответа: {str(e)}"


def get_embedding(text: str) -> List[float]:
    """
    Получить эмбеддинг текста через ollama (API v2)
    
    Args:
        text: Текст для получения эмбеддинга
        
    Returns:
        Список чисел (эмбеддинг) или пустой список при ошибке
    """
    # Проверяем кэш
    if USE_CACHE:
        cached = get_cached_embedding(text, settings.OLLAMA_EMBEDDING_MODEL)
        if cached is not None:
            logger.debug(f"Эмбеддинг получен из кэша для текста: {text[:50]}...")
            return cached
    
    try:
        vectors = _fetch_embeddings_from_api([text])
        if not vectors or not vectors[0]:
            return []
        embedding = vectors[0]

        if USE_CACHE:
            cache_embedding(text, settings.OLLAMA_EMBEDDING_MODEL, embedding)
            logger.debug(f"Эмбеддинг закэширован для текста: {text[:50]}...")

        return embedding
    except Exception as e:
        logger.error(f"Ошибка при получении эмбеддинга: {e}")
        return []


def get_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """
    Получить эмбеддинги для нескольких текстов за один запрос (GPU-оптимизировано)
    
    Args:
        texts: Список текстов для получения эмбеддингов
        
    Returns:
        Список эмбеддингов
    """
    if not texts:
        return []
    
    # Проверяем кэш для каждого текста
    embeddings = []
    texts_to_fetch = []
    indices_to_fetch = []
    
    if USE_CACHE:
        for i, text in enumerate(texts):
            cached = get_cached_embedding(text, settings.OLLAMA_EMBEDDING_MODEL)
            if cached is not None:
                embeddings.append(cached)
                logger.debug(f"Эмбеддинг {i} получен из кэша")
            else:
                embeddings.append(None)
                texts_to_fetch.append(text)
                indices_to_fetch.append(i)
    else:
        embeddings = [None] * len(texts)
        texts_to_fetch = texts
        indices_to_fetch = list(range(len(texts)))
    
    # Получаем эмбеддинги для текстов, которых нет в кэше
    if texts_to_fetch:
        fetched_embeddings = _fetch_embeddings_from_api(texts_to_fetch)
        if not fetched_embeddings or len(fetched_embeddings) != len(texts_to_fetch):
            logger.error(
                "Пакет эмбеддингов: ожидалось %s векторов, получено %s",
                len(texts_to_fetch),
                len(fetched_embeddings) if fetched_embeddings else 0,
            )
            return [emb for emb in embeddings if emb is not None]

        for i, embedding in enumerate(fetched_embeddings):
            text = texts_to_fetch[i]
            index = indices_to_fetch[i]
            embeddings[index] = embedding
            if USE_CACHE:
                cache_embedding(text, settings.OLLAMA_EMBEDDING_MODEL, embedding)
                logger.debug(f"Эмбеддинг {index} закэширован")
    
    return embeddings


def search_documents(query: str, collection, top_k: int = None) -> List[Dict]:
    """
    Поиск релевантных документов в векторной базе
    
    Args:
        query: Поисковый запрос
        collection: Коллекция ChromaDB
        top_k: Количество результатов для возврата
        
    Returns:
        Список найденных документов с метаданными
    """
    if top_k is None:
        top_k = settings.TOP_K_RESULTS
    
    logger.info(f"Поиск релевантных документов для запроса: '{query}'")
    
    # Получаем эмбеддинг запроса
    query_embedding = get_embedding(query)
    
    if not query_embedding:
        logger.warning("Не удалось получить эмбеддинг запроса")
        return []
    
    # Ищем релевантные документы
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k
    )
    
    documents = []
    if results['documents'] and results['documents'][0]:
        for i, doc in enumerate(results['documents'][0]):
            score = results['distances'][0][i] if results['distances'] else 0.0
            # Преобразуем косинусное расстояние в оценку релевантности
            # Для косинусного расстояния: 0 = идентичные векторы, 1 = противоположные
            # Ограничиваем диапазон [0, 1]
            relevance_score = max(0.0, min(1.0, 1.0 - score))
            
            documents.append({
                "text": doc,
                "score": relevance_score,
                "metadata": results['metadatas'][0][i] if results['metadatas'] else {},
                "distance": score
            })
    
    logger.info(f"Найдено {len(documents)} релевантных документов")
    return documents


def generate_answer(query: str, context_docs: List[Dict]) -> str:
    """
    Генерация ответа с использованием ollama
    
    Args:
        query: Пользовательский запрос
        context_docs: Список документов контекста
        
    Returns:
        Сгенерированный ответ
    """
    # Формируем контекст из найденных документов
    context = "\n\n".join([
        f"--- Документ {i+1} (источник: {doc['metadata'].get('title', 'Без названия')}) ---\n{doc['text']}"
        for i, doc in enumerate(context_docs)
    ])

    prompt = f"""Роль: Ты — аналитик корпоративной базы знаний. Ты отвечаешь подробно, структурированно и по делу, опираясь исключительно на факты из загруженных документов.

Правила работы:

Анализ контекста: Проанализируй предоставленные фрагменты документов. Они могут содержать ответ не целиком, а по частям. Собери эти части воедино.
Язык ответа: Отвечай на том же языке, на котором задан вопрос.
Обработка отсутствия данных:
Если в контексте нет ответа, прямо скажи об этом. Не предлагай помощь в других вопросах и не додумывай.
Если в контексте есть информация, частично касающаяся вопроса, ответь только на ту часть, по которой есть данные, и укажи, что остальная информация отсутствует.
Формат: Старайся структурировать ответ (списки, абзацы), если это помогает пониманию.
Контекст:
{context}

Запрос: {query}

Твой структурированный ответ на основе документов:"""

    return chat_completion(prompt, timeout=120)


class OllamaEmbeddingFunction:
    """
    Кастомная функция эмбеддингов для ChromaDB, использующая Ollama API
    
    Эта функция позволяет ChromaDB использовать Ollama для генерации
    эмбеддингов с правильной размерностью (1024 для bge-m3)
    """
    
    def __init__(self):
        """Инициализация функции эмбеддингов"""
        self.name = "ollama_embedding"
    
    def __call__(self, input: list) -> list:
        """
        Генерация эмбеддингов для списка текстов
        
        Args:
            input: Список текстов для эмбеддинга
            
        Returns:
            Список эмбеддингов
        """
        if not input:
            return []
        
        return _fetch_embeddings_from_api(list(input))


# Переэкспорт функции инвалидации кэша для удобства импорта
if USE_CACHE:
    from utils.cache import invalidate_embedding_cache
