#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для создания векторной базы данных из файлов в папке data/
Поддерживает HTML, DOCX, PDF, XLSX, XLS, PPTX, DOC форматы.
Использует ollama для генерации эмбеддингов и ChromaDB для хранения.
"""

import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from bs4 import BeautifulSoup
import chromadb
import json
from typing import Any, List, Dict, Optional, Callable, Set, Tuple
import hashlib

# Импорт конфигурации и логирования
from config import settings, get_logger, fetch_remote_model_ids

# Импорт общих функций для работы с эмбеддингами
from utils.embeddings import get_embedding, get_embeddings_batch, invalidate_embedding_cache, chat_completion

from core.chunking import build_chunks_for_file, chunk_text_fixed_size
from core.html_text import get_index_text
from core.index_manifest import (
    build_index_manifest,
    file_signature,
    load_index_manifest,
    manifest_path,
    save_index_manifest,
    settings_fingerprint,
)
from core.retrieval import bm25_index_path, load_bm25_corpus, save_bm25_index

# Получаем логгер для этого модуля
logger = get_logger(__name__)

# Библиотеки для обработки разных форматов
try:
    from docx import Document
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False

try:
    import pdfplumber
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

try:
    from openpyxl import load_workbook
    XLSX_AVAILABLE = True
except ImportError:
    XLSX_AVAILABLE = False

try:
    import xlrd
    XLS_AVAILABLE = True
except ImportError:
    XLS_AVAILABLE = False

try:
    from pptx import Presentation
    PPTX_AVAILABLE = True
except ImportError:
    PPTX_AVAILABLE = False

try:
    import docx2txt
    DOC_AVAILABLE = True
except ImportError:
    DOC_AVAILABLE = False

# Устанавливаем UTF-8 для вывода в консоль (Windows) только при прямом запуске скрипта.
if sys.platform == 'win32' and __name__ == '__main__':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Конфигурация загружается из config/settings.py
# OLLAMA_URL, OLLAMA_MODEL, OLLAMA_CHAT_MODEL, CHROMA_PERSIST_DIR,
# DATA_DIR, CHUNK_SIZE, CHUNK_OVERLAP, BATCH_SIZE


def _relative_source_path(file_path: Path) -> str:
    """Вернуть путь относительно DATA_DIR, а для временных файлов — имя файла."""
    try:
        return str(file_path.relative_to(settings.DATA_DIR))
    except ValueError:
        return file_path.name


def extract_text_from_html(html_path: Path) -> Optional[Dict[str, str]]:
    """Извлечь текст и метаданные из HTML файла"""
    try:
        with open(html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Удаляем скрипты и стили
        for script in soup(["script", "style", "nav", "footer", "header"]):
            script.decompose()
        
        # Получаем заголовок
        title = ""
        title_tag = soup.find('title')
        if title_tag:
            title = title_tag.get_text().strip()
        
        # Получаем h1
        h1 = ""
        h1_tag = soup.find('h1')
        if h1_tag:
            h1 = h1_tag.get_text().strip()
        
        # Основной текст (зачёркнутое → [УСТАРЕЛО: …] при STRIKETHROUGH_INDEX_MODE=mark)
        content_root = soup.find("article") or soup.find(id="xwikicontent") or soup.body or soup
        text = get_index_text(content_root, separator=" ")
        
        return {
            "title": title or h1 or Path(html_path).stem,
            "content": text,
            "path": _relative_source_path(html_path)
        }
    except Exception as e:
        print(f"Ошибка при чтении {html_path}: {e}")
        return None


def extract_text_from_txt(txt_path: Path) -> Optional[Dict[str, str]]:
    """Извлечь текст из TXT файла."""
    try:
        text = txt_path.read_text(encoding='utf-8', errors='replace')
        text = re.sub(r'\s+', ' ', text).strip()
        return {
            "title": Path(txt_path).stem,
            "content": text,
            "path": _relative_source_path(txt_path),
        }
    except Exception as e:
        logger.error(f"Ошибка при чтении TXT {txt_path}: {e}")
        return None


def extract_text_from_docx(docx_path: Path) -> Optional[Dict[str, str]]:
    """Извлечь текст и метаданные из DOCX файла"""
    if not DOCX_AVAILABLE:
        logger.warning(f"Библиотека python-docx не установлена. Пропуск: {docx_path.name}")
        return None
    
    try:
        doc = Document(docx_path)
        
        # Извлекаем текст из параграфов
        paragraphs = []
        for para in doc.paragraphs:
            if para.text.strip():
                paragraphs.append(para.text.strip())
        
        # Извлекаем текст из таблиц
        for table in doc.tables:
            for row in table.rows:
                row_text = []
                for cell in row.cells:
                    if cell.text.strip():
                        row_text.append(cell.text.strip())
                if row_text:
                    paragraphs.append(" | ".join(row_text))
        
        text = "\n".join(paragraphs)
        
        # Очистка текста
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()
        
        # Получаем заголовок из свойств документа или первого параграфа
        title = doc.core_properties.title or ""
        if not title and paragraphs:
            title = paragraphs[0][:100]
        
        return {
            "title": title or Path(docx_path).stem,
            "content": text,
            "path": _relative_source_path(docx_path)
        }
    except Exception as e:
        logger.error(f"Ошибка при чтении DOCX {docx_path}: {e}")
        return None


def extract_text_from_pdf(pdf_path: Path) -> Optional[Dict[str, str]]:
    """Извлечь текст и метаданные из PDF файла"""
    if not PDF_AVAILABLE:
        logger.warning(f"Библиотека pdfplumber не установлена. Пропуск: {pdf_path.name}")
        return None
    
    try:
        text_parts = []
        title = ""
        
        with pdfplumber.open(pdf_path) as pdf:
            # Пытаемся получить заголовок из метаданных
            if pdf.metadata:
                title = pdf.metadata.get('Title', '') or pdf.metadata.get('Title', '')
            
            # Извлекаем текст со всех страниц
            for page_num, page in enumerate(pdf.pages, 1):
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
                    
                    # Если заголовок не найден, берем первую строку первой страницы
                    if not title and page_num == 1:
                        lines = page_text.split('\n')
                        if lines:
                            title = lines[0].strip()[:100]
        
        text = "\n".join(text_parts)
        
        # Очистка текста
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()
        
        return {
            "title": title or Path(pdf_path).stem,
            "content": text,
            "path": _relative_source_path(pdf_path)
        }
    except Exception as e:
        logger.error(f"Ошибка при чтении PDF {pdf_path}: {e}")
        return None


def extract_text_from_xlsx(xlsx_path: Path) -> Optional[Dict[str, str]]:
    """Извлечь текст и метаданные из XLSX файла"""
    if not XLSX_AVAILABLE:
        logger.warning(f"Библиотека openpyxl не установлена. Пропуск: {xlsx_path.name}")
        return None
    
    try:
        wb = load_workbook(xlsx_path, read_only=True, data_only=True)
        text_parts = []
        
        for sheet_name in wb.sheetnames:
            sheet = wb[sheet_name]
            sheet_text = []
            
            for row in sheet.iter_rows(values_only=True):
                row_values = [str(cell) if cell is not None else "" for cell in row]
                row_text = " | ".join(row_values).strip()
                if row_text:
                    sheet_text.append(row_text)
            
            if sheet_text:
                text_parts.append(f"Лист: {sheet_name}\n" + "\n".join(sheet_text))
        
        wb.close()
        
        text = "\n\n".join(text_parts)
        
        # Очистка текста
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()
        
        return {
            "title": Path(xlsx_path).stem,
            "content": text,
            "path": _relative_source_path(xlsx_path)
        }
    except Exception as e:
        logger.error(f"Ошибка при чтении XLSX {xlsx_path}: {e}")
        return None


def extract_text_from_xls(xls_path: Path) -> Optional[Dict[str, str]]:
    """Извлечь текст и метаданные из XLS файла (старый формат Excel)"""
    if not XLS_AVAILABLE:
        logger.warning(f"Библиотека xlrd не установлена. Пропуск: {xls_path.name}")
        return None
    
    try:
        wb = xlrd.open_workbook(xls_path)
        text_parts = []
        
        for sheet_idx in range(wb.nsheets):
            sheet = wb.sheet_by_index(sheet_idx)
            sheet_text = []
            
            for row_idx in range(sheet.nrows):
                row_values = []
                for col_idx in range(sheet.ncols):
                    cell = sheet.cell_value(row_idx, col_idx)
                    if cell:
                        row_values.append(str(cell))
                
                if row_values:
                    sheet_text.append(" | ".join(row_values))
            
            if sheet_text:
                text_parts.append(f"Лист: {sheet.name}\n" + "\n".join(sheet_text))
        
        text = "\n\n".join(text_parts)
        
        # Очистка текста
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()
        
        return {
            "title": Path(xls_path).stem,
            "content": text,
            "path": _relative_source_path(xls_path)
        }
    except Exception as e:
        logger.error(f"Ошибка при чтении XLS {xls_path}: {e}")
        return None


def extract_text_from_pptx(pptx_path: Path) -> Optional[Dict[str, str]]:
    """Извлечь текст и метаданные из PPTX файла"""
    if not PPTX_AVAILABLE:
        logger.warning(f"Библиотека python-pptx не установлена. Пропуск: {pptx_path.name}")
        return None
    
    try:
        prs = Presentation(pptx_path)
        text_parts = []
        title = ""
        
        for slide_num, slide in enumerate(prs.slides, 1):
            slide_text = []
            
            # Извлекаем текст со всех форм на слайде
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text.strip():
                    slide_text.append(shape.text.strip())
                    
                    # Если заголовок не найден, берем текст с первого слайда
                    if not title and slide_num == 1:
                        title = shape.text.strip()[:100]
            
            if slide_text:
                text_parts.append(f"Слайд {slide_num}: " + " ".join(slide_text))
        
        text = "\n\n".join(text_parts)
        
        # Очистка текста
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()
        
        return {
            "title": title or Path(pptx_path).stem,
            "content": text,
            "path": _relative_source_path(pptx_path)
        }
    except Exception as e:
        logger.error(f"Ошибка при чтении PPTX {pptx_path}: {e}")
        return None


def _normalize_doc_paragraphs(raw: str) -> Tuple[str, str]:
    """Заголовок — первая непустая строка до схлопывания; абзацы сохраняем."""
    lines = (raw or "").splitlines()
    title = ""
    for line in lines:
        stripped = line.strip()
        if stripped:
            title = stripped[:100]
            break
    normalized = [re.sub(r"[ \t]+", " ", line).strip() for line in lines]
    content = re.sub(r"\n{3,}", "\n\n", "\n".join(normalized)).strip()
    return title, content


def _extract_text_as_docx_zip(doc_path: Path) -> Optional[str]:
    """Попробовать прочитать файл как DOCX (ZIP) с неверным расширением .doc."""
    import zipfile

    if not zipfile.is_zipfile(doc_path):
        return None
    try:
        if DOCX_AVAILABLE:
            doc = Document(doc_path)
            paragraphs = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
            for table in doc.tables:
                for row in table.rows:
                    cells = [c.text.strip() for c in row.cells if c.text and c.text.strip()]
                    if cells:
                        paragraphs.append(" | ".join(cells))
            if paragraphs:
                return "\n".join(paragraphs)
        if DOC_AVAILABLE:
            text = docx2txt.process(str(doc_path))
            if text and str(text).strip():
                return str(text)
    except Exception as e:
        logger.debug("DOC как DOCX-ZIP не прочитан (%s): %s", doc_path.name, e)
    return None


def _extract_doc_via_external_tool(doc_path: Path) -> Optional[str]:
    """Извлечь текст через antiword / catdoc / textutil с таймаутом."""
    candidates: List[List[str]] = []
    if shutil.which("antiword"):
        candidates.append(["antiword", str(doc_path)])
    if shutil.which("catdoc"):
        candidates.append(["catdoc", "-w", str(doc_path)])
    if sys.platform == "darwin" and shutil.which("textutil"):
        candidates.append(["textutil", "-convert", "txt", "-stdout", str(doc_path)])

    for cmd in candidates:
        try:
            completed = subprocess.run(
                cmd,
                capture_output=True,
                timeout=60,
                check=False,
            )
            if completed.returncode != 0:
                logger.warning(
                    "Утилита %s вернула код %s для %s",
                    cmd[0],
                    completed.returncode,
                    doc_path.name,
                )
                continue
            text = completed.stdout.decode("utf-8", errors="replace")
            if text.strip():
                return text
        except subprocess.TimeoutExpired:
            logger.warning("Таймаут утилиты %s при чтении %s", cmd[0], doc_path.name)
        except Exception as e:
            logger.warning("Ошибка утилиты %s для %s: %s", cmd[0], doc_path.name, e)
    return None


def extract_text_from_doc(doc_path: Path) -> Optional[Dict[str, str]]:
    """Извлечь текст из .doc: сначала как DOCX-ZIP, иначе через системные утилиты."""
    raw = _extract_text_as_docx_zip(doc_path)
    if raw is None:
        raw = _extract_doc_via_external_tool(doc_path)
    if raw is None:
        logger.warning(
            "Пропуск DOC %s: docx2txt не читает бинарный .doc; "
            "установите antiword/catdoc (или textutil на macOS) либо сохраните как .docx",
            doc_path.name,
        )
        return None

    title, content = _normalize_doc_paragraphs(raw)
    if not content:
        logger.warning("DOC %s не содержит извлекаемого текста", doc_path.name)
        return None
    return {
        "title": title or Path(doc_path).stem,
        "content": content,
        "path": _relative_source_path(doc_path),
    }


def chunk_text(text: str, chunk_size: int = None, overlap: int = None) -> List[str]:
    """Разбить текст на чанки (совместимость: фиксированный размер)."""
    return chunk_text_fixed_size(text, chunk_size=chunk_size, overlap=overlap)


def _contextual_prefix_for_chunk(doc_title: str, section_path: str, chunk_body: str) -> str:
    """Короткая аннотация для Contextual Retrieval (только для индексации)."""
    body = re.sub(r"\s+", " ", chunk_body or "").strip()
    if len(body) < 40:
        return ""
    clip = body[:900]
    prompt = f"""Документ: {doc_title or "без названия"}
