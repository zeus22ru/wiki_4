#!/usr/bin/env python3
"""
Flask веб-приложение для вопрос-ответной системы с RAG и цитированием
"""

from flask import Flask, render_template, request, jsonify, Response, stream_with_context
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
import chromadb
import threading
import time
import json
import traceback

# Импорт конфигурации и логирования
from config import (
    settings,
    get_logger,
    inference_server_reachable,
    inference_servers_are_split,
    fetch_remote_model_ids,
)
from config.chat_runtime import rag_chat_defaults, resolve_chat_rag_options

# Каталоги нужны до инициализации БД / RAG
settings.ensure_directories()

# Импорт RAG системы
from core.rag import (
    RAGSystem,
    RAGResult,
    classify_out_of_kb_query,
    enrich_query_from_attachments,
    ensure_attachments_inference_supported,
    fix_mermaid_block_code,
)
from core.chat_attachments import (
    AttachmentBundle,
    ChatAttachmentError,
    attachments_enabled,
    load_attachments,
    user_message_display_text,
)
from core.chat_history import get_chat_history
from utils.embeddings import ChatCompletionError

# Импорт маршрутов
from api.routes.chat import chat_bp
from api.routes.documents import documents_bp
from api.routes.admin import admin_bp
from api.routes.auth import auth_bp
from api.routes.chat_attachments import chat_attachments_bp
from api.routes.issues import issues_bp
from api.routes.telegram import telegram_bp
from api.middleware.auth import can_access_chat, current_user_id, remember_guest_chat
from api.middleware.internal_auth import is_trusted_internal_request

# Получаем логгер для этого модуля
logger = get_logger(__name__)

_SENSITIVE_BODY_KEYS = frozenset({
    "password", "password_hash", "token", "secret", "init_data", "code",
})

_CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com "
    "https://telegram.org https://*.telegram.org; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com "
    "https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
    "img-src 'self' data: blob: https:; "
    "connect-src 'self' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://telegram.org; "
    "frame-ancestors 'self' https://web.telegram.org https://*.telegram.org; "
    "base-uri 'self'; "
    "form-action 'self'"
)


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
            "section_path": s.get("section_path", ""),
            "chunk_kind": s.get("chunk_kind", ""),
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
        "images": list(getattr(rag_result, "images", None) or []),
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


def _parse_attachment_ids(data: dict) -> list:
    raw = data.get("attachment_ids") if isinstance(data, dict) else None
    if raw is None:
        return []
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _load_chat_attachment_bundle(attachment_ids: list) -> AttachmentBundle | None:
    if not attachment_ids:
        return None
    if not attachments_enabled():
        raise ChatAttachmentError("Вложения к чату отключены")
    bundle = load_attachments(attachment_ids)
    ensure_attachments_inference_supported(bundle)
    return bundle


def _require_string_field(data: dict, field: str, *, allow_empty: bool = False):
    """Вернуть строку поля или (None, error_response) при неверном типе."""
    if field not in data:
        return ("" if allow_empty else None), None
    value = data.get(field)
    if value is None and allow_empty:
        return "", None
    if not isinstance(value, str):
        return None, (jsonify({"error": f"Поле {field} должно быть строкой"}), 400)
    return value, None


