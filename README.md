# Векторная база знаний для вопрос-ответной системы

Система для создания векторной базы данных из различных форматов файлов и вопрос-ответной системы на базе знаний с использованием **Ollama** или **LM Studio** (OpenAI-совместимый локальный API) и ChromaDB. Переключение задаётся в `.env` через `INFERENCE_BACKEND`.

Отдельная инструкция для конечных пользователей: `[docs/user_guide.md](docs/user_guide.md)`.
Инструкция для системного администратора по установке на Linux-сервер: `[docs/production_setup.md](docs/production_setup.md)`.
Инструкция для системного администратора по установке на Windows Server: `[docs/windows_server_setup.md](docs/windows_server_setup.md)`.

## Структура проекта

```
wiki_4/
├── api/                     # API модуль
│   ├── middleware/         # Middleware (доступ, роли, гостевые сессии)
│   └── routes/             # API маршруты (chat, auth, documents, admin)
├── config/                  # Конфигурация
│   ├── settings.py         # Централизованные настройки
│   └── logging_config.py   # Настройки логирования
├── core/                    # Ядро системы
│   └── rag.py              # RAG система с поддержкой цитирования
├── data/                    # Исходные данные
│   ├── pages/              # Экспортированные страницы XWiki
│   └── uploads/            # Загруженные файлы
├── docs/                    # Документация
├── logs/                    # Логи системы
├── models/                  # Модели данных
├── tests/                   # Автотесты (pytest)
├── scripts/                 # Скрипты утилит (включая create_admin.py)
├── static/                  # Статические файлы (CSS, JS)
├── templates/               # HTML шаблоны
├── utils/                   # Утилиты
│   ├── cache.py            # Кэширование эмбеддингов
│   ├── embeddings.py       # Работа с эмбеддингами
│   ├── formatters.py       # Форматирование данных
│   └── validators.py       # Валидация данных
├── .env.example             # Пример конфигурации
├── docker-compose.yml       # Docker конфигурация
├── GPU_SETUP.md             # Настройка GPU
├── create_vector_db.py     # Скрипт создания векторной БД
├── qa_system.py            # CLI вопрос-ответная система
├── web_app.py              # Flask веб-приложение
├── start.bat               # Скрипт запуска на Windows
├── requirements.txt        # Зависимости Python
├── chroma_db/              # Векторная база данных (ChromaDB)
├── cache/                  # Кэш эмбеддингов
└── README.md               # Этот файл
```

## Требования

- Python 3.10+
- Сервер инференса: **Ollama** (Docker или нативно) или **LM Studio** с включённым локальным сервером
- Модели эмбеддингов и чата, согласованные с размерностью уже собранной Chroma (для `bge-m3` обычно 1024 измерений)

## Установка

### 1. Установка зависимостей Python

```bash
pip install -r requirements.txt
```

### 2. Настройка Ollama (или LM Studio)

Для **LM Studio** установите приложение, включите локальный сервер, загрузите модели эмбеддингов и чата, в `.env` укажите `INFERENCE_BACKEND=lmstudio` и `OLLAMA_URL` на этот сервер. Раздел «Переключатель Ollama и LM Studio» ниже описывает API.

Для **Ollama** установите и запустите контейнер (или нативный Ollama):

```bash
# Запуск контейнера с поддержкой GPU (рекомендуется)
docker run -d --gpus all -p 11434:11434 --name ollama ollama/ollama

# Или без GPU
docker run -d -p 11434:11434 --name ollama ollama/ollama
```

Загрузите необходимые модели:

```bash
# Модель для эмбеддингов (многоязычная, 1024 измерений)
docker exec -it ollama ollama pull bge-m3

# Модель для генерации ответов
docker exec -it ollama ollama pull qwen3.5:4b

# Проверка доступных моделей
docker exec -it ollama ollama list
```

### 3. Конфигурация

Скопируйте пример конфигурации и настройте параметры:

