# Инструкция администратора по установке Wiki QA System на Linux-сервер

Документ описывает установку веб-приложения Wiki QA System на Linux-сервер, настройку инференса через Ollama или LM Studio, первичную индексацию базы знаний, запуск как systemd-сервиса, публикацию через Nginx и базовое сопровождение.

Для Windows Server используйте отдельную инструкцию: `[docs/windows_server_setup.md](windows_server_setup.md)`.

Инструкция рассчитана на администратора, который разворачивает приложение в рабочей среде. Примеры ниже используют Ubuntu/Debian и путь установки `/opt/wiki-qa`.

## 1. Что устанавливается

Wiki QA System - это Flask-приложение для вопросно-ответного поиска по базе знаний. Система использует:

- Python-приложение `web_app.py` для веб-интерфейса и API.
- SQLite для пользователей, истории чатов и служебных данных.
- ChromaDB в локальном каталоге для векторной базы.
- Ollama или LM Studio для эмбеддингов и генерации ответов.
- Каталоги `data`, `chroma_db`, `cache` и `logs` для рабочих данных.

Основные сетевые порты:

- `5000` - внутренний порт Flask/Gunicorn.
- `80` и `443` - публичный доступ через Nginx.
- `11434` - Ollama API, если используется Ollama.
- `1234` или другой локальный порт - LM Studio API, если используется LM Studio.

## 2. Требования к серверу

Минимальная конфигурация:

- ОС: Ubuntu 22.04 LTS, Debian 12 или совместимая Linux-система.
- CPU: 2 ядра.
- RAM: 8 ГБ.
- Диск: от 50 ГБ SSD.
- Python: 3.10 или новее.
- Доступ в интернет для установки пакетов и загрузки моделей.

Рекомендуемая конфигурация:

- CPU: 4+ ядра.
- RAM: 16+ ГБ.
- Диск: 100+ ГБ SSD.
- GPU NVIDIA с установленным драйвером и NVIDIA Container Toolkit, если планируется запуск больших моделей в Ollama.

Проверьте сервер:

```bash
cat /etc/os-release
python3 --version
nproc
free -h
df -h
```

## 3. Подготовка системы

Обновите пакеты и установите базовые зависимости:

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y \
  git curl wget ca-certificates gnupg \
  python3 python3-venv python3-dev python3-pip \
  build-essential nginx certbot python3-certbot-nginx \
  sqlite3 htop net-tools
```

Создайте отдельного пользователя приложения:

```bash
sudo useradd -r -s /bin/bash -m -d /opt/wiki-qa wikiqa
sudo mkdir -p /opt/wiki-qa
sudo chown -R wikiqa:wikiqa /opt/wiki-qa
```

Все дальнейшие команды установки приложения выполняйте от пользователя `wikiqa`, если не указано `sudo`:

```bash
sudo -iu wikiqa
```

## 4. Установка проекта

Склонируйте репозиторий или скопируйте архив проекта на сервер:

```bash
cd /opt
git clone <URL_РЕПОЗИТОРИЯ> wiki-qa
sudo chown -R wikiqa:wikiqa /opt/wiki-qa
sudo -iu wikiqa
cd /opt/wiki-qa
```

Создайте виртуальное окружение и установите зависимости:

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install gunicorn
```

Проверьте, что приложение импортируется:

```bash
python -c "from web_app import app; print(app.name)"
```

## 5. Настройка инференса

Для работы системы нужен сервер, который умеет:

- строить эмбеддинги для вопросов и документов;
- генерировать текстовые ответы.

Поддерживаются два варианта: Ollama и LM Studio. В продакшене обычно проще обслуживать Ollama на том же сервере или на отдельной машине в локальной сети.

### Вариант A: Ollama

Установите Docker от пользователя с правами `sudo`:

```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker wikiqa
```

Перезайдите в сессию пользователя `wikiqa` после добавления в группу `docker`.

Запустите Ollama без GPU:

```bash
docker run -d \
  --name ollama \
  --restart unless-stopped \
  -p 127.0.0.1:11434:11434 \
  -v ollama_data:/root/.ollama \
  ollama/ollama
```

Если настроен GPU NVIDIA, используйте:

```bash
docker run -d \
  --name ollama \
  --restart unless-stopped \
  --gpus all \
  -p 127.0.0.1:11434:11434 \
  -v ollama_data:/root/.ollama \
  ollama/ollama
```