def _normalize_chat_query(data: dict):
    if not data:
        logger.warning("Получен пустой запрос чата")
        return None, (jsonify({"error": "Не указано сообщение"}), 400)

    attachment_ids = _parse_attachment_ids(data)
    if "message" in data and data.get("message") is None:
        logger.warning("Некорректный тип сообщения: NoneType")
        return None, (jsonify({"error": "Сообщение должно быть строкой"}), 400)

    raw_message = data.get("message", "")
    if not isinstance(raw_message, str):
        logger.warning("Некорректный тип сообщения: %s", type(raw_message).__name__)
        return None, (jsonify({"error": "Сообщение должно быть строкой"}), 400)

    query = raw_message.strip()
    has_attachments = bool(attachment_ids)
    max_chars = int(getattr(settings, "CHAT_MESSAGE_MAX_CHARS", 1000) or 1000)

    if not query and not has_attachments:
        logger.warning("Получено пустое сообщение без вложений")
        return None, (jsonify({"error": "Введите сообщение или прикрепите файл"}), 400)
    if query and len(query) < 3 and not has_attachments:
        logger.warning(f"Слишком короткий запрос: {len(query)} символов")
        return None, (jsonify({"error": "Слишком короткий запрос. Минимальная длина: 3 символа"}), 400)
    if len(query) > max_chars:
        logger.warning(f"Слишком длинный запрос: {len(query)} символов")
        return None, (
            jsonify({"error": f"Слишком длинный запрос. Максимальная длина: {max_chars} символов"}),
            400,
        )

    return {"query": query, "attachment_ids": attachment_ids}, None


def _chat_options(data: dict) -> dict:
    return resolve_chat_rag_options(data)


class ChatNotFoundError(Exception):
    """Запрошенный чат отсутствует."""


def _trusted_telegram_user_id(data: dict):
    """telegram_user_id из тела только для доверенного внутреннего запроса."""
    if not is_trusted_internal_request():
        return None
    return data.get("telegram_user_id") if isinstance(data, dict) else None


def _telegram_linked_user_id(chat_history, telegram_user_id) -> int | None:
    """user_id wiki_4, привязанный к telegram_user_id, или None."""
    try:
        tg_user_id_int = int(telegram_user_id)
    except (TypeError, ValueError):
        return None
    link = chat_history.get_telegram_link(tg_user_id_int)
    if not link or not link.get("user_id"):
        return None
    return link["user_id"]


def _can_access_chat_for_request(chat_history, chat_session, data: dict) -> bool:
    """Проверка доступа: веб-сессия, гостевые cookie или доверенная Telegram-привязка."""
    if can_access_chat(chat_session):
        return True
    if current_user_id():
        return False
    tg_user_id = _trusted_telegram_user_id(data)
    linked_user_id = _telegram_linked_user_id(chat_history, tg_user_id)
    return linked_user_id is not None and chat_session.user_id == linked_user_id


def _resolve_chat_session(data: dict, query: str, attachments: AttachmentBundle | None = None):
    chat_history = get_chat_history()
    raw_chat_id = data.get("chat_id")
    chat_id = _int_or_none(raw_chat_id)
    tg_user_id = _trusted_telegram_user_id(data)

    if raw_chat_id not in (None, ""):
        if chat_id is None or chat_id <= 0:
            raise ValueError("Некорректный chat_id")
        chat_session = chat_history.get_session(chat_id)
        if not chat_session:
            raise ChatNotFoundError("Чат не найден")
        if not _can_access_chat_for_request(chat_history, chat_session, data):
            linked_user_id = _telegram_linked_user_id(chat_history, tg_user_id)
            if (
                linked_user_id is not None
                and not current_user_id()
                and chat_session.user_id is None
            ):
                title_source = query or user_message_display_text(query, attachments)
                title = (title_source[:60] + "...") if len(title_source) > 60 else title_source
                session = chat_history.create_session(
                    user_id=linked_user_id, title=title or "Новый чат"
                )
                return chat_history, session.id
            raise PermissionError("Нет доступа к чату")
        return chat_history, chat_id

    # Telegram-идентификация только для доверенного внутреннего запроса
    if tg_user_id is not None and not current_user_id():
        try:
            tg_user_id_int = int(tg_user_id)
            link = chat_history.get_telegram_link(tg_user_id_int)
            if link and link.get("user_id"):
                title_source = query or user_message_display_text(query, attachments)
                title = (title_source[:60] + "...") if len(title_source) > 60 else title_source
                session = chat_history.create_session(
                    user_id=link["user_id"], title=title or "Новый чат"
                )
                return chat_history, session.id
        except (TypeError, ValueError):
            pass

    title_source = query or user_message_display_text(query, attachments)
    title = (title_source[:60] + "...") if len(title_source) > 60 else title_source
    session = chat_history.create_session(user_id=current_user_id(), title=title or "Новый чат")
    if session.user_id is None:
        remember_guest_chat(session.id)
    return chat_history, session.id


