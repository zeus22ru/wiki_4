#!/usr/bin/env python3
"""
Flask веб-приложение для вопрос-ответной системы с RAG и цитированием
"""

from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import chromadb
from chromadb.config import Settings
import threading
import time
from functools import wraps
import requests

# Импорт конфигурации и логирования
from config import settings, get_logger, inference_server_reachable, fetch_remote_model_ids

# Импорт RAG системы
from core.rag import RAGSystem

# Импорт общих функций для работы с эмбеддингами
from utils.embeddings import get_embedding, search_documents

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
rag_system = None
db_initialized = False
init_lock = threading.Lock()


def initialize_database():
    """Инициализация подключения к ChromaDB и RAG системы"""
    global collection, rag_system, db_initialized
    
    with init_lock:
        if db_initialized:
            return collection, rag_system
        
        try:
            client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
            
            collection = client.get_collection(name=settings.CHROMA_COLLECTION_NAME)
            count = collection.count()
            
            # Инициализируем RAG систему
            rag_system = RAGSystem(settings.CHROMA_COLLECTION_NAME)
            
            db_initialized = True
            logger.info(f"Загружена векторная база данных: {count} документов")
            logger.info("RAG система инициализирована")
            return collection, rag_system
        except Exception as e:
            logger.error(f"Ошибка при загрузке векторной базы данных: {e}")
            return None, None


@app.route('/')
@log_api_request
def index():
    """Главная страница"""
    return render_template('index.html')


@app.route('/api/health', methods=['GET'])
@log_api_request
def health_check():
    """Проверка здоровья системы"""
    ollama_status = inference_server_reachable()
    logger.debug(f"Сервер инференса (Ollama/LM Studio) доступен: {ollama_status}")
    
    coll, rag = initialize_database()
    db_status = coll is not None
    rag_status = rag is not None
    logger.debug(f"База данных статус: {db_status}, RAG статус: {rag_status}")
    
    return jsonify({
        "ollama": ollama_status,
        "database": db_status,
        "rag": rag_status,
        "status": "ok" if ollama_status and db_status else "error"
    })


