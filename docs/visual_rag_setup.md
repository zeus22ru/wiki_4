# Визуальный RAG и portable OCR — установка и настройка

Документ описывает включение индексации визуального содержимого (изображения,
OCR, vision-описание) в проекте `wiki_4`. Реализация соответствует ТЗ
`docs/TZ_visual_rag_rapidocr_windows.md`.

> Функция выключена по умолчанию (`KB_VISUAL_ENABLED=false`). Включайте её
> осознанно после подготовки portable OCR-комплекта и проверки vision-модели.

## 1. Архитектура

| Слой | Модуль | Назначение |
|---|---|---|
| Извлечение | `core/document_extraction/` | Единый реестр адаптеров: текст, HTML/XWiki, DOCX, PDF, PPTX, XLSX, изображения, DOC/XLS |
| Каталог | `core/kb_catalog.py` | SQLite: Source / Asset / Occurrence / Analysis, генерации, GC |
| Хранилище | `core/visual_assets.py` | Оригиналы по SHA-256, производные, кэш анализа, staging, атомарная запись |
| OCR | `core/ocr.py` | Провайдер RapidOCR-json: `health_check`, `recognize`, `close`; pipe/oneshot; кэш |
| Подготовка растра | `core/imaging_utils.py` | Растеризация SVG, тайлинг крупных схем |
| Vision | `core/visual_analysis.py` | JSON-описание по версионированной схеме, граф схемы, один repair |
| Индексация | `core/visual_indexing.py`, `core/visual_pipeline.py` | Сохранение ассетов, OCR/vision, визуальные чанки |
| Контекст ответа | `core/visual_context.py` | Отбор изображений и EvidenceBundle |
| Выдача | `core/visual_serving.py`, `GET /api/documents/images/<occ>` | Безопасная отдача original/preview/thumbnail |
| XWiki | `core/xwiki_assets.py` | Скачивание ресурсов статьи через авторизованную сессию |

Модель данных: `Source` → `Asset` (байты по SHA-256) → `Occurrence` (появление
в документе) → `Analysis` (OCR/vision для версии изображения).

## 2. Portable RapidOCR-json (Windows x64)

Проверенный на этой машине комплект — выпуск **v0.2.0** (runtime-баннер сообщает
версию движка `1.1.0`). Распакован в:

```text
.tools/rapidocr-json/0.2.0/
  RapidOCR-json.exe                 # фактическое имя без подчёркивания
  cmd.txt
  models/
    ch_PP-OCRv3_det_infer.onnx
    ch_ppocr_mobile_v2.0_cls_infer.onnx
    rec_cyrillic_PP-OCRv3_infer.onnx
    dict_cyrillic.txt
    rec_en_PP-OCRv3_infer.onnx
    dict_en.txt
    ... (китайский, японский, корейский и др.)
  licenses/                         # добавлены вручную (в архиве их нет)
  runtime_manifest.json             # сгенерирован scripts/rapidocr_manifest.py
```

Реальный протокол EXE (проверено):

- **oneshot:** `RapidOCR-json.exe --models=models --det=… --cls=… --rec=… --keys=… --image=<путь>`
- **pipe:** запустить EXE с теми же model-аргументами без `--image`, затем писать
  в stdin по одной строке `{"image_path": "<путь>"}` и читать JSON-ответ.
- Ответ: `{"code":100,"data":[{"box":[[x,y],…],"score":…,"text":"…"}]}`;
  `code=100` — текст найден, `code=101` — текста нет.
- При старте печатаются служебные строки (`RapidOCR-json v1.1.0`, `OCR init completed.`),
  их нужно пропускать до первого JSON.

Профили (`--rec`/`--keys`):

| Профиль | rec | keys |
|---|---|---|
| `cyrillic` | `rec_cyrillic_PP-OCRv3_infer.onnx` | `dict_cyrillic.txt` |
| `english` | `rec_en_PP-OCRv3_infer.onnx` | `dict_en.txt` |
| `chinese_v4` | `rec_ch_PP-OCRv4_infer.onnx` | `ppocr_keys_v1.txt` |