Загрузите модели:

```bash
docker exec -it ollama ollama pull bge-m3
docker exec -it ollama ollama pull qwen2.5:7b
docker exec -it ollama ollama list
curl http://127.0.0.1:11434/api/tags
```

Важно: модель эмбеддингов должна совпадать с моделью, которой создана ChromaDB. Для `bge-m3` размерность обычно 1024. Если заменить embedding-модель, векторную базу нужно пересоздать.

### Вариант B: LM Studio

LM Studio должен быть установлен на сервере или на отдельной машине, доступной приложению по сети.

В LM Studio:

1. Загрузите embedding-модель и chat-модель.
2. Включите локальный OpenAI-совместимый сервер.
3. Запомните базовый URL, например `http://127.0.0.1:1234`.
4. Получите точные идентификаторы моделей:

```bash
curl http://127.0.0.1:1234/v1/models
```

В `.env` для LM Studio обязательно укажите `INFERENCE_BACKEND=lmstudio`, URL сервера и `id` моделей из ответа `/v1/models`.

## 6. Конфигурация `.env`

Создайте конфигурацию:

```bash
cd /opt/wiki-qa
cp .env.example .env
nano .env
```

Сгенерируйте секретные ключи:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
python -c "import secrets; print(secrets.token_hex(32))"
```

Пример `.env` для установки с Ollama:

```dotenv
INFERENCE_BACKEND=ollama
OLLAMA_URL=http://127.0.0.1:11434
OLLAMA_EMBEDDING_MODEL=bge-m3
OLLAMA_CHAT_MODEL=qwen2.5:7b
CHAT_MAX_TOKENS=2048

CHROMA_PERSIST_DIR=/opt/wiki-qa/chroma_db
CHROMA_COLLECTION_NAME=wiki_knowledge
DATA_DIR=/opt/wiki-qa/data
UPLOAD_DIR=/opt/wiki-qa/data/uploads

API_HOST=127.0.0.1
API_PORT=5000
FLASK_DEBUG=false
CORS_ORIGINS=https://wiki.example.com

RAG_TOP_K=5
RAG_MIN_SCORE=0.0
RAG_MAX_CITATIONS=5
RAG_MAX_CONTEXT_LENGTH=3000

LOG_LEVEL=INFO
LOG_DIR=/opt/wiki-qa/logs

SECRET_KEY=<СГЕНЕРИРОВАННЫЙ_SECRET_KEY>
JWT_SECRET_KEY=<СГЕНЕРИРОВАННЫЙ_JWT_SECRET_KEY>
JWT_EXPIRATION_HOURS=24

DATABASE_PATH=/opt/wiki-qa/data/wiki_qa.db

CACHE_ENABLED=true
CACHE_TTL=3600
CACHE_DIR=/opt/wiki-qa/cache

