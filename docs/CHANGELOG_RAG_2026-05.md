# Отчёт о доработках RAG (май 2026)

Краткое описание реализованных блоков: гибридный поиск, структурное чанкирование с contextual retrieval, память диалога и расширение запросов.

---

## 1. Гибридный поиск (BM25 + dense, RRF, cross-encoder)

**Модуль:** `core/retrieval.py`

- Векторный поиск по-прежнему через ChromaDB (dense).
- Лексический поиск: **BM25** (`rank_bm25`), корпус синхронизирован с чанками индекса.
- Слияние списков кандидатов: **RRF** (Reciprocal Rank Fusion), константа `RRF_K_CONSTANT` (по умолчанию 60).
- Опциональный **cross-encoder rerank** (`sentence_transformers.CrossEncoder`), скор приводится к диапазону через sigmoid.

**Индексация:** после успешной записи в Chroma в каталог `CHROMA_PERSIST_DIR` сохраняется файл `bm25_corpus.pkl` (имя задаётся `BM25_INDEX_FILENAME`). Без переиндексации BM25 недоступен — гибридный режим фактически сводится к dense.

**Настройки (`config/settings.py`, переменные окружения):**

| Переменная | Назначение |
|------------|------------|
| `RETRIEVAL_MODE` | `hybrid` \| `dense` \| `sparse` |
| `BM25_INDEX_FILENAME` | имя pickle-файла корпуса BM25 |
| `RAG_FUSION_CANDIDATES` | сколько кандидатов тянуть до слияния |
| `RRF_K_CONSTANT` | параметр RRF |
| `RRF_SCORE_NORMALIZER` | масштаб отображения RRF-скора до rerank |
| `RERANK_ENABLED` | включить cross-encoder (по умолчанию `false`) |
| `RERANK_MODEL` | идентификатор модели (например `cross-encoder/ms-marco-MiniLM-L-6-v2`) |
| `RERANK_TOP_N` | сколько верхних кандидатов переранжировать |

**Зависимости:** `requirements.txt` — добавлены `rank_bm25`, `sentence-transformers`.

**Интеграция:** `core/rag.py` — метод `retrieve_documents` формирует запросы через расширение (см. п. 3) и вызывает `hybrid_retrieve`. Возвращаемое значение: `(документы, код_ошибки, expansion, diagnostics)`.

---

## 2. Структурное чанкирование и Contextual Retrieval

**Модуль:** `core/chunking.py`

- **HTML:** обход DOM по заголовкам `h1`–`h6`, спискам, таблицам, блокам `p` / `div` / `section` / `article` / `blockquote` / `pre`; путь раздела собирается в виде цепочки «→».
- **DOCX:** стили `Heading*`, таблицы по строкам.
- **Прочие форматы:** fallback — абзацы и эвристика «псевдозаголовков».
- Склейка слишком коротких блоков: лимиты `STRUCTURAL_CHUNK_MAX_CHARS`, `STRUCTURAL_CHUNK_MIN_CHARS`.
- Отключение структуры: `STRUCTURAL_CHUNKING_ENABLED=false` — используется прежняя нарезка фиксированной длины (`CHUNK_SIZE` / `CHUNK_OVERLAP`), реализация в `chunk_text_fixed_size`.

**Метаданные чанка в Chroma:** `section_path`, `chunk_kind`, `parent_headings_json`, при contextual — `contextual_prefix`.

**Contextual Retrieval:** при `CONTEXTUAL_RETRIEVAL_ENABLED=true` для первых `CONTEXTUAL_RETRIEVAL_MAX_CHUNKS` чанков документа вызывается LLM (`create_vector_db._contextual_prefix_for_chunk`), краткая аннотация добавляется **только** к строке для эмбеддинга и BM25; в поле `documents` в Chroma остаётся исходный текст для отображения в ответах.

**Файлы:** `create_vector_db.py` — `process_file` / `embed_documents_batch` / сохранение BM25; `preview_document` учитывает новый способ нарезки.

**UI:** `static/script.js` — в панели источников выводятся `section_path` и `chunk_kind`; `static/style.css` — класс `.source-section-path`.

---

## 3. Память диалога: переписывание запроса, HyDE, multi-query

**Модуль:** `core/rag.py` — `expand_retrieval_queries`

- При непустой истории и `CONVERSATIONAL_REWRITE_ENABLED=true` запрос переписывается в **один самодостаточный** поисковый запрос (LLM).
- `RAG_MULTI_QUERY_ENABLED=true` — генерируются 2–3 альтернативные формулировки; участвуют в dense и sparse.
- `RAG_HYDE_ENABLED=true` — строится короткий гипотетический «ответ»; добавляется как **дополнительный** dense-запрос.

Ограничение глубины истории для этого шага: `RAG_QUERY_EXPANSION_MAX_MESSAGES`.

**API и хранение:**

- `web_app.py` — `/api/chat` и `/api/chat/stream` передают в RAG историю и получают единый путь поиска; в `diagnostics` попадают `expansion` и `retrieval`.
- В SQLite у сообщений добавлена колонка **`retrieval_query_text`** (миграция через `_ensure_column` в `core/chat_history.py`); для ответов ассистента сохраняется переписанный запрос. Модель `models/chat.py` — поле `retrieval_query_text` в `to_dict` при наличии.

**Промпт генерации:** блок «ПОИСКОВЫЙ ЗАПРОС» использует `rewritten` запрос, если он отличается от исходной реплики пользователя (`generate_rag_prompt`).

---

## 4. Прочие изменения

- `tests/test_web_app.py` — моки `retrieve_documents` обновлены под 4 возвращаемых значения; убраны проверки `build_retrieval_query` в stream-тестах (поиск идёт через `expand_retrieval_queries` + `retrieve_documents` с `conversation_history`).
- Исправлены синтаксические ошибки в `core/chunking.py` (скобки в условии `is_heading`, аннотация `Callable`).

---

## 5. Что сделать после обновления кода

1. Установить зависимости: `pip install -r requirements.txt` (в том же окружении Python, из которого запускается приложение). Пакет BM25 в PyPI называется **`rank-bm25`**, в коде импортируется как `rank_bm25`. Если в логах было «rank_bm25 не установлен», чаще всего не ставили зависимости или сервер запущен другим интерпретатором Python — проверьте `where python` / `python -c "import rank_bm25"`.
2. При необходимости выставить в `.env` режимы (`RETRIEVAL_MODE`, `RERANK_ENABLED`, contextual, HyDE, multi-query).
3. Выполнить **полную переиндексацию** базы знаний, чтобы появились BM25-корпус, новые метаданные чанков и (при включении) contextual-префиксы.

---

*Документ отражает состояние кодовой базы на момент фиксации описанных изменений.*
