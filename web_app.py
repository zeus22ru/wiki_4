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
from core.chat_history import get_chat_history

# Импорт общих функций для работы с эмбеддингами
from api.routes.chat import chat_bp
from api.routes.documents import documents_bp
from api.routes.admin import admin_bp
from api.routes.auth import auth_bp
from api.middleware.auth import can_access_chat, current_user_id, remember_guest_chat

# Получаем логгер для этого модуля
logger = get_logger(__name__)


def _rag_result_to_api_dict(rag_result: RAGResult) -> dict:
    """Тот же формат полей, что и у JSON-ответа POST /api/chat."""
    sources = []
    for s in rag_result.sources:
        sources.append({
            "title": s.get("title", "Без названия"),
            "path": s.get("path", "N/A"),
            "source": s.get("source", s.get("title", "Без названия")),
            "chunk_id": s.get("chunk_id"),
            "score": s.get("score"),
            "relevance": s.get("relevance", round(float(s.get("score", 0)), 2)),
            "text": s.get("text", ""),
            "file_type": s.get("file_type", ""),
            "chunk_index": s.get("chunk_index"),
            "total_chunks": s.get("total_chunks"),
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
        "diagnostics": rag_result.diagnostics or {},
    }


def _get_json_body() -> dict:
    """Единая безопасная обработка JSON body."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _int_or_none(value):
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _chat_options(data: dict) -> dict:
    try:
        min_score = float(data["min_score"]) if data.get("min_score") is not None else None
    except (TypeError, ValueError):
        min_score = None
    return {
        "top_k": _int_or_none(data.get("top_k")),
        "min_score": min_score,
        "answer_mode": data.get("answer_mode") or "default",
    }


def _resolve_chat_session(data: dict, query: str):
    chat_history = get_chat_history()
    chat_id = _int_or_none(data.get("chat_id"))
    if chat_id:
        chat_session = chat_history.get_session(chat_id)
        if chat_session and can_access_chat(chat_session):
            return chat_history, chat_id
        raise PermissionError("Нет доступа к чату")
    title = (query[:60] + "...") if len(query) > 60 else query
    session = chat_history.create_session(user_id=current_user_id(), title=title or "Новый чат")
    if session.user_id is None:
        remember_guest_chat(session.id)
    return chat_history, session.id


def _conversation_history_for_rag(chat_history, chat_id: int, limit: int = 10) -> list[dict]:
    """Последние сообщения текущего чата для понимания уточняющих вопросов."""
    return [
        {"role": msg.role, "content": msg.content}
        for msg in chat_history.get_recent_messages(chat_id, limit=limit)
        if msg.role in {"user", "assistant"} and msg.content
    ]


def _maybe_update_chat_title(chat_history, chat_id: int, query: str) -> None:
    """Переименовать новый пустой чат по первому успешному вопросу."""
    session = chat_history.get_session(chat_id)
    if not session or session.title != "Новый чат":
        return
    title = query.strip()
    if len(title) > 60:
        title = title[:57].rstrip() + "..."
    if title:
        chat_history.update_session(chat_id, title=title)


def _sse_event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


app = Flask(__name__)
app.secret_key = settings.SECRET_KEY
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)
_cors = settings.CORS_ORIGINS.strip()
if _cors in ("*", ""):
    CORS(app)
else:
    _origin_list = [o.strip() for o in _cors.split(",") if o.strip()]
    CORS(app, origins=_origin_list or ["http://127.0.0.1:5000", "http://localhost:5000"])

app.register_blueprint(chat_bp)
app.register_blueprint(documents_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(auth_bp)

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
                           if k not in ['password', 'password_hash', 'token', 'secret']}
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
    data = _get_json_body()
    
    if not data or 'message' not in data:
        logger.warning("Получен запрос без сообщения")
        return jsonify({"error": "Не указано сообщение"}), 400
    
    query = data['message'].strip()
    options = _chat_options(data)
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
        try:
            chat_history, chat_id = _resolve_chat_session(data, query)
        except PermissionError:
            return jsonify({"error": "Нет доступа к чату"}), 403
        conversation_history = _conversation_history_for_rag(chat_history, chat_id)
        chat_history.add_message(
            session_id=chat_id,
            role="user",
            content=query,
            metadata={"answer_mode": options["answer_mode"]},
        )
        started = time.time()
        rag_result = rag.query(
            query,
            top_k=options["top_k"],
            min_score=options["min_score"],
            max_citations=settings.RAG_MAX_CITATIONS,
            answer_mode=options["answer_mode"],
            conversation_history=conversation_history,
        )
        latency_ms = int((time.time() - started) * 1000)
        logger.info(f"Сгенерирован ответ длиной {len(rag_result.answer)} символов")
        logger.info(f"Извлечено {len(rag_result.citations)} цитат")
    except Exception:
        logger.error("Ошибка при выполнении RAG запроса:\n%s", traceback.format_exc())
        return jsonify({"error": "Ошибка при обработке запроса. Подробности в журнале сервера."}), 500

    if rag_result.retrieve_error == "embedding_unavailable":
        logger.error(
            "Эмбеддинг запроса не получен — в Chroma есть векторы, но поиск без эмбеддинга вопроса невозможен"
        )
        payload = {
            "answer": rag_result.answer,
            "sources": [],
            "citations": [],
            "chat_id": chat_id,
            "diagnostics": rag_result.diagnostics or {},
        }
        chat_history.add_message(
            session_id=chat_id,
            role="assistant",
            content=rag_result.answer,
            metadata={"retrieve_error": "embedding_unavailable", "latency_ms": latency_ms},
        )
        return jsonify(payload)

    if rag_result.retrieve_error == "search_error":
        logger.error("Ошибка Chroma при поиске")
        return jsonify({"error": "Ошибка поиска в векторной базе"}), 500

    payload = _rag_result_to_api_dict(rag_result)
    payload["chat_id"] = chat_id
    assistant_message = chat_history.add_message(
        session_id=chat_id,
        role="assistant",
        content=payload["answer"],
        sources=payload["sources"],
        citations=payload["citations"],
        metadata={
            "model_name": settings.OLLAMA_CHAT_MODEL,
            "rag_settings_snapshot": {
                "top_k": options["top_k"] or settings.RAG_TOP_K,
                "min_score": options["min_score"] if options["min_score"] is not None else settings.RAG_MIN_SCORE,
                "answer_mode": options["answer_mode"],
            },
            "latency_ms": latency_ms,
            "diagnostics": payload.get("diagnostics", {}),
        },
    )
    _maybe_update_chat_title(chat_history, chat_id, query)
    payload["message_id"] = assistant_message.id
    logger.debug(f"Источники: {[s['title'] for s in payload['sources']]}")
    return jsonify(payload)


@app.route('/api/chat/stream', methods=['POST'])
@log_api_request
def chat_stream():
    """RAG-чат с потоковой передачей текста (SSE). Итоговые sources/citations — в событии type=done."""
    data = _get_json_body()

    if not data or 'message' not in data:
        logger.warning("stream: запрос без сообщения")
        return jsonify({"error": "Не указано сообщение"}), 400

    query = data['message'].strip()
    options = _chat_options(data)
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

    try:
        chat_history, chat_id = _resolve_chat_session(data, query)
    except PermissionError:
        return jsonify({"error": "Нет доступа к чату"}), 403
    conversation_history = _conversation_history_for_rag(chat_history, chat_id)
    chat_history.add_message(
        session_id=chat_id,
        role="user",
        content=query,
        metadata={"answer_mode": options["answer_mode"]},
    )

    stream_headers = {
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
        "Content-Type": "text/event-stream; charset=utf-8",
    }

    def generate():
        # Комментарий SSE: первый байты уходят клиенту до первого токена LLM (лучше для прокси/буферов).
        yield ": stream-open\n\n"
        yield _sse_event({"type": "status", "message": "Ищу релевантные документы..."})
        started = time.time()
        try:
            retrieval_query = rag.build_retrieval_query(query, conversation_history)
            documents, retrieve_error = rag.retrieve_documents(retrieval_query, options["top_k"], options["min_score"])

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
                assistant_message = chat_history.add_message(
                    session_id=chat_id,
                    role="assistant",
                    content=rr.answer,
                    metadata={"retrieve_error": "embedding_unavailable"},
                )
                _maybe_update_chat_title(chat_history, chat_id, query)
                yield _sse_event({
                    "type": "done",
                    "chat_id": chat_id,
                    "message_id": assistant_message.id,
                    **_rag_result_to_api_dict(rr),
                })
                return

            if retrieve_error == "search_error":
                yield _sse_event({"type": "error", "message": "Ошибка поиска в векторной базе"})
                return

            if not documents:
                rr = RAGResult(
                    answer="К сожалению, я не нашёл релевантной информации для ответа на ваш вопрос.",
                    citations=[],
                    sources=[],
                )
                assistant_message = chat_history.add_message(
                    session_id=chat_id,
                    role="assistant",
                    content=rr.answer,
                    metadata={"retrieval_status": "no_documents"},
                )
                _maybe_update_chat_title(chat_history, chat_id, query)
                yield _sse_event({
                    "type": "done",
                    "chat_id": chat_id,
                    "message_id": assistant_message.id,
                    **_rag_result_to_api_dict(rr),
                })
                return

            yield _sse_event({"type": "status", "message": "Документы найдены, модель формирует ответ..."})
            for evt in rag.stream_rag_answer(
                query,
                documents,
                settings.RAG_MAX_CITATIONS,
                answer_mode=options["answer_mode"],
                conversation_history=conversation_history,
                retrieval_query=retrieval_query,
            ):
                if evt.get("type") == "delta":
                    yield _sse_event({"type": "delta", "text": evt.get("text", "")})
                elif evt.get("type") == "done":
                    rag_result = evt.get("rag_result")
                    if rag_result is None:
                        yield _sse_event({"type": "error", "message": "Пустой результат RAG"})
                        return
                    payload = _rag_result_to_api_dict(rag_result)
                    assistant_message = chat_history.add_message(
                        session_id=chat_id,
                        role="assistant",
                        content=payload["answer"],
                        sources=payload["sources"],
                        citations=payload["citations"],
                        metadata={
                            "model_name": settings.OLLAMA_CHAT_MODEL,
                            "rag_settings_snapshot": {
                                "top_k": options["top_k"] or settings.RAG_TOP_K,
                                "min_score": options["min_score"] if options["min_score"] is not None else settings.RAG_MIN_SCORE,
                                "answer_mode": options["answer_mode"],
                            },
                            "latency_ms": int((time.time() - started) * 1000),
                            "diagnostics": payload.get("diagnostics", {}),
                        },
                    )
                    _maybe_update_chat_title(chat_history, chat_id, query)
                    yield _sse_event({
                        "type": "done",
                        "chat_id": chat_id,
                        "message_id": assistant_message.id,
                        **payload,
                    })
        except Exception:
            logger.error("Ошибка в потоке /api/chat/stream:\n%s", traceback.format_exc())
            yield _sse_event({
                "type": "error",
                "message": "Ошибка при обработке запроса. Подробности в журнале сервера.",
            })

    return Response(stream_with_context(generate()), headers=stream_headers)


@app.route('/api/chat/verify', methods=['POST'])
@log_api_request
def verify_chat_answer():
    """Проверить ответ ассистента по сохраненным цитатам."""
    data = _get_json_body()
    answer = (data.get("answer") or "").strip()
    citations = data.get("citations") or []
    sources = data.get("sources") or []

    if not answer:
        return jsonify({"error": "Не указан текст ответа для проверки"}), 400
    if not isinstance(citations, list) or not isinstance(sources, list):
        return jsonify({"error": "sources и citations должны быть списками"}), 400

    coll, rag = initialize_database()
    if not coll or not rag:
        return jsonify({"error": "База данных недоступна"}), 500

    if not inference_server_reachable():
        return jsonify({
            "error": "Сервер LLM недоступен. Проверьте OLLAMA_URL и запуск Ollama или LM Studio.",
        }), 500

    try:
        result = rag.verify_answer_against_sources(answer, citations, sources)
    except Exception:
        logger.error("Ошибка при проверке ответа:\n%s", traceback.format_exc())
        return jsonify({"error": "Ошибка при проверке ответа. Подробности в журнале сервера."}), 500

    return jsonify({"verification": result})


@app.route('/api/chat/suggestions', methods=['POST'])
@log_api_request
def suggest_chat_questions():
    """Сгенерировать уточняющие вопросы к готовому ответу."""
    data = _get_json_body()
    answer = (data.get("answer") or "").strip()
    citations = data.get("citations") or []
    sources = data.get("sources") or []

    if not answer:
        return jsonify({"suggestions": []})
    if not isinstance(citations, list) or not isinstance(sources, list):
        return jsonify({"error": "sources и citations должны быть списками"}), 400

    coll, rag = initialize_database()
    if not coll or not rag:
        return jsonify({"error": "База данных недоступна"}), 500

    if not inference_server_reachable():
        return jsonify({"suggestions": []})

    try:
        suggestions = rag.suggest_followup_questions(answer, citations, sources)
    except Exception:
        logger.warning("Не удалось сгенерировать рекомендации:\n%s", traceback.format_exc())
        suggestions = []

    return jsonify({"suggestions": suggestions})


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
    if settings.API_KEY and request.path.startswith('/api/') and not request.path.startswith('/api/auth'):
        api_key = request.headers.get("X-API-Key") or request.args.get("api_key")
        admin_key = request.headers.get("X-Admin-Key") or request.args.get("admin_key")
        if request.path.startswith('/api/admin') and settings.ADMIN_API_KEY:
            if admin_key != settings.ADMIN_API_KEY:
                return jsonify({"error": "Требуется админ-доступ"}), 401
        elif api_key != settings.API_KEY and admin_key != settings.ADMIN_API_KEY:
            return jsonify({"error": "Требуется API key"}), 401
    
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
