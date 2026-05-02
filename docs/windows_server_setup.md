# Инструкция администратора по установке Wiki QA System на Windows Server

Документ описывает установку и настройку Wiki QA System на Windows Server. Инструкция использует PowerShell, Python для Windows, Waitress как production WSGI-сервер и NSSM для запуска приложения как службы Windows.

Примеры ниже используют путь установки `C:\wiki-qa`. Если приложение устанавливается в другой каталог, замените путь во всех командах.

## 1. Состав системы

Wiki QA System включает:

- Flask-приложение `web_app.py` с веб-интерфейсом и API.
- SQLite-базу `data\wiki_qa.db` для пользователей, истории чатов и служебных данных.
- ChromaDB в локальном каталоге `chroma_db` для векторного индекса.
- Ollama или LM Studio для эмбеддингов и генерации ответов.
- Каталоги `data`, `cache`, `logs` и `chroma_db` для рабочих данных.

Основные порты:

- `5000` - внутренний порт веб-приложения.
- `80` и `443` - внешний доступ через IIS или Nginx, если используется reverse proxy.
- `11434` - Ollama API.
- `1234` - типичный порт локального сервера LM Studio.

## 2. Требования

Минимально:

- Windows Server 2019/2022 или Windows 10/11 для тестовой установки.
- PowerShell 5.1 или новее.
- Python 3.10 или новее.
- 8 ГБ RAM.
- 50 ГБ свободного места.

Рекомендуется:

- 16+ ГБ RAM.
- SSD.
- 4+ CPU cores.
- GPU NVIDIA для локального запуска крупных моделей.
- Отдельная учетная запись Windows для службы приложения.

Проверка системы:

```powershell
$PSVersionTable.PSVersion
Get-ComputerInfo | Select-Object WindowsProductName, WindowsVersion, OsHardwareAbstractionLayer
Get-CimInstance Win32_ComputerSystem | Select-Object TotalPhysicalMemory
Get-PSDrive C
```

## 3. Установка системных компонентов

### Python

Установите Python 3.10+ одним из способов:

1. Через официальный установщик с сайта Python.
2. Через winget:

```powershell
winget install Python.Python.3.12
```

После установки откройте новый PowerShell и проверьте:

```powershell
python --version
pip --version
```

Если команда `python` не найдена, проверьте переменную `PATH` или используйте Python Launcher:

```powershell
py -3 --version
```

### Git

```powershell
winget install Git.Git
```

Откройте новый PowerShell и проверьте:

```powershell
git --version
```

### NSSM

NSSM нужен, чтобы запускать Python-приложение как службу Windows.

Скачайте NSSM с официального сайта и распакуйте, например, в `C:\Tools\nssm`.

Проверьте:

```powershell
C:\Tools\nssm\win64\nssm.exe version
```

## 4. Установка проекта

Создайте каталог:

```powershell
New-Item -ItemType Directory -Force -Path C:\wiki-qa
```

Склонируйте репозиторий:

```powershell
git clone <URL_РЕПОЗИТОРИЯ> C:\wiki-qa
Set-Location C:\wiki-qa
```

Создайте виртуальное окружение:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install waitress
```

Если PowerShell запрещает запуск `Activate.ps1`, разрешите выполнение скриптов для текущего пользователя:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Проверьте импорт приложения:

```powershell
python -c "from web_app import app; print(app.name)"
```

## 5. Настройка инференса

Приложению нужен сервер инференса для двух задач:

- создание эмбеддингов;
- генерация ответов.

Можно использовать Ollama или LM Studio.

### Вариант A: Ollama на Windows

Установите Ollama для Windows с официального сайта или через winget, если пакет доступен:

```powershell
winget search Ollama
winget install Ollama.Ollama
```

После установки проверьте доступность API:

```powershell
curl.exe http://127.0.0.1:11434/api/tags
```

Загрузите модели:

```powershell
ollama pull bge-m3
ollama pull qwen2.5:7b
ollama list
```

Если сервер без GPU или памяти мало, используйте более легкую chat-модель, например `qwen2.5:3b`, и укажите ее в `.env`.

Важно: embedding-модель должна совпадать с моделью, которой создавалась ChromaDB. Если заменить `OLLAMA_EMBEDDING_MODEL`, векторную базу нужно пересоздать.

### Вариант B: LM Studio

Установите LM Studio на сервер или на отдельную машину в локальной сети.

В LM Studio:

1. Загрузите embedding-модель.
2. Загрузите chat-модель.
3. Включите Local Server.
4. Проверьте список моделей:

```powershell
curl.exe http://127.0.0.1:1234/v1/models
```

Для `.env` нужны точные значения `id` из ответа `/v1/models`.

## 6. Настройка `.env`

Создайте файл конфигурации:

```powershell
Set-Location C:\wiki-qa
Copy-Item .env.example .env
notepad .env
```

Сгенерируйте секретные ключи:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
python -c "import secrets; print(secrets.token_hex(32))"
```

