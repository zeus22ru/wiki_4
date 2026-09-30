# План исправления по результатам аудита (2026-09-30)

Источник: анализ кодовой базы от 2026-09-30. Старый `CODE_AUDIT.md` (июнь 2026) устарел: пункты про параллельный reindex, `CHUNK_OVERLAP >= CHUNK_SIZE`, нестроковый `message`, clamp `top_k`, BM25-fallback и stream-тест уже исправлены.

## 0. Общие правила для всех потоков

1. Работать только в **своих файлах** (раздел «Владение файлами» у потока). Если нужна правка чужого файла, не править, а описать в финальном отчёте (файл, строка, что и зачем).
2. Единственные допустимые пересечения между потоками описаны в разделе «Контракты». Имена и сигнатуры из контрактов менять нельзя.
3. Не делать `git commit`, `git push`, `git stash`, `git checkout`, `git reset`. Не удалять отслеживаемые git файлы, кроме явно указанных в потоке.
4. Каждое исправление сопровождать тестом (pytest), который падает до исправления и проходит после. Тесты класть в `tests/` рядом с существующими по теме.
5. Стиль: русские комментарии и docstring, как в проекте. Без эмодзи. Не добавлять новые зависимости без необходимости, а если добавляете, писать в отчёт.
6. Не создавать новые `.md` файлы, кроме явно указанных.
7. Тесты запускать так (интерпретатор Python 3.12 с зависимостями уже есть в `/tmp/wv12`, без `torch`; если его нет, создать через `uv venv --python 3.12 /tmp/wv12` и поставить `requirements.txt` без `sentence-transformers`):

```bash
WT=/tmp/wt_<имя_потока>; mkdir -p $WT
cd /Users/zeus/project/wiki_4
env PYTHONDONTWRITEBYTECODE=1 DATABASE_PATH=$WT/d/db.sqlite DATA_DIR=$WT/d UPLOAD_DIR=$WT/d/up \
  CHROMA_PERSIST_DIR=$WT/chroma LOG_DIR=$WT/logs CACHE_DIR=$WT/cache CHAT_ATTACHMENTS_DIR=$WT/d/chat_attachments \
  TELEGRAM_OFFSET_PATH=$WT/d/tg.json BITRIX24_EVENT_OFFSET_PATH=$WT/d/bx.json SETTINGS_OVERRIDES_PATH=$WT/d/ov.json \
  /tmp/wv12/bin/python -m pytest -q -p no:cacheprovider --ignore=tests/e2e <нужные тесты>
```

Так тесты не создают `cache/`, `chroma_db/`, `data/`, `logs/` в репозитории. Если они всё же появились (их не было до работы), удалить в конце. Не оставлять `__pycache__` вне `.gitignore`-путей.
8. Известный тест, падающий из-за окружения: `tests/test_retrieval_embed_batch.py::test_rerank_cross_encoder_caps_text` (нет `sentence-transformers`). Поток D делает его независимым от окружения.
9. Финальный отчёт потока: список сделанных пунктов (ID), изменённые файлы, добавленные тесты, результат запуска тестов своей области, что не сделано и почему, замечания для других потоков. Кратко, без воды.

## 1. Потоки и владение файлами

| Поток | Тема | Файлы, которыми владеет |
|---|---|---|
| A | Загрузки, вложения, документы | `api/routes/documents.py`, `core/chat_attachments.py`, `api/routes/chat_attachments.py`, новый `utils/filenames.py`, `tests/test_chat_attachments.py`, `tests/test_documents_reindex.py`, новый `tests/test_filenames.py` |
| I | Индексатор | `create_vector_db.py`, `core/index_manifest.py`, `core/chunking.py`, `tests/test_index_manifest.py`, `tests/test_chunking_settings.py`, `tests/test_documents_reindex.py` (только тесты индексатора, не пересекаясь с A: в A остаются только тесты роутов) |
| B | Идентичность и доступ: Telegram, auth, issues, боты | `core/chat_history.py`, `models/chat.py`, `api/routes/telegram.py`, `api/routes/auth.py`, `api/middleware/auth.py`, новый `api/middleware/internal_auth.py`, `api/routes/issues.py`, `utils/issue_rate_limit.py`, `scripts/telegram_bot_worker.py`, `scripts/bitrix24_bot_worker.py`, `config/chat_runtime.py`, `tests/test_auth.py`, `tests/test_telegram_integration.py`, `tests/test_telegram_webapp.py`, `tests/test_bitrix24_integration.py`, `tests/test_issues.py`, `tests/test_chat_history.py`, `tests/test_chat_runtime.py` |
| C | Веб-приложение и конфигурация | `web_app.py`, `api/routes/chat.py`, `api/routes/admin.py`, `config/settings.py`, `config/runtime_overrides.py`, `config/settings_catalog.py`, `config/validation.py`, `config/logging_config.py`, `.env.example`, `tests/test_web_app.py`, `tests/test_product_features.py`, `tests/conftest.py` |
| D | LLM и RAG-ядро | `utils/embeddings.py`, `utils/cache.py`, `core/rag.py`, `core/retrieval.py`, `core/html_text.py`, `tests/test_rag_*.py`, `tests/test_retrieval_embed_batch.py`, `tests/test_chat_reasoning.py`, `tests/test_inference_reachable_cache.py`, `tests/test_mermaid_fix.py`, `tests/test_merge_mermaid_raw.py`, `tests/test_html_strikethrough.py` |
| E | Фронтенд, зависимости, чистка | `templates/*`, `static/*`, `requirements.txt`, новый `requirements-rerank.txt`, `requirements-dev.txt`, `README.md`, `CODE_AUDIT.md`, `api/middleware/validation.py`, `api/middleware/__init__.py`, `utils/validators.py`, `utils/__init__.py`, `qa_system.py`, `core/__init__.py`, `scripts/*` (кроме двух bot-воркеров), `tests/test_frontend_contract.py`, `tests/test_scripts_smoke.py` |

