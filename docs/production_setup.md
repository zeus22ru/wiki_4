# Инструкция по установке Wiki QA System на продакшн-сервер

## Содержание

1. [Требования к серверу](#требования-к-серверу)
2. [Установка системных зависимостей](#установка-системных-зависимостей)
3. [Установка Docker и Ollama](#установка-docker-и-ollama)
4. [Клонирование и настройка проекта](#клонирование-и-настройка-проекта)
5. [Настройка переменных окружения](#настройка-переменных-окружения)
6. [Создание векторной базы данных](#создание-векторной-базы-данных)
7. [Запуск веб-приложения](#запуск-веб-приложения)
8. [Настройка systemd для автозапуска](#настройка-systemd-для-автозапуска)
9. [Настройка Nginx (рекомендуется)](#настройка-nginx-рекомендуется)
10. [Настройка SSL сертификатов](#настройка-ssl-сертификатов)
11. [Резервное копирование](#резервное-копирование)
12. [Мониторинг и логирование](#мониторинг-и-логирование)
13. [Обновление системы](#обновление-системы)
14. [Устранение неполадок](#устранение-неполадок)

---

## Требования к серверу

### Минимальные требования

| Компонент | Минимальные требования | Рекомендуемые требования |
|-----------|----------------------|------------------------|
| **ОС** | Ubuntu 20.04 LTS / Debian 11+ | Ubuntu 22.04 LTS / Debian 12+ |
| **CPU** | 2 ядра | 4+ ядра |
| **RAM** | 8 ГБ | 16+ ГБ |
| **Диск** | 50 ГБ | 100+ ГБ SSD |
| **Сеть** | Стабильное соединение | Выделенный IP / домен |

### Проверка системных требований

```bash
# Проверка версии ОС
cat /etc/os-release

# Проверка CPU
nproc

# Проверка RAM
free -h

# Проверка свободного дискового пространства
df -h

# Проверка портов (5000, 11434, 6333)
netstat -tuln | grep -E '5000|11434|6333'
```

---

## Установка системных зависимостей

### 1. Обновление системы

```bash
sudo apt update && sudo apt upgrade -y
```

### 2. Установка Python 3.10+

```bash
# Проверка версии Python
python3 --version

# Если версия ниже 3.10, установите Python 3.10+
sudo apt install -y software-properties-common
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.10 python3.10-venv python3.10-dev python3-pip
```

### 3. Установка необходимых системных пакетов

```bash
sudo apt install -y \
    git \
    curl \
    wget \
    build-essential \
    libpq-dev \
    libssl-dev \
    libffi-dev \
    nginx \
    supervisor \
    certbot \
    python3-certbot-nginx \
    htop \
    iotop \
    net-tools
```

### 4. Создание пользователя для приложения

```bash
# Создание системного пользователя
sudo useradd -r -s /bin/bash -m -d /opt/wiki-qa wikiqa

# Создание директорий
sudo mkdir -p /opt/wiki-qa/{data,logs,cache,backups}
sudo chown -R wikiqa:wikiqa /opt/wiki-qa
```

---

## Установка Docker и Ollama

### 1. Установка Docker

```bash
# Установка Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Добавление пользователя в группу docker
sudo usermod -aG docker $USER
newgrp docker

# Проверка установки
docker --version
```

### 2. Установка Docker Compose

```bash
# Установка Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Проверка установки
docker-compose --version
```

### 3. Запуск Ollama

```bash
# Запуск контейнера Ollama
docker run -d \
    --name ollama \
    --restart unless-stopped \
    -p 11434:11434 \
    -v ollama_data:/root/.ollama \
    ollama/ollama

# Ожидание запуска Ollama (около 30 секунд)
sleep 30

# Проверка статуса
docker ps | grep ollama

# Проверка доступности API
curl http://localhost:11434/api/tags
```

### 4. Загрузка моделей

```bash
# Загрузка модели для эмбеддингов (bge-m3)
docker exec -it ollama ollama pull bge-m3

# Загрузка модели для генерации ответов (qwen2.5:7b)
docker exec -it ollama ollama pull qwen2.5:7b

# Проверка загруженных моделей
docker exec -it ollama ollama list
```

> **Примечание:** Модель `qwen2.5:7b` требует около 4.7 ГБ VRAM. Если у вас нет дискретной видеокарты, используйте модель `qwen2.5:3b` (меньше по размеру).

---

## Клонирование и настройка проекта

### 1. Клонирование репозитория

```bash
# Переключение в директорию /opt
cd /opt

# Клонирование проекта (замените URL на ваш репозиторий)
git clone <URL_РЕПОЗИТОРИЯ> wiki-qa
cd wiki-qa
```

### 2. Создание виртуального окружения

```bash
# Создание виртуального окружения Python
python3.10 -m venv venv

# Активация виртуального окружения
source venv/bin/activate

# Обновление pip
pip install --upgrade pip
```

### 3. Установка Python зависимостей

```bash
# Установка зависимостей из requirements.txt
pip install -r requirements.txt

# Установка дополнительных пакетов
pip install gunicorn
pip install waitress
```

### 4. Копирование файла конфигурации

```bash
# Копирование .env.example в .env
cp .env.example .env

# Редактирование файла .env (см. следующий раздел)
nano .env
```

---

## Настройка переменных окружения

### Файл `.env`

Скопируйте и отредактируйте файл `.env` с следующими настройками:

```bash
# ============================================
# Wiki QA System - Production Configuration
# ============================================

# ============================================
# Ollama настройки
# ============================================
# URL для подключения к Ollama API
OLLAMA_URL=http://localhost:11434

# Модель для генерации эмбеддингов
OLLAMA_EMBEDDING_MODEL=bge-m3

# Модель для генерации ответов
# Для систем без GPU: qwen2.5:3b
# Для систем с GPU: qwen2.5:7b
OLLAMA_CHAT_MODEL=qwen2.5:7b

# ============================================
# ChromaDB настройки
# ============================================
# Директория для хранения векторной базы данных
CHROMA_PERSIST_DIR=/opt/wiki-qa/data/chroma_db

# Имя коллекции в ChromaDB
CHROMA_COLLECTION_NAME=wiki_knowledge

# ============================================
# Data настройки
# ============================================
# Директория с исходными данными
DATA_DIR=/opt/wiki-qa/data/pages

# Директория для загруженных файлов
UPLOAD_DIR=/opt/wiki-qa/data/uploads

# Размер чанка в символах для разбиения текста
CHUNK_SIZE=500

# Перекрытие чанков в символах
CHUNK_OVERLAP=50

# Размер пакета для пакетной обработки эмбеддингов
BATCH_SIZE=10

# ============================================
# API настройка
# ============================================
# Хост для запуска API сервера
API_HOST=0.0.0.0

# Порт для запуска API сервера
API_PORT=5000

# Количество релевантных документов для поиска
TOP_K_RESULTS=3

# ============================================
# RAG настройка
# ============================================
RAG_TOP_K=5
RAG_MAX_CITATIONS=5
RAG_MIN_SCORE=0.5
RAG_MAX_CONTEXT_LENGTH=3000

# ============================================
# Logging настройка
# ============================================
# Уровень логирования: DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_LEVEL=INFO

# Директория для хранения логов
LOG_DIR=/opt/wiki-qa/logs

# ============================================
# Security настройка
# ============================================
# Секретный ключ для приложения (ОБЯЗАТЕЛЬНО ИЗМЕНИТЬ!)
# Сгенерируйте случайный ключ: python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY=<ВАШ_СЛУЧАЙНЫЙ_СЕКРЕТ_КЛЮЧ>

# ============================================
# Database настройка
# ============================================
# Путь к файлу базы данных SQLite
DATABASE_PATH=/opt/wiki-qa/data/wiki_qa.db

# ============================================
# Cache настройка
# ============================================
# Включить кэширование эмбеддингов
CACHE_ENABLED=true

# Время жизни кэша в секундах
CACHE_TTL=3600

# Директория для хранения кэша
CACHE_DIR=/opt/wiki-qa/cache

# ============================================
# File upload настройка
# ============================================
# Максимальный размер загружаемого файла в байтах (10MB)
MAX_FILE_SIZE=10485760

# Разрешённые расширения файлов
ALLOWED_EXTENSIONS=html,htm,txt,docx,doc,pdf,xlsx,xls,pptx
```

### Генерация секретных ключей

```bash
# Генерация SECRET_KEY
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### Проверка конфигурации

```bash
# Проверка валидации настроек
python3 -c "from config.settings import settings; print('OK' if settings.validate() else 'ERROR')"
```

---

## Создание векторной базы данных

### 1. Подготовка данных

```bash
# Создание директории для данных
mkdir -p /opt/wiki-qa/data/pages

# Загрузка HTML файлов в директорию /opt/wiki-qa/data/pages
# (через FTP, SCP или другие методы)
```

### 2. Создание векторной базы данных

```bash
# Активация виртуального окружения
source venv/bin/activate

# Запуск скрипта создания векторной базы данных
python3 create_vector_db.py

# Скрипт выполнит:
# - Сканирование папки data/pages/
# - Извлечение текста из HTML файлов
# - Разбиение на чанки
# - Генерацию эмбеддингов через Ollama
# - Сохранение в ChromaDB
```

### 3. Проверка созданной базы данных

```bash
# Проверка количества документов в базе
python3 -c "
import chromadb
from chromadb.config import Settings
client = chromadb.PersistentClient(path='/opt/wiki-qa/data/chroma_db')
collection = client.get_collection(name='wiki_knowledge')
print(f'Документов в базе: {collection.count()}')
"
```

---

## Запуск веб-приложения

### 1. Тестовый запуск

```bash
# Активация виртуального окружения
source venv/bin/activate

# Тестовый запуск Flask приложения
python3 web_app.py

# Откройте в браузере: http://localhost:5000
# Проверьте API: http://localhost:5000/api/health
```

### 2. Запуск через Gunicorn (рекомендуется)

```bash
# Установка Gunicorn
pip install gunicorn

# Запуск через Gunicorn
gunicorn --bind 0.0.0.0:5000 \
         --workers 4 \
         --timeout 120 \
         --access-logfile /opt/wiki-qa/logs/access.log \
         --error-logfile /opt/wiki-qa/logs/error.log \
         --log-level info \
         web_app:app
```

### 3. Запуск через Waitress (альтернатива для Windows)

```bash
# Установка Waitress
pip install waitress

# Запуск через Waitress
waitress-serve --host=0.0.0.0 --port=5000 --threads=4 web_app:app
```

---

## Настройка systemd для автозапуска

### 1. Создание файла сервиса

```bash
sudo nano /etc/systemd/system/wiki-qa.service
```

### 2. Содержимое файла wiki-qa.service

```ini
[Unit]
Description=Wiki QA System - Векторная база знаний
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=wikiqa
Group=wikiqa
WorkingDirectory=/opt/wiki-qa
Environment="PATH=/opt/wiki-qa/venv/bin"
ExecStart=/opt/wiki-qa/venv/bin/gunicorn \
    --bind 0.0.0.0:5000 \
    --workers 4 \
    --timeout 120 \
    --access-logfile /opt/wiki-qa/logs/access.log \
    --error-logfile /opt/wiki-qa/logs/error.log \
    --log-level info \
    web_app:app
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### 3. Активация сервиса

```bash
# Перезагрузка конфигурации systemd
sudo systemctl daemon-reload

# Включение автозапуска при загрузке
sudo systemctl enable wiki-qa

# Запуск сервиса
sudo systemctl start wiki-qa

# Проверка статуса
sudo systemctl status wiki-qa

# Просмотр логов
sudo journalctl -u wiki-qa -f
```

### 4. Управление сервисом

```bash
# Остановка сервиса
sudo systemctl stop wiki-qa

# Перезапуск сервиса
sudo systemctl restart wiki-qa

# Проверка логов
sudo journalctl -u wiki-qa -n 100
```

---

## Настройка Nginx (рекомендуется)

### 1. Создание конфигурации Nginx

```bash
sudo nano /etc/nginx/sites-available/wiki-qa
```

### 2. Содержимое конфигурации

```nginx
# Wiki QA System - Nginx Configuration

upstream wikiqa_backend {
    server 127.0.0.1:5000;
    keepalive 64;
}

server {
    listen 80;
    listen [::]:80;
    server_name your-domain.com;  # Замените на ваш домен

    # Логи
    access_log /var/log/nginx/wiki-qa-access.log;
    error_log /var/log/nginx/wiki-qa-error.log;

    # Клиентские тела
    client_max_body_size 10M;

    # Статические файлы
    location /static/ {
        alias /opt/wiki-qa/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # API и приложение
    location / {
        proxy_pass http://wikiqa_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
        proxy_connect_timeout 120s;
        proxy_send_timeout 120s;
    }

    # Health check endpoint
    location /api/health {
        proxy_pass http://wikiqa_backend;
        access_log off;
    }
}
```

### 3. Активация конфигурации

```bash
# Создание симлинка
sudo ln -s /etc/nginx/sites-available/wiki-qa /etc/nginx/sites-enabled/

# Проверка конфигурации
sudo nginx -t

# Перезапуск Nginx
sudo systemctl restart nginx
```

---

## Настройка SSL сертификатов

### 1. Установка Let's Encrypt

```bash
# Установка Certbot
sudo apt install -y certbot python3-certbot-nginx
```

### 2. Получение SSL сертификата

```bash
# Получение сертификата (замените your-domain.com на ваш домен)
sudo certbot --nginx -d your-domain.com -d www.your-domain.com
```

### 3. Автоматическое продление сертификата

```bash
# Проверка автоматического продления
sudo certbot renew --dry-run

# Certbot автоматически добавит cron задачу для продления
```

### 4. Конфигурация с HTTPS

После получения сертификата Nginx автоматически обновит конфигурацию для использования HTTPS.

---

## Резервное копирование

### 1. Создание скрипта резервного копирования

```bash
sudo nano /opt/wiki-qa/scripts/backup.sh
```

### 2. Содержимое скрипта backup.sh

```bash
#!/bin/bash

# Wiki QA System - Backup Script
# ============================================

BACKUP_DIR="/opt/wiki-qa/backups"
DATE=$(date +%Y%m%d_%H%M%S)
RETENTION_DAYS=30

# Создание директории для бэкапа
mkdir -p $BACKUP_DIR

# Бэкап векторной базы данных
echo "Creating backup of ChromaDB..."
tar -czf $BACKUP_DIR/chroma_db_$DATE.tar.gz -C /opt/wiki-qa/data chroma_db

# Бэкап базы данных SQLite
echo "Creating backup of SQLite database..."
cp /opt/wiki-qa/data/wiki_qa.db $BACKUP_DIR/wiki_qa_$DATE.db

# Бэкап конфигурации
echo "Creating backup of configuration..."
cp /opt/wiki-qa/.env $BACKUP_DIR/.env_$DATE

# Бэкап данных
echo "Creating backup of data..."
tar -czf $BACKUP_DIR/data_$DATE.tar.gz -C /opt/wiki-qa/data pages

# Удаление старых бэкапов
echo "Cleaning up old backups (older than $RETENTION_DAYS days)..."
find $BACKUP_DIR -name "*.tar.gz" -o -name "*.db" -o -name ".env_*" | \
    while read file; do
        if [ $(find $file -mtime +$RETENTION_DAYS) ]; then
            rm -f $file
            echo "Deleted: $file"
        fi
    done

echo "Backup completed: $DATE"
```

### 3. Настройка прав доступа

```bash
chmod +x /opt/wiki-qa/scripts/backup.sh
chown wikiqa:wikiqa /opt/wiki-qa/scripts/backup.sh
```

### 4. Добавление в cron

```bash
# Редактирование crontab
sudo crontab -e

# Добавление задачи на ежедневное резервное копирование в 2:00 ночи
0 2 * * * /opt/wiki-qa/scripts/backup.sh >> /opt/wiki-qa/logs/backup.log 2>&1
```

---

## Мониторинг и логирование

### 1. Настройка ротации логов

```bash
sudo nano /etc/logrotate.d/wiki-qa
```

### 2. Содержимое logrotate конфигурации

```
/opt/wiki-qa/logs/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 0640 wikiqa wikiqa
    sharedscripts
    postrotate
        systemctl reload wiki-qa > /dev/null 2>&1 || true
    endscript
}
```

### 3. Настройка мониторинга с помощью Uptime Kuma (опционально)

```bash
# Установка Uptime Kuma
docker run -d \
    --name uptime-kuma \
    --restart unless-stopped \
    -p 3001:3001 \
    -v uptime-kuma:/app/data \
    louislam/uptime-kuma
```

### 4. Проверка статуса системы

```bash
# Проверка всех сервисов
sudo systemctl status wiki-qa
docker ps | grep ollama
sudo systemctl status nginx
```

---

## Обновление системы

### 1. Обновление кода

```bash
cd /opt/wiki-qa
git pull origin main

# Установка новых зависимостей
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Перезапуск сервиса

```bash
sudo systemctl restart wiki-qa
```

### 3. Обновление Ollama моделей

```bash
# Остановка контейнера
docker stop ollama

# Удаление старого контейнера
docker rm ollama

# Запуск нового контейнера
docker run -d \
    --name ollama \
    --restart unless-stopped \
    -p 11434:11434 \
    -v ollama_data:/root/.ollama \
    ollama/ollama

# Ожидание запуска
sleep 30

# Загрузка моделей
docker exec -it ollama ollama pull bge-m3
docker exec -it ollama ollama pull qwen2.5:7b
```

---

## Устранение неполадок

### Проблема: Ollama недоступен

```bash
# Проверка статуса контейнера
docker ps | grep ollama

# Проверка логов
docker logs ollama

# Перезапуск контейнера
docker restart ollama

# Проверка доступности API
curl http://localhost:11434/api/tags
```

### Проблема: Веб-приложение не запускается

```bash
# Проверка логов сервиса
sudo journalctl -u wiki-qa -n 50

# Проверка порта
sudo netstat -tuln | grep 5000

# Проверка прав доступа
ls -la /opt/wiki-qa/
ls -la /opt/wiki-qa/data/
ls -la /opt/wiki-qa/logs/
```

### Проблема: Ошибка при генерации эмбеддингов

```bash
# Проверка модели
docker exec -it ollama ollama list

# Проверка логов RAG
tail -f /opt/wiki-qa/logs/rag/rag_detailed.log

# Проверка доступности Ollama API
curl -X POST http://localhost:11434/api/embeddings \
    -H "Content-Type: application/json" \
    -d '{"model": "bge-m3", "prompt": "test"}'
```

### Проблема: Высокая нагрузка на CPU

```bash
# Проверка использования ресурсов
htop

# Уменьшение количества workers в Gunicorn
# Измените --workers 4 на --workers 2 в systemd файле
```

### Проблема: Ошибка SSL сертификата

```bash
# Проверка статуса сертификата
sudo certbot certificates

# Ручное продление
sudo certbot renew

# Проверка конфигурации Nginx
sudo nginx -t
```

---

## Дополнительные ресурсы

- [Ollama Documentation](https://ollama.ai/docs)
- [ChromaDB Documentation](https://docs.trychroma.com/)
- [Flask Documentation](https://flask.palletsprojects.com/)
- [Gunicorn Documentation](https://docs.gunicorn.org/)
- [Nginx Documentation](https://nginx.org/en/docs/)

---

## Контактная информация

Для вопросов и поддержки системного администратора.