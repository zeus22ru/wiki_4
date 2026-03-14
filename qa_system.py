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

# Конфигурация
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "bge-m3"  # Модель для эмбеддингов (соответствует create_vector_db.py)
OLLAMA_CHAT_MODEL = "qwen2.5:7b"  # Модель для генерации ответов
CHROMA_PERSIST_DIR = "./chroma_db"
TOP_K_RESULTS = 3  # Количество релевантных документов для поиска


def get_embedding(text: str) -> List[float]:
    """Получить эмбеддинг текста через ollama (API v2)"""
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/embed",
            json={
                "model": OLLAMA_MODEL,
                "input": text
            },
            timeout=60
        )
        response.raise_for_status()
        result = response.json()
        # API v2 возвращает embeddings (массив) или embedding (один)
        if "embeddings" in result:
            return result["embeddings"][0]
        elif "embedding" in result:
            return result["embedding"]
        return []
    except Exception as e:
        print(f"Ошибка при получении эмбеддинга: {e}")
        return []


def search_documents(query: str, collection, top_k: int = TOP_K_RESULTS) -> List[Dict]:
    """Поиск релевантных документов в векторной базе"""
    print(f"Поиск релевантных документов для запроса: '{query}'")
    
    # Получаем эмбеддинг запроса
    query_embedding = get_embedding(query)
    
    if not query_embedding:
        print("Не удалось получить эмбеддинг запроса")
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
    
    print(f"Найдено {len(documents)} релевантных документов")
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
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": OLLAMA_CHAT_MODEL,
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
        return f"Произошла ошибка при генерации ответа: HTTP {e.response.status_code if hasattr(e, 'response') and e.response else 'Unknown'}"
    except requests.exceptions.Timeout:
        return "Произошла ошибка при генерации ответа: Превышено время ожидания"
    except requests.exceptions.ConnectionError:
        return "Произошла ошибка при генерации ответа: Не удалось подключиться к Ollama"
    except Exception as e:
        return f"Произошла ошибка при генерации ответа: {str(e)}"


def interactive_mode(collection):
    """Интерактивный режим вопрос-ответ"""
    print("\n" + "=" * 60)
    print("Режим вопрос-ответ (введите 'exit' для выхода)")
    print("=" * 60 + "\n")
    
    while True:
        try:
            query = input("Ваш вопрос: ").strip()
            
            if query.lower() in ['exit', 'quit', 'выход', 'q']:
                print("До свидания!")
                break
            
            if not query:
                continue
            
            # Ищем релевантные документы
            docs = search_documents(query, collection)
            
            if not docs:
                print("\nНе найдено релевантных документов в базе знаний.\n")
                continue
            
            # Генерируем ответ
            print("\nГенерация ответа...")
            answer = generate_answer(query, docs)
            
            print("\n" + "-" * 60)
            print("ОТВЕТ:")
            print("-" * 60)
            print(answer)
            print("-" * 60 + "\n")
            
        except KeyboardInterrupt:
            print("\n\nДо свидания!")
            break
        except Exception as e:
            print(f"\nОшибка: {e}\n")


def single_query_mode(collection, query: str):
    """Режим одиночного запроса"""
    # Ищем релевантные документы
    docs = search_documents(query, collection)
    
    if not docs:
        print("\nНе найдено релевантных документов в базе знаний.")
        return
    
    # Выводим найденные документы
    print("\n" + "=" * 60)
    print("РЕЛЕВАНТНЫЕ ДОКУМЕНТЫ:")
    print("=" * 60)
    for i, doc in enumerate(docs, 1):
        print(f"\n--- Документ {i} ---")
        print(f"Источник: {doc['metadata'].get('title', 'Без названия')}")
        print(f"Путь: {doc['metadata'].get('path', 'N/A')}")
        print(f"Релевантность: {1 - doc['distance']:.2f}")
        print(f"Текст: {doc['text'][:300]}...")
    
    # Генерируем ответ
    print("\n" + "=" * 60)
    print("Генерация ответа...")
    print("=" * 60)
    answer = generate_answer(query, docs)
    
    print("\n" + "-" * 60)
    print("ОТВЕТ:")
    print("-" * 60)
    print(answer)
    print("-" * 60)


def main():
    """Главная функция"""
    print("=" * 60)
    print("Вопрос-ответная система на базе знаний")
    print("=" * 60)
    
    # Проверяем доступность ollama
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        response.raise_for_status()
        print(f"Ollama доступен по адресу: {OLLAMA_URL}")
    except Exception as e:
        print(f"Ошибка: Ollama недоступен по адресу {OLLAMA_URL}")
        print(f"Убедитесь, что ollama запущен в Docker")
        return
    
    # Подключаемся к ChromaDB
    try:
        client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
        collection = client.get_collection("wiki_knowledge")
        count = collection.count()
        print(f"Загружена векторная база данных: {count} документов")
    except Exception as e:
        print(f"Ошибка при загрузке векторной базы данных: {e}")
        print(f"Запустите сначала create_vector_db.py для создания базы")
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