## 2. Контракты между потоками

**K1. Внутренний ключ Telegram (B создаёт, C использует).**
Файл `api/middleware/internal_auth.py`, функция:

```python
def is_trusted_internal_request() -> bool:
    """True, если заголовок X-API-Key совпадает (hmac.compare_digest) с settings.TELEGRAM_INTERNAL_API_KEY
    и этот ключ непустой. Пустой ключ никогда не считается доверенным."""
```

C в `web_app.py` принимает поле `telegram_user_id` из тела `/api/chat` и `/api/chat/stream` только если `is_trusted_internal_request()` истинно. Иначе поле игнорируется (запрос обрабатывается как гостевой/веб-сессия). Пока файла нет, C импортирует функцию внутри `try/except ImportError` с заглушкой, возвращающей `False`, и убирает заглушку, когда файл появится.

**K2. Хук переиндексации (A создаёт, C использует).**
В `api/routes/documents.py`:

```python
def set_reindex_callback(callback: "Callable[[], None] | None") -> None:
    """Зарегистрировать функцию, вызываемую после успешной переиндексации (сброс RAG в web_app)."""
```

A вызывает зарегистрированный callback вместо `sys.modules.get("web_app")` (эту функцию `_reset_long_lived_rag_state` удалить). C в `web_app.py` определяет `reset_rag_state()` (под `init_lock` обнуляет `collection`, `rag_system`, `db_initialized`, вызывает `core.retrieval.invalidate_bm25_cache()`) и регистрирует её: `documents_module.set_reindex_callback(reset_rag_state)` сразу после регистрации blueprints. Работает и при запуске `python web_app.py`.

**K3. Безопасные имена файлов (A создаёт, остальные используют при необходимости).**
`utils/filenames.py`:

```python
def safe_filename(name: str, *, default: str = "file") -> str:
    """Сохраняет кириллицу и расширение, убирает путь и опасные символы, ограничивает длину.
    'Отчёт (финал).PDF' -> 'Отчёт_финал.pdf'; никогда не возвращает имя без расширения, если оно было в исходном."""

def file_extension(name: str) -> str:
    """Расширение в нижнем регистре без точки; '' если нет."""
```

**K4. Режимы ответа (B владеет `config/chat_runtime.py`).**
Серверный список остаётся `default | brief | employee_instruction`. B добавляет в `config/chat_runtime.py` словарь `TELEGRAM_MODE_ALIASES` (русские режимы бота -> серверные) и функцию `normalize_answer_mode(value) -> str`, которую использует и `resolve_chat_rag_options`. Воркер Telegram отправляет уже нормализованные значения. Новые серверные режимы (`detailed`, `by_sources`, `step_by_step`) B добавляет только вместе с ветками в `core/rag.py` `generate_rag_prompt`; поскольку `core/rag.py` принадлежит D, B сначала маппит на существующие три режима (`подробно`/`по_источникам`/`по_шагам` -> `default`, `кратко` -> `brief`, `инструкция` -> `employee_instruction`) и пишет в отчёт предложение по новым режимам.

**K5. Шкала score (D владеет, остальным только знать).**
После правок D `score` документов в `hybrid` и `sparse` нормализуется так, чтобы лежать в [0, 1] и быть сопоставимой с порогом `min_score` из UI (описание в потоке D). Остальные потоки не должны полагаться на старую шкалу.

## 3. Поток A. Загрузки, вложения, документы

Цель: русские имена файлов работают, вложения безопасны, приватные вложения не попадают в базу знаний, хук переиндексации не зависит от имени модуля.

A1. **Кириллические имена.** Создать `utils/filenames.py` (контракт K3) и заменить `secure_filename` в `documents.py` (`upload_document`, `preview_document_upload`, `_find_existing_document`) и в `core/chat_attachments.py` (`save_uploaded_file`). Проверка расширения регистронезависимая. Тесты: `Отчёт.pdf`, `Снимок экрана 2026.PNG`, `a/../b.txt`, имя без расширения, очень длинное имя, только эмодзи в имени (fallback `file` + расширение сохраняется).
A2. **Перезапись при загрузке.** Если файл с таким именем уже есть в `UPLOAD_DIR`, отвечать 409 с `existing` и принимать `overwrite=true` (query/form). Тест на оба режима.
A3. **MIME вложений.** В `core/chat_attachments.py` не хранить и не использовать клиентский MIME для отдачи. Тип определять только по расширению из белого списка (`image/png`, `image/jpeg`, `image/webp`, `image/gif`, для текстовых `text/plain; charset=utf-8`). `.xml` и `.json` отдавать как `text/plain`. В `GET /api/chat/attachments/<id>` добавить заголовки `X-Content-Type-Options: nosniff`, `Content-Disposition: inline` только для изображений, для остальных `attachment`. Тест: загрузка `a.txt` с `Content-Type: text/html` отдаётся как `text/plain`.
A4. **Безопасная отдача документов.** В `GET /api/documents/open`: `.html`/`.htm` отдавать как `text/plain` либо `attachment` (по выбору, задокументировать), остальные типы с `nosniff`. Тест.
A5. **Каталог вложений и очистка.** Добавить функцию `cleanup_old_attachments(max_age_hours)` в `core/chat_attachments.py` (удаляет файл и `.meta.json`) и вызывать её лениво при загрузке не чаще раза в час (без потоков). Лимит `CHAT_ATTACHMENT_TTL_HOURS` читать через `getattr(settings, "CHAT_ATTACHMENT_TTL_HOURS", 72)`; добавление поля в `Settings` делает C, A просто использует `getattr` с дефолтом. Тест на удаление старых.
A6. **Хук переиндексации.** Реализовать K2, удалить `_reset_long_lived_rag_state`. Тест: callback вызывается после успешного job и не вызывается после упавшего.
A7. **Доступ без авторизации.** `/api/documents/open` и `/related` остаются доступными пользователям, но: `related` не сканирует `DATA_DIR` при каждом запросе (кэш списка документов на 30 секунд с инвалидацией после upload/reindex), `_scan_documents` пропускает каталог `CHAT_ATTACHMENTS_DIR` и `UPLOAD_DIR/../chat_attachments`. `open` не отдаёт файлы из каталога вложений. Тесты.
A8. **Лимит загрузки вложений.** Ограничить число файлов в одном запросе значением `CHAT_ATTACHMENT_MAX_COUNT` (сейчас проверяется только при использовании). Тест.

