# Аудит кода

Дата: 2026-06-02  
Область: Flask API, RAG/Chroma/BM25, индексация документов, история чатов, frontend, вспомогательные скрипты, документация и тесты.  
Ограничение аудита: безопасность намеренно не рассматривалась; код приложения не исправлялся, обновлён только этот отчёт.

## Краткий вывод

Проект близок к рабочему состоянию, но сейчас тестовый набор не зелёный: `python -m pytest` даёт `68 passed / 1 failed`. Главные дефекты связаны не с синтаксисом, а с жизненным циклом индекса и состоянием чата: после переиндексации долгоживущий `RAGSystem` может продолжать работать со старым BM25/Chroma-состоянием, параллельные reindex-задачи конкурируют за одну коллекцию, а frontend легко рассинхронизируется при reload, ошибках валидации и переключении чатов во время SSE-стрима.

Приоритет исправлений:

1. Стабилизировать reindex: один активный job, атомарное обновление индекса и сброс/пересоздание `RAGSystem`.
2. Привести chat API к единому контракту ошибок и валидировать `message`, `top_k`, `min_score`, `answer_mode` на сервере.
3. Исправить состояние frontend-чата: первый экран, reload, SSE abort/ignore stale responses, mobile sidebar.
4. Починить падающий тест stream-чата и добавить тесты на reindex, RAG-параметры, chitchat stream и partial embedding failures.
5. Синхронизировать CLI/скрипты/README с текущим RAG-поведением.

## Проверки

- `python -m pytest`
- Результат: `68 passed, 1 failed, 3 warnings`.
- Падающий тест: `tests/test_web_app.py::test_api_chat_stream_success`.
- Предупреждения: устаревшие Pydantic V1 `@validator` в `utils/validators.py`; deprecation warning ChromaDB/asyncio на Python 3.14.

## High

### 1. После переиндексации глобальный `RAGSystem` может использовать устаревший BM25/Chroma state

Файлы: `web_app.py`, `api/routes/documents.py`, `core/rag.py`, `core/retrieval.py`, `create_vector_db.py`

`web_app.py` хранит глобальные `collection`, `rag_system`, `db_initialized`. Reindex в `api/routes/documents.py` вызывает `create_vector_db()`, который пересоздаёт коллекцию и сохраняет новый BM25-корпус, но уже созданный `rag_system` не сбрасывается. BM25 bundle в RAG загружается лениво и может остаться привязанным к старому набору chunk id.

Сценарий: запустить приложение, выполнить RAG-запрос, затем `POST /api/documents/reindex`, дождаться `done` и без перезапуска задать вопрос по новым документам. Возможны старые источники, пустые результаты после RRF или непредсказуемая выдача.

Рекомендация: после успешного reindex пересоздавать `RAGSystem` и Chroma collection reference либо вводить явный метод reload, который сбрасывает коллекцию, BM25 bundle и related caches.

### 2. Параллельные reindex-задачи не ограничены

Файл: `api/routes/documents.py`

Каждый `POST /api/documents/reindex` создаёт новый daemon-поток. Нет проверки уже выполняющегося job, нет mutex на Chroma/BM25 и нет очереди. Несколько потоков одновременно пишут в один `CHROMA_PERSIST_DIR`, удаляют/создают одну коллекцию и перезаписывают `bm25_corpus.pkl`.

Сценарий: два быстрых запроса на `/api/documents/reindex`; оба job могут перейти в `running`.

Рекомендация: разрешить один активный reindex на инстанс, второй запрос возвращать как `409` или ставить в очередь; операции переключения коллекции и записи BM25 выполнять под lock.

### 3. Частичный сбой эмбеддингов может silently уменьшить индекс и сломать BM25

Файл: `create_vector_db.py`

В параллельном режиме исключение batch'а логируется, но процесс продолжается. Если хотя бы часть batch'ей успешна, старая коллекция удаляется и создаётся новая с неполным набором `ids`. Затем `bm25_texts` строится из полного `documents`, а `ids` содержит только успешно embedded документы, поэтому `save_bm25_index(ids, bm25_texts)` может завершиться ошибкой длины и оставить hybrid-поиск без свежего BM25.

