#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тестовый скрипт для проверки API ollama
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import requests
import json

OLLAMA_URL = "http://localhost:11434"

def test_ollama_connection():
    """Проверка подключения к ollama"""
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        response.raise_for_status()
        result = response.json()
        print("✓ Ollama доступен")
        print(f"Доступные модели:")
        for model in result.get('models', []):
            print(f"  - {model.get('name')}")
        return True
    except Exception as e:
        print(f"✗ Ошибка подключения к ollama: {e}")
        return False


def test_embeddings_api_v1():
    """Тест API v1 для эмбеддингов (/api/embeddings)"""
    print("\n--- Тест API v1 (/api/embeddings) ---")
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/embeddings",
            json={
                "model": "qwen",
                "prompt": "Тестовый текст для проверки эмбеддингов"
            },
            timeout=30
        )
        print(f"Статус: {response.status_code}")
        print(f"Ответ: {response.text[:500]}")
        
        if response.status_code == 200:
            result = response.json()
            embedding = result.get("embedding", [])
            print(f"✓ Эмбеддинг получен, размер: {len(embedding)}")
            return True
        else:
            print(f"✗ Ошибка API v1")
            return False
    except Exception as e:
        print(f"✗ Ошибка: {e}")
        return False


def test_embeddings_api_v2():
    """Тест API v2 для эмбеддингов (/api/embed)"""
    print("\n--- Тест API v2 (/api/embed) ---")
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/embed",
            json={
                "model": "qwen",
                "input": "Тестовый текст для проверки эмбеддингов"
            },
            timeout=30
        )
        print(f"Статус: {response.status_code}")
        print(f"Ответ: {response.text[:500]}")
        
        if response.status_code == 200:
            result = response.json()
            if "embeddings" in result:
                embeddings = result["embeddings"]
                print(f"✓ Эмбеддинг получен, размер: {len(embeddings[0]) if embeddings else 0}")
                return True
            elif "embedding" in result:
                embedding = result["embedding"]
                print(f"✓ Эмбеддинг получен, размер: {len(embedding)}")
                return True
        else:
            print(f"✗ Ошибка API v2")
            return False
    except Exception as e:
        print(f"✗ Ошибка: {e}")
        return False


def test_model_for_embeddings(model_name):
    """Тест конкретной модели для эмбеддингов"""
    print(f"\n--- Тест модели {model_name} ---")
    try:
        # Пробуем API v2
        response = requests.post(
            f"{OLLAMA_URL}/api/embed",
            json={
                "model": model_name,
                "input": "Тестовый текст"
            },
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            if "embeddings" in result:
                embeddings = result["embeddings"]
                print(f"✓ Модель {model_name} поддерживает эмбеддинги (API v2)")
                print(f"  Размер эмбеддинга: {len(embeddings[0]) if embeddings else 0}")
                return True
            elif "embedding" in result:
                embedding = result["embedding"]
                print(f"✓ Модель {model_name} поддерживает эмбеддинги (API v2)")
                print(f"  Размер эмбеддинга: {len(embedding)}")
                return True
        else:
            print(f"✗ Модель {model_name} не поддерживает эмбеддинги через API v2")
            print(f"  Статус: {response.status_code}")
            print(f"  Ответ: {response.text[:200]}")
            return False
    except Exception as e:
        print(f"✗ Ошибка: {e}")
        return False


def main():
    print("=" * 60)
    print("Тестирование API ollama для эмбеддингов")
    print("=" * 60)
    
    # Проверка подключения
    if not test_ollama_connection():
        return
    
    # Тест разных API
    api_v1_works = test_embeddings_api_v1()
    api_v2_works = test_embeddings_api_v2()
    
    # Тест разных моделей
    models_to_test = ["qwen", "nomic-embed-text", "mxbai-embed-large", "all-minilm"]
    
    print("\n" + "=" * 60)
    print("Тестирование разных моделей")
    print("=" * 60)
    
    working_models = []
    for model in models_to_test:
        if test_model_for_embeddings(model):
            working_models.append(model)
    
    print("\n" + "=" * 60)
    print("РЕЗУЛЬТАТЫ")
    print("=" * 60)
    print(f"API v1 (/api/embeddings): {'✓ Работает' if api_v1_works else '✗ Не работает'}")
    print(f"API v2 (/api/embed): {'✓ Работает' if api_v2_works else '✗ Не работает'}")
    print(f"\nМодели, поддерживающие эмбеддинги:")
    if working_models:
        for model in working_models:
            print(f"  ✓ {model}")
    else:
        print("  ✗ Не найдено моделей, поддерживающих эмбеддинги")
        print("\nРекомендация: установите модель для эмбеддингов:")
        print("  docker exec -it ollama ollama pull nomic-embed-text")


if __name__ == "__main__":
    main()