MAX_FILE_SIZE=10485760
ALLOWED_EXTENSIONS=html,htm,txt,docx,doc,pdf,xlsx,xls,pptx
```

Для LM Studio замените блок инференса:

```dotenv
INFERENCE_BACKEND=lmstudio
OLLAMA_URL=http://127.0.0.1:1234
OLLAMA_EMBEDDING_MODEL=<ID_EMBEDDING_МОДЕЛИ_ИЗ_/v1/models>
OLLAMA_CHAT_MODEL=<ID_CHAT_МОДЕЛИ_ИЗ_/v1/models>
```

Назначение важных параметров:

- `INFERENCE_BACKEND` - `ollama` или `lmstudio`; задает формат API-запросов.
- `OLLAMA_URL` - базовый URL сервера инференса. Название переменной историческое и используется также для LM Studio.
- `OLLAMA_EMBEDDING_MODEL` - модель эмбеддингов.
- `OLLAMA_CHAT_MODEL` - модель генерации ответов.
- `CHROMA_PERSIST_DIR` - каталог локальной векторной базы.
- `DATA_DIR` - каталог исходных документов базы знаний.
- `UPLOAD_DIR` - каталог документов, загруженных через веб-интерфейс.
- `DATABASE_PATH` - SQLite-файл пользователей, чатов и истории.
- `SECRET_KEY` и `JWT_SECRET_KEY` - обязательные секреты, которые нельзя оставлять значениями из примера.
- `API_KEY` - необязательный ключ для защиты `/api/*`.
- `ADMIN_API_KEY` - необязательный ключ для защиты `/api/admin/*`.
- `CORS_ORIGINS` - список разрешенных origin через запятую; в продакшене не оставляйте `*`, если фронтенд доступен по известному домену.

Проверьте права:

```bash
chmod 600 /opt/wiki-qa/.env
mkdir -p /opt/wiki-qa/data/uploads /opt/wiki-qa/chroma_db /opt/wiki-qa/cache /opt/wiki-qa/logs
chown -R wikiqa:wikiqa /opt/wiki-qa
```

Проверьте загрузку настроек:

```bash
source venv/bin/activate
python -c "from config import settings; print(settings.INFERENCE_BACKEND, settings.OLLAMA_URL); print(settings.validate())"
```

## 7. Подготовка базы знаний

Скопируйте документы в каталог `DATA_DIR`, например:

```bash
mkdir -p /opt/wiki-qa/data
rsync -av /path/to/exported/wiki/ /opt/wiki-qa/data/
```

Поддерживаемые форматы:

- `html`, `htm`, `txt`;
- `docx`, `doc`;
- `pdf`;
- `xlsx`, `xls`;
- `pptx`.

Создайте векторную базу:

```bash
cd /opt/wiki-qa
source venv/bin/activate
python create_vector_db.py
```

После завершения проверьте коллекцию ChromaDB:

```bash
python - <<'PY'
import chromadb
from config import settings

client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
collection = client.get_collection(settings.CHROMA_COLLECTION_NAME)
print("Документов в ChromaDB:", collection.count())
PY
```

Если менялись исходные документы или embedding-модель, пересоздайте векторную базу и очистите кэш:

```bash
python -c "from utils.embeddings import invalidate_embedding_cache; invalidate_embedding_cache()"
python create_vector_db.py
```

## 8. Создание администратора

Администратор нужен для вкладок управления документами и диагностики.

```bash
cd /opt/wiki-qa
source venv/bin/activate
python scripts/create_admin.py --username admin --email admin@example.com
```

Скрипт запросит пароль скрытым вводом. Также пароль можно передать параметром `--password`, но для продакшена безопаснее вводить его интерактивно.

## 9. Проверочный запуск

Запустите приложение вручную:

```bash
cd /opt/wiki-qa
source venv/bin/activate
python web_app.py
```

В другом терминале проверьте:

```bash
curl http://127.0.0.1:5000/api/health
curl http://127.0.0.1:5000/api/models
```

Проверьте вопрос к базе знаний:

```bash
curl -X POST http://127.0.0.1:5000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Тестовый вопрос","top_k":3,"min_score":0.0}'
```

Остановите ручной запуск `Ctrl+C` и переходите к настройке сервиса.

## 10. Systemd-сервис

Создайте сервис:

```bash
sudo nano /etc/systemd/system/wiki-qa.service
```

Содержимое:

```ini
[Unit]
Description=Wiki QA System
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=wikiqa
Group=wikiqa
WorkingDirectory=/opt/wiki-qa
EnvironmentFile=/opt/wiki-qa/.env
ExecStart=/opt/wiki-qa/venv/bin/gunicorn \
  --bind 127.0.0.1:5000 \
  --workers 2 \
  --threads 4 \
  --timeout 300 \
  --access-logfile /opt/wiki-qa/logs/access.log \
  --error-logfile /opt/wiki-qa/logs/error.log \
  --log-level info \
  web_app:app
Restart=always
RestartSec=10
KillSignal=SIGINT

[Install]
WantedBy=multi-user.target
```

Запустите сервис:

```bash
sudo systemctl daemon-reload
sudo systemctl enable wiki-qa
sudo systemctl start wiki-qa
sudo systemctl status wiki-qa
```

Проверьте логи:

```bash
sudo journalctl -u wiki-qa -n 100 --no-pager
tail -f /opt/wiki-qa/logs/error.log
```

Если модель отвечает медленно, увеличьте `--timeout`. Если сервер маломощный, уменьшите `--workers` до `1`.

## 11. Nginx reverse proxy

Создайте конфигурацию:

```bash
sudo nano /etc/nginx/sites-available/wiki-qa
```

Пример для домена `wiki.example.com`:

```nginx
upstream wikiqa_backend {
    server 127.0.0.1:5000;
    keepalive 32;
}

server {
    listen 80;
    listen [::]:80;
    server_name wiki.example.com;

    access_log /var/log/nginx/wiki-qa-access.log;
    error_log /var/log/nginx/wiki-qa-error.log;

    client_max_body_size 10M;

    location /static/ {
        alias /opt/wiki-qa/static/;
        expires 30d;
        add_header Cache-Control "public";
    }

    location / {
        proxy_pass http://wikiqa_backend;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_read_timeout 300s;
        proxy_connect_timeout 60s;
        proxy_send_timeout 300s;
    }
}
```

Активируйте сайт:

```bash
sudo ln -s /etc/nginx/sites-available/wiki-qa /etc/nginx/sites-enabled/wiki-qa
sudo nginx -t
sudo systemctl reload nginx
```

Откройте `http://wiki.example.com` и войдите под созданным администратором.

## 12. HTTPS

Выпустите сертификат Let's Encrypt:

```bash
sudo certbot --nginx -d wiki.example.com
```

Проверьте автопродление:

```bash
sudo certbot renew --dry-run
```

После включения HTTPS укажите точный домен в `.env`:

```dotenv
CORS_ORIGINS=https://wiki.example.com
```

Затем перезапустите приложение:

```bash
sudo systemctl restart wiki-qa
```

## 13. Ограничение доступа и безопасность

Рекомендуемые меры:

- Не публикуйте порт `5000` наружу; он должен слушать только `127.0.0.1`.
- Не публикуйте Ollama/LM Studio в интернет. Используйте `127.0.0.1` или закрытую сеть.
- Храните `.env` с правами `600`.
- Замените `SECRET_KEY` и `JWT_SECRET_KEY` перед первым запуском.
- Ограничьте SSH-доступ к серверу.
- Настройте firewall, оставив снаружи только `22`, `80` и `443`.

Пример `ufw`:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
sudo ufw status
```

Если внешним интеграциям нужен API, задайте `API_KEY` и передавайте его в заголовке:

```bash
curl -H "X-API-Key: <API_KEY>" https://wiki.example.com/api/health
```

Для административных эндпоинтов можно дополнительно задать `ADMIN_API_KEY` и использовать `X-Admin-Key`.

## 14. Резервное копирование

Критичные данные:

- `/opt/wiki-qa/.env` - конфигурация и секреты.
- `/opt/wiki-qa/data/wiki_qa.db` - пользователи и история.
- `/opt/wiki-qa/chroma_db` - векторная база.
- `/opt/wiki-qa/data` - исходные и загруженные документы.
- `/opt/wiki-qa/cache` - кэш, необязателен для восстановления.

Создайте каталог:

```bash
sudo mkdir -p /opt/wiki-qa/backups
sudo chown wikiqa:wikiqa /opt/wiki-qa/backups
```

Создайте скрипт `/opt/wiki-qa/scripts/backup.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/wiki-qa"
BACKUP_DIR="$APP_DIR/backups"
DATE="$(date +%Y%m%d_%H%M%S)"

mkdir -p "$BACKUP_DIR"

tar -czf "$BACKUP_DIR/wikiqa_config_$DATE.tar.gz" -C "$APP_DIR" .env
tar -czf "$BACKUP_DIR/wikiqa_data_$DATE.tar.gz" -C "$APP_DIR" data
tar -czf "$BACKUP_DIR/wikiqa_chroma_$DATE.tar.gz" -C "$APP_DIR" chroma_db

find "$BACKUP_DIR" -type f -mtime +30 -delete
```

Выдайте права и добавьте cron:

```bash
chmod 700 /opt/wiki-qa/scripts/backup.sh
sudo crontab -e
```

Пример ежедневного запуска в 02:00:

```cron
0 2 * * * /opt/wiki-qa/scripts/backup.sh >> /opt/wiki-qa/logs/backup.log 2>&1
```

Периодически проверяйте восстановление на тестовом сервере. Бэкап без проверки восстановления не считается надежным.

## 15. Обновление приложения

Перед обновлением сделайте бэкап:

```bash
/opt/wiki-qa/scripts/backup.sh
```

Обновите код и зависимости:

```bash
sudo -iu wikiqa
cd /opt/wiki-qa
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
pip install gunicorn
```

Если изменились документы, embedding-модель или логика индексации, пересоздайте ChromaDB:

```bash
python -c "from utils.embeddings import invalidate_embedding_cache; invalidate_embedding_cache()"
python create_vector_db.py
```

Перезапустите сервис:

```bash
sudo systemctl restart wiki-qa
sudo systemctl status wiki-qa
```

Проверьте:

```bash
curl https://wiki.example.com/api/health
curl https://wiki.example.com/api/models
```

## 16. Мониторинг и логи

Основные команды:

```bash
sudo systemctl status wiki-qa
sudo journalctl -u wiki-qa -f
tail -f /opt/wiki-qa/logs/error.log
tail -f /opt/wiki-qa/logs/access.log
tail -f /opt/wiki-qa/logs/rag/rag_detailed.log
docker logs -f ollama
```

Проверка доступности:

```bash
curl -f http://127.0.0.1:5000/api/health
curl -f http://127.0.0.1:5000/api/models
```

Настройте ротацию логов:

```bash
sudo nano /etc/logrotate.d/wiki-qa
```

Содержимое:

```text
/opt/wiki-qa/logs/*.log /opt/wiki-qa/logs/rag/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 0640 wikiqa wikiqa
}
```

## 17. Диагностика типовых проблем

### Веб-приложение не запускается

Проверьте сервис, логи и импорт приложения:

```bash
sudo systemctl status wiki-qa
sudo journalctl -u wiki-qa -n 100 --no-pager
sudo -iu wikiqa
cd /opt/wiki-qa
source venv/bin/activate
python -c "from web_app import app; print('OK')"
```

Частые причины:

- не установлены зависимости из `requirements.txt`;
- не задан `SECRET_KEY` или `JWT_SECRET_KEY`;
- нет прав на `data`, `logs`, `cache` или `chroma_db`;
- занят порт `5000`.

### Сервер инференса недоступен

Для Ollama:

```bash
docker ps --filter name=ollama
docker logs ollama --tail 100
curl http://127.0.0.1:11434/api/tags
docker exec -it ollama ollama list
```

Для LM Studio:

```bash
curl http://127.0.0.1:1234/v1/models
```

Проверьте, что `OLLAMA_URL` и `INFERENCE_BACKEND` в `.env` соответствуют выбранному серверу.

### Модель не найдена

Для Ollama:

```bash
docker exec -it ollama ollama list
docker exec -it ollama ollama pull bge-m3
docker exec -it ollama ollama pull qwen2.5:7b
```

Для LM Studio используйте точный `id` модели из `/v1/models`, а не отображаемое имя в интерфейсе.

### Плохие или пустые ответы

Проверьте:

- создана ли ChromaDB и есть ли документы в коллекции;
- совпадает ли embedding-модель с той, на которой строилась база;
- не слишком ли высокий `RAG_MIN_SCORE`;
- доступны ли исходные документы в `DATA_DIR`;
- есть ли ошибки в `logs/rag/rag_detailed.log`.

Команда проверки количества документов:

```bash
sudo -iu wikiqa
cd /opt/wiki-qa
source venv/bin/activate
python - <<'PY'
import chromadb
from config import settings
client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
collection = client.get_collection(settings.CHROMA_COLLECTION_NAME)
print(collection.count())
PY
```

### Загрузка файлов не работает

Проверьте:

```bash
ls -ld /opt/wiki-qa/data/uploads
grep MAX_FILE_SIZE /opt/wiki-qa/.env
grep ALLOWED_EXTENSIONS /opt/wiki-qa/.env
sudo journalctl -u wiki-qa -n 100 --no-pager
```

Также проверьте `client_max_body_size` в Nginx. Он должен быть не меньше `MAX_FILE_SIZE`.

### Ответы обрываются

Увеличьте лимит:

```dotenv
CHAT_MAX_TOKENS=4096
```

После изменения:

```bash
sudo systemctl restart wiki-qa
```

## 18. Контрольный чек-лист после установки

- Приложение запускается через `systemd` и имеет статус `active`.
- Nginx проксирует домен на `127.0.0.1:5000`.
- HTTPS-сертификат выпущен и автопродление проверено.
- `SECRET_KEY` и `JWT_SECRET_KEY` заменены.
- Порт `5000` не открыт наружу.
- Ollama или LM Studio доступны приложению.
- Модели эмбеддингов и чата загружены.
- Векторная база создана и содержит документы.
- Администратор создан и может войти в веб-интерфейс.
- Бэкап настроен и тест восстановления запланирован.
- Логи и logrotate настроены.