Сценарий: `EMBEDDING_WORKERS > 1`, один batch эмбеддингов падает, остальные успешны. Итоговая Chroma-коллекция неполная, BM25 не сохранён или не соответствует ожиданиям.

Рекомендация: считать неполное покрытие фатальной ошибкой либо явно сохранять только полностью согласованный subset `ids/texts`; перед удалением старой коллекции проверять, что получены все ожидаемые эмбеддинги.

### 4. `CHUNK_OVERLAP >= CHUNK_SIZE` приводит к зависанию fixed-size chunking

Файлы: `core/chunking.py`, `config/settings_catalog.py`, `api/routes/admin.py`

`chunk_text_fixed_size()` обновляет позицию как `start = end - overlap`. Если `overlap` равен или больше `chunk_size`, `start` не продвигается вперёд или уходит назад. Значения могут попасть из env/runtime overrides, а кросс-полевая проверка инварианта не выполняется.

Сценарий: установить `CHUNK_SIZE=500`, `CHUNK_OVERLAP=600` и запустить индексацию файла, который пойдёт через fixed-size fallback.

Рекомендация: валидировать `0 <= CHUNK_OVERLAP < CHUNK_SIZE` на уровне settings/admin API и добавить guard непосредственно в `chunk_text_fixed_size()`.

### 5. Chat API падает 500 на нестроковом `message`

Файл: `web_app.py`

`/api/chat` и `/api/chat/stream` проверяют наличие ключа `message`, но сразу вызывают `data['message'].strip()`. Для `{"message": null}`, числа или объекта возникает `AttributeError`, и клиент получает 500 вместо ошибки валидации 400.

Сценарий: `POST /api/chat` с JSON `{"message": 123}`.

Рекомендация: проверять `isinstance(message, str)` до `.strip()` и возвращать единый 400 для некорректного типа.

### 6. Падающий тест stream-чата фиксирует рассинхрон chitchat и RAG-веток

Файл: `tests/test_web_app.py`

`test_api_chat_stream_success` отправляет короткое сообщение `"привет мир"`. Текущая логика классифицирует его как chitchat и в `/api/chat/stream` идёт через `stream_chitchat_answer`, поэтому тест не видит статусы `"Ищу релевантные документы"` и `"Документы найдены"` и падает.

Сценарий: `python -m pytest tests/test_web_app.py::test_api_chat_stream_success`.

Рекомендация: разделить тесты на chitchat-stream и RAG-stream; для RAG-stream использовать рабочий вопрос с доменным словарём или мокать классификатор.

## Medium

### 7. User-сообщение сохраняется до завершения RAG и может остаться без assistant-ответа

Файл: `web_app.py`

В non-stream и stream ветках `chat_history.add_message(role="user")` выполняется до RAG/LLM. При `retrieve_error == "search_error"` или необработанном исключении пользовательское сообщение уже записано, а ответа ассистента нет.

Сценарий: Chroma падает после записи user message. После reload в истории остаётся вопрос без ответа, а следующий запрос получает такой контекст в `conversation_history`.

Рекомендация: вводить статус failed, транзакцию user+assistant или откат user-сообщения при фатальной ошибке.

### 8. Stream и non-stream chat по-разному обрабатывают `search_error`

Файл: `web_app.py`

`POST /api/chat` при `retrieve_error == "search_error"` возвращает HTTP 500. `POST /api/chat/stream` отдаёт SSE `type: error` при HTTP 200. В обоих случаях состояние истории отличается от успешного сценария, но контракт для клиента разный.

Сценарий: симулировать падение retrieval и сравнить `/api/chat` с `/api/chat/stream`.

Рекомендация: выбрать единую политику для retriever failures: одинаковый статус, одинаковые записи истории и одинаковые поля диагностики.

### 9. Ошибки потоковой генерации LLM превращаются в обычный текст ответа

Файлы: `utils/embeddings.py`, `core/rag.py`, `web_app.py`

`chat_completion_stream()` при HTTP/timeout/connection errors `yield`-ит строки вида `"Произошла ошибка при генерации ответа..."`. Верхний уровень может накопить этот текст как обычный assistant answer и сохранить его в историю.