@app.route('/api/chat', methods=['POST'])
@log_api_request
def chat():
    """Обработка запроса чата с использованием RAG системы"""
    data = request.get_json()
    
    if not data or 'message' not in data:
        logger.warning("Получен запрос без сообщения")
        return jsonify({"error": "Не указано сообщение"}), 400
    
    query = data['message'].strip()
    logger.info(f"Запрос чата: '{query[:100]}...'")
    
    if not query:
        logger.warning("Получено пустое сообщение")
        return jsonify({"error": "Пустое сообщение"}), 400
    
    # Валидация длины запроса
    if len(query) < 3:
        logger.warning(f"Слишком короткий запрос: {len(query)} символов")
        return jsonify({"error": "Слишком короткий запрос. Минимальная длина: 3 символа"}), 400
    
    if len(query) > 1000:
        logger.warning(f"Слишком длинный запрос: {len(query)} символов")
        return jsonify({"error": "Слишком длинный запрос. Максимальная длина: 1000 символов"}), 400
    
    # Инициализируем базу данных и RAG систему
    coll, rag = initialize_database()
    if not coll or not rag:
        logger.error("База данных или RAG система недоступна")
        return jsonify({"error": "База данных недоступна"}), 500
    
    if not inference_server_reachable():
        logger.error("Сервер LLM недоступен по OLLAMA_URL (ожидается /api/tags или /v1/models)")
        return jsonify({"error": "Сервер LLM недоступен. Проверьте OLLAMA_URL и запуск Ollama или LM Studio."}), 500
    
    # Используем RAG систему для поиска и генерации ответа с цитированием
    logger.info(f"Выполнение RAG запроса: '{query}'")
    
    # Поиск релевантных документов через RAG с использованием min_score
    try:
        docs, retrieve_err = rag.retrieve_documents(
            query, top_k=settings.TOP_K_RESULTS, min_score=0.0
        )
        logger.info(f"Найдено {len(docs)} релевантных документов (ошибка поиска: {retrieve_err!r})")
    except Exception as e:
        logger.error(f"Ошибка при поиске документов: {e}")
        return jsonify({"error": "Ошибка при поиске в базе знаний"}), 500
    
    if retrieve_err == "embedding_unavailable":
        logger.error("Эмбеддинг запроса не получен — в Chroma есть векторы, но поиск без эмбеддинга вопроса невозможен")
        return jsonify({
            "answer": (
                "Поиск по базе не выполнен: не удалось получить эмбеддинг для вашего вопроса. "
                "Индекс в Chroma уже заполнен, но для каждого запроса нужна работающая модель эмбеддингов "
                "(загрузите модель в LM Studio / Ollama, проверьте OLLAMA_EMBEDDING_MODEL и INFERENCE_BACKEND / EMBEDDING_API_MODE)."
            ),
            "sources": [],
            "citations": [],
        })
    
    if retrieve_err == "search_error":
        logger.error("Ошибка Chroma при поиске")
        return jsonify({"error": "Ошибка поиска в векторной базе"}), 500
    
    if not docs:
        logger.info("Не найдено релевантных документов")
        return jsonify({
            "answer": "К сожалению, я не нашёл релевантной информации для ответа на ваш вопрос.",
            "sources": [],
            "citations": []
        })
    
    # Используем новый метод query() для полной RAG-цепочки
    try:
        rag_result = rag.query(query, top_k=settings.TOP_K_RESULTS, min_score=0.0, max_citations=5)
        logger.info(f"Сгенерирован ответ длиной {len(rag_result.answer)} символов")
        logger.info(f"Извлечено {len(rag_result.citations)} цитат")
    except Exception as e:
        logger.error(f"Ошибка при выполнении RAG запроса: {e}")
        return jsonify({"error": f"Ошибка при обработке запроса: {str(e)}"}), 500
    
    # Формируем список источников
    sources = []
    for doc in docs:
        sources.append({
            "title": doc['metadata'].get('title', 'Без названия'),
            "path": doc['metadata'].get('path', 'N/A'),
            "relevance": round(doc['score'], 2)
        })
    
    # Формируем список цитат
    citations = []
    for citation in rag_result.citations:
        citations.append({
            "text": citation.text,
            "source": citation.source,
            "chunk_id": citation.chunk_id,
            "score": round(citation.score, 2)
        })
    
    logger.debug(f"Источники: {[s['title'] for s in sources]}")
    
    return jsonify({
        "answer": rag_result.answer,
        "sources": sources,
        "citations": citations
    })


@app.route('/api/models', methods=['GET'])
def get_models():
    """Список моделей с Ollama (/api/tags) или LM Studio (/v1/models) в зависимости от настроек."""
    logger.info("Запрос списка моделей с сервера инференса")
    try:
        models = fetch_remote_model_ids()
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
    logger.info(f"OLLAMA_URL: {settings.OLLAMA_URL}")
    backend = settings.INFERENCE_BACKEND or "(по EMBEDDING_API_MODE/CHAT_API_MODE)"
    logger.info(f"INFERENCE_BACKEND: {backend}")
    logger.info(
        f"API: эмбеддинги={settings.EMBEDDING_API_MODE}, чат={settings.CHAT_API_MODE} "
        f"(openai → /v1/embeddings + /v1/chat/completions; ollama → /api/embed + /api/generate)"
    )
    logger.info(f"Модель эмбеддингов: {settings.OLLAMA_EMBEDDING_MODEL}")
    logger.info(f"Модель чата: {settings.OLLAMA_CHAT_MODEL}")
    logger.info(f"Хост: {settings.API_HOST}, Порт: {settings.API_PORT}")
    
    initialize_database()
    app.run(host=settings.API_HOST, port=settings.API_PORT, debug=True)