Приёмка: тесты потока проходят, ручная проверка через Flask test client: загрузка `Снимок экрана.png` возвращает 201, `a.txt` с `text/html` отдаётся как `text/plain`.

## 4. Поток I. Индексатор

Цель: индексатор парсится на Python 3.10+, корректно работает с реальными файлами и не ломается из-за одного плохого документа.

I1. **Синтаксис.** Строка `"id": f"{hashlib.md5(f'{doc_data['path']}_{j}'...` заменить на вычисление в отдельной переменной (совместимо с 3.10). Проверить `python3.10 -m py_compile` (через `uv venv --python 3.10`, если получится; иначе `ast.parse(..., feature_version=(3, 10))`). Тест на парсинг файла с `feature_version=(3,10)`.
I2. **Регистр расширений.** `scan_supported_files` находит `.PDF`, `.Docx` и т.п. (обход `rglob("*")` с фильтром по `suffix.lower()`), исключения `.crdownload/.tmp/.temp/.bak` тоже регистронезависимы. Тест.
I3. **Служебные каталоги.** `scan_supported_files` пропускает `CHAT_ATTACHMENTS_DIR`, `.git`, `__pycache__` и файлы, чьи имена начинаются с `~$`. Тест: `.txt` внутри каталога вложений не попадает в результат.
I4. **`.doc`.** `extract_text_from_doc`: `docx2txt` не читает бинарный `.doc`. Сначала пробовать как zip (`.docx` с неверным расширением), иначе, если в системе есть `antiword` или `catdoc`/`textutil`, использовать его через `subprocess` с таймаутом, иначе логировать понятное предупреждение и пропускать. Заголовок брать до схлопывания пробелов (первая непустая строка), а не после `re.sub(r'\s+',' ')`; структуру абзацев сохранять (не схлопывать `\n`, схлопывать только повторяющиеся пробелы внутри строк). Тесты на заголовок и на fallback без внешних утилит.
I5. **Отпечаток настроек в manifest.** В `core/index_manifest.py` добавить `settings_fingerprint()`: хэш от `OLLAMA_EMBEDDING_MODEL`, `EMBEDDING_API_MODE`, `CHUNK_SIZE`, `CHUNK_OVERLAP`, `STRUCTURAL_CHUNKING_ENABLED`, `STRUCTURAL_CHUNK_MAX_CHARS`, `STRUCTURAL_CHUNK_MIN_CHARS`, `CONTEXTUAL_RETRIEVAL_ENABLED`, `STRIKETHROUGH_INDEX_MODE`. Сохранять его в manifest. В `reindex_vector_db` при несовпадении отпечатка делать полную индексацию с `full_reason="settings_changed"`. Manifest без отпечатка (старый) считать несовпадающим один раз. Тесты.
I6. **Устойчивость incremental.** Изменённый файл, который стал пустым/нечитаемым, не должен валить весь reindex: логировать, удалять его старые чанки из Chroma/BM25/manifest, добавлять в `diagnostics["failed_files"]`. Новые файлы без чанков записывать в manifest с пустым `chunk_ids` и пометкой `skipped: true`, чтобы не обрабатывать их при каждом запуске (пересчёт при изменении `sha256`). Тесты на оба случая.
I7. **Атомарность полной пересборки.** В `create_vector_db` создавать новую коллекцию под временным именем (`<name>__new`), заполнять, затем удалять старую и переименовывать через `collection.modify(name=...)`. Если операция переименования недоступна, оставить текущую схему, но обернуть в try/except с откатом: при ошибке `add` не терять предыдущую коллекцию. BM25 писать во временный файл и подменять через `os.replace`. Это меняет `save_bm25_index` из `core/retrieval.py` (владелец D): вместо правки чужого файла записывать BM25 в индексаторе самостоятельно через вызов `save_bm25_index(ids, texts)` и описать в отчёте пожелание к D (параметр `atomic=True`).
I8. **`chunk_text_fixed_size`.** Гарантировать прогресс цикла: `start = max(end - overlap, start + 1)` и дополнительный guard `overlap < chunk_size // 2` при уточнении границы по предложению (если граница даёт шаг меньше `overlap`, игнорировать границу). Тест-регрессия: `chunk_size=500, overlap=400` завершается быстро, покрывает весь текст, нет дублей подряд. Файл `core/chunking.py`.
I9. **Мелочи.** Убрать лишнюю f-строку-обёртку вокруг md5; неиспользуемый `extract_func`-параметр в `chunking.py:342` либо использовать, либо удалить вместе с вызовами; логировать итоговое число пропущенных/упавших файлов в `diagnostics`.