def _conversation_history_for_rag(chat_history, chat_id: int, limit: int | None = None) -> list[dict]:
    """Последние сообщения текущего чата для понимания уточняющих вопросов."""
    if limit is None:
        limit = max(2, int(settings.RAG_QUERY_EXPANSION_MAX_MESSAGES))
    # Берём с запасом, чтобы после фильтра failed осталось достаточно контекста
    recent = chat_history.get_recent_messages(chat_id, limit=limit * 2)
    history: list[dict] = []
    for msg in recent:
        if msg.role not in {"user", "assistant"} or not msg.content:
            continue
        meta = msg.metadata if isinstance(msg.metadata, dict) else {}
        if meta.get("failed"):
            continue
        history.append({"role": msg.role, "content": msg.content})
    return history[-limit:]


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


def _mark_user_message_failed(chat_history, message_id: int | None, code: str) -> None:
    """Пометить user-сообщение как failed (контракт B: mark_message_failed)."""
    if message_id is None:
        return
    marker = getattr(chat_history, "mark_message_failed", None)
    if callable(marker):
        try:
            marker(message_id, code)
            return
        except Exception:
            logger.warning("mark_message_failed не удался для message_id=%s", message_id)
    updater = getattr(chat_history, "update_message_metadata", None)
    if callable(updater):
        try:
            updater(message_id, {"failed": True, "error": code})
        except Exception:
            logger.warning("update_message_metadata не удался для message_id=%s", message_id)


def _sse_event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _chat_error_payload(
    code: str,
    message: str,
    *,
    chat_id: int | None = None,
    diagnostics: dict | None = None,
) -> dict:
    payload = {"error": message, "message": message, "code": code}
    if chat_id is not None:
        payload["chat_id"] = chat_id
    if diagnostics:
        payload["diagnostics"] = diagnostics
    return payload


def _mask_request_body(body: dict) -> dict:
    """Скопировать dict тела запроса с маскировкой секретов."""
    safe = {}
    for key, value in body.items():
        if str(key).lower() in _SENSITIVE_BODY_KEYS:
            safe[key] = "***"
        else:
            safe[key] = value
    return safe


def _prepare_chat_request(data: dict):
    """
    Общая подготовка /api/chat и /api/chat/stream.

    Returns:
        (ctx, error_response) — ctx dict или None при ошибке.
    """
    normalized, error_response = _normalize_chat_query(data)
    if error_response:
        return None, error_response

    query = normalized["query"]
    attachment_ids = normalized["attachment_ids"]
    options = _chat_options(data)

    coll, rag = initialize_database()
    if not coll or not rag:
        logger.error("База данных или RAG система недоступна")
        return None, (jsonify({"error": "База данных недоступна"}), 500)

    if not inference_server_reachable():
        logger.error("Сервер LLM недоступен по OLLAMA_URL (ожидается /api/tags или /v1/models)")
        return None, (
            jsonify({
                "error": "Сервер LLM недоступен. Проверьте OLLAMA_URL и запуск Ollama или LM Studio.",
            }),
            500,
        )

    try:
        attachment_bundle = _load_chat_attachment_bundle(attachment_ids)
    except ChatAttachmentError as e:
        return None, (jsonify({"error": str(e)}), 400)

    try:
        chat_history, chat_id = _resolve_chat_session(data, query, attachment_bundle)
    except ValueError:
        return None, (jsonify({"error": "Некорректный chat_id"}), 400)
    except ChatNotFoundError:
        return None, (jsonify({"error": "Чат не найден"}), 404)
    except PermissionError:
        return None, (jsonify({"error": "Нет доступа к чату"}), 403)

    conversation_history = _conversation_history_for_rag(chat_history, chat_id)
    user_metadata = {"answer_mode": options["answer_mode"]}
    if attachment_bundle and attachment_bundle.items:
        user_metadata["attachments"] = attachment_bundle.metadata_list()
    user_message = chat_history.add_message(
        session_id=chat_id,
        role="user",
        content=user_message_display_text(query, attachment_bundle),
        metadata=user_metadata,
    )

    return {
        "query": query,
        "attachment_ids": attachment_ids,
        "options": options,
        "coll": coll,
        "rag": rag,
        "attachment_bundle": attachment_bundle,
        "chat_history": chat_history,
        "chat_id": chat_id,
        "conversation_history": conversation_history,
        "user_message_id": user_message.id,
    }, None