Пример `.env` для Windows Server с Ollama:

```dotenv
INFERENCE_BACKEND=ollama
OLLAMA_URL=http://127.0.0.1:11434
OLLAMA_EMBEDDING_MODEL=bge-m3
OLLAMA_CHAT_MODEL=qwen2.5:7b
CHAT_MAX_TOKENS=2048

CHROMA_PERSIST_DIR=C:\wiki-qa\chroma_db
CHROMA_COLLECTION_NAME=wiki_knowledge
DATA_DIR=C:\wiki-qa\data
UPLOAD_DIR=C:\wiki-qa\data\uploads

API_HOST=127.0.0.1
API_PORT=5000
FLASK_DEBUG=false
CORS_ORIGINS=http://wiki.example.local

RAG_TOP_K=5
RAG_MIN_SCORE=0.0
RAG_MAX_CITATIONS=5
RAG_MAX_CONTEXT_LENGTH=3000

LOG_LEVEL=INFO
LOG_DIR=C:\wiki-qa\logs

SECRET_KEY=<СГЕНЕРИРОВАННЫЙ_SECRET_KEY>
JWT_SECRET_KEY=<СГЕНЕРИРОВАННЫЙ_JWT_SECRET_KEY>
JWT_EXPIRATION_HOURS=24

DATABASE_PATH=C:\wiki-qa\data\wiki_qa.db

CACHE_ENABLED=true
CACHE_TTL=3600
CACHE_DIR=C:\wiki-qa\cache

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

Создайте рабочие каталоги:

```powershell
New-Item -ItemType Directory -Force -Path C:\wiki-qa\data
New-Item -ItemType Directory -Force -Path C:\wiki-qa\data\uploads
New-Item -ItemType Directory -Force -Path C:\wiki-qa\chroma_db
New-Item -ItemType Directory -Force -Path C:\wiki-qa\cache
New-Item -ItemType Directory -Force -Path C:\wiki-qa\logs
```

Проверьте конфигурацию:

```powershell
.\.venv\Scripts\Activate.ps1
python -c "from config import settings; print(settings.INFERENCE_BACKEND, settings.OLLAMA_URL); print(settings.validate())"
```

## 7. Подготовка базы знаний

Скопируйте документы в `C:\wiki-qa\data`. Поддерживаются:

- `html`, `htm`, `txt`;
- `docx`, `doc`;
- `pdf`;
- `xlsx`, `xls`;
- `pptx`.

Например:

```powershell
Copy-Item -Recurse -Force C:\exported-wiki\* C:\wiki-qa\data\
```

Создайте векторную базу:

```powershell
Set-Location C:\wiki-qa
.\.venv\Scripts\Activate.ps1
python create_vector_db.py
```

Проверьте количество документов в ChromaDB:

```powershell
@'
import chromadb
from config import settings

client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
collection = client.get_collection(settings.CHROMA_COLLECTION_NAME)
print("Документов в ChromaDB:", collection.count())
'@ | python
```

Если изменились документы или embedding-модель:

```powershell
python -c "from utils.embeddings import invalidate_embedding_cache; invalidate_embedding_cache()"
python create_vector_db.py
```

## 8. Создание администратора

```powershell
Set-Location C:\wiki-qa
.\.venv\Scripts\Activate.ps1
python scripts\create_admin.py --username admin --email admin@example.com
```

Скрипт запросит пароль. Не передавайте пароль в командной строке на рабочем сервере, чтобы он не остался в истории команд.

## 9. Проверочный запуск

Запустите приложение вручную:

```powershell
Set-Location C:\wiki-qa
.\.venv\Scripts\Activate.ps1
waitress-serve --host=127.0.0.1 --port=5000 --threads=4 web_app:app
```

В другом PowerShell проверьте:

```powershell
curl.exe http://127.0.0.1:5000/api/health
curl.exe http://127.0.0.1:5000/api/models
```

Проверьте тестовый запрос:

```powershell
curl.exe -X POST http://127.0.0.1:5000/api/chat `
  -H "Content-Type: application/json" `
  -d "{\"message\":\"Тестовый вопрос\",\"top_k\":3,\"min_score\":0.0}"
```