Приёмка: `create_vector_db.py` парсится под 3.10, тесты индексатора проходят, ручной прогон `reindex_vector_db` на временном `DATA_DIR` с 3 файлами (включая `.PDF` и пустой `.txt`) завершается без исключения (эмбеддинги мокать).

## 5. Поток B. Идентичность и доступ

Цель: убрать подмену личности и перебор кодов, добавить базовую защиту входа, починить режимы бота.

B1. **Внутренний ключ (K1).** Создать `api/middleware/internal_auth.py`. `POST /api/telegram/verify` и `/api/telegram/resolve` требуют `is_trusted_internal_request()`, иначе 401. Если `TELEGRAM_INTERNAL_API_KEY` пуст, отвечать 503 с понятным сообщением (интеграция не настроена). В `config/settings.py` дефолт `TELEGRAM_INTERNAL_API_KEY` менять нельзя (владелец C): в отчёте написать, что дефолт-литерал `"API_KEY"` должен стать `os.getenv("API_KEY", "")`. Воркер Telegram не должен стартовать, если ключ пуст (`main()` печатает ошибку и возвращает 1). Тесты.
B2. **Коды привязки.** В `core/chat_history.py`: код 8 символов (цифры и буквы без похожих `0O1I`, `secrets.choice`), TTL из настройки. Уникальность только среди активных кодов; при коллизии 5 повторных попыток. Убрать глобальный `UNIQUE` из схемы через миграцию: создать `telegram_links_new`, перенести данные, переименовать (с `PRAGMA user_version`). Удалить недостижимый блок «Инвалидировать...». Индекс `idx_telegram_links_code` оставить, если нужен для быстрого поиска активных кодов.
B3. **Лимит попыток verify.** Новая таблица или in-memory счётчик по `telegram_user_id`: 5 неверных кодов за 15 минут, затем 429 на 15 минут. Сообщение бота пользователю: «Слишком много попыток». Счётчик по `telegram_user_id` и по IP. Тесты (через `time` monkeypatch).
B4. **Один Telegram = один аккаунт.** `verify_telegram_link`: если `telegram_user_id` уже привязан к другому пользователю, отказ (409) с понятным текстом. Добавить `unlink` в `chat_history` и `POST /api/telegram/unlink` для авторизованного пользователя. `get_telegram_link` возвращает только активную привязку.
B5. **Роль в ответе бота.** Сообщение `handle_start` не раскрывает роль (только «Аккаунт привязан»). Текст ошибок сети для пользователя без `{exc}` (детали только в лог).
B6. **Режимы (K4).** Реализовать `TELEGRAM_MODE_ALIASES`, `normalize_answer_mode`, использовать в `resolve_chat_rag_options` и воркере. Тесты: `кратко` -> `brief`, `инструкция` -> `employee_instruction`, неизвестное -> `default`, для воркера `/mode кратко` меняет payload.
B7. **Авторизация.** `api/routes/auth.py`: пароль не короче 8 символов и не совпадает с username; email проверять regex; ограничение попыток входа: 10 неудач за 15 минут на пару (IP, identifier) -> 429 (in-memory, с очисткой старых ключей). Сообщения об ошибках без разглашения существования пользователя (уже так). Тесты.
B8. **Issues.** `utils/issue_rate_limit.py`: ключ только по IP (учитывать `X-Forwarded-For` только если `settings.TRUST_PROXY` включён; читать через `getattr(settings, "TRUST_PROXY", False)`), очищать пустые и устаревшие ключи, ограничить размер словаря. `api/routes/issues.py`: `/status` кэшировать результат `probe_github_issue_write_access` на 5 минут; текст ошибки GitHub наружу не отдавать, только общее сообщение (детали в лог). Тесты.
B9. **Feedback без владения.** Проверка владения `message_id` в `add_feedback`-роуте принадлежит C (`api/routes/chat.py`), а метод в `core/chat_history.py` B: добавить `chat_history.message_belongs_to_session(message_id, session_id) -> bool` (контракт для C).
B10. **Bitrix24-воркер.** Обернуть тело цикла в `try/except Exception` с логированием и паузой (по образцу Telegram-воркера); гостевые чаты Bitrix не плодить: передавать в `/api/chat` стабильный `chat_id` на `dialogId` (хранить соответствие в JSON рядом с offset-файлом) либо добавить в чат-историю пометку `source=bitrix24`. Выбрать первое, описать в отчёте.
B11. **Telegram-воркер.** Закрывать `resp` (`with requests.post(...)`), удалить неиспользуемый `stream_success`, обработать завершение потока без `done`/`error` как ошибку («Ответ прерван»), не отправлять пользователю частичный текст как готовый ответ без пометки. `TelegramSession` с ограничением размера словаря `_sessions` (LRU 1000).
B12. **Мелочи модели.** `models/chat.py`: удалить неиспользуемые `from_dict`, если нет вызовов (проверить `rg`).