app = Flask(__name__)
app.secret_key = settings.SECRET_KEY
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    MAX_CONTENT_LENGTH=settings.MAX_FILE_SIZE,
)

if getattr(settings, "TRUST_PROXY", False):
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

_cors = (settings.CORS_ORIGINS or "").strip()
if _cors == "*":
    CORS(app, supports_credentials=False)
elif _cors:
    _origin_list = [o.strip() for o in _cors.split(",") if o.strip()]
    if _origin_list:
        CORS(app, origins=_origin_list, supports_credentials=False)

app.register_blueprint(chat_bp)
app.register_blueprint(documents_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(chat_attachments_bp)
app.register_blueprint(issues_bp)
app.register_blueprint(telegram_bp)

# K2: хук сброса RAG после переиндексации (поток A регистрирует set_reindex_callback)
# Глобальные переменные объявлены ниже; reset_rag_state регистрируется после определения.


# Глобальные переменные для подключения к базе данных
collection = None
rag_system = None
db_initialized = False
init_lock = threading.Lock()


def reset_rag_state() -> None:
    """Сбросить долгоживущее состояние RAG после успешной переиндексации."""
    global collection, rag_system, db_initialized
    with init_lock:
        collection = None
        rag_system = None
        db_initialized = False
        try:
            from core.retrieval import invalidate_bm25_cache
            invalidate_bm25_cache()
        except Exception:
            logger.warning("Не удалось инвалидировать BM25-кэш при сбросе RAG")


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


try:
    from api.routes import documents as documents_module
    set_cb = getattr(documents_module, "set_reindex_callback", None)
    if callable(set_cb):
        set_cb(reset_rag_state)
except Exception:
    logger.debug("set_reindex_callback недоступен — хук переиндексации не зарегистрирован")

if not settings.FLASK_DEBUG:
    settings.validate()
    # После возможной генерации SECRET_KEY обновить Flask
    app.secret_key = settings.SECRET_KEY


@app.route('/')
def index():
    """Главная страница"""
    defaults = rag_chat_defaults()
    return render_template(
        'index.html',
        rag_top_k=defaults["top_k"],
        rag_min_score=defaults["min_score"],
    )


@app.route('/telegram-app')
def telegram_mini_app():
    """Мобильный интерфейс БочкарИИ, запускаемый внутри Telegram."""
    return render_template(
        'telegram_app.html',
        telegram_bot_username=settings.TELEGRAM_BOT_USERNAME,
    )


@app.route('/api/rag/defaults', methods=['GET'])
def rag_defaults():
    """Публичные дефолты RAG для панели чата (синхронизация с runtime-настройками)."""
    return jsonify(rag_chat_defaults())


@app.route('/api/health', methods=['GET'])
def health_check():
    """Проверка здоровья системы"""
    ollama_status = inference_server_reachable()
    logger.debug(f"Сервер инференса (Ollama/LM Studio) доступен: {ollama_status}")

    coll, rag = initialize_database()
    db_status = coll is not None
    rag_status = rag is not None
    logger.debug(f"База данных статус: {db_status}, RAG статус: {rag_status}")

    if ollama_status and db_status and rag_status:
        status = "ok"
    elif db_status:
        status = "degraded"
    else:
        status = "error"

    return jsonify({
        "ollama": ollama_status,
        "database": db_status,
        "rag": rag_status,
        "status": status,
    })


@app.route('/api/chat', methods=['POST'])
def chat():
    """Обработка запроса чата с использованием RAG системы"""
    data = _get_json_body()
    ctx, error_response = _prepare_chat_request(data)
    if error_response:
        return error_response

    query = ctx["query"]
    options = ctx["options"]
    rag = ctx["rag"]
    attachment_bundle = ctx["attachment_bundle"]
    chat_history = ctx["chat_history"]
    chat_id = ctx["chat_id"]
    conversation_history = ctx["conversation_history"]
    user_message_id = ctx["user_message_id"]

    logger.info(f"Запрос чата: '{query[:100]}...' (вложений: {len(ctx['attachment_ids'])})")
    logger.info(f"Выполнение RAG запроса: '{query}'")

    try:
        started = time.time()
        try:
            rag_result = rag.query(
                query,
                top_k=options["top_k"],
                min_score=options["min_score"],
                max_citations=settings.RAG_MAX_CITATIONS,
                answer_mode=options["answer_mode"],
                conversation_history=conversation_history,
                attachments=attachment_bundle,
            )
        except ChatCompletionError as e:
            logger.error("Ошибка генерации LLM для чата %s: %s", chat_id, e)
            _mark_user_message_failed(chat_history, user_message_id, e.code)
            return jsonify(_chat_error_payload(e.code, e.message, chat_id=chat_id)), 500
        latency_ms = int((time.time() - started) * 1000)
        logger.info(f"Сгенерирован ответ длиной {len(rag_result.answer)} символов")
        logger.info(f"Извлечено {len(rag_result.citations)} цитат")
    except Exception:
        logger.error("Ошибка при выполнении RAG запроса:\n%s", traceback.format_exc())
        _mark_user_message_failed(chat_history, user_message_id, "internal_error")
        return jsonify({"error": "Ошибка при обработке запроса. Подробности в журнале сервера."}), 500

    if rag_result.retrieve_error == "embedding_unavailable":
        logger.error(
            "Эмбеддинг запроса не получен — в Chroma есть векторы, но поиск без эмбеддинга вопроса невозможен"
        )
        _mark_user_message_failed(chat_history, user_message_id, "embedding_unavailable")
        return jsonify(_chat_error_payload(
            "embedding_unavailable",
            rag_result.answer,
            chat_id=chat_id,
            diagnostics=rag_result.diagnostics or {},
        )), 500

    if rag_result.retrieve_error == "search_error":
        logger.error("Ошибка Chroma при поиске")
        _mark_user_message_failed(chat_history, user_message_id, "search_error")
        return jsonify(_chat_error_payload(
            "search_error",
            "Ошибка поиска в векторной базе",
            chat_id=chat_id,
            diagnostics=rag_result.diagnostics or {},
        )), 500

    payload = _rag_result_to_api_dict(rag_result)
    payload["chat_id"] = chat_id
    expansion = (payload.get("diagnostics") or {}).get("expansion") or {}
    assistant_message = chat_history.add_message(
        session_id=chat_id,
        role="assistant",
        content=payload["answer"],
        sources=payload["sources"],
        citations=payload["citations"],
        metadata={
            "model_name": settings.OLLAMA_CHAT_MODEL,
            "rag_settings_snapshot": {
                "top_k": options["top_k"],
                "min_score": options["min_score"],
                "answer_mode": options["answer_mode"],
            },
            "latency_ms": latency_ms,
            "diagnostics": payload.get("diagnostics", {}),
            "images": payload.get("images", []),
        },
        retrieval_query_text=expansion.get("rewritten"),
    )
    _maybe_update_chat_title(chat_history, chat_id, query)
    payload["message_id"] = assistant_message.id
    logger.debug(f"Источники: {[s['title'] for s in payload['sources']]}")
    return jsonify(payload)


@app.route('/api/chat/stream', methods=['POST'])
def chat_stream():
    """RAG-чат с потоковой передачей текста (SSE). Итоговые sources/citations — в событии type=done."""
    data = _get_json_body()
    ctx, error_response = _prepare_chat_request(data)
    if error_response:
        return error_response

    query = ctx["query"]
    options = ctx["options"]
    rag = ctx["rag"]
    attachment_bundle = ctx["attachment_bundle"]
    chat_history = ctx["chat_history"]
    chat_id = ctx["chat_id"]
    conversation_history = ctx["conversation_history"]
    user_message_id = ctx["user_message_id"]
    has_attachments = bool(attachment_bundle and attachment_bundle.items)

    try:
        attachment_enrichment = enrich_query_from_attachments(query, attachment_bundle)
    except ChatCompletionError as e:
        _mark_user_message_failed(chat_history, user_message_id, e.code)
        return jsonify(_chat_error_payload(e.code, e.message, chat_id=chat_id)), 500
    search_query = attachment_enrichment.get("search_query") or query

    stream_headers = {
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
        "Content-Type": "text/event-stream; charset=utf-8",
    }

    def generate():
        # Комментарий SSE: первые байты уходят клиенту до первого токена LLM (лучше для прокси/буферов).
        yield ": stream-open\n\n"
        started = time.time()
        try:
            skip_kind = classify_out_of_kb_query(query, has_attachments=has_attachments)
            if skip_kind:
                yield _sse_event({"type": "status", "message": "Формирую ответ..."})
                for evt in rag.stream_chitchat_answer(query, conversation_history, kind=skip_kind):
                    if evt.get("type") == "delta":
                        yield _sse_event({"type": "delta", "text": evt.get("text", "")})
                    elif evt.get("type") == "done":
                        rag_result = evt.get("rag_result")
                        if rag_result is None:
                            yield _sse_event({"type": "error", "message": "Пустой результат"})
                            return
                        payload = _rag_result_to_api_dict(rag_result)
                        diag = dict(payload.get("diagnostics") or {})
                        diag["latency_ms"] = int((time.time() - started) * 1000)
                        payload["diagnostics"] = diag
                        assistant_message = chat_history.add_message(
                            session_id=chat_id,
                            role="assistant",
                            content=payload["answer"],
                            metadata={"retrieval_status": skip_kind},
                        )
                        _maybe_update_chat_title(chat_history, chat_id, query)
                        yield _sse_event({
                            "type": "done",
                            "chat_id": chat_id,
                            "message_id": assistant_message.id,
                            **payload,
                        })
                return

            yield _sse_event({"type": "status", "message": "Ищу релевантные документы..."})
            documents, retrieve_error, expansion, retrieve_diag = rag.retrieve_documents_auto(
                search_query, options["top_k"], options["min_score"], conversation_history
            )
            retrieval_query = expansion.get("rewritten") or search_query

            if retrieve_error == "embedding_unavailable":
                _mark_user_message_failed(chat_history, user_message_id, "embedding_unavailable")
                yield _sse_event({
                    "type": "error",
                    **_chat_error_payload(
                        "embedding_unavailable",
                        (
                            "Поиск по базе не выполнен: не удалось получить эмбеддинг для вашего вопроса. "
                            "Индекс в Chroma уже заполнен, но для каждого запроса нужна работающая модель эмбеддингов "
                            "(например, загрузите модель в LM Studio и проверьте OLLAMA_EMBEDDING_MODEL и INFERENCE_BACKEND=lmstudio)."
                        ),
                        chat_id=chat_id,
                        diagnostics={
                            "retrieval_status": "embedding_unavailable",
                            "retrieval": retrieve_diag,
                            "expansion": expansion,
                        },
                    ),
                })
                return

            if retrieve_error == "search_error":
                _mark_user_message_failed(chat_history, user_message_id, "search_error")
                yield _sse_event({
                    "type": "error",
                    **_chat_error_payload(
                        "search_error",
                        "Ошибка поиска в векторной базе",
                        chat_id=chat_id,
                        diagnostics={
                            "retrieval_status": "search_error",
                            "retrieval": retrieve_diag,
                            "expansion": expansion,
                        },
                    ),
                })
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
                attachments=attachment_bundle,
                attachment_enrichment=attachment_enrichment,
            ):
                if evt.get("type") == "delta":
                    yield _sse_event({"type": "delta", "text": evt.get("text", "")})
                elif evt.get("type") == "done":
                    rag_result = evt.get("rag_result")
                    if rag_result is None:
                        yield _sse_event({"type": "error", "message": "Пустой результат RAG"})
                        return
                    payload = _rag_result_to_api_dict(rag_result)
                    diag = dict(payload.get("diagnostics") or {})
                    diag["retrieval"] = retrieve_diag
                    diag["expansion"] = {
                        "rewritten": expansion.get("rewritten"),
                        "dense_queries": expansion.get("dense_queries"),
                        "hyde_used": bool(expansion.get("hyde_snippet")),
                        "multi_variants": expansion.get("multi_variants"),
                    }
                    diag["attachments"] = {
                        "count": attachment_enrichment.get("attachment_count", 0),
                        "kinds": attachment_enrichment.get("kinds", []),
                        "enrichment_ms": attachment_enrichment.get("enrichment_ms", 0),
                    }
                    payload["diagnostics"] = diag
                    assistant_message = chat_history.add_message(
                        session_id=chat_id,
                        role="assistant",
                        content=payload["answer"],
                        sources=payload["sources"],
                        citations=payload["citations"],
                        metadata={
                            "model_name": settings.OLLAMA_CHAT_MODEL,
                            "rag_settings_snapshot": {
                                "top_k": options["top_k"],
                                "min_score": options["min_score"],
                                "answer_mode": options["answer_mode"],
                            },
                            "latency_ms": int((time.time() - started) * 1000),
                            "diagnostics": payload.get("diagnostics", {}),
                            "images": payload.get("images", []),
                        },
                        retrieval_query_text=expansion.get("rewritten"),
                    )
                    _maybe_update_chat_title(chat_history, chat_id, query)
                    yield _sse_event({
                        "type": "done",
                        "chat_id": chat_id,
                        "message_id": assistant_message.id,
                        **payload,
                    })
        except ChatCompletionError as e:
            logger.error("Ошибка генерации LLM в потоке для чата %s: %s", chat_id, e)
            _mark_user_message_failed(chat_history, user_message_id, e.code)
            yield _sse_event({
                "type": "error",
                **_chat_error_payload(e.code, e.message, chat_id=chat_id),
            })
        except Exception:
            logger.error("Ошибка в потоке /api/chat/stream:\n%s", traceback.format_exc())
            _mark_user_message_failed(chat_history, user_message_id, "internal_error")
            yield _sse_event({
                "type": "error",
                "message": "Ошибка при обработке запроса. Подробности в журнале сервера.",
            })

    return Response(stream_with_context(generate()), headers=stream_headers)