После проверки остановите ручной запуск сочетанием `Ctrl+C`.

## 10. Запуск как служба Windows через NSSM

Откройте PowerShell от имени администратора.

Создайте службу:

```powershell
$nssm = "C:\Tools\nssm\win64\nssm.exe"

& $nssm install WikiQA "C:\wiki-qa\.venv\Scripts\waitress-serve.exe"
& $nssm set WikiQA AppDirectory "C:\wiki-qa"
& $nssm set WikiQA AppParameters "--host=127.0.0.1 --port=5000 --threads=4 web_app:app"
& $nssm set WikiQA DisplayName "Wiki QA System"
& $nssm set WikiQA Description "Веб-приложение Wiki QA System"
& $nssm set WikiQA Start SERVICE_AUTO_START
& $nssm set WikiQA AppStdout "C:\wiki-qa\logs\service-out.log"
& $nssm set WikiQA AppStderr "C:\wiki-qa\logs\service-error.log"
& $nssm set WikiQA AppRotateFiles 1
& $nssm set WikiQA AppRotateOnline 1
& $nssm set WikiQA AppRotateBytes 10485760
```

Запустите службу:

```powershell
Start-Service WikiQA
Get-Service WikiQA
```

Проверьте приложение:

```powershell
curl.exe http://127.0.0.1:5000/api/health
Get-Content C:\wiki-qa\logs\service-error.log -Tail 50
```

Управление службой:

```powershell
Restart-Service WikiQA
Stop-Service WikiQA
Start-Service WikiQA
```

Удаление службы при необходимости:

```powershell
Stop-Service WikiQA
& "C:\Tools\nssm\win64\nssm.exe" remove WikiQA confirm
```

## 11. Публикация через reverse proxy

Для рабочей установки не рекомендуется открывать Waitress напрямую наружу. Лучше оставить приложение на `127.0.0.1:5000`, а внешний доступ отдавать через IIS или Nginx.

### Вариант A: IIS с URL Rewrite и ARR

Установите роли и модули:

1. Включите роль IIS: Web Server.
2. Установите URL Rewrite.
3. Установите Application Request Routing.

В IIS Manager:

1. Откройте сервер.
2. Перейдите в `Application Request Routing Cache`.
3. Нажмите `Server Proxy Settings`.
4. Включите `Enable proxy`.

Создайте сайт, например `WikiQA`, с привязкой к домену `wiki.example.local`.

Добавьте правило reverse proxy на `http://127.0.0.1:5000`. Пример `web.config` в корне сайта IIS:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<configuration>
  <system.webServer>
    <rewrite>
      <rules>
        <rule name="ReverseProxyToWikiQA" stopProcessing="true">
          <match url="(.*)" />
          <action type="Rewrite" url="http://127.0.0.1:5000/{R:1}" />
        </rule>
      </rules>
    </rewrite>
  </system.webServer>
</configuration>
```

Для потоковых ответов чата увеличьте таймауты ARR/IIS, если ответы обрываются.

### Вариант B: Nginx for Windows

Скачайте Nginx for Windows и распакуйте, например, в `C:\nginx`.

Пример `C:\nginx\conf\nginx.conf`:

```nginx
worker_processes  1;

events {
    worker_connections  1024;
}