Приёмка: тесты потока проходят; ручная проверка: `POST /api/telegram/verify` без ключа -> 401, 6 неверных кодов подряд -> 429, регистрация с паролем `1` -> 400.

## 6. Поток C. Веб-приложение и конфигурация

Цель: убрать падения 500 на некорректном вводе, закрыть подмену `telegram_user_id`, добавить безопасные заголовки и убрать логирование секретов.

C1. **Подмена `telegram_user_id` (K1).** В `_resolve_chat_session`, `_can_access_chat_for_request`, `_telegram_linked_user_id`: использовать `telegram_user_id` только при `is_trusted_internal_request()`. Тесты: анонимный запрос с чужим `telegram_user_id` и `chat_id` получает 403; запрос с корректным внутренним ключом проходит.
C2. **Хук переиндексации (K2).** Реализовать `reset_rag_state()` и регистрацию колбэка. Тест: после вызова `initialize_database()` создаёт новый `RAGSystem`.
C3. **Логирование.** Удалить дублирование: оставить один механизм (декоратор `log_api_request` убрать, `before_request` и `after_request` оставить). Не логировать тело запросов на `/api/auth/*` и `/api/telegram/*`, для остальных маскировать ключи `password`, `password_hash`, `token`, `secret`, `init_data`, `code`. Тело логировать на DEBUG, максимум 200 символов, только если это `dict`. Тест: пароль не попадает в лог (`caplog`).
C4. **Некорректный ввод.** Все роуты в `web_app.py` (`mermaid_fix`, `verify_chat_answer`, `suggest_chat_questions`) принимают только `str` в `code`, `answer`, `parse_error`; иначе 400. JSON-список в теле не приводит к 500. Убрать мёртвую проверку `raw_message is None` в `_normalize_chat_query`. Вынести лимит 1000 символов сообщения в `settings.CHAT_MESSAGE_MAX_CHARS` (по умолчанию 1000) и минимум 3. Тесты.
C5. **Дедупликация чат-роутов.** Вынести общую подготовку (`normalize`, `options`, проверки БД и LLM, вложения, сессия, запись user-сообщения) из `chat()` и `chat_stream()` в приватные функции. Поведение не менять, тесты `tests/test_web_app.py` должны остаться зелёными без правки ожиданий (кроме явно нужных).
C6. **User-сообщение без ответа.** При `embedding_unavailable`, `search_error`, `ChatCompletionError` и общем исключении записывать в историю технический ответ ассистента с `metadata={"error": code}` и `role="assistant"` НЕ делать; вместо этого помечать user-сообщение `metadata.failed=true` (метод `update_message_metadata` в `core/chat_history.py` принадлежит B: контракт `chat_history.mark_message_failed(message_id, code)`; до появления метода C вызывает через `getattr` с проверкой). `_conversation_history_for_rag` исключает сообщения с `failed=true`. Поведение `/api/chat` и `/api/chat/stream` при `search_error` привести к одному: HTTP 500 для non-stream и SSE `error` для stream, одинаковые поля. Тесты.
C7. **Health.** `/api/health`: `status = "ok"` только если `ollama and database and rag`, иначе `"degraded"` (если хотя бы БД жива) или `"error"`. Поле `rag` сохраняется. Тест.
C8. **Заголовки безопасности.** `after_request`: `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN` (для `/telegram-app` без `X-Frame-Options`, чтобы работало во встроенном браузере Telegram), `Referrer-Policy: same-origin`, Content-Security-Policy с разрешением используемых CDN (`cdn.jsdelivr.net`, `cdnjs.cloudflare.com`, `fonts.googleapis.com`, `fonts.gstatic.com`, `telegram.org`) и `'unsafe-inline'` для стилей; включается флагом `SECURITY_HEADERS_ENABLED` (по умолчанию true). Тест на наличие заголовков.
C9. **CORS.** По умолчанию `CORS_ORIGINS` = пустой список для same-origin (без `*`), `*` только явно; `supports_credentials=False`. `.env.example` документирует. Тест.
C10. **Секреты.** `settings.validate()` при `FLASK_DEBUG=false` и дефолтных `SECRET_KEY`/`JWT_SECRET_KEY`: сгенерировать случайный `SECRET_KEY` на процесс и громко предупредить в лог (не падать), либо падать при `REQUIRE_SECRETS=true`. В `.env.example` закомментировать значения `SECRET_KEY`/`JWT_SECRET_KEY` и добавить команду генерации. `JWT_*` пометить как неиспользуемые (не удалять из документации, писать «зарезервировано») либо удалить из `Settings`, `settings_catalog`, `validate()` и `.env.example` (предпочтительно удалить, если нет использований `rg -i jwt`). `TELEGRAM_INTERNAL_API_KEY` дефолт `os.getenv("API_KEY", "")`. Одинаковый парсинг булевых через общий хелпер `_env_bool(name, default)` для всех флагов (включая `BITRIX24_ENABLED`, `TELEGRAM_*`). Убрать дубль `mkdir(TELEGRAM_OFFSET_PATH)`. Тесты.
C11. **Побочные эффекты импорта.** `Settings._create_directories()` не вызывать при импорте; вызывать явно из `web_app.py` (`create_app`-стиль, при `__main__` и при импорте `web_app`) и из скриптов, которым нужны каталоги. Безопасный вариант: оставить вызов, но ленивый (`settings.ensure_directories()`), и вызывать из `web_app.py`, `create_vector_db.py`, скриптов воркеров. В `create_vector_db.py`, скриптах воркеров и `core/rag.py` вызов делают их владельцы; в отчёте перечислить, где нужно добавить вызов. До согласования оставить текущее поведение, если это ломает тесты.
C12. **Overrides.** `apply_overrides`: применять только ключи, объявленные в `Settings` (`hasattr(type(settings_obj), key)`) и только с приведением к типу текущего значения; ошибки логировать `logger.warning`, не глотать молча. При нарушении инварианта чанкинга игнорировать только проблемные ключи, а не все overrides. `save_overrides` + чтение-изменение-запись в `admin.update_setting` под общим `threading.Lock`; при записи использовать уникальное имя временного файла. Валидация границ для всех `int`/`float` спецификаций из `settings_catalog` (если есть `min`/`max` в `ui`, применять не только для слайдеров). Тесты.
C13. **Админка.** `api/routes/admin.py`: убрать двойной `from flask import`, `limit` в `/api/chats/feedback` ограничить (1..500), `_chroma_status` переиспользует существующий клиент через `core.retrieval`/`web_app` (не создавать `PersistentClient` каждый вызов), кэш overview под lock.
C14. **`api/routes/chat.py`.** `add_feedback`: если задан `message_id`, проверять принадлежность сообщения сессии (контракт B9) и что сообщение роли `assistant`; требовать `session_id`, если нет прав администратора. Поиск чатов: экранировать `%` и `_` можно только в `core/chat_history.py` (владелец B), C передаёт запрос как есть. `total` при поиске возвращать по числу найденных. `offset` учитывать и при поиске (через `search_sessions(..., offset=)`, параметр добавляет B; до этого игнорировать). `add_message` роут (`POST /api/chats/<id>/messages`): запретить роль `assistant` для не-администратора (клиент не должен подделывать ответы ассистента), тест.
C15. **Прокси.** Добавить опциональный `ProxyFix` при `TRUST_PROXY=true` (`getattr` в `web_app.py`, поле в `Settings`).