```bash
cp .env.example .env
```

Отредактируйте `.env` файл с вашими настройками:

- `**INFERENCE_BACKEND**` (`ollama` или `lmstudio`) и `**OLLAMA_URL**`
- Идентификаторы моделей (`OLLAMA_EMBEDDING_MODEL`, `OLLAMA_CHAT_MODEL`): у LM Studio — как в `GET /v1/models` (поле `id`)
- Путь к векторной БД (ChromaDB), размеры чанков, пороги RAG и прочее

### 4. (Опционально) Создание администратора

Если планируете пользоваться вкладками администрирования и управлять базой знаний через веб-интерфейс, создайте admin-пользователя:

```bash
python scripts/create_admin.py --username admin --email admin@example.com
```

Пароль можно передать аргументом `--password` или ввести скрытым вводом при запуске.

### Переключатель Ollama и LM Studio (`INFERENCE_BACKEND`)

Одна переменная задаёт пресет HTTP API и проверок доступности сервера (см. `[config/settings.py](config/settings.py)`):


| `INFERENCE_BACKEND` | Эмбеддинги            | Ответы чата                 | Проверка «сервер жив»               |
| ------------------- | --------------------- | --------------------------- | ----------------------------------- |
| `**ollama**`        | `POST /api/embed`     | `POST /api/generate`        | `GET /api/tags`                     |
| `**lmstudio**`      | `POST /v1/embeddings` | `POST /v1/chat/completions` | `GET /v1/models` (список не пустой) |


Если `**INFERENCE_BACKEND` не задан**, используются явные `**EMBEDDING_API_MODE`** / `**CHAT_API_MODE**` (`ollama` или `openai`), иначе по умолчанию режим Ollama.

Явные `**EMBEDDING_API_MODE**` и `**CHAT_API_MODE**` в `.env` **перекрывают** пресет (для нестандартных схем).

**LM Studio:** укажите `OLLAMA_URL` на локальный API (часто порт `1234`), в моделях — точные `id` из списка сервера, например `text-embedding-bge-m3` и `qwen/qwen3.5-9b`. Перед запросами загрузите модели в LM Studio. Сырой `GET /api/tags` у LM Studio не является признаком работоспособности; приложение для режима `lmstudio` опирается на `/v1/models`.

**Важно:** векторы в Chroma уже привязаны к модели и размерности, использованным при `create_vector_db.py`. Для каждого **нового** вопроса всё равно нужен **рабочий** сервис эмбеддингов той же размерности.

## Использование

### 1. Создание векторной базы данных

Запустите скрипт для создания векторной базы данных из файлов в папке `data/`:

```bash
python create_vector_db.py
```

Скрипт поддерживает следующие форматы файлов:

- **HTML/HTM** - веб-страницы
- **DOCX** - документы Microsoft Word
- **PDF** - документы Adobe Acrobat
- **XLSX/XLS** - электронные таблицы Excel
- **PPTX** - презентации PowerPoint
- **DOC** - документы Word (старый формат)

Скрипт выполнит следующие действия:

- Просканирует папку `data/` и найдет все поддерживаемые файлы
- Извлечет текст из файлов
- Разобьет текст на чанки (по 500 символов с перекрытием 50)
- Сгенерирует эмбеддинги через Ollama (модель bge-m3)
- Сохранит векторную базу данных в папку `chroma_db/`

### 2. Вопрос-ответная система

#### Интерактивный режим

Запустите систему в интерактивном режиме:

```bash
python qa_system.py
```

Система предложит вводить вопросы и будет генерировать ответы на основе найденных документов.

Для выхода введите: `exit`, `quit`, `выход` или `q`

#### Одиночный запрос

Вы также можете задать вопрос напрямую из командной строки:

```bash
python qa_system.py "Как настроить принтер на ТСД?"
```

### 3. Веб-приложение

Запустите Flask веб-приложение:

```bash
python web_app.py
```

Или используйте скрипт для Windows:

