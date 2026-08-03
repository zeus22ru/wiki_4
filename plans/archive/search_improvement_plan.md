# План улучшения логики поиска

## 📊 Общая архитектура поиска

```
┌─────────────┐    ┌──────────────┐    ┌─────────────┐    ┌─────────────┐
│   User      │───▶│  web_app.py  │───▶│  RAGSystem  │───▶│  ChromaDB   │
│  Request    │    │  (Flask)     │    │  (core/rag) │    │  (Vector DB)│
└─────────────┘    └──────────────┘    └─────────────┘    └─────────────┘
                                              │
                                              ▼
                                    ┌─────────────────┐
                                    │  Ollama API     │
                                    │  (Embeddings)   │
                                    └─────────────────┘
```

---

## 🔴 Критические проблемы в логике поиска

### 1. Дублирование кода поиска

**Проблема:** Логика поиска дублируется в двух местах:
- [`core/rag.py:retrieve_documents()`](core/rag.py:113) - основной метод
- [`utils/embeddings.py:search_documents()`](utils/embeddings.py:147) - дублирующий метод

**Последствия:**
- Сложнее поддерживать код
- Риск рассинхронизации логики
- Дублирование логирования

### 2. Неполная реализация метода `query()`

**Проблема:** Метод [`query()`](core/rag.py:418) возвращает `RAGResult` с пустым `answer`:

```python
# core/rag.py:418-488
def query(self, query: str, top_k: int = 5, min_score: float = 0.0,
          include_citations: bool = True, max_citations: int = 5) -> RAGResult:
    # 1. Поиск документов
    documents = self.retrieve_documents(query, top_k, min_score)

    # 2. Генерация промпта
    prompt = self.generate_rag_prompt(query, documents)

    # 3. Возвращает результат с ПУСТЫМ answer
    return RAGResult(
        answer="",  # ❌ Пустой ответ!
        citations=[],
        sources=sources
    )
```

**Последствия:**
- Ответ генерируется отдельно в [`web_app.py:194`](web_app.py:194)
- Разделяет логику RAG-цепочки
- Метод `query()` не выполняет полную работу

### 3. Непоследовательное использование `enrich_answer_with_citations()`

**Проблема:** Метод вызывается с разными аргументами в разных местах:

```python
# web_app.py:216 - вызывается с answer и docs
rag_result = rag.enrich_answer_with_citations(answer, docs)

# Но query() возвращает RAGResult с пустым answer
# Это создаёт путаницу в том, где происходит обогащение
```

### 4. Игнорирование параметра `min_score`

**Проблема:** Параметр [`min_score`](core/rag.py:117) в [`retrieve_documents()`](core/rag.py:113) не используется эффективно:

```python
# core/rag.py:165
if relevance_score >= min_score:  # Проверка есть
    documents.append({...})
```

**Проблема:** В [`web_app.py:179`](web_app.py:179) не передаётся `min_score`:

```python
# web_app.py:179 - не использует min_score!
docs = rag.retrieve_documents(query, top_k=settings.TOP_K_RESULTS)
```

### 5. Отсутствие пакетной обработки эмбеддингов

**Проблема:** В [`web_app.py`](web_app.py) используется одиночная генерация эмбеддингов, хотя в [`utils/embeddings.py`](utils/embeddings.py) есть функция [`get_embeddings_batch()`](utils/embeddings.py:81) для пакетной обработки:

```python
# web_app.py:179 - одиночный эмбеддинг
query_embedding = get_embedding(query)  # ❌ Один запрос

# В utils/embeddings.py есть пакетная обработка
def get_embeddings_batch(texts: List[str]) -> List[List[float]]:
    # ✅ Можно использовать для оптимизации
```

### 6. Проблема с кэшированием в web_app.py

**Проблема:** В [`web_app.py`](web_app.py) не используется кэширование эмбеддингов, хотя оно доступно:

```python
# utils/embeddings.py:16-19 - кэширование доступно
try:
    from utils.cache import get_cached_embedding, cache_embedding, invalidate_embedding_cache
    USE_CACHE = True
except ImportError:
    USE_CACHE = False

# Но web_app.py не использует кэш
```

### 7. Неправильное преобразование расстояния в релевантность

**Проблема:** В [`core/rag.py:161`](core/rag.py:161) используется простое преобразование:

```python
# core/rag.py:161
relevance_score = 1.0 - min(score, 1.0)
```

**Проблема:** ChromaDB возвращает косинусное расстояние, которое может быть:
- От 0 (идентичные векторы) до 2 (полностью противоположные)
- Значение 1.0 не является верхней границей

**Рекомендация:** Использовать более корректное преобразование:
```python
# Для косинусного расстояния: 0 = идентичны, 1 = противоположны
relevance_score = 1.0 - score  # score в [0, 1]
```

### 8. Отсутствие обработки пустых результатов

**Проблема:** В [`web_app.py:182-188`](web_app.py:182) проверяется `if not docs`, но нет обработки случаев, когда:
- Эмбеддинг не был получен
- ChromaDB вернул пустой результат

```python
# web_app.py:179-188
docs = rag.retrieve_documents(query, top_k=settings.TOP_K_RESULTS)
if not docs:
    return jsonify({"answer": "Не найдено релевантных документов..."})
```