Сценарий: LLM был доступен на preflight, но упал во время генерации. Пользователь и история получают служебную ошибку как будто это ответ модели.

Рекомендация: возвращать отдельное error-событие/исключение и не сохранять служебный текст как content успешного assistant-сообщения.

### 10. `top_k`, `min_score`, `answer_mode` принимаются без серверного clamp/whitelist

Файлы: `config/chat_runtime.py`, `web_app.py`, `core/retrieval.py`

`resolve_chat_rag_options()` приводит значения к `int/float`, но не ограничивает диапазон. `answer_mode` берётся из payload как есть. В итоге `top_k=0`, отрицательный `min_score`, огромный `top_k` или неизвестный mode уходят дальше в retrieval/prompt logic.

Сценарий: `POST /api/chat` с `{"message":"рабочий вопрос","top_k":0,"min_score":-1,"answer_mode":"unknown"}`.

Рекомендация: на backend ограничить `top_k`, `min_score` и whitelist `answer_mode`; синхронизировать лимиты с UI и `settings_catalog`.

### 11. Несуществующий `chat_id` в `/api/chat` возвращает 403 вместо 404

Файл: `web_app.py`

`_resolve_chat_session()` при переданном `chat_id` получает session и, если её нет, бросает тот же `PermissionError`, что и при отсутствии доступа. Клиент не отличает удалённый чат от чужого.

Сценарий: `POST /api/chat` с `chat_id`, которого нет в SQLite.

Рекомендация: отдельно возвращать 404 для отсутствующей сессии и 403 для существующей, но недоступной.

### 12. `/api/chats` принимает отрицательные `limit` и `offset`

Файлы: `api/routes/chat.py`, `core/chat_history.py`

`limit` и `offset` из query string не нормализуются. Для авторизованного пользователя отрицательный limit может попасть в SQL; в SQLite `LIMIT -1` означает «без лимита». Для гостя slicing с отрицательными значениями тоже даёт неочевидный результат.

Сценарий: `GET /api/chats?limit=-1`.

Рекомендация: clamp `limit` в разумный диапазон, `offset >= 0`; аналогично проверить feedback/list endpoints.

### 13. Hybrid retrieval не падает обратно на BM25 при сбое dense-эмбеддингов

Файл: `core/retrieval.py`

В режиме `hybrid`, если dense embeddings не получены, функция возвращает `embedding_unavailable` до использования BM25. При наличии валидного BM25-корпуса поиск мог бы вернуть sparse-only результаты, но сейчас временный сбой embed API отключает весь retrieval.

Сценарий: `RETRIEVAL_MODE=hybrid`, BM25-файл есть, сервис эмбеддингов недоступен.

Рекомендация: добавить degraded fallback на sparse-only с диагностикой, либо явно документировать, что hybrid требует dense-часть.

### 14. Split `EMBEDDING_API_MODE` и `CHAT_API_MODE` могут ломать health/model checks

Файл: `config/settings.py`

Проверка доступности и список моделей завязаны на общий режим совместимости, хотя embedding и chat API могут быть разными. При нестандартной конфигурации один сервис может проверяться endpoint'ом другого.

Сценарий: embeddings через Ollama, chat через OpenAI-compatible endpoint или наоборот.

Рекомендация: разделить health checks и model discovery для embedding backend и chat backend.

### 15. Frontend создаёт/показывает состояние чата до клиентской валидации сообщения

Файлы: `static/script.js`, `web_app.py`

`handleSubmit()` вызывает `ensureChat()`, добавляет user message в DOM и только затем получает 400 от сервера для слишком короткого/длинного сообщения. Сервер такое сообщение в БД не пишет, но UI уже показывает его вместе с ошибкой.

Сценарий: отправить `"hi"` длиной 2 символа. В текущем DOM появится user message и ошибка, после reload они исчезнут, а пустой чат может остаться в sidebar.

Рекомендация: валидировать длину и диапазоны RAG-параметров на клиенте до `ensureChat()` и `addMessage()`, а при ошибке откатывать оптимистичный DOM.

