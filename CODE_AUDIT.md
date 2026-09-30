# Аудит кода (актуальный статус)

Дата обновления: 2026-09-30  
План исправлений: [`plans/audit-fix-plan.md`](plans/audit-fix-plan.md)

Старый отчёт (июнь 2026) устарел: пункты про параллельный reindex, `CHUNK_OVERLAP >= CHUNK_SIZE`, нестроковый `message`, clamp `top_k`, BM25-fallback и stream-тест уже закрыты или закрываются потоками A–E текущего плана.

## Что остаётся / следить после интеграционной фазы

1. **Rerank / GPU.** `sentence-transformers` вынесен в `requirements-rerank.txt`; на CPU-only сервере пакет не ставится. Проверить, что при `RERANK_ENABLED=true` окружение явно ставит этот файл.
2. **Служебные каталоги в репозитории.** `.superpowers/`, `.impeccable/`, `design-prototypes/`, `outputs/`, `plans/redisign/*.html` — решение владельца, не удаляются автоматически. Кандидаты в `.gitignore` (см. отчёт потока E).
3. **Интеграция потоков.** После параллельных правок A/I/B/C/D/E нужен полный `pytest --ignore=tests/e2e`, `pyflakes`, `compileall` под 3.10/3.12 и сверка контрактов K1–K5 из плана.
4. **Telegram WebApp SDK.** Скрипт `telegram.org/js/telegram-web-app.js` остаётся внешним (обязателен для Mini App); остальной фронтенд vendor — локальный в `static/vendor/`.
5. **Качество поиска.** Стемминг/лемматизация для русского BM25, полноценный incremental BM25 и смена СУБД — вне текущего плана (раздел 10 `audit-fix-plan.md`).

## Уже закрыто в коде (не повторять из старого аудита)

- Параллельный reindex без ограничения / clamp `top_k` / BM25-fallback при отсутствии индекса — исправлено ранее.
- Нестроковый `message` и связанные валидации chat API — в зоне потока C.
- CLI `qa_system.py` переведён на `RAGSystem.query()` (поток E); legacy `search_documents`/`generate_answer` в embeddings больше не использует.
- Мёртвые `api/middleware/validation.py` и `utils/validators.py` удалены (поток E).
