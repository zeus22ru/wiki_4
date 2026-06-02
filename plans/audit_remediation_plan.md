# План поэтапной реализации исправлений и улучшений

Дата: 2026-06-02  
Источник: `CODE_AUDIT.md`  
Статус: план к реализации  
Ограничение: план не включает задачи по безопасности; фокус на корректности, стабильности, производительности, UX и поддерживаемости.

## Цели

1. Вернуть проект в зелёное состояние по тестам.
2. Устранить ошибки, которые могут портить индекс, историю чатов или ответы RAG.
3. Зафиксировать единые backend-контракты для chat/retrieval/reindex.
4. Стабилизировать frontend-состояние чата и SSE-стриминг.
5. Добавить измерения производительности до крупных оптимизаций.
6. Синхронизировать CLI, скрипты, тесты и документацию с текущей архитектурой.

## Принципы реализации

- Каждый этап должен завершаться зелёным `python -m pytest` или явным списком оставшихся известных падений.
- Сначала исправлять дефекты, которые могут привести к потере/рассинхрону данных, затем UX и оптимизацию.
- Не смешивать крупные архитектурные изменения с мелкими bugfix'ами в одном PR/коммите.
- Для каждого исправления добавлять минимальный регрессионный тест, если дефект воспроизводим без реального LLM/Chroma.
- Для оптимизаций сначала добавить метрики, затем менять алгоритмы.

## Предлагаемая разбивка

| Этап | Название | Приоритет | Результат |
|---|---|---|---|
| 0 | Базовая стабилизация CI | Критический | Тесты снова зелёные, зафиксирована отправная точка |
| 1 | Backend-контракты chat API | Критический | Валидация входа, единые ошибки, предсказуемая история |
| 2 | Надёжная индексация и reindex | Критический | Reindex не портит индекс и не конкурирует сам с собой |
| 3 | Retrieval/RAG устойчивость | Высокий | Hybrid-поиск и LLM-stream корректно деградируют |
| 4 | Frontend состояние чата | Высокий | Нет дублей чатов, гонок SSE и рассинхрона UI/БД |
| 5 | Наблюдаемость и performance baseline | Высокий | Есть метрики latency и размеров ключевых структур |
| 6 | Оптимизация индексации и retrieval | Средний | Меньше лишней работы на reindex/search |
| 7 | SQLite/history maintenance | Средний | История масштабируется лучше, админка не деградирует резко |
| 8 | Скрипты, CLI и документация | Средний | Инструменты запускаются, docs не противоречат коду |
| 9 | Расширение тестового покрытия | Сквозной | Основные регрессии из аудита закрыты тестами |

## Этап 0. Базовая стабилизация CI

### Цель

Убрать текущее падение `tests/test_web_app.py::test_api_chat_stream_success` и получить чистую базу перед более глубокими изменениями.

### Задачи

- Разделить тесты stream-чата на два сценария:
  - RAG-stream: вопрос с доменными признаками, который не классифицируется как chitchat.
  - Chitchat-stream: короткое приветствие, которое идёт через `stream_chitchat_answer`.
- В RAG-stream тесте проверять вызовы `retrieve_documents_auto()` и `stream_rag_answer()`.
- В chitchat-stream тесте проверять статус `"Формирую ответ..."`, отсутствие retrieval-вызовов и корректное `done`.
- Проверить, что текущие fixtures не зависят от порядка запуска тестов.

### Файлы

- `tests/test_web_app.py`
- `core/rag.py`
- `web_app.py`

### Критерии готовности

- `python -m pytest tests/test_web_app.py::test_api_chat_stream_success` проходит.
- `python -m pytest` проходит полностью.
- В тестах явно покрыты обе ветки stream routing.

### Риски

- Если тесты начнут мокать слишком много внутренней логики, они перестанут ловить реальные рассинхроны маршрутизации.

## Этап 1. Backend-контракты chat API

### Цель

Сделать входные параметры и ошибки chat API предсказуемыми для клиента и истории чатов.

### Задачи

- Добавить общую функцию нормализации chat request:
  - `message` должен быть строкой.
  - trim выполняется после проверки типа.
  - длина проверяется до создания/записи сообщения.
  - `top_k` clamp в допустимый диапазон.
  - `min_score` clamp в `0..1`.
  - `answer_mode` через whitelist.
