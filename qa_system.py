#!/usr/bin/env python3
"""
Скрипт для вопрос-ответной системы на основе векторной базы данных
Использует ollama для генерации ответов и ChromaDB для поиска релевантных документов.
"""

import chromadb
from chromadb.config import Settings
import requests
from typing import List, Dict
import sys

# Импорт конфигурации и логирования
from config import settings, get_logger

# Импорт кэширования
from utils import get_cached_embedding, cache_embedding

# Получаем логгер для этого модуля
logger = get_logger(__name__)


def get_embedding(text: str) -> List[float]:
    """Получить эмбеддинг текста через ollama (API v2) с кэшированием"""
    # Проверяем кэш
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
                "input": text
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
        cache_embedding(text, settings.OLLAMA_EMBEDDING_MODEL, embedding)
        logger.debug(f"Эмбеддинг закэширован для текста: {text[:50]}...")
        
        return embedding
    except Exception as e:
        logger.error(f"Ошибка при получении эмбеддинга: {e}")
        return []


def search_documents(query: str, collection, top_k: int = None) -> List[Dict]:
    """Поиск релевантных документов в векторной базе"""
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
    """Генерация ответа с использованием ollama"""
    # Формируем контекст из найденных документов
    context = "\n\n".join([
        f"--- Документ {i+1} (источник: {doc['metadata'].get('title', 'Без названия')}) ---\n{doc['text']}"
        for i, doc in enumerate(context_docs)
    ])

#5. Будь кратким и по существу    

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


def interactive_mode(collection):
    """Интерактивный режим вопрос-ответ"""
    logger.info("\n" + "=" * 60)
    logger.info("Режим вопрос-ответ (введите 'exit' для выхода)")
    logger.info("=" * 60 + "\n")
    
    while True:
        try:
            query = input("Ваш вопрос: ").strip()
            
            if query.lower() in ['exit', 'quit', 'выход', 'q']:
                logger.info("До свидания!")
                break
            
            if not query:
                continue
            
            # Ищем релевантные документы
            docs = search_documents(query, collection)
            
            if not docs:
                logger.warning("\nНе найдено релевантных документов в базе знаний.\n")
                continue
            
            # Генерируем ответ
            logger.info("\nГенерация ответа...")
            answer = generate_answer(query, docs)
            
            print("\n" + "-" * 60)
            print("ОТВЕТ:")
            print("-" * 60)
            print(answer)
            print("-" * 60 + "\n")
            
        except KeyboardInterrupt:
            logger.info("\n\nДо свидания!")
            break
        except Exception as e:
            logger.error(f"\nОшибка: {e}\n")


def single_query_mode(collection, query: str):
    """Режим одиночного запроса"""
    # Ищем релевантные документы
    docs = search_documents(query, collection)
    
    if not docs:
        logger.warning("\nНе найдено релевантных документов в базе знаний.")
        return
    
    # Выводим найденные документы
    logger.info("\n" + "=" * 60)
    logger.info("РЕЛЕВАНТНЫЕ ДОКУМЕНТЫ:")
    logger.info("=" * 60)
    for i, doc in enumerate(docs, 1):
        print(f"\n--- Документ {i} ---")
        print(f"Источник: {doc['metadata'].get('title', 'Без названия')}")
        print(f"Путь: {doc['metadata'].get('path', 'N/A')}")
        print(f"Релевантность: {1 - doc['distance']:.2f}")
        print(f"Текст: {doc['text'][:300]}...")
    
    # Генерируем ответ
    logger.info("\n" + "=" * 60)
    logger.info("Генерация ответа...")
    logger.info("=" * 60)
    answer = generate_answer(query, docs)
    
    print("\n" + "-" * 60)
    print("ОТВЕТ:")
    print("-" * 60)
    print(answer)
    print("-" * 60)


def main():
    """Главная функция"""
    logger.info("=" * 60)
    logger.info("Вопрос-ответная система на базе знаний")
    logger.info("=" * 60)
    
    # Проверяем доступность ollama
    try:
        response = requests.get(f"{settings.OLLAMA_URL}/api/tags", timeout=5)
        response.raise_for_status()
        logger.info(f"Ollama доступен по адресу: {settings.OLLAMA_URL}")
    except Exception as e:
        logger.error(f"Ошибка: Ollama недоступен по адресу {settings.OLLAMA_URL}")
        logger.error(f"Убедитесь, что ollama запущен в Docker")
        return
    
    # Подключаемся к ChromaDB
    try:
        client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
        collection = client.get_collection(settings.CHROMA_COLLECTION_NAME)
        count = collection.count()
        logger.info(f"Загружена векторная база данных: {count} документов")
    except Exception as e:
        logger.error(f"Ошибка при загрузке векторной базы данных: {e}")
        logger.error(f"Запустите сначала create_vector_db.py для создания базы")
        return
    
    # Определяем режим работы
    if len(sys.argv) > 1:
        # Режим одиночного запроса
        query = " ".join(sys.argv[1:])
        single_query_mode(collection, query)
    else:
        # Интерактивный режим
        interactive_mode(collection)


if __name__ == "__main__":
    main()
