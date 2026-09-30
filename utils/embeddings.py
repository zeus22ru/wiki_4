#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Общие функции для работы с эмбеддингами

Этот модуль содержит функции для получения эмбеддингов, поиска документов
и генерации ответов, которые используются в разных частях проекта.
"""

import json
import re
import requests
from typing import List, Dict, Optional, Iterator, Any, Union
from config import settings, get_logger
from utils.cache import get_cached_embedding, cache_embedding, invalidate_embedding_cache  # noqa: F401 (реэкспорт для create_vector_db)

logger = get_logger(__name__)


class ChatCompletionError(RuntimeError):
    """Явная ошибка генерации LLM, которую нельзя отдавать как обычный текст ответа."""

    def __init__(self, message: str, *, code: str = "generation_error"):
        super().__init__(message)
        self.code = code
        self.message = message

_THINK_BLOCK_RE = re.compile(
    r"<(?:think|redacted_thinking)\b[^>]*>[\s\S]*?</(?:think|redacted_thinking)\b[^>]*>",
    re.IGNORECASE,
)
_COT_PREFIX_MARKERS = (
    "the user is asking",
    "looking at the context",
    "let's draft",
    "i need to search",
    "i should structure",
)


def _looks_like_json_string_array(text: str) -> bool:
    """Ответ LLM с JSON-массивом строк — не обрезать по первой кириллице."""
    t = (text or "").strip()
    if not t:
        return False
    if t.startswith("[") and t.endswith("]"):
        return True
    if t.endswith("]") and ('",' in t or '",\n' in t or re.search(r'(?<!\\)"\s*,', t)):
        return True
    return False


def _chat_disable_thinking() -> bool:
    return bool(getattr(settings, "CHAT_DISABLE_THINKING", True))


_FENCE_BLOCK_RE = re.compile(r"```[\s\S]*?```", re.MULTILINE)


def _mask_code_fences(text: str) -> tuple[str, List[str]]:
    """Временно убрать fenced-блоки, чтобы CoT-обрезка не ломала ```mermaid."""
    fences: List[str] = []

    def _repl(match: re.Match) -> str:
        fences.append(match.group(0))
        return f"\n\x00FENCE{len(fences) - 1}\x00\n"

    return _FENCE_BLOCK_RE.sub(_repl, text), fences


def _unmask_code_fences(text: str, fences: List[str]) -> str:
    out = text or ""
    for idx, fence in enumerate(fences):
        out = out.replace(f"\x00FENCE{idx}\x00", fence)
    return out.strip()


def _has_cot_prefix_markers(text: str) -> bool:
    """Есть ли явный английский CoT-префикс в первых 400 символах."""
    lower_head = (text or "")[:400].lower()
    return any(marker in lower_head for marker in _COT_PREFIX_MARKERS)


def _first_cyrillic_paragraph_start(text: str) -> Optional[int]:
    """Индекс начала первого абзаца, начинающегося с кириллицы (после опц. markdown-маркеров)."""
    for match in re.finditer(
        r"(?:^|\n\n+)([#>*\-\s]*[\u0400-\u04FF])",
        text or "",
        flags=re.MULTILINE,
    ):
        # start() указывает на \n\n или начало; берём содержимое абзаца
        group_start = match.start(1)
        # откатиться к началу абзаца (после \n\n)
        para_boundary = text.rfind("\n\n", 0, group_start)
        if para_boundary >= 0:
            return para_boundary + 2
        return 0
    return None


def strip_model_reasoning(text: str) -> str:
    """
    Убрать из ответа модели блоки thinking и явный английский CoT-префикс.

    Вырезает только:
    - блоки ``<think>...</think>`` / ``<redacted_thinking>...``;
    - английский CoT-префикс (маркеры ``_COT_PREFIX_MARKERS`` в первых 400 символах)
      до первого абзаца, начинающегося с кириллицы.

    Ответ без CoT-маркеров (в т.ч. начинающийся с латиницы/цифр) возвращается без изменений.
    """
    if not text:
        return ""
    cleaned = _THINK_BLOCK_RE.sub("", text).strip()
    if not cleaned:
        return ""
    if _looks_like_json_string_array(cleaned):
        return cleaned

    masked, fences = _mask_code_fences(cleaned)

    if _has_cot_prefix_markers(masked):
        start = _first_cyrillic_paragraph_start(masked)
        if start is not None:
            return _unmask_code_fences(masked[start:].lstrip(), fences)
        # CoT есть, но кириллического абзаца нет — оставить как есть после think-блоков
        return _unmask_code_fences(masked, fences)

    return _unmask_code_fences(masked, fences)


def _prepare_chat_user_content(prompt: str) -> str:
    if not _chat_disable_thinking():
        return prompt
    if "/no_think" in prompt:
        return prompt
    return f"{prompt.rstrip()}\n\n/no_think"


def _assistant_no_think_prefill() -> str:
    """Prefill для LM Studio/Qwen3: пустой закрытый think-блок, чтобы пропустить фазу reasoning."""
    open_tag = "<" + "think" + ">"
    close_tag = "</" + "think" + ">"
    return f"{open_tag}\n{close_tag}\n\n"


ChatMessageContent = Union[str, List[Dict[str, Any]]]


def _append_no_think_to_text(text: str) -> str:
    return _prepare_chat_user_content(text)


def _prepare_multimodal_user_parts(parts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not _chat_disable_thinking():
        return parts
    out = [dict(p) for p in parts]
    for i, part in enumerate(out):
        if part.get("type") == "text":
            text = str(part.get("text") or "")
            if "/no_think" not in text:
                out[i] = {**part, "text": _append_no_think_to_text(text)}
            return out
    out.insert(0, {"type": "text", "text": "/no_think"})
    return out


def _finalize_openai_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    msgs: List[Dict[str, Any]] = []
    for item in messages:
        role = item.get("role")
        content = item.get("content")
        if role == "user" and isinstance(content, list):
            msgs.append({"role": "user", "content": _prepare_multimodal_user_parts(content)})
        elif role == "user" and isinstance(content, str):
            msgs.append({"role": "user", "content": _append_no_think_to_text(content)})
        else:
            msgs.append(dict(item))
    if _chat_disable_thinking():
        if not msgs or msgs[-1].get("role") != "assistant":
            msgs.append({"role": "assistant", "content": _assistant_no_think_prefill()})
    return msgs


def build_multimodal_user_content(
    text: str,
    image_data_urls: Optional[List[str]] = None,
) -> ChatMessageContent:
    """OpenAI-совместимый content: текст + изображения data URL."""
    parts: List[Dict[str, Any]] = []
    if (text or "").strip():
        parts.append({"type": "text", "text": text.strip()})
    for url in image_data_urls or []:
        if url:
            parts.append({"type": "image_url", "image_url": {"url": url}})
    if not parts:
        parts.append({"type": "text", "text": "Опиши вложение."})
    return parts


def _build_openai_chat_payload(
    *,
    prompt: Optional[str] = None,
    messages: Optional[List[Dict[str, Any]]] = None,
    stream: bool,
) -> dict:
    if messages is None:
        if prompt is None:
            raise ValueError("prompt or messages required")
        messages = [{"role": "user", "content": prompt}]
    payload_messages = _finalize_openai_messages(messages)
    payload = {
        "model": settings.OLLAMA_CHAT_MODEL,
        "messages": payload_messages,
        "temperature": 0.3,
        "top_p": 0.9,
        "max_tokens": settings.CHAT_MAX_TOKENS,
        "stream": stream,
    }
    if _chat_disable_thinking():
        kwargs = {"enable_thinking": False}
        payload["chat_template_kwargs"] = kwargs
        payload["extra_body"] = {"chat_template_kwargs": kwargs}
    return payload


def _vision_error_message(http_body: str = "") -> str:
    hint = (
        "Модель не приняла изображение. Для скриншотов нужна vision-модель "
        "(например qwen/qwen3.5-9b в LM Studio) и INFERENCE_BACKEND=lmstudio / CHAT_API_MODE=openai."
    )
    if http_body:
        return f"{hint} Ответ сервера: {http_body[:400]}"
    return hint


def _openai_chat_stream_request(payload: dict, timeout: int) -> Iterator[str]:
    base = settings.OLLAMA_URL.rstrip("/")
    try:
        with requests.post(
            f"{base}/v1/chat/completions",
            json=payload,
            timeout=timeout,
            headers=_embedding_headers(),
            stream=True,
        ) as response:
            response.raise_for_status()
            for line in _iter_utf8_lines(response):
                if not line or line.startswith(":"):
                    continue
                if not line.startswith("data:"):
                    continue
                data = line[5:].lstrip()
                if data.strip() == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue
                choices = obj.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                content = delta.get("content")
                if content:
                    yield content
    except requests.exceptions.HTTPError as e:
        body = e.response.text[:800] if e.response is not None else ""
        code = e.response.status_code if e.response is not None else "?"
        logger.error("HTTP ошибка chat/completions (stream): %s %s", code, body)
        if e.response is not None and e.response.status_code in (400, 422):
            raise ChatCompletionError(_vision_error_message(body), code="vision_unsupported") from e
        raise ChatCompletionError(f"Ошибка генерации ответа: HTTP {code}", code="generation_error") from e
    except requests.exceptions.Timeout as e:
        logger.error("Таймаут при генерации ответа (stream, chat/completions)")
        raise ChatCompletionError(
            "Ошибка генерации ответа: превышено время ожидания",
            code="generation_timeout",
        ) from e
    except requests.exceptions.ConnectionError as e:
        logger.error("Ошибка подключения к серверу LLM (stream, chat/completions)")
        raise ChatCompletionError(
            "Ошибка генерации ответа: не удалось подключиться к серверу LLM",
            code="generation_unavailable",
        ) from e
    except ChatCompletionError:
        raise
    except Exception as e:
        logger.error("Ошибка при потоковой генерации: %s", e)
        raise ChatCompletionError("Ошибка генерации ответа", code="generation_error") from e


def chat_completion_messages(
    messages: List[Dict[str, Any]],
    timeout: int = 120,
) -> str:
    """Полный ответ по списку messages (в т.ч. multimodal)."""
    raw = "".join(chat_completion_messages_stream(messages, timeout=timeout))
    if _chat_disable_thinking():
        return strip_model_reasoning(raw)
    return raw.strip()


def chat_completion_messages_stream(
    messages: List[Dict[str, Any]],
    timeout: int = 120,
) -> Iterator[str]:
    """Потоковая генерация по messages (OpenAI chat/completions)."""
    mode = getattr(settings, "CHAT_API_MODE", "ollama") or "ollama"
    if mode != "openai":
        raise ChatCompletionError(
            "Multimodal-чат требует CHAT_API_MODE=openai (LM Studio).",
            code="vision_unsupported",
        )
    payload = _build_openai_chat_payload(messages=messages, stream=True)
    yield from _openai_chat_stream_request(payload, timeout)


def chat_completion_messages_stream_filtered(
    messages: List[Dict[str, Any]],
    timeout: int = 120,
) -> Iterator[str]:
    return _filter_reasoning_stream(chat_completion_messages_stream(messages, timeout=timeout))


def _filter_reasoning_stream(chunks: Iterator[str]) -> Iterator[str]:
    """
    Не отдавать в UI фрагменты, которые потом исчезнут после strip_model_reasoning.

    Для английского CoT-префикса ждём первую кириллицу; иначе отдаём сразу
    (после вырезания закрытых ``<think>``-блоков).
    """
    if not _chat_disable_thinking():
        yield from chunks
        return

    buf = ""
    emitted = 0
    waiting_for_cyrillic = False
    for piece in chunks:
        if not piece:
            continue
        buf += piece

        # Закрытые think-блоки можно вырезать сразу
        cleaned = _THINK_BLOCK_RE.sub("", buf)
        if not cleaned.strip():
            continue

        if _looks_like_json_string_array(cleaned.strip()):
            public = cleaned.strip()
        elif _has_cot_prefix_markers(cleaned) or waiting_for_cyrillic:
            waiting_for_cyrillic = True
            start = _first_cyrillic_paragraph_start(cleaned)
            if start is None:
                continue
            waiting_for_cyrillic = False
            public = strip_model_reasoning(buf)
        else:
            public = strip_model_reasoning(buf)

        if len(public) <= emitted:
            continue
        delta = public[emitted:]
        emitted = len(public)
        yield delta


def _iter_utf8_lines(response: requests.Response):
    """
    Итерировать строки HTTP-потока с принудительной UTF-8 декодировкой.

    Некоторые LLM-серверы отдают stream без charset в Content-Type, и requests
    тогда может выбрать latin-1, что приводит к "Ð..." в кириллице.
    """
    for raw_line in response.iter_lines(decode_unicode=False):
        if raw_line is None:
            continue
        if isinstance(raw_line, bytes):
            yield raw_line.decode("utf-8", errors="replace")
        else:
            yield str(raw_line)


def _embedding_headers() -> dict:
    h = {"Content-Type": "application/json"}
    if getattr(settings, "OPENAI_API_KEY", ""):
        h["Authorization"] = f"Bearer {settings.OPENAI_API_KEY}"
    return h


def _parse_ollama_embedding_response(result: dict) -> List[List[float]]:
    if "embeddings" in result:
        return result["embeddings"]
    if "embedding" in result:
        return [result["embedding"]]
    return []


def _parse_openai_embedding_response(result: dict) -> List[List[float]]:
    data = result.get("data") or []
    ordered = sorted(data, key=lambda x: x.get("index", 0))
    out = []
    for item in ordered:
        emb = item.get("embedding")
        if emb:
            out.append(emb)
    return out


def _fetch_embeddings_from_api(texts: List[str]) -> List[List[float]]:
    """
    Запрос эмбеддингов к Ollama (/api/embed) или OpenAI-совместимому (/v1/embeddings).
    """
    if not texts:
        return []

    base = settings.OLLAMA_URL.rstrip("/")
    mode = getattr(settings, "EMBEDDING_API_MODE", "ollama") or "ollama"

    if mode == "openai":
        url = f"{base}/v1/embeddings"
        payload = {
            "model": settings.OLLAMA_EMBEDDING_MODEL,
            "input": texts if len(texts) > 1 else texts[0],
        }
        dims = getattr(settings, "EMBEDDING_DIMENSIONS", None)
        if dims is not None:
            payload["dimensions"] = int(dims)
        try:
            response = requests.post(
                url, json=payload, timeout=120, headers=_embedding_headers()
            )
            response.raise_for_status()
            return _parse_openai_embedding_response(response.json())
        except requests.exceptions.HTTPError as e:
            body = e.response.text[:800] if e.response is not None else ""
            logger.error(
                "Ошибка HTTP при эмбеддинге (openai %s): %s %s",
                url,
                e.response.status_code if e.response is not None else "?",
                body,
            )
            return []
        except requests.exceptions.RequestException as e:
            logger.error("Ошибка запроса эмбеддинга (openai %s): %s", url, e)
            return []

    # Ollama
    url = f"{base}/api/embed"
    dims = getattr(settings, "EMBEDDING_DIMENSIONS", None)
    # Сначала с dimensions (если заданы), затем без — совместимость со старыми серверами
    attempts: List[bool] = [True, False] if dims is not None else [False]
    for use_dimensions in attempts:
        payload: Dict[str, Any] = {"model": settings.OLLAMA_EMBEDDING_MODEL, "input": texts}
        if use_dimensions and dims is not None:
            payload["dimensions"] = int(dims)
        try:
            response = requests.post(
                url, json=payload, timeout=120, headers=_embedding_headers()
            )
            response.raise_for_status()
            parsed = _parse_ollama_embedding_response(response.json())
            if parsed:
                return parsed
        except requests.exceptions.HTTPError as e:
            if (
                use_dimensions
                and e.response is not None
                and e.response.status_code == 400
            ):
                logger.warning(
                    "Ollama /api/embed с dimensions=%s отклонён (400), повтор без dimensions",
                    dims,
                )
                continue
            body = e.response.text[:800] if e.response is not None else ""
            logger.error(
                "Ошибка HTTP при эмбеддинге (ollama %s): %s %s",
                url,
                e.response.status_code if e.response is not None else "?",
                body,
            )
            return []
        except requests.exceptions.RequestException as e:
            logger.error("Ошибка запроса эмбеддинга (ollama %s): %s", url, e)
            return []

    return []


def chat_completion(prompt: str, timeout: int = 120) -> str:
    """
    Полный ответ одним текстом. Внутри вызывается потоковый API (stream: true к Ollama
    и к OpenAI-совместимым серверам вроде LM Studio), фрагменты склеиваются здесь.
    """
    raw = "".join(chat_completion_stream(prompt, timeout=timeout))
    if _chat_disable_thinking():
        return strip_model_reasoning(raw)
    return raw.strip()


def chat_completion_stream(prompt: str, timeout: int = 120) -> Iterator[str]:
    """
    Потоковая генерация ответа (фрагменты текста).

    - CHAT_API_MODE=ollama: POST /api/generate с stream=true (NDJSON)
    - CHAT_API_MODE=openai: POST /v1/chat/completions с stream=true (SSE)
    """
    base = settings.OLLAMA_URL.rstrip("/")
    mode = getattr(settings, "CHAT_API_MODE", "ollama") or "ollama"

    if mode == "openai":
        payload = _build_openai_chat_payload(prompt=prompt, stream=True)
        yield from _openai_chat_stream_request(payload, timeout)
        return

    try:
        with requests.post(
            f"{base}/api/generate",
            json={
                "model": settings.OLLAMA_CHAT_MODEL,
                "prompt": prompt,
                "stream": True,
                "options": {
                    "temperature": 0.3,
                    "top_p": 0.9,
                    "num_predict": settings.CHAT_MAX_TOKENS,
                },
            },
            timeout=timeout,
            stream=True,
        ) as response:
            response.raise_for_status()
            for line in _iter_utf8_lines(response):
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                piece = obj.get("response")
                if piece:
                    yield piece
    except requests.exceptions.HTTPError as e:
        code = e.response.status_code if e.response is not None else "?"
        logger.error("HTTP ошибка при потоковой генерации (/api/generate): %s", code)
        raise ChatCompletionError(f"Ошибка генерации ответа: HTTP {code}", code="generation_error") from e
    except requests.exceptions.Timeout as e:
        logger.error("Таймаут при потоковой генерации (/api/generate)")
        raise ChatCompletionError(
            "Ошибка генерации ответа: превышено время ожидания",
            code="generation_timeout",
        ) from e
    except requests.exceptions.ConnectionError as e:
        logger.error("Ошибка подключения к Ollama (stream)")
        raise ChatCompletionError(
            "Ошибка генерации ответа: не удалось подключиться к Ollama",
            code="generation_unavailable",
        ) from e
    except Exception as e:
        logger.error("Ошибка при потоковой генерации: %s", e)
        if isinstance(e, ChatCompletionError):
            raise
        raise ChatCompletionError("Ошибка генерации ответа", code="generation_error") from e


def chat_completion_stream_filtered(prompt: str, timeout: int = 120) -> Iterator[str]:
    """Поток ответа с отсечением reasoning, если включён CHAT_DISABLE_THINKING."""
    return _filter_reasoning_stream(chat_completion_stream(prompt, timeout=timeout))


def get_embedding(text: str) -> List[float]:
    """
    Получить эмбеддинг текста через ollama (API v2)
    
    Args:
        text: Текст для получения эмбеддинга
        
    Returns:
        Список чисел (эмбеддинг) или пустой список при ошибке
    """
    cached = get_cached_embedding(text, settings.OLLAMA_EMBEDDING_MODEL)
    if cached is not None:
        logger.debug(f"Эмбеддинг получен из кэша для текста: {text[:50]}...")
        return cached
    
    try:
        vectors = _fetch_embeddings_from_api([text])
        if not vectors or not vectors[0]:
            return []
        embedding = vectors[0]
        cache_embedding(text, settings.OLLAMA_EMBEDDING_MODEL, embedding)
        logger.debug(f"Эмбеддинг закэширован для текста: {text[:50]}...")
        return embedding
    except Exception as e:
        logger.error(f"Ошибка при получении эмбеддинга: {e}")
        return []


def get_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """
    Получить эмбеддинги для нескольких текстов за один запрос.

    Контракт: либо полный список той же длины, либо ``[]`` при любом сбое
    (частичный результат не возвращается).
    """
    if not texts:
        return []
    
    embeddings: List[Optional[List[float]]] = [None] * len(texts)
    texts_to_fetch: List[str] = []
    indices_to_fetch: List[int] = []
    
    for i, text in enumerate(texts):
        cached = get_cached_embedding(text, settings.OLLAMA_EMBEDDING_MODEL)
        if cached is not None:
            embeddings[i] = cached
            logger.debug(f"Эмбеддинг {i} получен из кэша")
        else:
            texts_to_fetch.append(text)
            indices_to_fetch.append(i)
    
    if texts_to_fetch:
        fetched_embeddings = _fetch_embeddings_from_api(texts_to_fetch)
        if not fetched_embeddings or len(fetched_embeddings) != len(texts_to_fetch):
            logger.error(
                "Пакет эмбеддингов: ожидалось %s векторов, получено %s",
                len(texts_to_fetch),
                len(fetched_embeddings) if fetched_embeddings else 0,
            )
            return []

        for i, embedding in enumerate(fetched_embeddings):
            if not embedding:
                logger.error("Пакет эмбеддингов: пустой вектор в позиции %s", i)
                return []
            text = texts_to_fetch[i]
            index = indices_to_fetch[i]
            embeddings[index] = embedding
            cache_embedding(text, settings.OLLAMA_EMBEDDING_MODEL, embedding)
            logger.debug(f"Эмбеддинг {index} закэширован")
    
    if any(emb is None for emb in embeddings):
        return []
    return embeddings  # type: ignore[return-value]


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
            score = results['distances'][0][i] if results['distances'] else 0.0
            # Преобразуем косинусное расстояние в оценку релевантности
            # Для косинусного расстояния: 0 = идентичные векторы, 1 = противоположные
            # Ограничиваем диапазон [0, 1]
            relevance_score = max(0.0, min(1.0, 1.0 - score))
            
            documents.append({
                "text": doc,
                "score": relevance_score,
                "metadata": results['metadatas'][0][i] if results['metadatas'] else {},
                "distance": score
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

    return chat_completion(prompt, timeout=120)


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
        
        return _fetch_embeddings_from_api(list(input))


# invalidate_embedding_cache реэкспортируется из utils.cache (импорт выше)
