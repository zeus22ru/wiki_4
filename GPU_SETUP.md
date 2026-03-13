# Настройка Ollama с GPU для ускорения

## Требования

- NVIDIA GPU с поддержкой CUDA
- Установленные драйверы NVIDIA (версия 535+)
- Docker с поддержкой NVIDIA Container Toolkit
- Windows 11 с WSL2 (для Windows)

## Проверка наличия GPU

### Windows

```powershell
# Проверка наличия NVIDIA GPU
nvidia-smi

# Проверка версии драйвера
nvidia-smi --query-gpu=driver_version --format=csv
```

### Linux

```bash
# Проверка наличия NVIDIA GPU
nvidia-smi

# Проверка версии драйвера
nvidia-smi --query-gpu=driver_version --format=csv
```

## Установка NVIDIA Container Toolkit

### Windows (WSL2)

1. Установите WSL2:
```powershell
wsl --install
```

2. Установите Docker Desktop для Windows с поддержкой WSL2

3. Установите NVIDIA Container Toolkit в WSL2:
```bash
# В WSL2
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | sudo tee /etc/apt/sources.list.d/nvidia-docker.list

sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

### Linux

```bash
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | sudo tee /etc/apt/sources.list.d/nvidia-docker.list

sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

## Запуск Ollama с GPU

### Остановка текущего контейнера

```bash
docker stop ollama
docker rm ollama
```

### Запуск с поддержкой GPU

```bash
docker run -d --gpus all -p 11434:11434 --name ollama ollama/ollama
```

### Проверка работы GPU

```bash
# Проверка логов контейнера
docker logs ollama

# Проверка использования GPU
nvidia-smi
```

## Оптимизация моделей для GPU

### Использование моделей с поддержкой GPU

```bash
# Внутри контейнера ollama
docker exec -it ollama ollama pull qwen2.5:7b
docker exec -it ollama ollama pull qwen2.5:3b
```

### Настройка параметров GPU

Создайте файл конфигурации `~/.ollama/models/modelfile`:

```dockerfile
FROM qwen2.5:7b

# Параметры GPU
PARAMETER num_gpu 99  # Использовать 99% GPU
PARAMETER num_thread 8  # Количество потоков

# Параметры производительности
PARAMETER num_ctx 4096  # Размер контекста
PARAMETER temperature 0.3
```

## Проверка ускорения

### Тест без GPU

```bash
time python -c "import requests; r = requests.post('http://localhost:11434/api/embed', json={'model': 'qwen2.5:7b', 'input': 'test text'}, timeout=30); print('Done')"
```

### Тест с GPU

После запуска с GPU выполните тот же тест и сравните время.

## Устранение проблем

### GPU не обнаруживается

```bash
# Проверка доступности GPU в Docker
docker run --rm --gpus all nvidia/cuda:11.6.2-base-ubuntu20.04 nvidia-smi
```

### Ошибка "could not select device driver"

Убедитесь, что NVIDIA Container Toolkit установлен и настроен:

```bash
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

### Медленная работа даже с GPU

1. Проверьте использование GPU:
```bash
nvidia-smi -l 1
```

## Дополнительные оптимизации

### Пакетная обработка эмбеддингов

Измените скрипт для отправки нескольких текстов за один запрос:

```python
def get_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """Получить эмбеддинги для нескольких текстов за один запрос"""
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/embed",
            json={
                "model": OLLAMA_MODEL,
                "input": texts  # Массив текстов
            },
            timeout=120
        )
        response.raise_for_status()
        result = response.json()
        return result.get("embeddings", [])
    except Exception as e:
        print(f"Ошибка при получении эмбеддингов: {e}")
        return []
```

## Мониторинг производительности

```bash
# Мониторинг GPU в реальном времени
watch -n 1 nvidia-smi

# Мониторинг Docker контейнера
docker stats ollama
```

## Ожидаемое ускорение

- **Без GPU**: ~1-2 секунды на эмбеддинг
- **С GPU**: ~0.1-0.3 секунды на эмбеддинг
- **Ускорение**: 5-10x

Для базы данных с 1000 чанков:
- Без GPU: ~20-30 минут
- С GPU: ~2-5 минут