Раздел: {section_path or "не указан"}

Фрагмент:
{clip}

Задача: одно-два коротких предложения на русском: о чём этот фрагмент и зачем он полезен при поиске. Без вводных слов, без Markdown, только суть."""
    try:
        raw = (chat_completion(prompt, timeout=90) or "").strip()
        raw = raw.split("\n")[0].strip()
        return raw[:500] if raw else ""
    except Exception as e:
        logger.warning("Contextual retrieval: %s", e)
        return ""


def get_file_handlers() -> Dict[str, Callable[[Path], Optional[Dict[str, str]]]]:
    """Поддерживаемые форматы файлов и функции извлечения текста."""
    return {
        '.html': extract_text_from_html,
        '.htm': extract_text_from_html,
        '.txt': extract_text_from_txt,
        '.docx': extract_text_from_docx,
        '.pdf': extract_text_from_pdf,
        '.xlsx': extract_text_from_xlsx,
        '.xls': extract_text_from_xls,
        '.pptx': extract_text_from_pptx,
        '.doc': extract_text_from_doc,
    }


def _is_under_dir(path: Path, root: Optional[Path]) -> bool:
    if root is None:
        return False
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def scan_supported_files(data_dir: str) -> List[Path]:
    """Найти все поддерживаемые исходные файлы в стабильном порядке."""
    data_path = Path(data_dir)
    file_handlers = get_file_handlers()
    supported_exts = {ext.lower() for ext in file_handlers.keys()}
    excluded_extensions = {".crdownload", ".tmp", ".temp", ".bak"}
    skip_dir_names = {".git", "__pycache__"}

    attachments_dir: Optional[Path] = None
    raw_attachments = getattr(settings, "CHAT_ATTACHMENTS_DIR", None)
    if raw_attachments:
        try:
            attachments_dir = Path(str(raw_attachments)).resolve()
        except OSError:
            attachments_dir = None

    all_files: List[Path] = []
    for path in data_path.rglob("*"):
        if not path.is_file():
            continue
        if any(part in skip_dir_names for part in path.parts):
            continue
        if path.name.startswith("~$"):
            continue
        if _is_under_dir(path, attachments_dir):
            continue
        suffix = path.suffix.lower()
        if suffix not in supported_exts:
            continue
        if suffix in excluded_extensions:
            continue
        all_files.append(path)

    return sorted(
        all_files,
        key=lambda path: str(path).replace("\\", "/").lower(),
    )


def process_file(file_path: Path, extract_func: Callable[[Path], Optional[Dict[str, str]]]) -> List[Dict]:
    """Извлечь текст из одного файла и подготовить чанки для индексации."""
    file_started = time.perf_counter()
    ext = file_path.suffix.lower()
    extract_started = time.perf_counter()
    doc_data = extract_func(file_path)
    extract_ms = int((time.perf_counter() - extract_started) * 1000)

    if not doc_data or not doc_data["content"]:
        logger.warning(f"  Пропуск: не удалось извлечь текст из {file_path.name}")
        logger.info(
            "Reindex file diagnostics: file=%s ext=%s skipped=true extraction_ms=%s total_ms=%s chunks=0",
            file_path.name,
            ext,
            extract_ms,
            int((time.perf_counter() - file_started) * 1000),
        )
        return []

    chunk_started = time.perf_counter()
    chunk_items = build_chunks_for_file(file_path, doc_data)
    chunk_ms = int((time.perf_counter() - chunk_started) * 1000)
    documents = []

    for j, ch in enumerate(chunk_items):
        body = (ch.get("text") or "").strip()
        if not body:
            continue
        section_path = ch.get("section_path") or ""
        chunk_kind = ch.get("chunk_kind") or "text"
        headings = ch.get("parent_headings") or []
        try:
            headings_json = json.dumps(headings, ensure_ascii=False)
        except (TypeError, ValueError):
            headings_json = "[]"

        prefix = ""
        if settings.CONTEXTUAL_RETRIEVAL_ENABLED and j < settings.CONTEXTUAL_RETRIEVAL_MAX_CHUNKS:
            prefix = _contextual_prefix_for_chunk(doc_data.get("title") or "", section_path, body)

        embed_text = f"{prefix}\n\n{body}".strip() if prefix else body
        chunk_id_src = f"{doc_data['path']}_{j}"
        chunk_id = hashlib.md5(chunk_id_src.encode()).hexdigest()

        documents.append({
            "id": chunk_id,
            "text": body,
            "embed_text": embed_text,
            "metadata": {
                "title": doc_data["title"],
                "source": doc_data["title"] or doc_data["path"],
                "path": doc_data["path"],
                "file_type": ext,
                "chunk_index": j,
                "total_chunks": len(chunk_items),
                "section_path": section_path,
                "chunk_kind": chunk_kind,
                "parent_headings_json": headings_json,
                "contextual_prefix": prefix,
            }
        })

    logger.info(
        "Reindex file diagnostics: file=%s ext=%s skipped=%s extraction_ms=%s chunk_ms=%s total_ms=%s chunks=%s",
        file_path.name,
        ext,
        not bool(documents),
        extract_ms,
        chunk_ms,
        int((time.perf_counter() - file_started) * 1000),
        len(documents),
    )
    return documents


def embed_documents_batch(batch_docs: List[Dict]) -> List[Dict]:
    """Получить эмбеддинги для пачки документов."""
    batch_texts = [doc.get("embed_text") or doc["text"] for doc in batch_docs]
    batch_embeddings = get_embeddings_batch(batch_texts)
    embedded_documents = []

    if batch_embeddings and len(batch_embeddings) == len(batch_docs):
        for doc, embedding in zip(batch_docs, batch_embeddings):
            embedded_documents.append({
                "id": doc["id"],
                "text": doc["text"],
                "embed_text": doc.get("embed_text") or doc["text"],
                "metadata": doc["metadata"],
                "embedding": embedding,
            })
        return embedded_documents

    logger.warning("Пакетная обработка эмбеддингов не удалась, пробуем по одному...")
    for doc in batch_docs:
        embedding = get_embedding(doc.get("embed_text") or doc["text"])
        if embedding:
            embedded_documents.append({
                "id": doc["id"],
                "text": doc["text"],
                "embed_text": doc.get("embed_text") or doc["text"],
                "metadata": doc["metadata"],
                "embedding": embedding,
            })
        else:
            logger.error(f"Не удалось получить эмбеддинг для документа {doc['id']}")

    return embedded_documents


def preview_document(file_path: Path, duplicate_exists: bool = False) -> Dict:
    """Проанализировать документ без записи в ChromaDB."""
    path = Path(file_path)
    ext = path.suffix.lower()
    handlers = get_file_handlers()
    warnings = []

    if ext not in handlers:
        return {
            "filename": path.name,
            "file_type": ext.lstrip("."),
            "size_bytes": path.stat().st_size if path.exists() else 0,
            "supported": False,
            "warnings": ["Формат файла не поддерживается"],
            "chunk_count": 0,
            "chunks": [],
            "title": path.stem,
            "text_length": 0,
        }

    if duplicate_exists:
        warnings.append("Файл с таким именем уже есть в базе знаний")

    size_bytes = path.stat().st_size
    if size_bytes > 50 * 1024 * 1024:
        warnings.append("Файл больше 50 MB, индексация может занять много времени")

    doc_data = handlers[ext](path)
    if not doc_data or not doc_data.get("content"):
        return {
            "filename": path.name,
            "file_type": ext.lstrip("."),
            "size_bytes": size_bytes,
            "supported": True,
            "warnings": warnings + ["Не удалось извлечь текст из файла"],
            "chunk_count": 0,
            "chunks": [],
            "title": path.stem,
            "text_length": 0,
        }

    content = doc_data["content"]
    chunk_objs = build_chunks_for_file(path, doc_data)
    chunks = [c.get("text", "").strip() for c in chunk_objs if (c.get("text") or "").strip()]
    if not chunks:
        chunks = chunk_text(content)
    if len(content) < 200:
        warnings.append("В документе мало извлеченного текста")
    if not chunks:
        warnings.append("После разбиения не получилось полезных чанков")

    headings = re.findall(r"(?:(?:^|[.!?])\s*)([А-ЯA-Z][^.!?]{8,80})", content)
    return {
        "filename": path.name,
        "file_type": ext.lstrip("."),
        "size_bytes": size_bytes,
        "supported": True,
        "warnings": warnings,
        "chunk_count": len(chunks),
        "chunks": chunks[:3],
        "title": doc_data.get("title") or path.stem,
        "text_length": len(content),
        "headings": headings[:5],
    }


def process_files(file_paths: List[Path]) -> List[Dict]:
    """Обработать выбранные поддерживаемые файлы.

    Возвращает чанки. Счётчики skipped/failed пишутся в logger и в
    ``process_files.last_stats`` для diagnostics reindex.
    """
    started = time.perf_counter()
    documents = []
    skipped_files = 0
    failed_files = 0
    failed_file_names: List[str] = []

    file_handlers = get_file_handlers()
    all_files = list(file_paths)
    logger.info(f"Найдено файлов для обработки: {len(all_files)}")
    
    # Группируем файлы по типу для статистики
    file_counts = {}
    for file_path in all_files:
        ext = file_path.suffix.lower()
        file_counts[ext] = file_counts.get(ext, 0) + 1
    
    logger.info("Статистика по типам файлов:")
    for ext, count in sorted(file_counts.items()):
        logger.info(f"  {ext}: {count}")
    
    worker_count = max(1, settings.DOCUMENT_PROCESS_WORKERS)
    if worker_count == 1 or len(all_files) <= 1:
        for i, file_path in enumerate(all_files, 1):
            ext = file_path.suffix.lower()

            if ext not in file_handlers:
                continue

            logger.info(f"Обработка {i}/{len(all_files)}: {file_path.name} ({ext})")
            try:
                file_documents = process_file(file_path, file_handlers[ext])
            except Exception as e:
                failed_files += 1
                failed_file_names.append(file_path.name)
                logger.error(f"Ошибка при обработке {file_path}: {e}")
                continue
            if not file_documents:
                skipped_files += 1
            documents.extend(file_documents)
    else:
        logger.info(f"Параллельная обработка файлов: {worker_count} поток(ов)")
        results: List[List[Dict]] = [[] for _ in all_files]

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {}
            for i, file_path in enumerate(all_files):
                ext = file_path.suffix.lower()

                if ext not in file_handlers:
                    continue

                logger.info(f"Постановка в очередь {i + 1}/{len(all_files)}: {file_path.name} ({ext})")
                future = executor.submit(process_file, file_path, file_handlers[ext])
                futures[future] = (i, file_path)

            completed = 0
            for future in as_completed(futures):
                index, file_path = futures[future]
                completed += 1

                try:
                    results[index] = future.result()
                    if not results[index]:
                        skipped_files += 1
                    logger.info(
                        f"Готово {completed}/{len(futures)}: {file_path.name}, чанков: {len(results[index])}"
                    )
                except Exception as e:
                    failed_files += 1
                    failed_file_names.append(file_path.name)
                    logger.error(f"Ошибка при обработке {file_path}: {e}")

        for file_documents in results:
            documents.extend(file_documents)
    
    logger.info(f"Всего создано чанков: {len(documents)}")
    logger.info(
        "Reindex processing summary: files=%s chunks=%s skipped_files=%s failed_files=%s total_ms=%s",
        len(all_files),
        len(documents),
        skipped_files,
        failed_files,
        int((time.perf_counter() - started) * 1000),
    )
    process_files.last_stats = {  # type: ignore[attr-defined]
        "skipped_files": skipped_files,
        "failed_files": failed_files,
        "failed_file_names": failed_file_names,
        "files": len(all_files),
        "chunks": len(documents),
    }
    return documents


def process_all_files(data_dir: str) -> List[Dict]:
    """Обработать все поддерживаемые файлы в директории"""
    data_path = Path(data_dir)
    logger.info(f"Сканирование директории: {data_path}")
    return process_files(scan_supported_files(data_dir))


def create_vector_db(documents: List[Dict], progress_callback: Optional[Callable[[Dict], None]] = None):
    """Создать векторную базу данных в ChromaDB с пакетной обработкой для GPU"""
    logger.info("Создание векторной базы данных...")
    index_started = time.perf_counter()
    timings_ms: Dict[str, int] = {}

    def report_progress(progress: int, stage: str, message: str) -> None:
        if progress_callback:
            progress_callback({
                "progress": max(0, min(100, progress)),
                "stage": stage,
                "message": message,
            })
    
    # Создаем клиент ChromaDB. Старую коллекцию не трогаем, пока новые эмбеддинги не готовы.
    client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
    report_progress(12, "prepare", "Подготовка векторной коллекции")
    
    # Подготавливаем данные для вставки
    prepare_started = time.perf_counter()
    ids = []
    texts = []
    metadatas = []
    embeddings = []
    
    total_docs = len(documents)
    batches = []
    for start in range(0, total_docs, settings.BATCH_SIZE):
        batch_end = min(start + settings.BATCH_SIZE, total_docs)
        batches.append((start, batch_end, documents[start:batch_end]))
    timings_ms["prepare_ms"] = int((time.perf_counter() - prepare_started) * 1000)
    report_progress(15, "embedding", f"Генерация эмбеддингов: 0/{total_docs}")

    embedding_workers = max(1, settings.EMBEDDING_WORKERS)
    embedded_batches: List[List[Dict]] = [[] for _ in batches]
    embedding_started = time.perf_counter()

    if embedding_workers == 1 or len(batches) <= 1:
        embedded_count = 0
        for batch_index, (start, batch_end, batch_docs) in enumerate(batches):
            logger.info(
                f"Генерация эмбеддингов {start + 1}-{batch_end}/{total_docs} "
                f"(пакет {len(batch_docs)} документов)"
            )
            embedded_batches[batch_index] = embed_documents_batch(batch_docs)
            embedded_count += len(batch_docs)
            embedding_progress = 15 + int((embedded_count / max(total_docs, 1)) * 70)
            report_progress(
                embedding_progress,
                "embedding",
                f"Генерация эмбеддингов: {embedded_count}/{total_docs}",
            )
    else:
        logger.info(f"Параллельная генерация эмбеддингов: {embedding_workers} поток(ов)")
        with ThreadPoolExecutor(max_workers=embedding_workers) as executor:
            futures = {}
            for batch_index, (start, batch_end, batch_docs) in enumerate(batches):
                logger.info(
                    f"Постановка эмбеддингов в очередь {start + 1}-{batch_end}/{total_docs} "
                    f"(пакет {len(batch_docs)} документов)"
                )
                future = executor.submit(embed_documents_batch, batch_docs)
                futures[future] = (batch_index, start, batch_end)

            completed = 0
            embedded_count = 0
            for future in as_completed(futures):
                batch_index, start, batch_end = futures[future]
                completed += 1

                try:
                    embedded_batches[batch_index] = future.result()
                    embedded_count += batch_end - start
                    logger.info(
                        f"Эмбеддинги готовы {completed}/{len(futures)}: "
                        f"{start + 1}-{batch_end}/{total_docs}, "
                        f"получено: {len(embedded_batches[batch_index])}"
                    )
                    embedding_progress = 15 + int((embedded_count / max(total_docs, 1)) * 70)
                    report_progress(
                        embedding_progress,
                        "embedding",
                        f"Генерация эмбеддингов: {embedded_count}/{total_docs}",
                    )
                except Exception as e:
                    logger.error(f"Ошибка при генерации эмбеддингов {start + 1}-{batch_end}: {e}")

    timings_ms["embedding_ms"] = int((time.perf_counter() - embedding_started) * 1000)

    for embedded_batch in embedded_batches:
        for doc in embedded_batch:
            ids.append(doc["id"])
            texts.append(doc["text"])
            metadatas.append(doc["metadata"])
            embeddings.append(doc["embedding"])

    if not ids:
        raise RuntimeError("Не удалось получить эмбеддинги: старая векторная база не изменена")
    if len(ids) != total_docs:
        raise RuntimeError(
            "Получены не все эмбеддинги: "
            f"{len(ids)}/{total_docs}. Старая векторная база не изменена"
        )
    if not (len(ids) == len(texts) == len(metadatas) == len(embeddings)):
        raise RuntimeError("Несогласованные данные индексации: старая векторная база не изменена")
    
    # Вставляем данные в ChromaDB пакетами (максимальный размер пакета 5461)
    logger.info("Сохранение в ChromaDB...")
    report_progress(86, "saving", f"Сохранение в ChromaDB: 0/{len(ids)}")
    save_started = time.perf_counter()

    collection_name = settings.CHROMA_COLLECTION_NAME
    temp_name = f"{collection_name}__new"
    # Убрать незавершённую временную коллекцию от прошлого сбоя.
    try:
        client.delete_collection(temp_name)
    except Exception:
        pass

    collection = client.create_collection(
        name=temp_name,
        metadata={"description": "База знаний из XWiki"},
    )

    MAX_BATCH_SIZE = 5000  # Оставляем запас от лимита 5461

    total_docs = len(ids)
    saved = 0

    try:
        while saved < total_docs:
            batch_end = min(saved + MAX_BATCH_SIZE, total_docs)

            logger.info(f"Сохранение {saved+1}-{batch_end}/{total_docs} документов...")

            collection.add(
                ids=ids[saved:batch_end],
                documents=texts[saved:batch_end],
                metadatas=metadatas[saved:batch_end],
                embeddings=embeddings[saved:batch_end]
            )

            saved = batch_end
            save_progress = 86 + int((saved / max(total_docs, 1)) * 13)
            report_progress(save_progress, "saving", f"Сохранение в ChromaDB: {saved}/{total_docs}")
    except Exception:
        # При ошибке add временную коллекцию удаляем; старая остаётся нетронутой.
        try:
            client.delete_collection(temp_name)
        except Exception:
            pass
        raise

    # Атомарная подмена: удалить старую, переименовать временную.
    try:
        client.delete_collection(collection_name)
    except Exception:
        pass

    renamed = False
    try:
        collection.modify(name=collection_name)
        renamed = True
    except Exception as e:
        logger.warning(
            "Переименование коллекции %s -> %s недоступно (%s); "
            "пересоздаём под целевым именем",
            temp_name,
            collection_name,
            e,
        )

    if not renamed:
        collection = client.create_collection(
            name=collection_name,
            metadata={"description": "База знаний из XWiki"},
        )
        saved = 0
        while saved < total_docs:
            batch_end = min(saved + MAX_BATCH_SIZE, total_docs)
            collection.add(
                ids=ids[saved:batch_end],
                documents=texts[saved:batch_end],
                metadatas=metadatas[saved:batch_end],
                embeddings=embeddings[saved:batch_end],
            )
            saved = batch_end
        try:
            client.delete_collection(temp_name)
        except Exception:
            pass

    timings_ms["chroma_save_ms"] = int((time.perf_counter() - save_started) * 1000)
    
    logger.info(f"Векторная база данных создана! Всего документов: {len(ids)}")
    logger.info(f"База сохранена в: {settings.CHROMA_PERSIST_DIR}")
    
    # Инвалидируем кэш эмбеддингов после обновления базы
    logger.info("Инвалидация кэша эмбеддингов...")
    report_progress(99, "cache", "Очистка кэша эмбеддингов")
    invalidate_embedding_cache()
    logger.info("Кэш эмбеддингов очищен")

    bm25_texts = [d.get("embed_text") or d["text"] for d in documents]
    if len(ids) != len(bm25_texts):
        raise RuntimeError("BM25-корпус не совпадает с Chroma ids по длине")
    bm25_size_bytes = None
    bm25_started = time.perf_counter()
    try:
        save_bm25_index(ids, bm25_texts)
        bm25_path = bm25_index_path()
        if bm25_path.is_file():
            bm25_size_bytes = bm25_path.stat().st_size
        report_progress(100, "bm25", "Сохранён BM25-корпус для гибридного поиска")
    except Exception as e:
        logger.warning("BM25-индекс не сохранён: %s", e)
    finally:
        timings_ms["bm25_save_ms"] = int((time.perf_counter() - bm25_started) * 1000)

    manifest_started = time.perf_counter()
    try:
        manifest = save_index_manifest(documents)
        timings_ms["manifest_files"] = len(manifest.get("files") or {})
    except Exception as e:
        logger.warning("Manifest индекса не сохранён: %s", e)
    finally:
        timings_ms["manifest_save_ms"] = int((time.perf_counter() - manifest_started) * 1000)

    timings_ms["total_ms"] = int((time.perf_counter() - index_started) * 1000)
    logger.info(
        "Reindex create_vector_db summary: chunks=%s embeddings=%s skipped_embeddings=%s timings_ms=%s bm25_size_bytes=%s",
        len(documents),
        len(ids),
        len(documents) - len(ids),
        timings_ms,
        bm25_size_bytes,
    )
    return {
        "index_mode": "full",
        "chunks": len(ids),
        "embedded_chunks": len(ids),
        "skipped_embeddings": len(documents) - len(ids),
        "timings_ms": timings_ms,
        "bm25_size_bytes": bm25_size_bytes,
    }


def _embed_documents_or_raise(
    documents: List[Dict],
    progress_callback: Optional[Callable[[Dict], None]] = None,
) -> List[Dict]:
    """Сгенерировать эмбеддинги до любых изменений активной коллекции."""
    total_docs = len(documents)
    batches = []
    for start in range(0, total_docs, settings.BATCH_SIZE):
        batch_end = min(start + settings.BATCH_SIZE, total_docs)
        batches.append((start, batch_end, documents[start:batch_end]))

    embedded_batches: List[List[Dict]] = [[] for _ in batches]
    embedding_workers = max(1, settings.EMBEDDING_WORKERS)

    def report(done: int) -> None:
        if progress_callback:
            progress_callback({
                "progress": 15 + int((done / max(total_docs, 1)) * 55),
                "stage": "embedding",
                "message": f"Генерация эмбеддингов для изменённых чанков: {done}/{total_docs}",
            })

    if embedding_workers == 1 or len(batches) <= 1:
        embedded_count = 0
        for batch_index, (_start, _batch_end, batch_docs) in enumerate(batches):
            embedded_batches[batch_index] = embed_documents_batch(batch_docs)
            embedded_count += len(batch_docs)
            report(embedded_count)
    else:
        with ThreadPoolExecutor(max_workers=embedding_workers) as executor:
            futures = {
                executor.submit(embed_documents_batch, batch_docs): (batch_index, start, batch_end)
                for batch_index, (start, batch_end, batch_docs) in enumerate(batches)
            }
            embedded_count = 0
            for future in as_completed(futures):
                batch_index, start, batch_end = futures[future]
                try:
                    embedded_batches[batch_index] = future.result()
                except Exception as e:
                    logger.error(f"Ошибка при генерации эмбеддингов {start + 1}-{batch_end}: {e}")
                embedded_count += batch_end - start
                report(embedded_count)

    embedded_documents = [doc for batch in embedded_batches for doc in batch]
    if total_docs and len(embedded_documents) != total_docs:
        raise RuntimeError(
            "Получены не все эмбеддинги для incremental reindex: "
            f"{len(embedded_documents)}/{total_docs}. Активная база не изменена"
        )
    return embedded_documents


def _documents_by_path(documents: List[Dict]) -> Dict[str, List[Dict]]:
    grouped: Dict[str, List[Dict]] = {}
    for doc in documents:
        metadata = doc.get("metadata") or {}
        rel_path = str(metadata.get("path") or "").replace("\\", "/").lstrip("/")
        if rel_path:
            grouped.setdefault(rel_path, []).append(doc)
    return grouped


def _save_manifest_payload(manifest: Dict[str, Any]) -> None:
    out_path = manifest_path()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def reindex_vector_db(
    progress_callback: Optional[Callable[[Dict], None]] = None,
    incremental: bool = True,
) -> Dict[str, Any]:
    """Переиндексировать базу: incremental по manifest, иначе безопасный full fallback."""
    started = time.perf_counter()
    settings.ensure_directories()

    def report(progress: int, stage: str, message: str, **extra: Any) -> None:
        if progress_callback:
            payload = {
                "progress": max(0, min(100, progress)),
                "stage": stage,
                "message": message,
            }
            payload.update(extra)
            progress_callback(payload)

    report(1, "scan", "Сканирование документов")
    all_files = scan_supported_files(settings.DATA_DIR)
    current_by_path = {
        str(path.relative_to(Path(settings.DATA_DIR))).replace("\\", "/"): path
        for path in all_files
    }

    manifest = load_index_manifest()
    manifest_files = manifest.get("files") or {}
    current_fingerprint = settings_fingerprint()
    full_reason = None
    if not incremental:
        full_reason = "incremental_disabled"
    elif not manifest_files:
        full_reason = "manifest_missing"
    elif manifest.get("collection") != settings.CHROMA_COLLECTION_NAME:
        full_reason = "manifest_collection_mismatch"
    elif manifest.get("settings_fingerprint") != current_fingerprint:
        # Старый manifest без отпечатка тоже считается несовпадающим.
        full_reason = "settings_changed"
    elif load_bm25_corpus() is None:
        full_reason = "bm25_corpus_missing"

    if full_reason:
        report(5, "scan", f"Полная индексация: {full_reason}", diagnostics={"index_mode": "full"})
        documents = process_files(all_files)
        if not documents:
            raise RuntimeError("Не найдено документов для индексации")
        result = create_vector_db(documents, progress_callback=progress_callback)
        result["full_reason"] = full_reason
        result["files_total"] = len(all_files)
        stats = getattr(process_files, "last_stats", {}) or {}
        result["skipped_files"] = stats.get("skipped_files", 0)
        result["failed_files"] = stats.get("failed_files", 0)
        return result

    changed_paths: List[str] = []
    deleted_paths: List[str] = []
    unchanged_paths: List[str] = []
    new_paths: List[str] = []

    for rel_path, entry in manifest_files.items():
        path = current_by_path.get(rel_path)
        if path is None or not path.is_file():
            deleted_paths.append(rel_path)
            continue
        current = file_signature(path, Path(settings.DATA_DIR))
        if (
            current.get("size_bytes") != entry.get("size_bytes")
            or current.get("mtime_ns") != entry.get("mtime_ns")
            or current.get("sha256") != entry.get("sha256")
        ):
            changed_paths.append(rel_path)
        else:
            unchanged_paths.append(rel_path)

    known_paths = set(manifest_files.keys())
    new_paths = sorted(path for path in current_by_path.keys() if path not in known_paths)
    paths_to_process = sorted(set(changed_paths + new_paths))

    diagnostics: Dict[str, Any] = {
        "index_mode": "incremental",
        "files_total": len(all_files),
        "changed_files": len(changed_paths),
        "new_files": len(new_paths),
        "deleted_files": len(deleted_paths),
        "unchanged_files": len(unchanged_paths),
    }
    report(8, "scan", "Подготовка incremental reindex", diagnostics=diagnostics)

    if not paths_to_process and not deleted_paths:
        diagnostics["chunks_added"] = 0
        diagnostics["chunks_deleted"] = 0
        diagnostics["total_ms"] = int((time.perf_counter() - started) * 1000)
        logger.info("Reindex incremental summary: %s", diagnostics)
        report(100, "done", "Индекс уже актуален", diagnostics=diagnostics)
        return diagnostics

    changed_files = [current_by_path[path] for path in paths_to_process]
    changed_documents = process_files(changed_files) if changed_files else []
    process_stats = getattr(process_files, "last_stats", {}) or {}
    changed_docs_by_path = _documents_by_path(changed_documents)

    # Изменённые файлы без чанков: не валим весь reindex, чистим старые чанки.
    failed_changed_paths = [
        path for path in changed_paths if path not in changed_docs_by_path
    ]
    # Новые файлы без чанков: помечаем skipped в manifest, чтобы не гонять каждый раз.
    skipped_new_paths = [
        path for path in new_paths if path not in changed_docs_by_path
    ]
    if failed_changed_paths:
        logger.warning(
            "Изменённые файлы без чанков (удаляем старые записи): %s",
            ", ".join(failed_changed_paths[:10]),
        )
    if skipped_new_paths:
        logger.warning(
            "Новые файлы без чанков (skipped в manifest): %s",
            ", ".join(skipped_new_paths[:10]),
        )

    report(15, "embedding", f"Подготовлено изменённых чанков: {len(changed_documents)}", diagnostics=diagnostics)
    embedded_documents = (
        _embed_documents_or_raise(changed_documents, progress_callback=progress_callback)
        if changed_documents
        else []
    )

    client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
    try:
        collection = client.get_collection(settings.CHROMA_COLLECTION_NAME)
    except Exception as exc:
        logger.warning("Incremental reindex fallback to full: collection unavailable: %s", exc)
        documents = process_files(all_files)
        result = create_vector_db(documents, progress_callback=progress_callback)
        result["full_reason"] = "collection_missing"
        result["files_total"] = len(all_files)
        return result

    ids = [doc["id"] for doc in embedded_documents]
    texts = [doc["text"] for doc in embedded_documents]
    metadatas = [doc["metadata"] for doc in embedded_documents]
    embeddings = [doc["embedding"] for doc in embedded_documents]
    new_id_set: Set[str] = set(ids)

    # Удаляем чанки удалённых, успешно переиндексированных и «провалившихся» изменённых файлов.
    paths_needing_old_cleanup = deleted_paths + [
        p for p in changed_paths if p not in failed_changed_paths
    ] + failed_changed_paths

    affected_old_ids: Set[str] = set()
    ids_to_delete: Set[str] = set()
    for rel_path in paths_needing_old_cleanup:
        old_ids = {str(chunk_id) for chunk_id in (manifest_files.get(rel_path, {}).get("chunk_ids") or [])}
        affected_old_ids.update(old_ids)
        if rel_path in deleted_paths or rel_path in failed_changed_paths:
            ids_to_delete.update(old_ids)
        else:
            ids_to_delete.update(old_ids - new_id_set)

    report(75, "saving", "Обновление ChromaDB", diagnostics=diagnostics)
    max_batch_size = 5000
    for start in range(0, len(ids), max_batch_size):
        batch_end = min(start + max_batch_size, len(ids))
        collection.upsert(
            ids=ids[start:batch_end],
            documents=texts[start:batch_end],
            metadatas=metadatas[start:batch_end],
            embeddings=embeddings[start:batch_end],
        )
    if ids_to_delete:
        collection.delete(ids=sorted(ids_to_delete))

    bm25_corpus = load_bm25_corpus()
    if bm25_corpus:
        old_bm25_ids, old_bm25_texts = bm25_corpus
        retained = [
            (chunk_id, text)
            for chunk_id, text in zip(old_bm25_ids, old_bm25_texts)
            if str(chunk_id) not in affected_old_ids
        ]
        retained_ids = [chunk_id for chunk_id, _text in retained]
        retained_texts = [text for _chunk_id, text in retained]
    else:
        retained_ids = []
        retained_texts = []
    # Желательно atomic=True в save_bm25_index (поток D): пока вызываем как есть.
    save_bm25_index(
        retained_ids + ids,
        retained_texts + [doc.get("embed_text") or doc["text"] for doc in embedded_documents],
    )

    partial_manifest = build_index_manifest(embedded_documents)
    next_files = {
        rel_path: entry
        for rel_path, entry in manifest_files.items()
        if rel_path not in set(deleted_paths + changed_paths + skipped_new_paths)
    }
    next_files.update(partial_manifest.get("files") or {})

    # Провалившиеся изменённые — убираем из manifest (чанки уже удалены).
    for rel_path in failed_changed_paths:
        next_files.pop(rel_path, None)

    data_root = Path(settings.DATA_DIR)
    for rel_path in skipped_new_paths:
        source = current_by_path.get(rel_path)
        if source is None or not source.is_file():
            continue
        entry = file_signature(source, data_root)
        entry.update({
            "title": Path(rel_path).stem,
            "file_type": Path(rel_path).suffix.lower(),
            "chunk_ids": [],
            "exists": True,
            "skipped": True,
        })
        next_files[rel_path] = entry

    next_manifest = {
        "version": 1,
        "collection": settings.CHROMA_COLLECTION_NAME,
        "settings_fingerprint": current_fingerprint,
        "generated_at": partial_manifest.get("generated_at"),
        "files": dict(sorted(next_files.items())),
    }
    _save_manifest_payload(next_manifest)
    invalidate_embedding_cache()

    diagnostics.update({
        "chunks_added": len(ids),
        "chunks_deleted": len(ids_to_delete),
        "manifest_files": len(next_manifest["files"]),
        "failed_files": failed_changed_paths,
        "skipped_files": skipped_new_paths,
        "skipped_files_count": len(skipped_new_paths) + int(process_stats.get("skipped_files") or 0),
        "failed_files_count": len(failed_changed_paths) + int(process_stats.get("failed_files") or 0),
        "total_ms": int((time.perf_counter() - started) * 1000),
    })
    logger.info(
        "Reindex incremental summary: %s (skipped=%s failed=%s)",
        diagnostics,
        diagnostics["skipped_files_count"],
        diagnostics["failed_files_count"],
    )
    report(100, "done", "Incremental reindex завершён", diagnostics=diagnostics)
    return diagnostics


def main():
    """Главная функция"""
    settings.ensure_directories()
    logger.info("=" * 60)
    logger.info("Создание векторной базы знаний")
    logger.info("=" * 60)
    
    embedding_url = settings.get_embedding_base_url()
    try:
        model_names = fetch_remote_model_ids(role="embedding")
    except Exception as e:
        logger.error(f"Сервер эмбеддингов недоступен: {embedding_url}")
        logger.error(f"Не удалось получить список моделей: {e}")
        logger.error(
            "Проверьте EMBEDDING_BASE_URL/OLLAMA_URL, EMBEDDING_API_MODE и запуск сервера эмбеддингов."
        )
        return
    logger.info(f"Сервер эмбеддингов отвечает: {embedding_url}")

    model_found = False
    for name in model_names:
        if name == settings.OLLAMA_EMBEDDING_MODEL or name.startswith(
            settings.OLLAMA_EMBEDDING_MODEL + ":"
        ):
            model_found = True
            logger.info(f"Модель для эмбеддингов: {name} ✓")
            break

    if not model_found:
        logger.error(f"ВНИМАНИЕ: Модель {settings.OLLAMA_EMBEDDING_MODEL} не найдена в списке сервера!")
        logger.error(f"Доступные модели: {', '.join(model_names)}")
        if settings.INFERENCE_BACKEND == "ollama" or settings.EMBEDDING_API_MODE == "ollama":
            logger.error(f"Установите модель: ollama pull {settings.OLLAMA_EMBEDDING_MODEL}")
        else:
            logger.error("В LM Studio загрузите модель эмбеддингов с тем же id, что в OLLAMA_EMBEDDING_MODEL.")
        return
    
    # Обрабатываем все поддерживаемые файлы
    documents = process_all_files(settings.DATA_DIR)
    
    if not documents:
        logger.warning("Не найдено документов для обработки")
        return
    
    # Создаем векторную базу данных
    create_vector_db(documents)
    
    logger.info("=" * 60)
    logger.info("Готово!")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
