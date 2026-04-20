#!/usr/bin/env python3
"""
Скрипт для вопрос-ответной системы на основе векторной базы данных
Использует ollama для генерации ответов и ChromaDB для поиска релевантных документов.
"""

import chromadb
from chromadb.config import Settings
import sys

# Импорт конфигурации и логирования
from config import settings, get_logger, inference_server_reachable

# Импорт общих функций для работы с эмбеддингами
from utils.embeddings import get_embedding, search_documents, generate_answer

# Получаем логгер для этого модуля
logger = get_logger(__name__)


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
    
    if not inference_server_reachable():
        logger.error(f"Сервер инференса недоступен: {settings.OLLAMA_URL}")
        logger.error("Проверьте INFERENCE_BACKEND (ollama | lmstudio) и запуск Ollama или LM Studio.")
        return
    logger.info(f"Сервер инференса отвечает: {settings.OLLAMA_URL}")
    
    # Подключаемся к ChromaDB
    try:
        client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
        
        collection = client.get_collection(name=settings.CHROMA_COLLECTION_NAME)
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
