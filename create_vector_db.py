#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для создания векторной базы данных из HTML файлов в папке data/
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
from typing import List, Dict
import hashlib

# Устанавливаем UTF-8 для вывода в консоль (Windows)
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Конфигурация
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "bge-m3"  # Модель для эмбеддингов (BAAI/bge-m3 - многоязычная)
OLLAMA_CHAT_MODEL = "qwen2.5:7b"  # Модель для генерации ответов
CHROMA_PERSIST_DIR = "./chroma_db"
DATA_DIR = "./data"  # Обработка всех HTML файлов рекурсивно в папке data/
CHUNK_SIZE = 500  # Размер чанка в символах
CHUNK_OVERLAP = 50  # Перекрытие чанков
BATCH_SIZE = 10  # Размер пакета для пакетной обработки эмбеддингов


def get_embedding(text: str) -> List[float]:
    """Получить эмбеддинг текста через ollama (API v2)"""
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/embed",
            json={
                "model": OLLAMA_MODEL,
                "input": text
            },
            timeout=60
        )
        response.raise_for_status()
        result = response.json()
        # API v2 возвращает embeddings (массив) или embedding (один)
        if "embeddings" in result:
            return result["embeddings"][0]
        elif "embedding" in result:
            return result["embedding"]
        return []
    except Exception as e:
        print(f"Ошибка при получении эмбеддинга: {e}")
        return []


def get_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """Получить эмбеддинги для нескольких текстов за один запрос (GPU-оптимизировано)"""
    if not texts:
        return []
    
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/embed",
            json={
                "model": OLLAMA_MODEL,
                "input": texts  # Массив текстов для пакетной обработки
            },
            timeout=120
        )
        response.raise_for_status()
        result = response.json()
        return result.get("embeddings", [])
    except Exception as e:
        print(f"Ошибка при пакетном получении эмбеддингов: {e}")
        return []


def extract_text_from_html(html_path: Path) -> Dict[str, str]:
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
            "path": str(html_path.relative_to(DATA_DIR))
        }
    except Exception as e:
        print(f"Ошибка при чтении {html_path}: {e}")
        return None


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """Разбить текст на чанки"""
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


def process_html_files(data_dir: str) -> List[Dict]:
    """Обработать все HTML файлы в директории"""
    data_path = Path(data_dir)
    documents = []
    
    print(f"Сканирование директории: {data_path}")
    
    # Находим все HTML файлы
    html_files = list(data_path.rglob("*.html"))
    print(f"Найдено HTML файлов: {len(html_files)}")
    
    for i, html_file in enumerate(html_files, 1):
        print(f"Обработка {i}/{len(html_files)}: {html_file.name}")
        
        doc_data = extract_text_from_html(html_file)
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
                        "chunk_index": j,
                        "total_chunks": len(chunks)
                    }
                })
    
    print(f"Всего создано чанков: {len(documents)}")
    return documents


def create_vector_db(documents: List[Dict]):
    """Создать векторную базу данных в ChromaDB с пакетной обработкой для GPU"""
    print("Создание векторной базы данных...")
    
    # Создаем клиент ChromaDB
    client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
    
    # Удаляем коллекцию если существует
    try:
        client.delete_collection("wiki_knowledge")
    except:
        pass
    
    # Создаем коллекцию
    collection = client.create_collection(
        name="wiki_knowledge",
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
        batch_end = min(processed + BATCH_SIZE, total_docs)
        batch_docs = documents[processed:batch_end]
        batch_texts = [doc["text"] for doc in batch_docs]
        
        print(f"Генерация эмбеддингов {processed+1}-{batch_end}/{total_docs} (пакет {len(batch_texts)} документов)")
        
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
            print(f"Пакетная обработка не удалась, пробуем по одному...")
            for doc in batch_docs:
                embedding = get_embedding(doc["text"])
                if embedding:
                    ids.append(doc["id"])
                    texts.append(doc["text"])
                    metadatas.append(doc["metadata"])
                    embeddings.append(embedding)
                else:
                    print(f"Не удалось получить эмбеддинг для документа {doc['id']}")
        
        processed = batch_end
    
    # Вставляем данные в ChromaDB
    print("Сохранение в ChromaDB...")
    collection.add(
        ids=ids,
        documents=texts,
        metadatas=metadatas,
        embeddings=embeddings
    )
    
    print(f"Векторная база данных создана! Всего документов: {len(ids)}")
    print(f"База сохранена в: {CHROMA_PERSIST_DIR}")


def main():
    """Главная функция"""
    print("=" * 60, flush=True)
    print("Создание векторной базы знаний", flush=True)
    print("=" * 60, flush=True)
    
    # Проверяем доступность ollama
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        response.raise_for_status()
        print(f"Ollama доступен по адресу: {OLLAMA_URL}", flush=True)
        
        # Проверяем наличие модели для эмбеддингов
        models = response.json().get("models", [])
        model_names = [m.get("name", "") for m in models]
        
        # Проверяем наличие модели (с учетом суффикса :latest)
        model_found = False
        for name in model_names:
            if name == OLLAMA_MODEL or name.startswith(OLLAMA_MODEL + ":"):
                model_found = True
                print(f"Модель для эмбеддингов: {name} ✓")
                break
        
        if not model_found:
            print(f"ВНИМАНИЕ: Модель {OLLAMA_MODEL} не найдена!", flush=True)
            print(f"Доступные модели: {', '.join(model_names)}", flush=True)
            print(f"Установите модель: docker exec ollama-ai ollama pull {OLLAMA_MODEL}", flush=True)
            return
        
    except Exception as e:
        print(f"Ошибка: Ollama недоступен по адресу {OLLAMA_URL}", flush=True)
        print(f"Убедитесь, что ollama запущен в Docker с поддержкой GPU:", flush=True)
        print(f"  docker run -d --gpus all -p 11434:11434 --name ollama-ai ollama/ollama", flush=True)
        return
    
    # Обрабатываем HTML файлы
    documents = process_html_files(DATA_DIR)
    
    if not documents:
        print("Не найдено документов для обработки", flush=True)
        return
    
    # Создаем векторную базу данных
    create_vector_db(documents)
    
    print("=" * 60, flush=True)
    print("Готово!", flush=True)
    print("=" * 60, flush=True)


if __name__ == "__main__":
    main()