### 16. Активный чат не восстанавливается после reload

Файл: `static/script.js`

`currentChatId` хранится только в памяти. После F5 sidebar загружает историю, но `currentChatId` снова `null`; первая отправка без выбора чата создаёт новый чат вместо продолжения последнего.

Сценарий: начать гостевой диалог, обновить страницу, сразу отправить следующий вопрос. В истории появляется новый чат.

Рекомендация: сохранять текущий chat id в `sessionStorage/localStorage` или автоматически открывать последний чат после `loadChats()`.

### 17. Гонка SSE при переключении чата во время генерации

Файл: `static/script.js`

У stream-запроса нет `AbortController` и request id. Если во время ответа открыть другой чат, старый stream продолжает выполняться и в `done` может перезаписать `currentChatId` старым `payload.chat_id`. Ответ также может записываться в DOM-узлы, которые уже удалены через `resetMessages()`.

Сценарий: отправить долгий вопрос, во время генерации кликнуть другой чат, дождаться завершения.

Рекомендация: отменять активный stream при `openChat()`/новой отправке или игнорировать устаревшие события по generation id.

### 18. Обрыв SSE без `done` оставляет незавершённый ответ

Файл: `static/script.js`

`readStream()` имеет `doneReceived`, но после окончания reader loop не проверяет, был ли получен `done` или `error`. При сетевом обрыве остаётся частичный ответ с состоянием `streaming-in-progress` и без кнопок источников/feedback.

Сценарий: прервать сеть во время stream generation.

Рекомендация: после loop, если `doneReceived === false`, снять streaming-класс и показать системную ошибку/предложение повторить.

### 19. На mobile полностью скрыта навигация по чатам

Файлы: `static/style.css`, `templates/index.html`

При ширине `max-width: 768px` `.workspace-sidebar` получает `display: none`. В sidebar находятся «Новый чат», поиск, список и очистка истории; альтернативного drawer/FAB/header-кнопки нет.

Сценарий: открыть UI на телефоне или в DevTools с шириной 768px.

Рекомендация: сделать mobile drawer/sidebar toggle или продублировать ключевые действия в header.

### 20. Первый пользовательский вопрос добавляется под статическим welcome-сообщением

Файлы: `templates/index.html`, `static/script.js`

HTML содержит начальное приветствие в `#messages`. При первой отправке `handleSubmit()` не очищает контейнер и не вызывает `resetMessages()`, поэтому диалог начинается ниже приветственного сообщения, хотя в истории чата этого welcome-сообщения нет.

Сценарий: открыть страницу и сразу отправить первый вопрос.

Рекомендация: перед первым user message в новом чате очищать welcome либо генерировать welcome только через JS-состояние.

### 21. Polling reindex jobs может запускаться несколькими цепочками

Файл: `static/script.js`

Каждый `startReindex()` вызывает `pollJobs()`, а тот ставит новый `setTimeout` при active job. Нет единого timer id и отмены предыдущей цепочки.

Сценарий: быстро нажать «Переиндексировать» несколько раз.

Рекомендация: хранить polling timer/generation и гарантировать только одну активную цепочку.

### 22. Экспорт диалога включает служебные UI-элементы

Файлы: `static/script.js`, `static/js/clipboard.js`

Экспорт берёт `innerText` из `.message-content`, где после ответа находятся кнопки источников, проверки, feedback, suggestions и результаты verify. В markdown-экспорт попадает не только текст диалога.

Сценарий: получить ответ с источниками, нажать «Скачать диалог».

Рекомендация: экспортировать из сохранённой истории API или клонировать DOM и удалять служебные элементы перед чтением текста.

### 23. `eval_coverage_basket.py` не запускается как в примерах

Файл: `scripts/eval_coverage_basket.py`

Скрипт импортирует `config`, `core.chat_history`, `core.rag`, но не добавляет корень проекта в `sys.path`. При запуске в стиле `python scripts/eval_coverage_basket.py ...` из корня на стандартной конфигурации Python возможен `ModuleNotFoundError: No module named 'config'`.

Сценарий: выполнить пример из docstring.

