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
    
    # Получаем эмбеддинг из Ollama
    try:
        response = requests.post(
            f"{settings.OLLAMA_URL}/api/embed",
            json={
                "model": settings.OLLAMA_EMBEDDING_MODEL,
                "input": text,
                "dimensions": 1024
            },
            timeout=60
        )
        response.raise_for_status()
        result = response.json()
        # API v2 возвращает embeddings (массив) или embedding (один)
        if "embeddings" in result:
            embedding = result["embeddings"][0]
        elif "embedding" in result:
            embedding = result["embedding"]
        else:
            return []
        
        # Кэшируем эмбеддинг
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
        try:
            response = requests.post(
                f"{settings.OLLAMA_URL}/api/embed",
                json={
                    "model": settings.OLLAMA_EMBEDDING_MODEL,
                    "input": texts_to_fetch,  # Массив текстов для пакетной обработки
                    "dimensions": 1024
                },
                timeout=120
            )
            response.raise_for_status()
            result = response.json()
            fetched_embeddings = result.get("embeddings", [])
            
            # Кэшируем и вставляем полученные эмбеддинги
            for i, embedding in enumerate(fetched_embeddings):
                text = texts_to_fetch[i]
                index = indices_to_fetch[i]
                embeddings[index] = embedding
                if USE_CACHE:
                    cache_embedding(text, settings.OLLAMA_EMBEDDING_MODEL, embedding)
                    logger.debug(f"Эмбеддинг {index} закэширован")
                    
        except Exception as e:
            logger.error(f"Ошибка при пакетном получении эмбеддингов: {e}")
            # Возвращаем только кэшированные эмбеддинги
            return [emb for emb in embeddings if emb is not None]
    
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
            documents.append({
                "text": doc,
                "metadata": results['metadatas'][0][i] if results['metadatas'] else {},
                "distance": results['distances'][0][i] if results['distances'] else 0
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

    try:
        response = requests.post(
            f"{settings.OLLAMA_URL}/api/generate",
            json={
                "model": settings.OLLAMA_CHAT_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.3,
                    "top_p": 0.9,
                    "num_predict": 500
                }
            },
            timeout=120
        )
        
        response.raise_for_status()
        result = response.json()
        return result.get("response", "").strip()
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP ошибка при генерации ответа: {e.response.status_code if hasattr(e, 'response') and e.response else 'Unknown'}")
        return f"Произошла ошибка при генерации ответа: HTTP {e.response.status_code if hasattr(e, 'response') and e.response else 'Unknown'}"
    except requests.exceptions.Timeout:
        logger.error("Таймаут при генерации ответа")
        return "Произошла ошибка при генерации ответа: Превышено время ожидания"
    except requests.exceptions.ConnectionError:
        logger.error("Ошибка подключения к Ollama")
        return "Произошла ошибка при генерации ответа: Не удалось подключиться к Ollama"
    except Exception as e:
        logger.error(f"Ошибка при генерации ответа: {str(e)}")
        return f"Произошла ошибка при генерации ответа: {str(e)}"


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
        
        try:
            response = requests.post(
                f"{settings.OLLAMA_URL}/api/embed",
                json={
                    "model": settings.OLLAMA_EMBEDDING_MODEL,
                    "input": input,
                    "dimensions": 1024
                },
                timeout=120
            )
            response.raise_for_status()
            result = response.json()
            embeddings = result.get("embeddings", [])
            return embeddings
        except Exception as e:
            logger.error(f"Ошибка при генерации эмбеддингов через Ollama: {e}")
            return []


# Переэкспорт функции инвалидации кэша для удобства импорта
if USE_CACHE:
    from utils.cache import invalidate_embedding_cache