- Синхронизировать frontend limits и backend limits:
  - `templates/index.html`
  - `static/script.js`
  - `config/chat_runtime.py`
  - возможно `utils/validators.py`
- Развести ошибки `chat_id`:
  - отсутствующий чат -> 404.
  - существующий, но недоступный -> 403.
- Нормализовать `limit` и `offset` в `/api/chats`.
- Принять решение по `utils/validators.py`:
  - либо подключить Pydantic v2 схемы к runtime routes;
  - либо удалить/сократить мёртвую валидацию и оставить простую ручную нормализацию.

### Файлы

- `web_app.py`
- `api/routes/chat.py`
- `config/chat_runtime.py`
- `utils/validators.py`
- `api/middleware/validation.py`
- `templates/index.html`
- `static/script.js`
- `tests/test_web_app.py`
- `tests/test_chat_runtime.py`

### Тесты

- `POST /api/chat` с `message: null` -> 400.
- `POST /api/chat` с `message: 123` -> 400.
- `POST /api/chat/stream` с нестроковым `message` -> 400.
- `top_k=0`, `top_k=-1`, `top_k=100000` нормализуются или отклоняются по выбранному контракту.
- `min_score=-1`, `min_score=2` нормализуются или отклоняются.
- unknown `answer_mode` возвращает default или 400, но поведение должно быть зафиксировано тестом.
- Несуществующий `chat_id` -> 404.
- `GET /api/chats?limit=-1` не выгружает всё.

### Критерии готовности

- Клиент не может получить 500 из-за некорректного типа `message`.
- Backend и frontend используют одинаковые ограничения.
- Поведение invalid inputs описано тестами.

## Этап 2. Надёжная индексация и reindex

### Цель

Исключить ситуации, когда reindex портит или частично обновляет рабочую базу.

### Задачи

- Запретить параллельные reindex-задачи:
  - добавить global lock или состояние active job;
  - второй запрос возвращать `409` с понятным JSON;
  - UI должен показывать текущий активный job, а не запускать новый.
- Исправить partial embedding failure:
  - если получены не все эмбеддинги, считать reindex failed;
  - не удалять старую коллекцию при неполном результате;
  - BM25 строить только из согласованного набора `ids/texts`.
- Сделать переключение коллекции более атомарным:
  - подготовить новую коллекцию под временным именем;
  - проверить count и базовые инварианты;
  - затем переключить активную коллекцию.
- После успешного reindex сбрасывать долгоживущий RAG state:
  - `collection`
  - `rag_system`
  - `db_initialized`
  - BM25 bundle/cache внутри `RAGSystem`
- Добавить TTL/лимит размера `_jobs`, чтобы список jobs не рос бесконечно.
- Устранить race чтения `_jobs[job_id]` после старта потока.

### Файлы

- `api/routes/documents.py`
- `create_vector_db.py`
- `web_app.py`
- `core/rag.py`
- `core/retrieval.py`
- `tests/test_web_app.py`
- новый тестовый модуль для reindex, например `tests/test_documents_reindex.py`

### Тесты

- Два подряд `POST /api/documents/reindex`: первый `202`, второй `409` или queued по выбранному контракту.
- Partial embedding failure не вызывает удаление старой коллекции.
- При несовпадении длины `ids/texts` BM25 не сохраняется как успешный.
- После successful reindex вызывается reset/reload RAG state.
- `/api/documents/jobs` возвращает последние jobs и не падает при pending/running.

### Критерии готовности

- Reindex не может параллельно писать в одну коллекцию.
- Частичный reindex не считается успешным.
- После reindex ответы используют актуальный индекс без перезапуска приложения.

### Риски

- Атомарное переключение коллекций в Chroma может требовать аккуратной проверки поддержки rename/swap. Если rename нет, нужен безопасный fallback с временной коллекцией и настройкой active collection name.

## Этап 3. Retrieval/RAG устойчивость

### Цель

Сделать RAG-путь устойчивым к частичным сбоям embedding, Chroma и LLM-stream.

### Задачи

- Добавить degraded fallback для hybrid retrieval:
  - если dense embeddings недоступны, но BM25 есть, возвращать sparse-only результаты;
  - в diagnostics явно писать `degraded: true`, `dense_error`, `used_sparse_fallback`.