http {
    include       mime.types;
    default_type  application/octet-stream;
    sendfile      on;

    server {
        listen 80;
        server_name wiki.example.local;

        client_max_body_size 10M;

        location /static/ {
            alias C:/wiki-qa/static/;
            expires 30d;
        }

        location / {
            proxy_pass http://127.0.0.1:5000;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_buffering off;
            proxy_read_timeout 300s;
            proxy_send_timeout 300s;
        }
    }
}
```

Проверьте и запустите:

```powershell
C:\nginx\nginx.exe -t
Start-Process C:\nginx\nginx.exe
```

Для production-сервера Nginx также нужно запускать как службу. Это можно сделать через NSSM аналогично приложению.

## 12. Windows Firewall

Если приложение используется только через reverse proxy, порт `5000` наружу открывать не нужно.

Откройте HTTP/HTTPS:

```powershell
New-NetFirewallRule -DisplayName "WikiQA HTTP" -Direction Inbound -Protocol TCP -LocalPort 80 -Action Allow
New-NetFirewallRule -DisplayName "WikiQA HTTPS" -Direction Inbound -Protocol TCP -LocalPort 443 -Action Allow
```

Для временной проверки без reverse proxy можно открыть `5000`, но после настройки IIS/Nginx правило лучше удалить:

```powershell
New-NetFirewallRule -DisplayName "WikiQA App 5000 Temporary" -Direction Inbound -Protocol TCP -LocalPort 5000 -Action Allow
Remove-NetFirewallRule -DisplayName "WikiQA App 5000 Temporary"
```

Не публикуйте наружу порты Ollama или LM Studio. Они должны быть доступны только локально или из доверенной внутренней сети.

## 13. HTTPS

Для доменного сервера используйте один из вариантов:

- сертификат организации, выпущенный внутренним УЦ;
- публичный сертификат Let's Encrypt через win-acme;
- сертификат, установленный на внешнем reverse proxy или балансировщике.

Для IIS удобно использовать win-acme:

1. Скачайте win-acme.
2. Запустите `wacs.exe` от имени администратора.
3. Выберите сайт IIS.
4. Выпустите сертификат и включите автопродление.

После настройки HTTPS обновите `.env`:

```dotenv
CORS_ORIGINS=https://wiki.example.local
```

Перезапустите службу:

```powershell
Restart-Service WikiQA
```

## 14. Безопасность

Рекомендуемые настройки:

- Замените `SECRET_KEY` и `JWT_SECRET_KEY`.
- Ограничьте права на `C:\wiki-qa\.env`.
- Не открывайте наружу порты `5000`, `11434`, `1234`.
- Используйте HTTPS.
- Создайте отдельную учетную запись Windows для службы.
- Ограничьте доступ к каталогу `C:\wiki-qa`.
- Регулярно устанавливайте обновления Windows.
- Не храните резервные копии только на том же диске.

Пример ограничения доступа к `.env`:

```powershell
icacls C:\wiki-qa\.env /inheritance:r
icacls C:\wiki-qa\.env /grant Administrators:F
icacls C:\wiki-qa\.env /grant SYSTEM:F
icacls C:\wiki-qa\.env /grant "Users:R"
```

Если API используется внешними интеграциями, задайте `API_KEY`:

```dotenv
API_KEY=<СЛУЧАЙНЫЙ_API_KEY>
ADMIN_API_KEY=<СЛУЧАЙНЫЙ_ADMIN_API_KEY>
```

Пример запроса:

```powershell
curl.exe -H "X-API-Key: <API_KEY>" http://wiki.example.local/api/health
```

## 15. Резервное копирование

Критичные данные:

- `C:\wiki-qa\.env`;
- `C:\wiki-qa\data\wiki_qa.db`;
- `C:\wiki-qa\data`;
- `C:\wiki-qa\chroma_db`;
- `C:\wiki-qa\logs`, если нужны для расследований.

Создайте скрипт `C:\wiki-qa\scripts\backup.ps1`:

```powershell
$ErrorActionPreference = "Stop"

$AppDir = "C:\wiki-qa"
$BackupDir = "D:\Backups\wiki-qa"
$Date = Get-Date -Format "yyyyMMdd_HHmmss"
$Target = Join-Path $BackupDir "wikiqa_$Date"

New-Item -ItemType Directory -Force -Path $Target | Out-Null

Copy-Item "$AppDir\.env" "$Target\.env" -Force
Copy-Item "$AppDir\data" "$Target\data" -Recurse -Force
Copy-Item "$AppDir\chroma_db" "$Target\chroma_db" -Recurse -Force

Compress-Archive -Path "$Target\*" -DestinationPath "$BackupDir\wikiqa_$Date.zip" -Force
Remove-Item $Target -Recurse -Force

Get-ChildItem $BackupDir -Filter "wikiqa_*.zip" |
  Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } |
  Remove-Item -Force
