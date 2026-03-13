#!/usr/bin/env python3
"""
Flask веб-приложение для вопрос-ответной системы
"""

from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import chromadb
from chromadb.config import Settings
import requests
from typing import List, Dict
import threading
import queue

app = Flask(__name__)
CORS(app)

# Конфигурация
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "bge-m3"
OLLAMA_CHAT_MODEL = "qwen2.5:7b"
CHROMA_PERSIST_DIR = "./chroma_db"
TOP_K_RESULTS = 3

# Глобальные переменные для подключения к базе данных
collection = None
db_initialized = False
init_lock = threading.Lock()


def initialize_database():
    """Инициализация подключения к ChromaDB"""
    global collection, db_initialized
    
    with init_lock:
        if db_initialized:
            return collection
        
        try:
            client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
            collection = client.get_collection("wiki_knowledge")
            count = collection.count()
            db_initialized = True
            print(f"Загружена векторная база данных: {count} документов")
            return collection
        except Exception as e:
            print(f"Ошибка при загрузке векторной базы данных: {e}")
            return None


def get_embedding(text: str) -> List[float]:
    """Получить эмбеддинг текста через ollama"""
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
    query_embedding = get_embedding(query)
    
    if not query_embedding:
        return []
    
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
    
    return documents


def generate_answer(query: str, context_docs: List[Dict]) -> str:
    """Генерация ответа с использованием ollama"""
    context = "\n\n".join([
        f"--- Документ {i+1} (источник: {doc['metadata'].get('title', 'Без названия')}) ---\n{doc['text']}"
        for i, doc in enumerate(context_docs)
    ])
    
    prompt = f"""Ты - полезный ассистент по базе знаний компании. Отвечай на вопросы пользователя, используя только предоставленный контекст.

Контекст из базы знаний:
{context}

Вопрос пользователя: {query}

Инструкции:
1. Отвечай на русском языке
2. Используй только информацию из предоставленного контекста
3. Если в контексте нет информации для ответа, честно скажи об этом
4. Приводи ссылки на источники (названия документов)
5. Будь кратким и по существу

Ответ:"""

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


@app.route('/')
def index():
    """Главная страница"""
    return render_template('index.html')


@app.route('/api/health', methods=['GET'])
def health_check():
    """Проверка здоровья системы"""
    ollama_status = False
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        ollama_status = response.status_code == 200
    except:
        pass
    
    coll = initialize_database()
    db_status = coll is not None
    
    return jsonify({
        "ollama": ollama_status,
        "database": db_status,
        "status": "ok" if ollama_status and db_status else "error"
    })


@app.route('/api/chat', methods=['POST'])
def chat():
    """Обработка запроса чата"""
    data = request.get_json()
    
    if not data or 'message' not in data:
        return jsonify({"error": "Не указано сообщение"}), 400
    
    query = data['message'].strip()
    
    if not query:
        return jsonify({"error": "Пустое сообщение"}), 400
    
    # Инициализируем базу данных
    coll = initialize_database()
    if not coll:
        return jsonify({"error": "База данных недоступна"}), 500
    
    # Проверяем доступность Ollama
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        response.raise_for_status()
    except:
        return jsonify({"error": "Ollama недоступен"}), 500
    
    # Ищем релевантные документы
    docs = search_documents(query, coll)
    
    if not docs:
        return jsonify({
            "answer": "Не найдено релевантных документов в базе знаний.",
            "sources": []
        })
    
    # Генерируем ответ
    answer = generate_answer(query, docs)
    
    # Формируем список источников
    sources = []
    for doc in docs:
        sources.append({
            "title": doc['metadata'].get('title', 'Без названия'),
            "path": doc['metadata'].get('path', 'N/A'),
            "relevance": round(1 - doc['distance'], 2)
        })
    
    return jsonify({
        "answer": answer,
        "sources": sources
    })


@app.route('/api/models', methods=['GET'])
def get_models():
    """Получить список доступных моделей Ollama"""
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        response.raise_for_status()
        result = response.json()
        models = [model['name'] for model in result.get('models', [])]
        return jsonify({"models": models})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    # Инициализируем базу данных при запуске
    initialize_database()
    app.run(host='0.0.0.0', port=5000, debug=True)
