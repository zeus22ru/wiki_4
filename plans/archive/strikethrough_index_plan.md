# Учёт зачёркнутого текста в индексации и RAG

Статус: **реализовано** (код и тесты; после деплоя нужен reindex).

Связанный план Cursor: `strikethrough_index_handling_b655ccee.plan.md`

## Проблема

Зачёркнутый текст в wiki (XWiki → `<del>` в HTML) при индексации сливается с актуальным через `get_text()` в [`create_vector_db.py`](../create_vector_db.py) и [`core/chunking.py`](../core/chunking.py). RAG может выдать устаревшие шаги (пример: «Код ошибки 268» — передача декларации Володе/Елене/Сергею).

## Решение (согласовано)

| Требование | Реализация |
|------------|------------|
| Зачёркнутое **чанкуется** | Текст не удаляется; попадает в тот же чанк, что и актуальный абзац |
| Пометка **устаревшего** | Обёртка `[УСТАРЕЛО: …]` вокруг содержимого `<del>` / `<s>` / `<strike>` / `line-through` |
| Промпт | Не использовать `[УСТАРЕЛО]` как инструкцию; **явно упоминать** пользователю, что по теме в источнике есть устаревшие сведения |

### Режим по умолчанию

```env
STRIKETHROUGH_INDEX_MODE=mark   # mark | exclude | keep
```

- **mark** — зачёркнутое в чанке с `[УСТАРЕЛО: …]` (default)
- **exclude** — полное исключение strike-текста
- **keep** — текущее поведение (откат)

## Затрагиваемые файлы

- Новый: [`core/html_text.py`](../core/html_text.py)
- [`create_vector_db.py`](../create_vector_db.py) — `extract_text_from_html`
- [`core/chunking.py`](../core/chunking.py) — `chunk_html_structural`
- [`config/settings.py`](../config/settings.py) — `STRIKETHROUGH_INDEX_MODE`
- [`core/rag.py`](../core/rag.py) — `generate_rag_prompt`
- [`tests/test_html_strikethrough.py`](../tests/test_html_strikethrough.py)
- [`README.md`](../README.md)

Не менять: [`scripts/parse_xwiki.py`](../scripts/parse_xwiki.py) (исходный HTML с `<del>`).

## Правила промпта (кратко)

1. `[УСТАРЕЛО: …]` — не шаги и не обязательные действия.
2. Если в контексте есть `[УСТАРЕЛО: …]` по теме вопроса — в ответе **кратко сообщить**, что в wiki есть устаревшая информация, с [Источник: …].
3. Актуальная часть — текст вне `[УСТАРЕЛО: …]`.

## Приёмка

- Reindex после деплоя.
- Запрос «Код ошибки 268»: актуальные шаги + упоминание obsolete, без обязательного сценария из `<del>`.

## Оценка

2–3 рабочих дня (утилита, тесты, промпт, reindex).