@app.route('/api/mermaid/fix', methods=['POST'])
def mermaid_fix():
    """Починить синтаксис одного блока Mermaid (fallback после ошибки рендера в браузере)."""
    data = _get_json_body()
    code, err = _require_string_field(data, "code")
    if err:
        return err
    parse_error, err = _require_string_field(data, "parse_error", allow_empty=True)
    if err:
        return err
    code = (code or "").strip()
    parse_error = (parse_error or "").strip()
    if not code:
        return jsonify({"error": "Не указан code"}), 400
    if len(code) > 12000:
        return jsonify({"error": "Слишком длинный блок Mermaid"}), 400

    if not inference_server_reachable():
        fixed = fix_mermaid_block_code(code, parse_error=parse_error)
        return jsonify({
            "code": fixed,
            "changed": fixed != code,
            "llm_used": False,
        })

    fixed = fix_mermaid_block_code(code, parse_error=parse_error)
    return jsonify({
        "code": fixed,
        "changed": fixed != code,
        "llm_used": bool(getattr(settings, "MERMAID_AUTOFIX_ENABLED", True)),
    })


@app.route('/api/chat/verify', methods=['POST'])
def verify_chat_answer():
    """Проверить ответ ассистента по сохраненным цитатам."""
    data = _get_json_body()
    answer, err = _require_string_field(data, "answer")
    if err:
        return err
    answer = (answer or "").strip()
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
def suggest_chat_questions():
    """Сгенерировать уточняющие вопросы к готовому ответу."""
    data = _get_json_body()
    answer, err = _require_string_field(data, "answer", allow_empty=True)
    if err:
        return err
    answer = (answer or "").strip()
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
    """
    Список моделей с сервера инференса (/api/tags или /v1/models).

    При раздельных провайдерах ``models`` — объединение, а ``chat_models`` и
    ``embedding_models`` содержат списки соответствующих серверов.
    """
    logger.info("Запрос списка моделей с сервера инференса")
    try:
        if inference_servers_are_split():
            chat_models = fetch_remote_model_ids(role="chat")
            embedding_models = fetch_remote_model_ids(role="embedding")
            models = list(dict.fromkeys(chat_models + embedding_models))
        else:
            models = fetch_remote_model_ids()
            chat_models = models
            embedding_models = models
        logger.info(f"Найдено {len(models)} моделей")
        return jsonify({
            "models": models,
            "chat_models": chat_models,
            "embedding_models": embedding_models,
        })
    except Exception:
        logger.error("Ошибка при получении списка моделей:\n%s", traceback.format_exc())
        return jsonify({"error": "Не удалось получить список моделей."}), 500


