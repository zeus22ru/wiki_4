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
import time
from functools import wraps

# Импорт конфигурации и логирования
from config import settings, get_logger

# Получаем логгер для этого модуля
logger = get_logger(__name__)

app = Flask(__name__)
CORS(app)


# ============================================
# Декораторы для логирования
# ============================================

def log_api_request(f):
    """Декоратор для логирования API запросов и ответов"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        start_time = time.time()
        
        # Логируем запрос
        logger.info(f"API запрос: {request.method} {request.path}")
        logger.debug(f"IP клиента: {request.remote_addr}")
        logger.debug(f"User-Agent: {request.user_agent}")
        
        # Логируем тело запроса (без чувствительных данных)
        if request.is_json and request.data:
            try:
                data = request.get_json()
                # Удаляем чувствительные данные
                safe_data = {k: v for k, v in data.items()
                           if k not in ['password', 'token', 'secret']}
                logger.debug(f"Тело запроса: {safe_data}")
            except:
                pass
        
        try:
            # Выполняем функцию
            response = f(*args, **kwargs)
            
            # Вычисляем время выполнения
            duration = time.time() - start_time
            
            # Логируем ответ
            if hasattr(response, 'status_code'):
                logger.info(f"API ответ: {request.path} - Статус: {response.status_code} - Время: {duration:.3f}с")
            else:
                logger.info(f"API ответ: {request.path} - Время: {duration:.3f}с")
            
            return response
        except Exception as e:
            # Логируем ошибку
            duration = time.time() - start_time
            logger.error(f"API ошибка: {request.path} - {str(e)} - Время: {duration:.3f}с")
            raise
    
    return decorated_function

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
            client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
            collection = client.get_collection(settings.CHROMA_COLLECTION_NAME)
            count = collection.count()
            db_initialized = True
            logger.info(f"Загружена векторная база данных: {count} документов")
            return collection
        except Exception as e:
            logger.error(f"Ошибка при загрузке векторной базы данных: {e}")
            return None


def get_embedding(text: str) -> List[float]:
    """Получить эмбеддинг текста через ollama"""
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
        if "embeddings" in result:
            return result["embeddings"][0]
        elif "embedding" in result:
            return result["embedding"]
        return []
    except Exception as e:
        logger.error(f"Ошибка при получении эмбеддинга: {e}")
        return []


def search_documents(query: str, collection, top_k: int = None) -> List[Dict]:
    """Поиск релевантных документов в векторной базе"""
    if top_k is None:
        top_k = settings.TOP_K_RESULTS
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
        return f"Произошла ошибка при генерации ответа: HTTP {e.response.status_code if hasattr(e, 'response') and e.response else 'Unknown'}"
    except requests.exceptions.Timeout:
        return "Произошла ошибка при генерации ответа: Превышено время ожидания"
    except requests.exceptions.ConnectionError:
        return "Произошла ошибка при генерации ответа: Не удалось подключиться к Ollama"
    except Exception as e:
        return f"Произошла ошибка при генерации ответа: {str(e)}"


@app.route('/')
@log_api_request
def index():
    """Главная страница"""
    return render_template('index.html')


@app.route('/api/health', methods=['GET'])
@log_api_request
def health_check():
    """Проверка здоровья системы"""
    ollama_status = False
    try:
        response = requests.get(f"{settings.OLLAMA_URL}/api/tags", timeout=5)
        ollama_status = response.status_code == 200
        logger.debug(f"Ollama статус: {ollama_status}")
    except Exception as e:
        logger.warning(f"Ollama недоступен: {e}")
    
    coll = initialize_database()
    db_status = coll is not None
    logger.debug(f"База данных статус: {db_status}")
    
    return jsonify({
        "ollama": ollama_status,
        "database": db_status,
        "status": "ok" if ollama_status and db_status else "error"
    })


@app.route('/api/chat', methods=['POST'])
@log_api_request
def chat():
    """Обработка запроса чата"""
    data = request.get_json()
    
    if not data or 'message' not in data:
        logger.warning("Получен запрос без сообщения")
        return jsonify({"error": "Не указано сообщение"}), 400
    
    query = data['message'].strip()
    logger.info(f"Запрос чата: '{query[:100]}...'")  # Логируем первые 100 символов
    
    if not query:
        logger.warning("Получено пустое сообщение")
        return jsonify({"error": "Пустое сообщение"}), 400
    
    # Инициализируем базу данных
    coll = initialize_database()
    if not coll:
        logger.error("База данных недоступна")
        return jsonify({"error": "База данных недоступна"}), 500
    
    # Проверяем доступность Ollama
    try:
        response = requests.get(f"{settings.OLLAMA_URL}/api/tags", timeout=5)
        response.raise_for_status()
    except Exception as e:
        logger.error(f"Ollama недоступен: {e}")
        return jsonify({"error": "Ollama недоступен"}), 500
    
    # Ищем релевантные документы
    docs = search_documents(query, coll)
    logger.info(f"Найдено {len(docs)} релевантных документов")
    
    if not docs:
        logger.info("Не найдено релевантных документов")
        return jsonify({
            "answer": "Не найдено релевантных документов в базе знаний.",
            "sources": []
        })
    
    # Генерируем ответ
    answer = generate_answer(query, docs)
    logger.info(f"Сгенерирован ответ длиной {len(answer)} символов")
    
    # Формируем список источников
    sources = []
    for doc in docs:
        sources.append({
            "title": doc['metadata'].get('title', 'Без названия'),
            "path": doc['metadata'].get('path', 'N/A'),
            "relevance": round(1 - doc['distance'], 2)
        })
    
    logger.debug(f"Источники: {[s['title'] for s in sources]}")
    
    return jsonify({
        "answer": answer,
        "sources": sources
    })


@app.route('/api/models', methods=['GET'])
def get_models():
    """Получить список доступных моделей Ollama"""
    logger.info("Запрос списка моделей Ollama")
    try:
        response = requests.get(f"{settings.OLLAMA_URL}/api/tags", timeout=5)
        response.raise_for_status()
        result = response.json()
        models = [model['name'] for model in result.get('models', [])]
        logger.info(f"Найдено {len(models)} моделей")
        return jsonify({"models": models})
    except Exception as e:
        logger.error(f"Ошибка при получении списка моделей: {e}")
        return jsonify({"error": str(e)}), 500


@app.before_request
def log_request_info():
    """Логирование входящих запросов"""
    # Пропускаем логирование статических файлов
    if request.path.startswith('/static'):
        return
    
    logger.info(
        f"Request: {request.method} {request.path} | "
        f"IP: {request.remote_addr} | "
        f"User-Agent: {request.user_agent}"
    )
    # Логируем тело запроса для POST/PUT
    if request.method in ['POST', 'PUT'] and request.is_json:
        try:
            body = request.get_json()
            # Логируем только первые 200 символов для безопасности
            body_str = str(body)[:200]
            logger.debug(f"Request body: {body_str}...")
        except Exception:
            pass


@app.after_request
def log_response_info(response):
    """Логирование исходящих ответов"""
    # Пропускаем логирование статических файлов
    if request.path.startswith('/static'):
        return response
    
    logger.info(
        f"Response: {response.status_code} | "
        f"Path: {request.path}"
    )
    return response


if __name__ == '__main__':
    # Инициализируем базу данных при запуске
    logger.info("Запуск Flask приложения")
    logger.info(f"Ollama URL: {settings.OLLAMA_URL}")
    logger.info(f"Модель эмбеддингов: {settings.OLLAMA_EMBEDDING_MODEL}")
    logger.info(f"Модель чата: {settings.OLLAMA_CHAT_MODEL}")
    logger.info(f"Хост: {settings.API_HOST}, Порт: {settings.API_PORT}")
    
    initialize_database()
    app.run(host=settings.API_HOST, port=settings.API_PORT, debug=True)
