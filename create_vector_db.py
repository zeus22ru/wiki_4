#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для создания векторной базы данных из файлов в папке data/
Поддерживает HTML, DOCX, PDF, XLSX, XLS, PPTX, DOC форматы.
Использует ollama для генерации эмбеддингов и ChromaDB для хранения.
"""

import os
import re
import sys
from pathlib import Path
from bs4 import BeautifulSoup
import chromadb
from chromadb.config import Settings
import requests
import json
from typing import List, Dict, Optional
import hashlib

# Импорт конфигурации и логирования
from config import settings, get_logger

# Импорт кэширования
from utils import get_cached_embedding, cache_embedding, invalidate_embedding_cache

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

# Устанавливаем UTF-8 для вывода в консоль (Windows)
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Конфигурация загружается из config/settings.py
# OLLAMA_URL, OLLAMA_MODEL, OLLAMA_CHAT_MODEL, CHROMA_PERSIST_DIR,
# DATA_DIR, CHUNK_SIZE, CHUNK_OVERLAP, BATCH_SIZE


def get_embedding(text: str) -> List[float]:
    """Получить эмбеддинг текста через ollama (API v2) с кэшированием"""
    # Проверяем кэш
    cached = get_cached_embedding(text, settings.OLLAMA_EMBEDDING_MODEL)
    if cached is not None:
        logger.debug(f"Эмбеддинг получен из кэша для текста: {text[:50]}...")
        return cached
    
    # Получаем эмбеддинг из Ollama
    try:
        response = requests.post(
            f"{settings.OLLAMA_URL}/api/embed",
            json={
                "model": settings.OLLAMA_EMBEDDING_MODEL,
                "input": text
            },
            timeout=60
        )
        response.raise_for_status()
        result = response.json()
        # API v2 возвращает embeddings (массив) или embedding (один)
        if "embeddings" in result:
            embedding = result["embeddings"][0]
        elif "embedding" in result:
            embedding = result["embedding"]
        else:
            return []
        
        # Кэшируем эмбеддинг
        cache_embedding(text, settings.OLLAMA_EMBEDDING_MODEL, embedding)
        logger.debug(f"Эмбеддинг закэширован для текста: {text[:50]}...")
        
        return embedding
    except Exception as e:
        logger.error(f"Ошибка при получении эмбеддинга: {e}")
        return []


def get_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """Получить эмбеддинги для нескольких текстов за один запрос (GPU-оптимизировано) с кэшированием"""
    if not texts:
        return []
    
    # Проверяем кэш для каждого текста
    embeddings = []
    texts_to_fetch = []
    indices_to_fetch = []
    
    for i, text in enumerate(texts):
        cached = get_cached_embedding(text, settings.OLLAMA_EMBEDDING_MODEL)
        if cached is not None:
            embeddings.append(cached)
            logger.debug(f"Эмбеддинг {i} получен из кэша")
        else:
            embeddings.append(None)
            texts_to_fetch.append(text)
            indices_to_fetch.append(i)
    
    # Получаем эмбеддинги для текстов, которых нет в кэше
    if texts_to_fetch:
        try:
            response = requests.post(
                f"{settings.OLLAMA_URL}/api/embed",
                json={
                    "model": settings.OLLAMA_EMBEDDING_MODEL,
                    "input": texts_to_fetch  # Массив текстов для пакетной обработки
                },
                timeout=120
            )
            response.raise_for_status()
            result = response.json()
            fetched_embeddings = result.get("embeddings", [])
            
            # Кэшируем и вставляем полученные эмбеддинги
            for i, embedding in enumerate(fetched_embeddings):
                text = texts_to_fetch[i]
                index = indices_to_fetch[i]
                embeddings[index] = embedding
                cache_embedding(text, settings.OLLAMA_EMBEDDING_MODEL, embedding)
                logger.debug(f"Эмбеддинг {index} закэширован")
                
        except Exception as e:
            logger.error(f"Ошибка при пакетном получении эмбеддингов: {e}")
            # Возвращаем только кэшированные эмбеддинги
            return [emb for emb in embeddings if emb is not None]
    
    return embeddings


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
        
        # Получаем основной текст
        text = soup.get_text(separator=' ', strip=True)
        
        # Очистка текста
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()
        
        return {
            "title": title or h1 or Path(html_path).stem,
            "content": text,
            "path": str(html_path.relative_to(settings.DATA_DIR))
        }
    except Exception as e:
        print(f"Ошибка при чтении {html_path}: {e}")
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
            "path": str(docx_path.relative_to(settings.DATA_DIR))
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
            "path": str(pdf_path.relative_to(settings.DATA_DIR))
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
            "path": str(xlsx_path.relative_to(settings.DATA_DIR))
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
            "path": str(xls_path.relative_to(settings.DATA_DIR))
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
            "path": str(pptx_path.relative_to(DATA_DIR))
        }
    except Exception as e:
        logger.error(f"Ошибка при чтении PPTX {pptx_path}: {e}")
        return None


def extract_text_from_doc(doc_path: Path) -> Optional[Dict[str, str]]:
    """Извлечь текст и метаданные из DOC файла (старый формат Word)"""
    if not DOC_AVAILABLE:
        logger.warning(f"Библиотека docx2txt не установлена. Пропуск: {doc_path.name}")
        return None
    
    try:
        text = docx2txt.process(doc_path)
        
        # Очистка текста
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()
        
        # Берем первую строку как заголовок
        lines = text.split('\n')
        title = lines[0].strip()[:100] if lines else Path(doc_path).stem
        
        return {
            "title": title,
            "content": text,
            "path": str(doc_path.relative_to(settings.DATA_DIR))
        }
    except Exception as e:
        logger.error(f"Ошибка при чтении DOC {doc_path}: {e}")
        return None


def chunk_text(text: str, chunk_size: int = None, overlap: int = None) -> List[str]:
    """Разбить текст на чанки"""
    if chunk_size is None:
        chunk_size = settings.CHUNK_SIZE
    if overlap is None:
        overlap = settings.CHUNK_OVERLAP
    chunks = []
    start = 0
    text_len = len(text)
    
    while start < text_len:
        end = start + chunk_size
        chunk = text[start:end]
        
        # Пытаемся разбить по границе предложения
        if end < text_len:
            last_period = chunk.rfind('.')
            last_question = chunk.rfind('?')
            last_exclamation = chunk.rfind('!')
            last_boundary = max(last_period, last_question, last_exclamation)
            
            if last_boundary > chunk_size // 2:
                chunk = text[start:start + last_boundary + 1]
                end = start + last_boundary + 1
        
        chunks.append(chunk.strip())
        start = end - overlap
    
    return [c for c in chunks if len(c) > 50]


def process_all_files(data_dir: str) -> List[Dict]:
    """Обработать все поддерживаемые файлы в директории"""
    data_path = Path(data_dir)
    documents = []
    
    logger.info(f"Сканирование директории: {data_path}")
    
    # Поддерживаемые форматы файлов и соответствующие функции извлечения
    file_handlers = {
        '.html': extract_text_from_html,
        '.htm': extract_text_from_html,
        '.docx': extract_text_from_docx,
        '.pdf': extract_text_from_pdf,
        '.xlsx': extract_text_from_xlsx,
        '.xls': extract_text_from_xls,
        '.pptx': extract_text_from_pptx,
        '.doc': extract_text_from_doc,
    }
    
    # Собираем все файлы поддерживаемых форматов
    all_files = []
    for ext in file_handlers.keys():
        files = list(data_path.rglob(f"*{ext}"))
        all_files.extend(files)
    
    # Исключаем временные файлы и файлы с расширениями, которые не нужно обрабатывать
    excluded_extensions = {'.crdownload', '.tmp', '.temp', '.bak'}
    all_files = [f for f in all_files if f.suffix.lower() not in excluded_extensions]
    
    logger.info(f"Найдено файлов: {len(all_files)}")
    
    # Группируем файлы по типу для статистики
    file_counts = {}
    for file_path in all_files:
        ext = file_path.suffix.lower()
        file_counts[ext] = file_counts.get(ext, 0) + 1
    
    logger.info("Статистика по типам файлов:")
    for ext, count in sorted(file_counts.items()):
        logger.info(f"  {ext}: {count}")
    
    # Обрабатываем каждый файл
    for i, file_path in enumerate(all_files, 1):
        ext = file_path.suffix.lower()
        
        # Пропускаем файлы без расширения или неподдерживаемые
        if ext not in file_handlers:
            continue
        
        logger.info(f"Обработка {i}/{len(all_files)}: {file_path.name} ({ext})")
        
        # Вызываем соответствующую функцию извлечения
        extract_func = file_handlers[ext]
        doc_data = extract_func(file_path)
        
        if doc_data and doc_data["content"]:
            # Разбиваем на чанки
            chunks = chunk_text(doc_data["content"])
            
            for j, chunk in enumerate(chunks):
                documents.append({
                    "id": f"{hashlib.md5(f'{doc_data['path']}_{j}'.encode()).hexdigest()}",
                    "text": chunk,
                    "metadata": {
                        "title": doc_data["title"],
                        "path": doc_data["path"],
                        "file_type": ext,
                        "chunk_index": j,
                        "total_chunks": len(chunks)
                    }
                })
        else:
            logger.warning(f"  Пропуск: не удалось извлечь текст из {file_path.name}")
    
    logger.info(f"Всего создано чанков: {len(documents)}")
    return documents


def create_vector_db(documents: List[Dict]):
    """Создать векторную базу данных в ChromaDB с пакетной обработкой для GPU"""
    logger.info("Создание векторной базы данных...")
    
    # Создаем клиент ChromaDB
    client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
    
    # Удаляем коллекцию если существует
    try:
        client.delete_collection(settings.CHROMA_COLLECTION_NAME)
    except:
        pass
    
    # Создаем коллекцию
    collection = client.create_collection(
        name=settings.CHROMA_COLLECTION_NAME,
        metadata={"description": "База знаний из XWiki"}
    )
    
    # Подготавливаем данные для вставки
    ids = []
    texts = []
    metadatas = []
    embeddings = []
    
    total_docs = len(documents)
    processed = 0
    
    # Пакетная обработка для ускорения на GPU
    while processed < total_docs:
        batch_end = min(processed + settings.BATCH_SIZE, total_docs)
        batch_docs = documents[processed:batch_end]
        batch_texts = [doc["text"] for doc in batch_docs]
        
        logger.info(f"Генерация эмбеддингов {processed+1}-{batch_end}/{total_docs} (пакет {len(batch_texts)} документов)")
        
        # Получаем эмбеддинги для всего пакета за один запрос
        batch_embeddings = get_embeddings_batch(batch_texts)
        
        if batch_embeddings and len(batch_embeddings) == len(batch_docs):
            for doc, embedding in zip(batch_docs, batch_embeddings):
                ids.append(doc["id"])
                texts.append(doc["text"])
                metadatas.append(doc["metadata"])
                embeddings.append(embedding)
        else:
            # Если пакетная обработка не удалась, пробуем по одному
            logger.warning(f"Пакетная обработка не удалась, пробуем по одному...")
            for doc in batch_docs:
                embedding = get_embedding(doc["text"])
                if embedding:
                    ids.append(doc["id"])
                    texts.append(doc["text"])
                    metadatas.append(doc["metadata"])
                    embeddings.append(embedding)
                else:
                    logger.error(f"Не удалось получить эмбеддинг для документа {doc['id']}")
        
        processed = batch_end
    
    # Вставляем данные в ChromaDB пакетами (максимальный размер пакета 5461)
    logger.info("Сохранение в ChromaDB...")
    MAX_BATCH_SIZE = 5000  # Оставляем запас от лимита 5461
    
    total_docs = len(ids)
    saved = 0
    
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
    
    logger.info(f"Векторная база данных создана! Всего документов: {len(ids)}")
    logger.info(f"База сохранена в: {settings.CHROMA_PERSIST_DIR}")
    
    # Инвалидируем кэш эмбеддингов после обновления базы
    logger.info("Инвалидация кэша эмбеддингов...")
    invalidate_embedding_cache()
    logger.info("Кэш эмбеддингов очищен")


def main():
    """Главная функция"""
    logger.info("=" * 60)
    logger.info("Создание векторной базы знаний")
    logger.info("=" * 60)
    
    # Проверяем доступность ollama
    try:
        response = requests.get(f"{settings.OLLAMA_URL}/api/tags", timeout=5)
        response.raise_for_status()
        logger.info(f"Ollama доступен по адресу: {settings.OLLAMA_URL}")
        
        # Проверяем наличие модели для эмбеддингов
        models = response.json().get("models", [])
        model_names = [m.get("name", "") for m in models]
        
        # Проверяем наличие модели (с учетом суффикса :latest)
        model_found = False
        for name in model_names:
            if name == settings.OLLAMA_EMBEDDING_MODEL or name.startswith(settings.OLLAMA_EMBEDDING_MODEL + ":"):
                model_found = True
                logger.info(f"Модель для эмбеддингов: {name} ✓")
                break
        
        if not model_found:
            logger.error(f"ВНИМАНИЕ: Модель {settings.OLLAMA_EMBEDDING_MODEL} не найдена!")
            logger.error(f"Доступные модели: {', '.join(model_names)}")
            logger.error(f"Установите модель: docker exec ollama-ai ollama pull {settings.OLLAMA_EMBEDDING_MODEL}")
            return
        
    except Exception as e:
        logger.error(f"Ошибка: Ollama недоступен по адресу {settings.OLLAMA_URL}")
        logger.error(f"Убедитесь, что ollama запущен в Docker с поддержкой GPU:")
        logger.error(f"  docker run -d --gpus all -p 11434:11434 --name ollama-ai ollama/ollama")
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