> Внимание: апстримный `cmd.txt` для English ошибочно указывает `dict_chinese.txt`;
> корректный словарь — `dict_en.txt`.

**Смешанный русско-английский текст.** Кириллическая модель путает похожие
латинские/кириллические глифы и цифры (например, номер `00-00006695` читается как
`Oо-Oооо6695`). Поэтому включён второй проход английской моделью
(`OCR_DUAL_PASS=true`, `OCR_SECONDARY_PROFILE=english`): результаты объединяются,
при этом:
- основным остаётся кириллическое чтение (кириллица в тексте сохраняется);
- для чисто латинско-цифровых блоков выбирается более уверенное чтение второго прохода;
- оба варианта сохраняются (`text_raw` и `text_raw_alt`) и оба попадают в поиск,
  поэтому точные номера и технические имена находятся.

Настройка путей:

```env
OCR_PROVIDER=rapidocr_json
OCR_EXECUTABLE=D:/Development/zelenin_sa/wiki_4/.tools/rapidocr-json/0.2.0/RapidOCR-json.exe
OCR_MODE=oneshot
OCR_MODEL_PROFILE=cyrillic
OCR_SECONDARY_PROFILE=english
OCR_DUAL_PASS=true
OCR_ENGINE_VERSION=1.1.0
```

**Манифест и лицензии.** Сгенерировать манифест целостности:

```powershell
.\.venv\Scripts\python.exe scripts\rapidocr_manifest.py `
  --install .tools\rapidocr-json\0.2.0 `
  --archive .tools\rapidocr-json\_download\RapidOCR-json_v0.2.0.7z `
  --version 0.2.0 --runtime-version 1.1.0