### 9. Дублирование логики генерации промпта

**Проблема:** Промпт генерируется дважды:
1. В [`core/rag.py:336`](core/rag.py:336) - `generate_rag_prompt()`
2. В [`utils/embeddings.py:190`](utils/embeddings.py:190) - `generate_answer()`

```python
# core/rag.py:336 - один промпт
prompt = self.generate_rag_prompt(query, documents)

# utils/embeddings.py:190 - другой промпт
prompt = f"""Роль: Ты — аналитик корпоративной базы знаний..."""
```

### 10. Отсутствие валидации входных данных

**Проблема:** В [`web_app.py:154`](web_app.py:154) нет валидации длины запроса:

```python
# web_app.py:154
query = data['message'].strip()
# ❌ Нет проверки: query слишком короткий/длинный
```

---

## ✅ Предложения по улучшениям

### 1. Унификация кода поиска

```python
# utils/embeddings.py - сделать retrieve_documents() публичным
def retrieve_documents(query: str, collection, top_k: int = 5,
                      min_score: float = 0.0) -> List[Dict]:
    """Унифицированный метод поиска"""
    # ... реализация
```

### 2. Исправление метода query()

```python
def query(self, query: str, top_k: int = 5, min_score: float = 0.0,
          include_citations: bool = True, max_citations: int = 5) -> RAGResult:
    # 1. Поиск документов
    documents = self.retrieve_documents(query, top_k, min_score)

    if not documents:
        return RAGResult(
            answer="К сожалению, я не нашёл релевантной информации...",
            citations=[],
            sources=[]
        )

    # 2. Генерация промпта
    prompt = self.generate_rag_prompt(query, documents)

    # 3. Генерация ответа через Ollama
    answer = self._generate_answer(prompt)

    # 4. Обогащение ответа цитатами
    rag_result = self.enrich_answer_with_citations(answer, documents, max_citations)

    return rag_result
```

### 3. Использование пакетной обработки

```python
# web_app.py - использовать пакетную обработку
query_embedding = get_embedding(query)  # Одиночный запрос для простоты
# Или: query_embedding = get_embeddings_batch([query])[0]
```

### 4. Использование кэширования

```python
# web_app.py - добавить кэширование
from utils.cache import invalidate_embedding_cache

# После генерации ответа
invalidate_embedding_cache()
```

### 5. Исправление преобразования расстояния

```python
# core/rag.py:161
# Для косинусного расстояния (0 = идентичны, 1 = противоположны)
relevance_score = 1.0 - score
# Ограничиваем диапазон [0, 1]
relevance_score = max(0.0, min(1.0, relevance_score))
```

### 6. Добавление валидации

```python
# web_app.py
query = data['message'].strip()
if len(query) < 3:
    return jsonify({"error": "Слишком короткий запрос"}), 400
if len(query) > 1000:
    return jsonify({"error": "Слишком длинный запрос"}), 400
```

### 7. Улучшение обработки ошибок

```python
# web_app.py
try:
    docs = rag.retrieve_documents(query, top_k=settings.TOP_K_RESULTS)
except Exception as e:
    logger.error(f"Ошибка при поиске: {e}")
    return jsonify({"error": "Ошибка при поиске в базе знаний"}), 500
```

---

## 📋 Рекомендуемый план рефакторинга

```mermaid
graph TD
    A[Анализ текущей логики] --> B[Унификация кода поиска]
    B --> C[Исправление query()]
    C --> D[Использование кэширования]
    D --> E[Пакетная обработка эмбеддингов]
    E --> F[Исправление преобразования расстояния]
    F --> G[Добавление валидации]
    G --> H[Улучшение обработки ошибок]
```

---

## 🎯 Приоритет улучшений

| Приоритет | Проблема | Влияние |
|-----------|----------|---------|
| **P0** | Дублирование кода поиска | Высокое |
| **P0** | Неполная реализация query() | Высокое |
| **P1** | Игнорирование min_score | Среднее |
| **P1** | Неправильное преобразование расстояния | Среднее |
| **P2** | Отсутствие кэширования | Низкое |
| **P2** | Отсутствие пакетной обработки | Низкое |
| **P3** | Отсутствие валидации | Низкое |

---

## 📝 Исправления для реализации

### core/rag.py

1. **Исправить преобразование расстояния** (строка 161):
   ```python
   relevance_score = max(0.0, min(1.0, 1.0 - score))
   ```

2. **Добавить метод `_generate_answer()`** для генерации ответа через Ollama

3. **Исправить метод `query()`** для полной реализации RAG-цепочки

4. **Добавить обработку ошибок** при поиске документов

### web_app.py

1. **Добавить валидацию запроса** (строка 154)

2. **Использовать `min_score`** при поиске (строка 179)

3. **Добавить обработку ошибок** при поиске (строки 179-188)

4. **Использовать кэширование** после генерации ответа

### utils/embeddings.py

1. **Унифицировать код поиска** - сделать `retrieve_documents()` публичным и использовать его в `search_documents()`

2. **Добавить обработку ошибок** при получении эмбеддингов