Приёмка: `tests/test_web_app.py`, `tests/test_product_features.py`, `tests/test_auth.py` (не править чужие) проходят; ручная проверка через test client из аудита: список в JSON -> 400, нестроковый `code` -> 400, в ответах есть заголовки безопасности, пароль отсутствует в логах.

## 7. Поток D. LLM и RAG-ядро

Цель: ответы не обрезаются, ошибки HTTP корректны, шкала score единая, кэш эмбеддингов реально работает.

D1. **`strip_model_reasoning`.** Переписать так, чтобы он вырезал только: блоки `<think>...</think>`/`<redacted_thinking>`, и явный английский CoT-префикс (по `_COT_PREFIX_MARKERS` в первых 400 символах) до первого абзаца, начинающегося с кириллицы. Ответ, который начинается с латиницы/цифр и не содержит CoT-маркеров, возвращается без изменений. Тесты из аудита: `"1С:УПП — откройте раздел «Склад».\nЗатем нажмите Создать."` остаётся целым; `"EGAIS-статусы:\n\nОтправка идёт через УТМ."` целый; настоящий CoT (`"The user is asking...\n\nОтвет по-русски"`) вырезается; блоки `<think>` вырезаются; JSON-массив остаётся; fenced-код mermaid сохраняется. Поток `_filter_reasoning_stream` использует ту же логику и не должен отдавать в UI текст, который потом исчезнет (для англ. префикса ждать первую кириллицу, для остального отдавать сразу).
D2. **`if e.response`.** Во всех местах `utils/embeddings.py` заменить `e.response.status_code if e.response else "?"` на `... if e.response is not None else "?"`. Тест: HTTPError с 500 даёт «HTTP 500».
D3. **`get_embeddings_batch`.** При сбое возвращать `[]` (единый контракт «либо все, либо пусто»), не сдвинутый список. Проверить вызывающих (`core/retrieval.py`, `create_vector_db.py::embed_documents_batch`). Тесты.
D4. **Размерность эмбеддингов.** `dimensions: 1024` не прибивать: брать из `getattr(settings, "EMBEDDING_DIMENSIONS", None)`; если `None`, не отправлять поле. Поле в `Settings` добавляет C (использовать `getattr`); в отчёте указать. Тесты payload.
D5. **Кэш эмбеддингов (`utils/cache.py`).** Сделать персистентным: сохранять индекс при `set` не реже раза в 100 записей И при `atexit`; при загрузке индекса сверять с файлами на диске, удалять файлы `*.cache`, которых нет в индексе (осиротевшие), и записи без файла. Ключ кэша включает `EMBEDDING_API_MODE` и размерность. `_evict_lru` не сортировать весь индекс на каждой вставке (пакетная эвикция 10% при переполнении). Заменить `pickle` на безопасный формат (JSON-массив float или `array('f')` в бинарном файле). Убрать неиспользуемые `access_count`, ветку `USE_CACHE`/`try ImportError` в `embeddings.py`, дубль импорта `invalidate_embedding_cache`, неиспользуемые импорты `chromadb`, `Documents`, `EmbeddingFunction`, `Embeddings`. Тесты: запись, «перезапуск» (новый `FileCache` на том же каталоге) видит записи, осиротевшие файлы удаляются.
D6. **Шкала score (K5).** В `core/retrieval.py` для `hybrid`/`sparse` без rerank считать `score = rrf_score / max_possible_rrf`, где `max_possible_rrf = число_ранжирований / (RRF_K + 1)`, и ограничить [0,1]; `RRF_SCORE_NORMALIZER` оставить как множитель-фолбэк, если задан явно (не дефолт). Для dense оставить `1 - distance`. Документировать в докстринге, что `min_score` в hybrid относится к нормализованному RRF. `DEEP_RETRIEVAL_MIN_BEST_SCORE` теперь достижим. Тесты: один документ, найденный первым во всех ранжированиях, имеет score 1.0; `min_score=0.5` не отсекает его; смешанные шкалы после rerank сортируются корректно (после rerank документы за пределами `top_n` не должны иметь score выше переранжированных: сортировать общий список по score).
D7. **Rerank thread.** `_predict_rerank_scores`: не плодить потоки при повторных таймаутах (один общий `ThreadPoolExecutor(max_workers=1)`; если предыдущая задача ещё выполняется, сразу пропускать rerank). `_get_cross_encoder`: проверять кэшированную модель ДО `import sentence_transformers`, чтобы тест `test_rerank_cross_encoder_caps_text` проходил без пакета. Неизвестный `RETRIEVAL_MODE` логировать warning и трактовать как `hybrid`. Режим `sparse` без BM25 возвращает ошибку `search_error` с диагностикой `bm25_unavailable`, а не «нет документов».
D8. **BM25.** `save_bm25_index`: запись через временный файл и `os.replace`; формат JSON (сжатый gzip) вместо `pickle`, чтение старого pickle оставить только как миграционный fallback с warning. `bm25_ranking`: использовать `heapq.nlargest`/`numpy.argpartition` вместо полной сортировки. `get_embedding_fn` параметр `hybrid_retrieve` удалить вместе с передачей из `core/rag.py`. Тесты.
D9. **`core/rag.py` чистка.** Удалить неиспользуемые импорты (`requests`, `Settings`, `chat_completion_messages_stream_filtered`), f-строки без плейсхолдеров, неиспользуемые `total_text_length`, мёртвый `origins` в `retrieve_documents_deep`, дубль `_dedupe` (вынести в одну функцию), `should_skip_kb_retrieval`/`build_retrieval_query`/`highlight_citations_in_text`/`create_rag_system`/`looks_like_mermaid`, если они не используются в коде и тестах (проверить `rg` по репозиторию; если только в тестах и `core/__init__.py`, оставить). Эвристику `cot_in_raw` в логе удалить.
D10. **Дубли `query()` и `stream_rag_answer()`.** Вынести общие части (запись JSONL-лога этапов, пост-обработка ответа: strip reasoning, merge mermaid, автофикс, обогащение цитатами, сбор `diagnostics`) в приватные методы. В диагностику стрима добавить `top_k` и `min_score`, как в `query()`. Поведение и формат ответа не менять. Тесты `tests/test_rag_*.py` зелёные.
D11. **Хардкод эвристик chitchat.** Регэкспы `ка\s`, `ут\s` в `_KB_DOMAIN_HINT_RE` требуют границы слов (`\bка\b`, `\bут\b`), чтобы не срабатывать на окончания слов. Тесты на `"пока пока"` (chitchat), `"как тут дела"` (chitchat), `"ошибка ка"`/`"настройка УТ"` (не chitchat).
D12. **Логи обмена с LLM.** `LLM_EXCHANGE_LOG_ENABLED` оставить, но в лог не писать полный промпт с контекстом по умолчанию: писать длину и первые 500 символов, полный промпт только при `LLM_EXCHANGE_LOG_FULL=true` (читать через `getattr(settings, "LLM_EXCHANGE_LOG_FULL", False)`; поле добавляет C). Тест.
D13. **Побочные эффекты импорта `core/rag.py`.** Создание каталогов логов и хендлеров вынести в функцию `_setup_rag_logging()`, вызываемую один раз при первом создании `RAGSystem` (идемпотентно). Тесты не должны создавать каталоги `logs/` при простом импорте.

