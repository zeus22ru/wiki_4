# Qdrant Docker Setup

## Проблема с портами в Windows/Hyper-V

При запуске Qdrant в Docker на Windows может возникнуть ошибка:
```
Error response from daemon: ports are not available: exposing port TCP 0.0.0.0:6333 -> 127.0.0.1:0: listen tcp 0.0.0.0:6333: bind: An attempt was made to access a socket in a way forbidden by its access permissions.
```

Это происходит из-за того, что Hyper-V резервирует диапазоны портов для своих нужд.

## Решение

### 1. Использование альтернативных портов (рекомендуется)

В текущей конфигурации Qdrant запущен на портах:
- **HTTP API**: `localhost:6100` (вместо стандартного 6333)
- **gRPC API**: `localhost:6101` (вместо стандартного 6334)

### 2. Проверка зарезервированных портов

Для просмотра зарезервированных портов выполните:
```powershell
netsh interface ipv4 show excludedportrange protocol=tcp
```

### 3. Добавление исключений для портов

Если вы хотите использовать стандартные порты 6333/6334, добавьте исключения в Windows Firewall (запустите PowerShell от имени администратора):

```powershell
netsh int ipv4 add excludedportrange protocol=tcp startport=6333 numberofports=2
```

После этого перезапустите Docker Desktop.

## Запуск Qdrant

### Через docker-compose (рекомендуется)

```bash
docker-compose up -d
```

### Через PowerShell скрипт

```powershell
.\start_qdrant.ps1
```

### Вручную

```bash
docker run -d --name qdrant-vector-db -p 6100:6333 -p 6101:6334 -v qdrant_storage:/qdrant/storage qdrant/qdrant:latest
```

## Проверка работы

```bash
# Проверка статуса контейнера
docker ps | findstr qdrant

# Просмотр логов
docker logs qdrant-vector-db

# Остановка
docker-compose down

# Запуск
docker-compose up -d
```

## Доступ к Qdrant

- **Web UI**: http://localhost:6100/dashboard
- **HTTP API**: http://localhost:6100
- **gRPC API**: localhost:6101

## Настройка в приложении

При подключении к Qdrant из приложения используйте порт 6100 вместо стандартного 6333:

```python
from qdrant_client import QdrantClient

client = QdrantClient(
    url="http://localhost:6100",  # Используйте порт 6100
    prefer_grpc=False
)
```

## Сохранение данных

Данные Qdrant сохраняются в Docker volume `qdrant_storage`. При удалении контейнера данные сохраняются.

Для полного удаления данных:
```bash
docker-compose down -v
```