```bash
start.bat
```

Приложение будет доступно по адресу: [http://localhost:5000](http://localhost:5000)

#### API Endpoints

> Если в `.env` задан `API_KEY`, для `/api/*` нужен заголовок `X-API-Key`.  
> Если задан `ADMIN_API_KEY`, для `/api/admin/*` также проверяется `X-Admin-Key`.  
> Роуты управления документами (`/api/documents/*`) и админ-диагностики требуют роль `admin` в сессии.

**Системные эндпоинты:**

```bash
curl http://localhost:5000/api/health
curl http://localhost:5000/api/models
```

**RAG-чат:**

```bash
curl -X POST http://localhost:5000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Как настроить принтер на ТСД?","top_k":5,"min_score":0.0,"answer_mode":"default"}'

curl -N -X POST http://localhost:5000/api/chat/stream \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{"message":"Как настроить принтер на ТСД?","chat_id":1,"answer_mode":"steps"}'

curl -X POST http://localhost:5000/api/chat/verify \
  -H "Content-Type: application/json" \
  -d '{"answer":"...","sources":[],"citations":[]}'

curl -X POST http://localhost:5000/api/chat/suggestions \
  -H "Content-Type: application/json" \
  -d '{"answer":"...","sources":[],"citations":[]}'
```

**История диалогов (`/api/chats`):**

```bash
curl http://localhost:5000/api/chats
curl -X POST http://localhost:5000/api/chats -H "Content-Type: application/json" -d '{"title":"Новый чат"}'
curl http://localhost:5000/api/chats/1
curl -X PUT http://localhost:5000/api/chats/1 -H "Content-Type: application/json" -d '{"title":"Обновлённый заголовок"}'
curl -X DELETE http://localhost:5000/api/chats/1
curl -X DELETE http://localhost:5000/api/chats
curl http://localhost:5000/api/chats/1/messages
curl -X POST http://localhost:5000/api/chats/1/messages -H "Content-Type: application/json" -d '{"role":"user","content":"Привет"}'
curl -X POST http://localhost:5000/api/chats/feedback -H "Content-Type: application/json" -d '{"rating":"up","session_id":1}'
```

**Авторизация (`/api/auth`):**

```bash
curl http://localhost:5000/api/auth/me
curl -X POST http://localhost:5000/api/auth/register -H "Content-Type: application/json" -d '{"username":"user1","email":"user1@example.com","password":"secret"}'
curl -X POST http://localhost:5000/api/auth/login -H "Content-Type: application/json" -d '{"identifier":"user1@example.com","password":"secret"}'
curl -X POST http://localhost:5000/api/auth/logout
```

**База знаний (`/api/documents`, только admin):**

```bash
curl http://localhost:5000/api/documents
curl "http://localhost:5000/api/documents/open?path=uploads/example.docx"
curl -X POST http://localhost:5000/api/documents/upload -F "file=@example.docx"
curl -X POST http://localhost:5000/api/documents/preview -F "file=@example.docx"
curl -X POST http://localhost:5000/api/documents/related -H "Content-Type: application/json" -d '{"sources":[],"limit":5}'
curl -X POST http://localhost:5000/api/documents/reindex
curl http://localhost:5000/api/documents/jobs
```

**Админ-диагностика (только admin):**

```bash
curl http://localhost:5000/api/admin/overview
curl http://localhost:5000/api/admin/settings
```

## Конфигурация

Конфигурация централизована в `[config/settings.py](config/settings.py)` и загружается из `.env` файла. Вспомогательные функции: `inference_server_reachable()`, `fetch_remote_model_ids()`, `uses_openai_compatible_api()` (экспорт из пакета `config`).

### Основные параметры

```python
# Сервер LLM: ollama | lmstudio (пресет API; см. раздел выше)
INFERENCE_BACKEND = "ollama"           # или "lmstudio"

# Базовый URL (Ollama :11434, LM Studio — см. порт локального сервера)
OLLAMA_URL = "http://localhost:11434"
OLLAMA_EMBEDDING_MODEL = "bge-m3"      # У LM Studio — id из /v1/models
OLLAMA_CHAT_MODEL = "qwen2.5:7b"       # У LM Studio — id из /v1/models

# ChromaDB настройки
CHROMA_PERSIST_DIR = "./chroma_db"
CHROMA_COLLECTION_NAME = "wiki_knowledge"

# Data настройки
DATA_DIR = "./data"
UPLOAD_DIR = "./data/uploads"
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
BATCH_SIZE = 10

# API настройка
API_HOST = "0.0.0.0"
API_PORT = 5000
TOP_K_RESULTS = 3
API_KEY = ""                            # если задан, все /api/* требуют X-API-Key
ADMIN_API_KEY = ""                      # если задан, /api/admin/* требуют X-Admin-Key

# RAG настройка
RAG_TOP_K = 5
RAG_MAX_CITATIONS = 5
RAG_MIN_SCORE = 0.0                   # порог 0.5 часто отсекает реальные попадания
RAG_MAX_CONTEXT_LENGTH = 3000

# Cache настройка
CACHE_ENABLED = true
CACHE_TTL = 3600
```

### Полный список настроек

Смотрите `[config/settings.py](config/settings.py)` или `.env.example` для полного списка настроек.

## Архитектура

Система использует архитектуру RAG (Retrieval-Augmented Generation):

1. **Извлечение текста**: BeautifulSoup парсит HTML файлы и извлекает чистый текст
2. **Чанкование**: Текст разбивается на фрагменты для лучшего поиска
3. **Эмбеддинги**: сервер инференса (Ollama или LM Studio) генерирует вектор запроса и сопоставляет с индексом
4. **Векторный поиск**: ChromaDB выполняет семантический поиск по запросу
5. **Генерация ответа**: чат-модель на том же сервере формирует ответ по найденному контексту
6. **Цитирование**: Извлекаются и форматируются цитаты из найденных документов
7. **Кэширование**: Эмбеддинги кэшируются для ускорения повторных запросов
8. **Логирование**: Детальное логирование в файлы для отладки

## Примеры использования

### Создание базы данных

```bash
$ python create_vector_db.py
============================================================
Создание векторной базы знаний
============================================================
Ollama доступен по адресу: http://localhost:11434
Модель для эмбеддингов: bge-m3 ✓
Сканирование директории: data
Найдено файлов: 85
Статистика по типам файлов:
  .html: 70
  .docx: 10
  .pdf: 5
Обработка 1/85: WebHome.html
...
Всего создано чанков: 420
Генерация эмбеддингов 1/420
...
Векторная база данных создана! Всего документов: 420
База сохранена в: ./chroma_db
Инвалидация кэша эмбеддингов...
Кэш эмбеддингов очищен
============================================================
Готово!
============================================================
```

### Вопрос-ответ (CLI)

```bash
$ python qa_system.py "Как настроить принтер на ТСД?"
============================================================
Вопрос-ответная система на базе знаний
============================================================
Ollama доступен по адресу: http://localhost:11434
Загружена векторная база данных: 420 документов

Поиск релевантных документов для запроса: 'Как настроить принтер на ТСД?'
Найдено 3 релевантных документов

============================================================
РЕЛЕВАНТНЫЕ ДОКУМЕНТЫ:
============================================================

--- Документ 1 ---
Источник: WMS. Настройка принтера на ТСД
Путь: xwiki/1c/instr/WMS. Настройка принтера на ТСД/WebHome.html
Релевантность: 0.85
Текст: Для настройки принтера на ТСД необходимо...

============================================================
Генерация ответа...
============================================================

------------------------------------------------------------
ОТВЕТ:
------------------------------------------------------------
Для настройки принтера на ТСД выполните следующие шаги:
1. Подключите принтер к ТСД через Bluetooth или USB
2. Установите драйверы принтера
3. Настройте параметры печати в 1С
------------------------------------------------------------
```

### Веб-приложение

Откройте браузер и перейдите по адресу: [http://localhost:5000](http://localhost:5000)

Интерфейс позволяет:

- Вести несколько диалогов: создавать, открывать, переименовывать и удалять чаты
- Автоматически сохранять историю вопросов, ответов, источников и цитат в SQLite
- Получать ответы потоково: сначала отображается статус поиска документов, затем текст ответа по мере генерации
- Настраивать стиль ответа, включая режим «Инструкция для сотрудника», количество источников и минимальную релевантность прямо в интерфейсе
- Просматривать расширенную панель источников с цитатами, путём документа и релевантностью
- Видеть уточняющие вопросы и связанные документы для продолжения работы с темой
- Оценивать ответы кнопками «Полезно» / «Не полезно»
- Загружать документы, смотреть diff новой версии перед сохранением и запускать переиндексацию во вкладке «База знаний»
- Смотреть состояние LLM, Chroma, моделей, RAG-настроек и карту качества базы знаний во вкладке «Админка»
- Скачать текущий диалог в Markdown
- Переключать тему (светлая/тёмная)

### API запрос

```bash
$ curl -X POST http://localhost:5000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Как настроить принтер на ТСД?"}'
```

Ответ:

```json
{
  "answer": "Для настройки принтера на ТСД выполните следующие шаги:\n1. Подключите принтер к ТСД через Bluetooth или USB\n2. Установите драйверы принтера\n3. Настройте параметры печати в 1С\n\n**Источники:**\n\n1. WMS. Настройка принтера на ТСД (ID: abc123) [релевантность: 85.00%]",
  "sources": [
    {
      "title": "WMS. Настройка принтера на ТСД",
      "path": "xwiki/1c/instr/WMS. Настройка принтера на ТСД/WebHome.html",
      "relevance": 0.85
    }
  ],
  "citations": [
    {
      "text": "Для настройки принтера на ТСД необходимо...",
      "source": "WMS. Настройка принтера на ТСД",
      "chunk_id": "abc123",
      "score": 0.85
    }
  ]
}
```

## Источник: WMS. Настройка принтера на ТСД

```

## Тестирование

Запуск тестов:

```bash
pytest
```

Запуск отдельных наборов:

```bash
pytest tests/test_web_app.py
pytest tests/test_auth.py
pytest tests/test_product_features.py
```

## Устранение неполадок

### Ollama недоступен

Убедитесь, что Docker контейнер с Ollama запущен:

```bash
docker ps --filter "name=ollama"
```

Если не запущен:

```bash
docker start ollama
```

### Модель не найдена

Проверьте, что модели загружены:

```bash
docker exec -it ollama ollama list
```

Если модели нет, загрузите их:

```bash
# Модель для эмбеддингов
docker exec -it ollama ollama pull bge-m3

# Модель для генерации ответов
docker exec -it ollama ollama pull qwen3.5:4b
```

### База данных не найдена

Убедитесь, что вы сначала запустили `create_vector_db.py` для создания базы данных.

### Ошибка при генерации эмбеддингов

Проверьте, что модель bge-m3 загружена:

```bash
docker exec -it ollama ollama list
```

Если модели нет, загрузите её:

```bash
docker exec -it ollama ollama pull bge-m3
```

### Кэш эмбеддингов

Если вы изменили данные в папке `data/`, инвалидация кэша может потребоваться:

```bash
# Через Python
python -c "from utils.embeddings import invalidate_embedding_cache; invalidate_embedding_cache()"
```

### Логи

Логи системы хранятся в папке `logs/`:

- `logs/rag/rag_detailed.log` - детальные логи RAG системы
- `logs/web_app.log` - логи веб-приложения

Уровень логирования можно изменить в `.env` файле через параметр `LOG_LEVEL`.

## Лицензия

MIT License