- Унифицировать `search_error` для stream и non-stream:
  - выбрать единый контракт HTTP/SSE;
  - решить, пишется ли user message при retrieval failure;
  - в обоих путях одинаково отражать failed state.
- Изменить потоковые LLM ошибки:
  - `chat_completion_stream()` не должен отдавать текст ошибки как обычный delta;
  - верхний уровень должен получать error event/exception;
  - failed assistant не должен сохраняться как успешный ответ.
- Пересмотреть cache TTL `inference_server_reachable()`:
  - для preflight можно оставить cache;
  - при ошибке генерации инвалидировать cache;
  - для критичных chat paths рассмотреть `use_cache=False`.
- Проверить split `EMBEDDING_API_MODE` и `CHAT_API_MODE`:
  - отдельная проверка embedding endpoint;
  - отдельная проверка chat endpoint;
  - admin overview должен показывать оба состояния.

### Файлы

- `core/retrieval.py`
- `core/rag.py`
- `utils/embeddings.py`
- `config/settings.py`
- `web_app.py`
- `api/routes/admin.py`
- `tests/test_retrieval_embed_batch.py`
- `tests/test_web_app.py`
- `tests/test_inference_reachable_cache.py`

### Тесты

- Hybrid + недоступные embeddings + валидный BM25 -> sparse fallback.
- Dense-only + недоступные embeddings -> `embedding_unavailable`.
- Stream generation timeout -> SSE error, без успешного assistant message.
- Non-stream generation error -> JSON error, история не содержит fake answer.
- Split backend health возвращает раздельную диагностику.

### Критерии готовности

- Временный сбой embedding API не отключает BM25 fallback в hybrid.
- Ошибки LLM не выглядят как нормальные ответы.
- Diagnostics помогают отличить нормальный ответ, degraded retrieval и failure.

## Этап 4. Frontend состояние чата и SSE

### Цель

Убрать рассинхрон между UI, серверной историей и активным stream-запросом.

### Задачи

- Валидация перед `ensureChat()`:
  - пустое сообщение;
  - min/max length;
  - `top_k`;
  - `min_score`;
  - `answer_mode`.
- Не создавать пустой чат до успешной клиентской валидации.
- Убрать статическое welcome-сообщение из HTML или очищать его перед первым user message.
- Восстанавливать активный чат после reload:
  - сохранять `currentChatId` в `sessionStorage`;
  - при `loadChats()` проверять доступность сохранённого chat id;
  - fallback: открыть последний чат или показать welcome.
- Добавить `AbortController` для `/api/chat/stream`:
  - отменять stream при `openChat()`;
  - отменять stream при logout/delete current chat;
  - игнорировать устаревшие события через request id.
- Обработать обрыв SSE без `done`:
  - снять `streaming-in-progress`;
  - показать системную ошибку;
  - не добавлять кнопки источников/feedback.
- Сделать mobile sidebar доступным:
  - drawer/overlay;
  - кнопка открытия в header;
  - закрытие по Escape/backdrop.
- Сделать один polling loop для reindex jobs.
- Исправить экспорт диалога:
  - либо экспортировать через API history;
  - либо чистить DOM от служебных элементов.
- Разделить inline errors и bot messages:
  - системные ошибки показывать toast/banner;
  - не включать их в экспорт диалога.

### Файлы

- `templates/index.html`
- `static/script.js`
- `static/style.css`
- `static/js/theme.js`
- `static/js/clipboard.js`
- возможно новые frontend test helpers, если будет добавлен JS test runner

### Проверки вручную

- Первый вопрос после открытия страницы не оставляет welcome как часть диалога.
- После F5 следующий вопрос уходит в текущий чат, а не создаёт дубль.
- При переключении чата во время stream старый ответ не перезаписывает новый `currentChatId`.
- На ширине 768px доступен список чатов и кнопка «Новый чат».
- При обрыве сети во время stream UI завершает состояние ошибки.
- Экспорт содержит только сообщения диалога.

### Критерии готовности

- UI и серверная история совпадают после reload.
- Нет известных гонок `currentChatId` при SSE.
- Mobile-режим сохраняет основные функции чата.

## Этап 5. Наблюдаемость и performance baseline

### Цель

Перед оптимизацией получить измеримые baseline-данные по RAG, reindex, SQLite и frontend stream render.

### Задачи