```

Создайте задачу в Планировщике:

```powershell
$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-ExecutionPolicy Bypass -File C:\wiki-qa\scripts\backup.ps1"
$Trigger = New-ScheduledTaskTrigger -Daily -At 2:00am
$Principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -RunLevel Highest
Register-ScheduledTask -TaskName "WikiQA Backup" -Action $Action -Trigger $Trigger -Principal $Principal
```

Проверьте ручной запуск:

```powershell
powershell.exe -ExecutionPolicy Bypass -File C:\wiki-qa\scripts\backup.ps1
```

## 16. Обновление приложения

Перед обновлением сделайте бэкап.

```powershell
powershell.exe -ExecutionPolicy Bypass -File C:\wiki-qa\scripts\backup.ps1
```

Остановите службу:

```powershell
Stop-Service WikiQA
```

Обновите код и зависимости:

```powershell
Set-Location C:\wiki-qa
git pull origin main
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install waitress
```

Если менялись документы, embedding-модель или логика индексации:

```powershell
python -c "from utils.embeddings import invalidate_embedding_cache; invalidate_embedding_cache()"
python create_vector_db.py
```

Запустите службу:

```powershell
Start-Service WikiQA
curl.exe http://127.0.0.1:5000/api/health
```

## 17. Мониторинг и логи

Проверка службы:

```powershell
Get-Service WikiQA
Get-EventLog -LogName Application -Newest 50
```

Логи приложения:

```powershell
Get-Content C:\wiki-qa\logs\service-error.log -Tail 100
Get-Content C:\wiki-qa\logs\service-out.log -Tail 100
Get-Content C:\wiki-qa\logs\web_app.log -Tail 100
Get-Content C:\wiki-qa\logs\rag\rag_detailed.log -Tail 100
```

Проверка портов:

```powershell
netstat -ano | findstr ":5000"
netstat -ano | findstr ":11434"
```

Проверка моделей:

```powershell
curl.exe http://127.0.0.1:5000/api/models
ollama list
```

## 18. Диагностика типовых проблем

### Служба WikiQA не запускается

Проверьте:

```powershell
Get-Service WikiQA
Get-Content C:\wiki-qa\logs\service-error.log -Tail 100
Set-Location C:\wiki-qa
.\.venv\Scripts\Activate.ps1
python -c "from web_app import app; print('OK')"
```

Частые причины:

- не установлены зависимости;
- неверный путь в NSSM;
- занят порт `5000`;
- ошибка в `.env`;
- нет прав на `data`, `logs`, `cache` или `chroma_db`.

### Ollama недоступен

```powershell
curl.exe http://127.0.0.1:11434/api/tags
ollama list
```

Если Ollama не запущен, откройте приложение Ollama или проверьте его службу/процесс в Windows.

### LM Studio недоступен

```powershell
curl.exe http://127.0.0.1:1234/v1/models
```

Проверьте, что в LM Studio включен Local Server и загружены модели.

### Модель не найдена

Для Ollama:

```powershell
ollama list
ollama pull bge-m3
ollama pull qwen2.5:7b
```

Для LM Studio используйте точный `id` из `/v1/models`.

### Нет ответов или плохой поиск

Проверьте:

- есть ли документы в ChromaDB;
- совпадает ли embedding-модель;
- не слишком ли высокий `RAG_MIN_SCORE`;
- доступен ли сервер инференса;
- есть ли ошибки в `C:\wiki-qa\logs\rag\rag_detailed.log`.

Проверка ChromaDB:

```powershell
@'
import chromadb
from config import settings
client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
collection = client.get_collection(settings.CHROMA_COLLECTION_NAME)
print(collection.count())
'@ | python
```

### Загрузка документов не работает

Проверьте:

```powershell
Test-Path C:\wiki-qa\data\uploads
Get-Item C:\wiki-qa\data\uploads
Select-String -Path C:\wiki-qa\.env -Pattern "MAX_FILE_SIZE|ALLOWED_EXTENSIONS"
Get-Content C:\wiki-qa\logs\service-error.log -Tail 100
```

Также проверьте лимит размера тела запроса в IIS или Nginx.

### Ответы обрываются

Увеличьте `CHAT_MAX_TOKENS`:

```dotenv
CHAT_MAX_TOKENS=4096
```

Перезапустите службу:

```powershell
Restart-Service WikiQA
```

Если используется reverse proxy, увеличьте таймауты IIS ARR или Nginx.

## 19. Контрольный чек-лист

- Python 3.10+ установлен.
- Зависимости из `requirements.txt` установлены в `.venv`.
- Waitress установлен.
- Ollama или LM Studio доступны приложению.
- Модели эмбеддингов и чата загружены.
- `.env` настроен, секретные ключи заменены.
- Рабочие каталоги созданы.
- Векторная база создана.
- Администратор создан.
- Ручной запуск Waitress проходит успешно.
- Служба `WikiQA` создана и запущена.
- IIS или Nginx проксирует внешний домен на `127.0.0.1:5000`.
- Firewall не открывает наружу порты `5000`, `11434`, `1234`.
- HTTPS настроен.
- Бэкап настроен и проверен.