Рекомендация: добавить bootstrap ROOT по аналогии с другими scripts или оформить запуск как `python -m scripts.eval_coverage_basket`.

### 24. `extract_long_paths.py` ищет архивы в `scripts/data`, а не в корневом `data`

Файл: `scripts/extract_long_paths.py`

`data_dir = Path(__file__).parent / 'data'` указывает на `scripts/data`. По структуре проекта и документации данные лежат в `data/` в корне.

Сценарий: `python scripts/extract_long_paths.py` сообщает, что ожидаемые zip-файлы не найдены.

Рекомендация: использовать `Path(__file__).resolve().parents[1] / "data"` или принимать путь аргументом.

### 25. CLI `qa_system.py` расходится с основным RAG

Файлы: `qa_system.py`, `utils/embeddings.py`, `core/rag.py`

CLI использует legacy-путь `search_documents()` + `generate_answer()`: dense-only поиск, `TOP_K_RESULTS`, без BM25/hybrid, query expansion, chitchat/off-topic routing, deep retrieval и цитирования как в веб-приложении.

Сценарий: один и тот же вопрос в CLI и web UI даёт разные источники и качество ответа.

Рекомендация: перевести CLI на `RAGSystem.query()` или явно документировать как legacy-инструмент.

## Low

### 26. `/api/health` выставляет `status: ok`, не учитывая `rag`

Файл: `web_app.py`

Ответ содержит `rag`, но итоговый `status` зависит только от `ollama` и `database`. Мониторинг может увидеть `ok`, хотя `RAGSystem` не инициализирован.

Рекомендация: включить `rag_status` в итоговый статус или добавить отдельное поле `degraded`.

### 27. Admin-only вкладки видны до завершения `/api/auth/me`

Файлы: `templates/index.html`, `static/script.js`

Кнопки «База знаний» и «Админка» присутствуют в HTML без `hidden`; скрываются только после async `initializeAuth()` и `applyAuthState()`.

Сценарий: замедлить сеть и обновить страницу гостем.

Рекомендация: скрывать `.admin-only` по умолчанию в HTML/CSS и показывать только после подтверждения роли.

### 28. Health-индикатор frontend игнорирует поле `rag`

Файлы: `static/script.js`, `web_app.py`

`checkHealth()` показывает «Онлайн», если `data.ollama && data.database`, но не учитывает `data.rag`.

Рекомендация: синхронизировать условие UI с backend health contract.

### 29. Mermaid theme не обновляется после смены темы

Файлы: `static/script.js`, `static/js/theme.js`

`ensureMermaidInitialized()` инициализирует Mermaid один раз и больше не меняет тему. После переключения light/dark уже отрендеренные и будущие диаграммы могут оставаться в старой теме до reload.

Рекомендация: переинициализировать Mermaid и перерендеривать диаграммы при смене темы.

### 30. Поиск чатов в sidebar подвержен гонке ответов

Файл: `static/script.js`

Debounce вызывает `loadChats()`, но запросы не отменяются и не имеют sequence id. Более ранний ответ может прийти позже и перезаписать список чатов неактуальной выдачей.

Рекомендация: использовать `AbortController` или request counter.

### 31. `showInlineError()` маскирует системные ошибки под ответ бота

Файл: `static/script.js`

Ошибки UI-операций рендерятся через `addMessage(..., 'bot')`. Это смешивает системные ошибки с сообщениями ассистента и затем может попасть в экспорт.

Рекомендация: использовать toast/banner/system message, отделённый от истории чата.

### 32. `qa_system.py` печатает релевантность как `1 - distance`

Файл: `qa_system.py`

`search_documents()` уже нормализует `score`, но CLI выводит `1 - doc['distance']` без clamp. Для некоторых distance возможно отрицательное или >1 значение.

Рекомендация: выводить `doc['score']`.

### 33. `utils/validators.py` использует устаревший Pydantic V1 API и не подключён к chat routes

Файлы: `utils/validators.py`, `api/middleware/validation.py`, `web_app.py`

Тестовый прогон показывает deprecation warnings для `@validator`. При этом runtime chat endpoints не используют эти схемы, поэтому лимиты и defaults расходятся с фактическим поведением.