- Добавить lightweight timing diagnostics:
  - query expansion;
  - embeddings;
  - dense Chroma query;
  - BM25 load/search;
  - RRF;
  - rerank;
  - LLM generation;
  - total request time.
- Для reindex логировать:
  - число файлов;
  - число chunks;
  - время extract/chunk/embed/save/BM25;
  - размер BM25-файла;
  - число failed/skipped documents.
- Для SQLite/admin overview логировать:
  - время выполнения heavy sections;
  - count таблиц;
  - размер DB-файла.
- Для frontend stream render:
  - в dev/debug режиме измерять частоту render и размер accumulated text;
  - не включать шумные метрики по умолчанию в production.
- Зафиксировать baseline в отдельном документе или логах перед изменениями этапа 6.

### Файлы

- `core/rag.py`
- `core/retrieval.py`
- `create_vector_db.py`
- `api/routes/admin.py`
- `core/chat_history.py`
- `static/script.js`
- `config/settings.py`

### Критерии готовности

- Можно ответить, где тратится время типичного chat-запроса.
- Можно сравнить reindex до/после incremental changes.
- Метрики не ломают текущий API и не перегружают логи.

## Этап 6. Оптимизация индексации и retrieval

### Цель

Снизить лишнюю работу при reindex/search без ухудшения качества ответов.

### Задачи

- Incremental reindex:
  - manifest по документам;
  - hash/mtime/size;
  - mapping document -> chunk ids;
  - обработка deleted files;
  - обновление Chroma только для изменённых документов.
- BM25 оптимизация:
  - измерить текущий размер и время загрузки;
  - кэшировать построенный BM25 с версией индекса;
  - рассмотреть хранение токенизированного корпуса;
  - при большом корпусе рассмотреть отдельный sparse backend.
- Batch Chroma queries:
  - проверить поддержку batch query embeddings;
  - заменить несколько одиночных queries на один batch-запрос, если результат и качество совпадают.
- Rerank budget:
  - ограничить длину текста для cross-encoder;
  - добавить timeout/fallback;
  - подобрать `RERANK_TOP_N` на основе latency baseline.
- Frontend stream render:
  - во время stream показывать plain text или реже обновлять Markdown;
  - полный Markdown/Mermaid render выполнять на `done`;
  - снизить количество DOM replacements.
- Post-answer запросы:
  - suggestions и related docs запускать по idle или по user action;
  - sidebar обновлять локально, если известны chat id/title.

### Файлы

- `create_vector_db.py`
- `core/chunking.py`
- `core/retrieval.py`
- `core/rag.py`
- `static/script.js`
- `api/routes/documents.py`
- возможно новый модуль `core/index_manifest.py`

### Тесты и проверки

- Incremental reindex меняет только изменённый документ.
- Удалённый документ исчезает из Chroma/BM25.
- Batch Chroma query возвращает эквивалентный набор top ids на fixture.
- Rerank timeout не ломает ответ.
- Визуально stream остаётся плавным на длинном ответе.

### Критерии готовности

- Reindex малого изменения быстрее полного rebuild.
- Retrieval latency не хуже baseline, качество не деградирует на тестовых вопросах.
- UI меньше нагружает main thread во время длинного stream.

## Этап 7. SQLite/history maintenance и admin overview

### Цель

Снизить деградацию истории и админской панели при росте данных.

### Задачи

- Добавить индексы:
  - `messages.created_at`;
  - `messages.role`;
  - `feedback.rating`;
  - `feedback.created_at`;
  - при необходимости expression/compound indexes под реальные запросы.
- Ограничить тяжёлые выборки:
  - date windows;
  - SQL LIMIT до фильтрации в Python;
  - отдельные lightweight endpoints для деталей.
- Кэшировать admin overview на короткий TTL.
- Добавить maintenance для guest/orphan sessions:
  - retention days;
  - dry-run mode;
  - ручной admin endpoint или script.
- Добавить опциональный `VACUUM`/cleanup script.

### Файлы

- `core/chat_history.py`
- `api/routes/admin.py`
- `api/routes/chat.py`
- `api/middleware/auth.py`
- возможно `scripts/maintenance_chat_history.py`
- `tests/test_chat_history.py` или существующие chat/auth tests

### Тесты

- Orphan guest sessions старше retention удаляются.
- Admin overview не сканирует больше заданного лимита для weak answers.
- Индексы создаются идемпотентно при старте.

