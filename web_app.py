#!/usr/bin/env python3
"""
Flask веб-приложение для вопрос-ответной системы с RAG и цитированием
"""

from flask import Flask, render_template, request, jsonify, Response, stream_with_context
from flask_cors import CORS
import chromadb
import threading
import time
import json
import traceback
from functools import wraps

# Импорт конфигурации и логирования
from config import settings, get_logger, inference_server_reachable, fetch_remote_model_ids

# Импорт RAG системы
from core.rag import RAGSystem, RAGResult

# Импорт общих функций для работы с эмбеддингами
from api.routes.chat import chat_bp

# Получаем логгер для этого модуля
logger = get_logger(__name__)


def _rag_result_to_api_dict(rag_result: RAGResult) -> dict:
    """Тот же формат полей, что и у JSON-ответа POST /api/chat."""
    sources = []
    for s in rag_result.sources:
        sources.append({
            "title": s.get("title", "Без названия"),
            "path": s.get("path", "N/A"),
            "relevance": s.get("relevance", round(float(s.get("score", 0)), 2)),
        })
    citations = []
    for citation in rag_result.citations:
        citations.append({
            "text": citation.text,
            "source": citation.source,
            "chunk_id": citation.chunk_id,
            "score": round(citation.score, 2),
        })
    return {
        "answer": rag_result.answer,
        "sources": sources,
        "citations": citations,
    }


def _sse_event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


app = Flask(__name__)
_cors = settings.CORS_ORIGINS.strip()
if _cors in ("*", ""):
    CORS(app)
else:
    _origin_list = [o.strip() for o in _cors.split(",") if o.strip()]
    CORS(app, origins=_origin_list or ["http://127.0.0.1:5000", "http://localhost:5000"])

app.register_blueprint(chat_bp)

if not settings.FLASK_DEBUG:
    settings.validate()


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
            except (ValueError, TypeError, json.JSONDecodeError):
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
    
    # Полная RAG-цепочка одним вызовом (порог и top_k — из settings.RAG_MIN_SCORE / RAG_TOP_K)
    logger.info(f"Выполнение RAG запроса: '{query}'")
    try:
        rag_result = rag.query(query, max_citations=settings.RAG_MAX_CITATIONS)
        logger.info(f"Сгенерирован ответ длиной {len(rag_result.answer)} символов")
        logger.info(f"Извлечено {len(rag_result.citations)} цитат")
    except Exception:
        logger.error("Ошибка при выполнении RAG запроса:\n%s", traceback.format_exc())
        return jsonify({"error": "Ошибка при обработке запроса. Подробности в журнале сервера."}), 500

    if rag_result.retrieve_error == "embedding_unavailable":
        logger.error(
            "Эмбеддинг запроса не получен — в Chroma есть векторы, но поиск без эмбеддинга вопроса невозможен"
        )
        return jsonify({
            "answer": rag_result.answer,
            "sources": [],
            "citations": [],
        })

    if rag_result.retrieve_error == "search_error":
        logger.error("Ошибка Chroma при поиске")
        return jsonify({"error": "Ошибка поиска в векторной базе"}), 500

    payload = _rag_result_to_api_dict(rag_result)
    logger.debug(f"Источники: {[s['title'] for s in payload['sources']]}")
    return jsonify(payload)


@app.route('/api/chat/stream', methods=['POST'])
@log_api_request
def chat_stream():
    """RAG-чат с потоковой передачей текста (SSE). Итоговые sources/citations — в событии type=done."""
    data = request.get_json()

    if not data or 'message' not in data:
        logger.warning("stream: запрос без сообщения")
        return jsonify({"error": "Не указано сообщение"}), 400

    query = data['message'].strip()
    if not query:
        return jsonify({"error": "Пустое сообщение"}), 400
    if len(query) < 3:
        return jsonify({"error": "Слишком короткий запрос. Минимальная длина: 3 символа"}), 400
    if len(query) > 1000:
        return jsonify({"error": "Слишком длинный запрос. Максимальная длина: 1000 символов"}), 400

    coll, rag = initialize_database()
    if not coll or not rag:
        return jsonify({"error": "База данных недоступна"}), 500

    if not inference_server_reachable():
        return jsonify({
            "error": "Сервер LLM недоступен. Проверьте OLLAMA_URL и запуск Ollama или LM Studio.",
        }), 500

    documents, retrieve_error = rag.retrieve_documents(query)

    stream_headers = {
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
        "Content-Type": "text/event-stream; charset=utf-8",
    }

    if retrieve_error == "embedding_unavailable":
        rr = RAGResult(
            answer=(
                "Поиск по базе не выполнен: не удалось получить эмбеддинг для вашего вопроса. "
                "Индекс в Chroma уже заполнен, но для каждого запроса нужна работающая модель эмбеддингов "
                "(например, загрузите модель в LM Studio и проверьте OLLAMA_EMBEDDING_MODEL и INFERENCE_BACKEND=lmstudio)."
            ),
            citations=[],
            sources=[],
            retrieve_error="embedding_unavailable",
        )

        def gen_embed_err():
            payload = {"type": "done", **_rag_result_to_api_dict(rr)}
            yield _sse_event(payload)

        return Response(stream_with_context(gen_embed_err()), headers=stream_headers)

    if retrieve_error == "search_error":
        return jsonify({"error": "Ошибка поиска в векторной базе"}), 500

    if not documents:
        rr = RAGResult(
            answer="К сожалению, я не нашёл релевантной информации для ответа на ваш вопрос.",
            citations=[],
            sources=[],
        )

        def gen_no_docs():
            yield _sse_event({"type": "done", **_rag_result_to_api_dict(rr)})

        return Response(stream_with_context(gen_no_docs()), headers=stream_headers)

    def generate():
        # Комментарий SSE: первый байты уходят клиенту до первого токена LLM (лучше для прокси/буферов).
        yield ": stream-open\n\n"
        try:
            for evt in rag.stream_rag_answer(query, documents, settings.RAG_MAX_CITATIONS):
                if evt.get("type") == "delta":
                    yield _sse_event({"type": "delta", "text": evt.get("text", "")})
                elif evt.get("type") == "done":
                    rag_result = evt.get("rag_result")
                    if rag_result is None:
                        yield _sse_event({"type": "error", "message": "Пустой результат RAG"})
                        return
                    yield _sse_event({"type": "done", **_rag_result_to_api_dict(rag_result)})
        except Exception:
            logger.error("Ошибка в потоке /api/chat/stream:\n%s", traceback.format_exc())
            yield _sse_event({
                "type": "error",
                "message": "Ошибка при обработке запроса. Подробности в журнале сервера.",
            })

    return Response(stream_with_context(generate()), headers=stream_headers)


@app.route('/api/models', methods=['GET'])
def get_models():
    """Список моделей с Ollama (/api/tags) или LM Studio (/v1/models) в зависимости от настроек."""
    logger.info("Запрос списка моделей с сервера инференса")
    try:
        models = fetch_remote_model_ids()
        logger.info(f"Найдено {len(models)} моделей")
        return jsonify({"models": models})
    except Exception:
        logger.error("Ошибка при получении списка моделей:\n%s", traceback.format_exc())
        return jsonify({"error": "Не удалось получить список моделей."}), 500


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
    app.run(host=settings.API_HOST, port=settings.API_PORT, debug=settings.FLASK_DEBUG)