```

SHA-256 архива v0.2.0: `7ad9b283d03436c6cd0296723188699299cb4e5cf9140b410c59543aa5793c40`.
Лицензии компонентов (`RapidOCR-json`, ONNX Runtime, PaddleOCR) лежат в
`.tools/rapidocr-json/0.2.0/licenses/`.

Требования к процессам: EXE запускается через список аргументов и `shell=False`;
отдельное консольное окно на Windows не открывается; при зависании процесс
завершается и допускается один повтор. Каталоги с кириллицей и пробелами
поддерживаются (путь задаётся явно, вызывается из `cwd` EXE).

## 3. Vision-модель

Vision-модель описывает изображения и извлекает связи (узлы/стрелки/условия).
Текстовые эмбеддинги остаются прежними.

Можно использовать **ту же модель, что и для ответов** — тогда достаточно не
задавать отдельные значения (они наследуются от чата) или задать их явно:

```env
VISUAL_ANALYSIS_ENABLED=true
# Пусто = берётся OLLAMA_CHAT_MODEL / CHAT_BASE_URL / CHAT_API_KEY.
# Явно — то же самое, что и модель ответов:
VISUAL_CHAT_MODEL=deepseek-flash
VISUAL_CHAT_BASE_URL=https://api.deepseek.com
#VISUAL_CHAT_API_KEY=
VISUAL_ANALYSIS_TIMEOUT_SEC=120
VISUAL_SCHEMA_VERSION=1
```

> **Важно.** Модель должна реально принимать изображения. Текстовые модели
> (в том числе облачные chat-модели без vision) вернут `vision_unsupported`, и
> описания картинок не будут построены — в индексе останутся только OCR-тексты.
> При этом приложение не ломается: если модель отвергает изображения,
> ответ генерируется по тексту с явной диагностикой
> `diagnostics.visual.fallback = vision_unsupported`, а найденные изображения
> помечаются `used_for_answer=false` (ТЗ §15.1 — без «молчаливого» отката).

Проверка возможностей: отправьте известную картинку и убедитесь, что модель
реально получает байты изображения (не путь/URL) и возвращает текст с картинки.
Смена модели инвалидирует кэш анализа.

## 4. Офисный рендеринг (опционально)

Для сложных объектов DOCX/PPTX/XLSX и старых `.doc`/`.xls` можно указать
portable LibreOffice. Без него источники обрабатываются нативно с `partial`.

```env
OFFICE_RENDERER_PATH=D:/Development/zelenin_sa/wiki_4/.tools/libreoffice-portable/program/soffice.exe
OFFICE_RENDER_TIMEOUT_SEC=180
```

PDF-рендеринг использует `pypdfium2` (PDFium) и не требует Poppler/Ghostscript.

## 5. Включение и переиндексация

```env
KB_VISUAL_ENABLED=true
KB_ASSETS_DIR=./data/kb_assets
# namespace должен соответствовать индексу, в который пишем
KB_VISUAL_INDEX_NAMESPACE=default
PDF_RENDER_DPI=200
VISUAL_TILE_SIZE=1600
VISUAL_TILE_OVERLAP=160
```

Два режима развёртывания:

- **Рабочий индекс** (проверка «в бою»): оставляем
  `CHROMA_COLLECTION_NAME=wiki_knowledge`, `KB_VISUAL_INDEX_NAMESPACE=default`.
  Визуальные чанки добавятся в ту же коллекцию при переиндексации.
- **Пилот** (безопаснее): отдельная коллекция, чтобы не задеть рабочую базу:

  ```env
  CHROMA_COLLECTION_NAME=wiki_knowledge_pilot
  KB_VISUAL_INDEX_NAMESPACE=pilot
  ```

Переиндексация:

```bat
.\.venv\Scripts\python.exe create_vector_db.py
```

> Полная переиндексация пересобирает коллекцию `CHROMA_COLLECTION_NAME` целиком
> (текст + визуал) и заново считает эмбеддинги — это время и стоимость вызовов
> модели эмбеддингов.

Каталоги `data/kb_assets/` и `.tools/` исключены из `scan_supported_files()`,
чтобы извлечённые изображения не индексировались повторно.

## 6. Ответ и выдача изображений

- `POST /api/chat` и финальное SSE-событие `done` содержат поле `images` (пустое
  при отсутствии картинок). Совместимо со старыми клиентами.
- `GET /api/documents/images/<occurrence_id>?variant=original|preview|thumbnail`
  отдаёт изображение. ID разрешается через каталог; путь файловой системы из
  запроса не принимается. SVG отдаётся не inline.
- История чата сохраняет `images` в metadata ассистентского сообщения и
  восстанавливает галерею при перезагрузке.

## 7. Диагностика и preview

Preview (`preview_document`) при включённом визуальном индексе возвращает блок
`visual`: число блоков text/table/visual, occurrences, native/rendered,
доступность OCR/vision/рендерера, warnings. До запуска OCR показывается
«ожидает распознавания», а не выдуманная длина текста.

Коды ошибок: `ocr_runtime_missing`, `ocr_model_missing`, `ocr_timeout`,
`ocr_invalid_response`, `asset_download_login`, `asset_decode_failed`,
`renderer_unavailable`, `vision_unsupported`, `vision_analysis_failed`,
`visual_budget_exceeded`, `source_stale`.

## 8. Кэш и обновления

- Ключ OCR-кэша: хэш растра + хэши моделей/словарей + версия движка/адаптера +
  язык + параметры подготовки/распознавания.
- Ключ vision-кэша: asset_id + модель + версия prompt/схемы + подготовка картинки.
- Повторная индексация неизменного источника не выполняет OCR/vision-вызовы.
- Изменение только UI-настройки (лимит выдачи картинок) не инвалидирует OCR.
- Неуспешные анализы (`failed`/`unavailable`/`pending`) не кэшируются навсегда и
  повторяются при следующем запуске.

## 9. Очистка и откат

```python
from core.visual_assets import VisualAssetStore
store = VisualAssetStore()
print(store.gc_orphans(grace_hours=72, dry_run=True))   # отчёт
store.gc_orphans(grace_hours=72, dry_run=False)          # удаление после grace
```

Откат: выключите `KB_VISUAL_ENABLED` и `RAG_VISUAL_CONTEXT_ENABLED` и верните
`CHROMA_COLLECTION_NAME` на согласованный комплект старой коллекции/BM25/manifest.
Исходные документы не удаляются.
