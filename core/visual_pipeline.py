#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Конвейер визуальной индексации для CLI/админ-reindex (ТЗ §13).

Общая точка входа для всех режимов индексации: извлекает документы единой
подсистемой (SourceAdapter), сохраняет ассеты, выполняет OCR/vision и строит
визуальные поисковые чанки. Визуальные чанки совместимы по схеме с текстовыми
(``id`` / ``text`` / ``embed_text`` / ``metadata``).
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from config import settings, get_logger
from core.document_extraction.adapters import register_default_adapters
from core.document_extraction.registry import adapter_for_path
from core.ocr import OCRProvider, build_ocr_provider
from core.visual_analysis import VisualAnalyzer
from core.visual_assets import VisualAssetStore
from core.visual_indexing import VisualIndexer, VisualChunk

logger = get_logger(__name__)


def visual_indexing_enabled() -> bool:
    return bool(getattr(settings, "KB_VISUAL_ENABLED", False))


def _relative_source_path(path: Path) -> str:
    try:
        return str(path.relative_to(settings.DATA_DIR))
    except ValueError:
        return path.name


def build_indexer(
    *,
    ocr: Optional[OCRProvider] = None,
    analyzer: Optional[VisualAnalyzer] = None,
    assets: Optional[VisualAssetStore] = None,
) -> VisualIndexer:
    """Собрать индексатор по настройкам (OCR/vision опционально)."""
    ocr = ocr if ocr is not None else build_ocr_provider()
    analyzer = analyzer if analyzer is not None else VisualAnalyzer()
    return VisualIndexer(ocr=ocr, analyzer=analyzer, assets=assets)


def chunk_to_document(chunk: VisualChunk) -> Dict[str, Any]:
    """Преобразовать визуальный чанк в документ индексатора."""
    return {
        "id": chunk.chunk_id,
        "text": chunk.text,
        "embed_text": chunk.embed_text or chunk.text,
        "metadata": chunk.metadata,
    }


def _visual_workers(override: Optional[int] = None) -> int:
    """Число потоков визуальной индексации (1 = последовательно)."""
    if override is not None:
        return max(1, int(override))
    try:
        return max(1, int(getattr(settings, "VISUAL_INDEX_WORKERS", 1) or 1))
    except (TypeError, ValueError):
        return 1