@app.before_request
def log_request_info():
    """Логирование входящих запросов и опциональная проверка API key."""
    if request.path.startswith('/static'):
        return
    internal_telegram_path = request.path in {
        '/api/telegram/verify',
        '/api/telegram/resolve',
    }
    if (
        settings.API_KEY
        and request.path.startswith('/api/')
        and not request.path.startswith('/api/auth')
        and not request.path.startswith('/api/issues')
        and request.path != '/api/telegram/webapp/auth'
        and (internal_telegram_path or not current_user_id())
    ):
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

    # Не логируем тела /api/auth/* и /api/telegram/*
    if request.path.startswith('/api/auth') or request.path.startswith('/api/telegram'):
        return
    if request.method in ['POST', 'PUT'] and request.is_json:
        try:
            body = request.get_json(silent=True)
            if isinstance(body, dict):
                safe = _mask_request_body(body)
                body_str = str(safe)[:200]
                logger.debug("Request body: %s...", body_str)
        except Exception:
            pass


@app.after_request
def after_request_hooks(response):
    """Логирование ответа и заголовки безопасности."""
    if request.path.startswith('/static'):
        return response

    logger.info(
        f"Response: {response.status_code} | "
        f"Path: {request.path}"
    )

    if getattr(settings, "SECURITY_HEADERS_ENABLED", True):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        # Telegram Mini App открывается во встроенном WebView — без X-Frame-Options
        if request.path != "/telegram-app":
            response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Content-Security-Policy", _CSP_POLICY)

    return response


if __name__ == '__main__':
    settings.ensure_directories()
    # Инициализируем базу данных при запуске
    logger.info("Запуск Flask приложения")
    logger.info(f"OLLAMA_URL: {settings.OLLAMA_URL}")
    backend = settings.INFERENCE_BACKEND or "(по EMBEDDING_API_MODE/CHAT_API_MODE)"
    logger.info(f"INFERENCE_BACKEND: {backend}")
    logger.info(
        f"API: эмбеддинги={settings.EMBEDDING_API_MODE}, чат={settings.CHAT_API_MODE} "
        f"(openai -> /v1/embeddings + /v1/chat/completions; ollama -> /api/embed + /api/generate)"
    )
    logger.info(f"Модель эмбеддингов: {settings.OLLAMA_EMBEDDING_MODEL}")
    logger.info(f"Модель чата: {settings.OLLAMA_CHAT_MODEL}")
    logger.info(f"Хост: {settings.API_HOST}, Порт: {settings.API_PORT}")

    initialize_database()
    app.run(host=settings.API_HOST, port=settings.API_PORT, debug=settings.FLASK_DEBUG)