### Критерии готовности

- Админская панель остаётся отзывчивой на большой тестовой SQLite базе.
- История имеет понятную политику обслуживания.

## Этап 8. Скрипты, CLI и документация

### Цель

Сделать вспомогательные инструменты запускаемыми и согласованными с текущим RAG.

### Задачи

- `scripts/eval_coverage_basket.py`:
  - добавить bootstrap project root;
  - проверить команды `export` и `run`;
  - добавить smoke-тест CLI help/import.
- `scripts/extract_long_paths.py`:
  - исправить путь к `data/`;
  - сделать input/output аргументами;
  - убрать warning по escape sequence.
- `qa_system.py`:
  - либо перевести на `RAGSystem.query()`;
  - либо переименовать/задокументировать как legacy dense CLI;
  - исправить вывод relevance через `doc["score"]`.
- Диагностические scripts:
  - убрать hardcoded модели/URL или читать `config.settings`;
  - явно пометить legacy endpoints.
- README/docs:
  - обновить описание structural chunking;
  - описать hybrid retrieval/BM25;
  - обновить API examples;
  - описать stream/chitchat поведение;
  - описать reindex lifecycle после исправлений.

### Файлы

- `scripts/eval_coverage_basket.py`
- `scripts/extract_long_paths.py`
- `scripts/test_ollama_api.py`
- `scripts/test_available_models.py`
- `qa_system.py`
- `README.md`
- `docs/*.md`
- `tests/test_scripts_smoke.py` или аналогичный новый модуль

### Критерии готовности

- Все documented commands запускаются из корня проекта.
- README не описывает устаревшую RAG-архитектуру.
- CLI не вводит пользователя в заблуждение относительно качества web RAG.

## Этап 9. Сквозное тестовое покрытие

### Цель

Закрыть регрессии из аудита тестами и уменьшить риск повторного появления дефектов.

### Минимальный набор тестов

- Chat validation:
  - типы `message`;
  - длина;
  - `top_k`;
  - `min_score`;
  - `answer_mode`.
- Stream routing:
  - RAG stream;
  - chitchat stream;
  - off-topic stream;
  - stream error.
- Reindex:
  - single active job;
  - partial embedding failure;
  - RAG reload after success;
  - jobs list.
- Retrieval:
  - hybrid sparse fallback;
  - dense-only embedding failure;
  - BM25 load failure.
- Chunking/settings:
  - `CHUNK_OVERLAP >= CHUNK_SIZE`;
  - invalid runtime override.
- Scripts:
  - imports;
  - `--help`;
  - path defaults.
- Frontend:
  - если JS test runner не добавляется, описать manual checklist;
  - если добавляется, покрыть pure functions и state transitions.

### Команды проверки

```powershell
python -m pytest
python -m pytest tests/test_web_app.py
python -m pytest tests/test_retrieval_embed_batch.py
python -m pytest tests/test_chat_runtime.py
```

Для будущего JS/e2e покрытия команду выбрать после решения по инструменту.

## Рекомендуемый порядок PR/коммитов

1. `test: split stream chat tests`
2. `fix: validate chat request options`
3. `fix: normalize chat history error handling`
4. `fix: serialize reindex jobs`
5. `fix: fail reindex on partial embeddings`
6. `fix: reload rag after reindex`
7. `fix: handle llm stream errors explicitly`
8. `fix: stabilize frontend chat state`
9. `fix: add mobile chat navigation`
10. `test: cover reindex and retrieval degradation`
11. `perf: add rag and reindex timing diagnostics`
12. `perf: reduce streaming markdown rerenders`
13. `perf: implement incremental reindex`
14. `docs: sync readme and scripts with current rag`

## Definition of Done для всей программы работ

- `python -m pytest` проходит без падений.
- Все High и Medium пункты из `CODE_AUDIT.md` либо исправлены, либо перенесены в отдельный backlog с обоснованием.
- Reindex не может параллельно повредить активный индекс.
- После reindex приложение отвечает по актуальной базе без restart.
- Chat API возвращает 400/403/404/500 предсказуемо и покрыт тестами.
- Frontend не создаёт дубли чатов после reload и не путает active chat при SSE.
- Есть baseline latency по RAG/reindex и минимум одна оптимизация проверена сравнением до/после.
- README и основные scripts соответствуют текущему поведению проекта.