Рекомендация: либо подключить единые Pydantic v2 схемы к маршрутам, либо удалить/переписать мёртвую валидацию.

### 34. README расходится с текущей реализацией RAG

Файл: `README.md`

README местами описывает fixed-size chunking «500 символов с перекрытием 50», простой Chroma vector search и старые примеры вывода, тогда как код по умолчанию использует structural chunking и hybrid retrieval с BM25.

Рекомендация: обновить архитектурное описание, примеры логов и пример API-ответа под текущий `RAGSystem`.

## Возможности оптимизации

### 35. Reindex выполняет полный rebuild даже при малых изменениях

Файлы: `api/routes/documents.py`, `create_vector_db.py`, `core/retrieval.py`

Текущий путь reindex заново обрабатывает все документы, генерирует все эмбеддинги, пересоздаёт Chroma-коллекцию и BM25-корпус. Для небольшой правки одного файла стоимость такая же, как для полной базы знаний.

Эффект: рост времени reindex пропорционально всему корпусу; при большом `data/` админская операция становится долгой и мешает обычному RAG.

Рекомендация: хранить manifest с `path`, `mtime`, `size`, content hash и списком chunk ids; переиндексировать только изменённые/новые/удалённые документы. Для BM25 можно либо перестраивать corpus после incremental Chroma update, либо держать отдельный lightweight inverted index/SQLite-таблицу.

### 36. BM25-корпус полностью грузится и строится в памяти

Файлы: `core/retrieval.py`, `core/rag.py`

`load_bm25_okapi()` читает весь pickle с текстами, токенизирует весь корпус и создаёт BM25-объект в памяти. На большом корпусе это увеличит стартовую задержку первого hybrid-запроса и потребление RAM.

Эффект: первый запрос после старта или после reload может быть заметно медленнее; несколько worker-процессов будут держать копии одного корпуса.

Рекомендация: измерить размер `bm25_corpus.pkl` и latency первого запроса; при росте корпуса рассмотреть persisted sparse index, ленивое mmap/SQLite-хранилище токенов или отдельный search service. Минимально - логировать время загрузки BM25 и количество документов.

### 37. Dense retrieval делает несколько Chroma-запросов параллельно на каждый expanded query

Файл: `core/retrieval.py`

При query expansion список dense-вариантов отправляется в `_dense_rankings_parallel()`, где каждый вариант вызывает отдельный `collection.query()`. Это проще, но может быть дороже batch-запроса и сильнее нагружает Chroma.

Эффект: при нескольких dense queries latency и contention растут; параллельные Chroma-запросы могут конкурировать за локальное хранилище.

Рекомендация: проверить, поддерживает ли текущая Chroma-версия batch `query_embeddings=[...]` с последующим разбором результатов. Если да, заменить несколько одиночных query на один batch-запрос и сравнить latency.

### 38. Rerank cross-encoder может стать главным bottleneck без budget control

Файлы: `core/retrieval.py`, `config/settings.py`

При включённом `RERANK_ENABLED` cross-encoder прогоняет пары `[query, document]` для `RERANK_TOP_N`. Это качественно полезно, но на CPU/слабой GPU быстро становится самой дорогой частью запроса.

Эффект: резкие задержки при больших `RAG_FUSION_CANDIDATES`, `RERANK_TOP_N` или длинных chunks.

Рекомендация: добавить метрики latency по этапам retrieval/rerank/generation, ограничить длину текста для rerank, держать отдельный timeout/budget и отключать rerank при перегрузке.

### 39. Admin overview делает тяжёлые агрегаты на лету

Файлы: `api/routes/admin.py`, `core/chat_history.py`

Админская сводка собирает usage/feedback/weak answers/documents при каждом открытии панели. Некоторые функции читают много строк и фильтруют в Python.

Эффект: по мере роста SQLite history вкладка «Админка» будет открываться медленнее и может блокировать обычные операции с историей.

Рекомендация: добавить SQL-level limits/date windows, индексы по `messages.created_at`, `messages.role`, `feedback.rating`, `feedback.created_at`; тяжёлые показатели кэшировать на короткий TTL.