Приёмка: `tests/test_rag_*.py`, `tests/test_retrieval_embed_batch.py`, `tests/test_chat_reasoning.py`, `tests/test_mermaid_fix.py`, `tests/test_merge_mermaid_raw.py` проходят без `sentence-transformers`; примеры из D1 в тестах; `rg "e.response else"` не находит старый паттерн.

## 8. Поток E. Фронтенд, зависимости, чистка

Цель: интерфейс работает без интернета, зависимости и документация соответствуют коду, мёртвый код убран.

E1. **Локальные библиотеки.** Скачать `marked` (закрепить версию, например 12.0.2), `dompurify` 3.2.4, `mermaid` 10.9.x (`mermaid.min.js`), `highlight.js` 11.9.0 (js и css `github-dark`) в `static/vendor/<lib>/<version>/`, подключить из `templates/index.html` и `templates/telegram_app.html` через `url_for('static', ...)`. Для Telegram Web App скрипт `telegram.org/js/telegram-web-app.js` оставить внешним (обязателен). Шрифт Inter: подключить локально (woff2 в `static/vendor/fonts/`) с `@font-face` или убрать Google Fonts и использовать системный стек. Если сеть недоступна и скачать нельзя, оставить CDN, но закрепить версии и добавить `integrity`/`crossorigin` (SRI-хэши получить через `curl` + `openssl dgst -sha384 -binary | openssl base64 -A`), и написать в отчёте.
E2. **`marked` API.** Проверить `static/script.js` и `static/telegram-app.js`: опция `highlight` в `marked.setOptions` не поддерживается в закреплённой версии (v8+), заменить на подсветку после рендера (`hljs.highlightElement` для `pre code`) либо на `marked-highlight`. Вызывать `marked.setOptions` один раз при инициализации, а не на каждом рендере. Обновить `?v=` номера у скриптов.
E3. **Fallback `sanitizeHtml`.** Если `DOMPurify` недоступен, не вставлять HTML вообще: показывать экранированный текст. Удалить слабую реализацию. Обновить `tests/test_frontend_contract.py` при необходимости.
E4. **Ошибки SSE.** Проверить пункты старого аудита, которые ещё актуальны в `static/script.js` (`AbortController`/id запроса при переключении чата, обрыв SSE без `done`, гонка поиска в sidebar, повторные цепочки polling reindex, экспорт диалога с служебными элементами, mermaid-тема). Каждый пункт: проверить по коду, если воспроизводится, исправить минимально; неактуальные перечислить в отчёте. Не переписывать файл целиком.
E5. **Индикатор health.** Учитывать `data.status` и `data.rag` из `/api/health` (контракт после C7: `ok | degraded | error`), показывать «Частично» для `degraded`.
E6. **Telegram-режимы в UI** не менять (там только `default`).
E7. **Зависимости.** `requirements.txt`: убрать `sentence-transformers` в новый `requirements-rerank.txt` (с комментарием, что нужен только при `RERANK_ENABLED=true`); `pytest` убрать из `requirements.txt` в `requirements-dev.txt`; проверить, что все импорты кода покрыты `requirements.txt` (`rank-bm25`, `docx2txt`, `xlrd` и др.), при необходимости добавить `python-multipart` не нужно. Обновить `scripts/bootstrap.ps1` только если он ссылается на состав requirements (проверить `rg`).
E8. **Версия Python.** README и `scripts/*`: согласовать заявленную версию с кодом (после потока I код совместим с 3.10+; оставить «Python 3.10+»). Добавить в README раздел «Запуск тестов» с командой из общих правил без переменных `WT`.
E9. **`CODE_AUDIT.md`.** Заменить содержимое кратким актуальным перечнем оставшихся замечаний и ссылкой на `plans/audit-fix-plan.md`; убрать пункты, которые уже исправлены (список в шапке этого плана). Это единственный разрешённый `.md`, который поток может перезаписать, плюс `README.md`.
E10. **Мёртвый код.** Удалить `api/middleware/validation.py` и убрать его экспорт из `api/middleware/__init__.py`; удалить или подключить `utils/validators.py` (удалить, если нет вызовов; убрать из `utils/__init__.py`, предупреждения Pydantic V1 пропадут); переписать `qa_system.py` на `RAGSystem.query()` (тонкий CLI) либо удалить и убрать упоминания из README (выбрать переписывание, файл небольшой). Если `utils/embeddings.py` ещё содержит `search_documents`/`generate_answer`, использованные `qa_system.py`, после переписывания они станут неиспользуемыми; удаление сделает поток D, в отчёте E указывает, что `qa_system.py` больше их не использует. `core/__init__.py` не экспортирует удалённые D символы (согласовать через отчёт).
E11. **Скрипты.** `scripts/eval_coverage_basket.py`: добавить `sys.path` bootstrap корня проекта; `scripts/extract_long_paths.py`: брать корневой `data/` (`Path(__file__).resolve().parents[1] / "data"`) и принимать путь аргументом; `scripts/capture_screenshots.py`: удалить неиспользуемые импорты; `scripts/parse_xwiki.py`: удалить `parse_qsl`; `scripts/test_available_models.py` и `scripts/test_ollama_api.py`: переименовать в `check_*.py` (чтобы pytest их не собирал) и обновить упоминания; убрать f-строки без плейсхолдеров. `docs/presentation/generate_pptx.py`: убрать неиспользуемый `nonlocal prs`. `tests/test_scripts_smoke.py` обновить под переименования.
E12. **Шум в репозитории (только рекомендации).** Не удалять `.superpowers/`, `.impeccable/`, `design-prototypes/`, `outputs/`, `plans/redisign/*.html` (это решение владельца), но подготовить в отчёте список и предложенные записи для `.gitignore`.

