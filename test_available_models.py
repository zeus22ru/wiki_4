#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тест доступных моделей на поддержку эмбеддингов
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import requests

OLLAMA_URL = "http://localhost:11434"

def test_model_embeddings(model_name):
    """Тест модели на поддержку эмбеддингов"""
    print(f"\n--- Тест модели: {model_name} ---")
    
    # Пробуем API v2
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/embed",
            json={
                "model": model_name,
                "input": "Тестовый текст"
            },
            timeout=30
        )
        
        print(f"Статус: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            if "embeddings" in result:
                embeddings = result["embeddings"]
                print(f"✓ Модель поддерживает эмбеддинги (API v2)")
                print(f"  Размер эмбеддинга: {len(embeddings[0]) if embeddings else 0}")
                return True, len(embeddings[0]) if embeddings else 0
            elif "embedding" in result:
                embedding = result["embedding"]
                print(f"✓ Модель поддерживает эмбеддинги (API v2)")
                print(f"  Размер эмбеддинга: {len(embedding)}")
                return True, len(embedding)
        else:
            print(f"✗ Ошибка: {response.text[:200]}")
            return False, 0
    except Exception as e:
        print(f"✗ Ошибка: {e}")
        return False, 0


def main():
    print("=" * 60)
    print("Тестирование доступных моделей")
    print("=" * 60)
    
    # Получаем список моделей
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        response.raise_for_status()
        result = response.json()
        models = [m.get('name') for m in result.get('models', [])]
        print(f"\nДоступные модели: {models}")
    except Exception as e:
        print(f"Ошибка получения списка моделей: {e}")
        return
    
    # Тестируем каждую модель
    working_models = []
    for model in models:
        works, size = test_model_embeddings(model)
        if works:
            working_models.append((model, size))
    
    print("\n" + "=" * 60)
    print("РЕЗУЛЬТАТЫ")
    print("=" * 60)
    
    if working_models:
        print("Модели, поддерживающие эмбеддинги:")
        for model, size in working_models:
            print(f"  ✓ {model} (размер: {size})")
        
        # Рекомендуем модель с наибольшим размером
        best_model = max(working_models, key=lambda x: x[1])
        print(f"\nРекомендуемая модель: {best_model[0]}")
    else:
        print("✗ Ни одна из доступных моделей не поддерживает эмбеддинги")
        print("\nРекомендация: установите модель для эмбеддингов:")
        print("  docker exec -it ollama ollama pull nomic-embed-text")
        print("  docker exec -it ollama ollama pull mxbai-embed-large")


if __name__ == "__main__":
    main()