### 40. Frontend перерендеривает Markdown целиком на каждом streaming tick

Файл: `static/script.js`

Во время SSE `readStream()` накапливает весь ответ в `accumulated` и периодически делает `streamContent.innerHTML = formatMessage(accumulated)`. Для длинных ответов это повторный parse/sanitize всего текста, а не только нового delta.

Эффект: на длинных ответах или слабых клиентах возможны лаги ввода/скролла; Mermaid placeholders и DOM пересоздаются многократно.

Рекомендация: держать throttling по времени/размеру, рендерить plain text во время стрима и делать полный Markdown render только на `done`, либо использовать incremental append для простого текста.

### 41. Дополнительные запросы после каждого ответа увеличивают latency UI

Файл: `static/script.js`

После ответа клиент запускает несколько независимых операций: suggestions, related documents, reload chats, verify по кнопке позже. Это полезно, но часть запросов стартует сразу после основного ответа и может создавать шум на backend.

Эффект: интерфейс визуально «догружается», backend получает burst после каждого ответа, особенно у admin-пользователя.

Рекомендация: откладывать suggestions/related documents до idle time или раскрытия блока пользователем; `loadChats()` после ответа можно заменить локальным обновлением текущего элемента sidebar.

### 42. История чатов и гостевые сессии не имеют обслуживания/архивации

Файлы: `core/chat_history.py`, `api/routes/chat.py`, `api/middleware/auth.py`

SQLite хранит сообщения, источники, цитаты и metadata JSON. Гостевые чаты, потерявшие cookie, остаются в базе без регулярной очистки.

Эффект: рост файла SQLite, замедление списков/поиска/админских агрегатов и увеличение backup size.

Рекомендация: добавить retention policy для guest/orphan-сессий, архивирование старых сообщений и периодический `VACUUM`/maintenance job.

### 43. Логи RAG/LLM могут стать заметной I/O-нагрузкой

Файлы: `core/rag.py`, `config/settings.py`

Подробные RAG-логи и `llm_exchange.jsonl` полезны для диагностики качества, но при активном использовании каждый запрос пишет крупные JSONL/текстовые записи.

Эффект: лишний disk I/O, большие log-файлы, замедление на HDD/сетевых дисках.

Рекомендация: ввести sampling, отдельный уровень детализации для production, метрику bytes written per request и возможность отключать llm exchange logging без перезапуска.

## Пробелы в тестах

- Нет теста, что после успешного reindex глобальный `RAGSystem`/BM25 сбрасывается или пересоздаётся.
- Нет тестов на запрет/очередь параллельных `/api/documents/reindex`.
- Нет тестов `create_vector_db()` на partial embedding failure и согласованность `ids/texts` для BM25.
- Нет негативных тестов для `message` не-строка, `top_k=0`, `top_k` слишком большой, `min_score < 0`, неизвестный `answer_mode`.
- Нет HTTP-тестов для stream chitchat/off-topic ветки; текущий падающий тест показывает этот пробел.
- Нет frontend/unit/e2e-тестов на reload активного чата, переключение чата во время SSE, mobile sidebar и клиентскую валидацию.
- Нет smoke-тестов для `scripts/eval_coverage_basket.py`, `scripts/extract_long_paths.py`, `qa_system.py`.
- Нет тестов на split embedding/chat backend health checks.

## Рекомендуемый порядок работ

1. Починить CI: разделить RAG-stream и chitchat-stream тесты, добиться зелёного `pytest`.
2. Закрыть критичные ошибки индексации: partial embedding failure, lock/queue reindex, reload `RAGSystem`.
3. Укрепить backend-контракты: типы входных данных, clamp параметров, единое поведение stream/non-stream ошибок.
4. Исправить frontend-состояние чата: welcome, reload, SSE cancellation, validation before optimistic UI.
5. Добавить базовые latency-метрики по этапам RAG, reindex и frontend-stream render, чтобы оптимизации опирались на измерения.
6. Обновить CLI/скрипты/README и добавить smoke-тесты на вспомогательные инструменты.