Приёмка: страницы открываются без обращений к внешним CDN (кроме Telegram SDK); `tests/test_frontend_contract.py`, `tests/test_scripts_smoke.py` проходят; `pyflakes` по своим файлам чист.

## 9. Порядок и проверка

Все потоки идут параллельно. После завершения выполняется интеграционная фаза (не поручается потокам):

1. Полный прогон `pytest --ignore=tests/e2e` с переменными окружения из раздела 0.
2. `pyflakes` по всем `*.py`, `python -m compileall` под 3.10 и 3.12.
3. Сквозные проверки из аудита через Flask test client: список в JSON -> 400; чужой `telegram_user_id` без ключа -> 403; вложение `a.txt` с `text/html` -> `text/plain`; загрузка `Снимок экрана.png` -> 201; `strip_model_reasoning("1С:УПП — ...")` не обрезает; `chunk_text_fixed_size(500, 400)` завершается; `/api/telegram/verify` без ключа -> 401, после 5 неверных кодов -> 429.
4. Проверка отсутствия конфликтов: `git status`, `git diff --stat` по потокам; каждый файл изменён только своим владельцем.
5. Ручной обзор отчётов потоков, сведение замечаний «для других потоков» и повторный короткий раунд исправлений.

## 10. Что сознательно не входит

- Переход на другую СУБД и полноценный incremental BM25.
- Стемминг/лемматизация для русского BM25 (отдельная задача качества поиска).
- Перепроектирование дизайна интерфейса.
- Удаление служебных каталогов из git (решение владельца репозитория).