def collect_visual_documents(
    files: List[Path],
    *,
    indexer: Optional[VisualIndexer] = None,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    options: Optional[Dict[str, Any]] = None,
    max_workers: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Собрать визуальные документы для списка файлов.

    Возвращает ``(documents, diagnostics)``. Ошибка одного источника не роняет
    пакет: она попадает в diagnostics, остальные файлы обрабатываются дальше.

    Основное время уходит на vision-запросы (~20 с на картинку, сеть), а OCR
    занимает около секунды, поэтому файлы обрабатываются пулом потоков
    (``VISUAL_INDEX_WORKERS``, 1 = последовательно). Каталог (``RLock`` + WAL),
    хранилище ассетов (атомарная идемпотентная запись) и OCR-провайдер
    потокобезопасны. Порядок чанков детерминирован: результаты собираются по
    исходному порядку файлов, а не по порядку завершения.
    """
    register_default_adapters()
    indexer = indexer or build_indexer()
    total = len(files)
    workers = _visual_workers(max_workers)
    results: List[Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]] = [([], None) for _ in files]
    progress_lock = threading.Lock()
    completed = {"n": 0}

    def report(path: Path, chunks: Optional[int] = None) -> None:
        """Прогресс считаем по числу завершённых файлов, а не по индексу."""
        with progress_lock:
            completed["n"] += 1
            payload: Dict[str, Any] = {
                "stage": "visual",
                "current": completed["n"],
                "total": total,
                "file": path.name,
            }
        if chunks is not None:
            payload["chunks"] = chunks
        if progress_callback:
            progress_callback(payload)

    def work(index: int, path: Path) -> None:
        if adapter_for_path(path) is None:
            return
        try:
            result = _extract(path)
            if result is None:
                return
            index_result = indexer.process(result, options=options)
            documents = [chunk_to_document(chunk) for chunk in index_result.chunks]
            results[index - 1] = (documents, {
                "file": path.name,
                "source_id": result.source_id,
                "status": index_result.status,
                "counters": index_result.counters,
                "diagnostics": index_result.diagnostics,
            })
            report(path, len(index_result.chunks))
        except Exception as exc:
            logger.error("Визуальная обработка %s не удалась: %s", path.name, exc)
            results[index - 1] = ([], {"file": path.name, "status": "failed", "error": str(exc)})
            report(path)

    logger.info(
        "Визуальная индексация: файлов=%s, потоков=%s", total, workers if total > 1 else 1
    )
    if workers == 1 or total <= 1:
        for index, path in enumerate(files, 1):
            work(index, path)
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(work, index, path) for index, path in enumerate(files, 1)]
            for future in futures:
                future.result()

    documents: List[Dict[str, Any]] = []
    diagnostics: List[Dict[str, Any]] = []
    for docs, diag in results:
        documents.extend(docs)
        if diag is not None:
            diagnostics.append(diag)

    try:
        indexer.ocr and indexer.ocr.close()  # noqa: B018
    except Exception:
        pass
    return documents, diagnostics


def _extract(path: Path):
    from core.document_extraction.registry import extract_source

    return extract_source(path, options={"relative_path": _relative_source_path(path)})


def visual_capabilities() -> Dict[str, Any]:
    """Доступность OCR/vision/рендерера для диагностики preview (ТЗ §17)."""
    from pathlib import Path as _Path

    ocr_exe = str(getattr(settings, "OCR_EXECUTABLE", "") or "")
    office = str(getattr(settings, "OFFICE_RENDERER_PATH", "") or "")
    try:
        import pypdfium2  # noqa: F401

        pdfium_ok = True
    except Exception:
        pdfium_ok = False
    return {
        "visual_enabled": bool(getattr(settings, "KB_VISUAL_ENABLED", False)),
        "ocr_provider": getattr(settings, "OCR_PROVIDER", "rapidocr_json"),
        "ocr_executable_present": bool(ocr_exe) and _Path(ocr_exe).is_file(),
        "ocr_profile": getattr(settings, "OCR_MODEL_PROFILE", "cyrillic"),
        "vision_enabled": bool(getattr(settings, "VISUAL_ANALYSIS_ENABLED", True)),
        "vision_model": getattr(settings, "VISUAL_CHAT_MODEL", "") or settings.OLLAMA_CHAT_MODEL,
        "pdf_renderer_available": pdfium_ok,
        "office_renderer_present": bool(office) and _Path(office).is_file(),
    }


def preview_source(path: Path) -> Dict[str, Any]:
    """Разобрать источник без записи в индекс и без OCR/vision (ТЗ §17).

    Возвращает счётчики блоков и визуальных вхождений, полноту извлечения,
    доступность OCR/vision/рендерера и warnings.
    """
    register_default_adapters()
    summary: Dict[str, Any] = {
        "filename": path.name,
        "supported": adapter_for_path(path) is not None,
        "capabilities": visual_capabilities(),
        "blocks": {"heading": 0, "paragraph": 0, "table": 0, "visual": 0, "page_fallback": 0},
        "text_blocks": 0,
        "visual_blocks": 0,
        "occurrences": 0,
        "assets_with_bytes": 0,
        "native_images": 0,
        "rendered_regions": 0,
        "unsupported_objects": 0,
        "status": "unknown",
        "warnings": [],
    }
    if not summary["supported"]:
        summary["status"] = "unsupported"
        summary["warnings"].append("Формат не поддерживается реестром адаптеров")
        return summary
    try:
        result = _extract(path)
    except Exception as exc:
        summary["status"] = "failed"
        summary["warnings"].append(str(exc))
        return summary

    for block in result.blocks:
        summary["blocks"][block.kind] = summary["blocks"].get(block.kind, 0) + 1
    summary["text_blocks"] = sum(1 for b in result.blocks if b.kind != "visual")
    summary["visual_blocks"] = summary["blocks"]["visual"] + summary["blocks"]["page_fallback"]
    summary["occurrences"] = len(result.visual_occurrences)
    summary["assets_with_bytes"] = sum(1 for o in result.visual_occurrences if o.image_bytes)
    summary["native_images"] = sum(1 for o in result.visual_occurrences if o.extraction_quality == "native")
    summary["rendered_regions"] = sum(1 for o in result.visual_occurrences if o.extraction_quality == "rendered")
    summary["status"] = result.status
    summary["diagnostics"] = result.diagnostics
    summary["title"] = result.title
    if result.status == "partial":
        summary["warnings"].append("Извлечение неполное: часть объектов недоступна")
    if summary["occurrences"] and not summary["capabilities"]["ocr_executable_present"]:
        summary["warnings"].append("OCR не запускался: EXE RapidOCR-json не найден — «ожидает распознавания»")
    return summary
