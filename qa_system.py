#!/usr/bin/env python3
"""
Скрипт для вопрос-ответной системы на основе векторной базы данных
Использует ollama для генерации ответов и ChromaDB для поиска релевантных документов.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, Optional

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import settings, get_logger, inference_server_reachable
from core.rag import RAGResult, RAGSystem

logger = get_logger(__name__)


def _print_sources(result: RAGResult) -> None:
    if not result.sources:
        return

    logger.info("\n" + "=" * 60)
    logger.info("РЕЛЕВАНТНЫЕ ДОКУМЕНТЫ:")
    logger.info("=" * 60)
    for i, source in enumerate(result.sources, 1):
        title = source.get("title") or source.get("source") or "Без названия"
        path = source.get("path") or "N/A"
        score = float(source.get("score") or source.get("relevance") or 0.0)
        text = str(source.get("text") or "")
        print(f"\n--- Документ {i} ---")
        print(f"Источник: {title}")
        print(f"Путь: {path}")
        print(f"Релевантность: {score:.2f}")
        if source.get("section_path"):
            print(f"Раздел: {source['section_path']}")
        print(f"Текст: {text[:300]}...")


def _print_answer(result: RAGResult) -> None:
    if result.retrieve_error:
        logger.warning("Retrieval warning: %s", result.retrieve_error)
    _print_sources(result)
    print("\n" + "-" * 60)
    print("ОТВЕТ:")
    print("-" * 60)
    print(result.answer)
    print("-" * 60 + "\n")


def ask(rag: RAGSystem, query: str, top_k: Optional[int], min_score: Optional[float], answer_mode: str) -> RAGResult:
    logger.info("\nГенерация ответа через RAGSystem.query()...")
    return rag.query(
        query,
        top_k=top_k,
        min_score=min_score,
        answer_mode=answer_mode,
    )


def interactive_mode(rag: RAGSystem, top_k: Optional[int], min_score: Optional[float], answer_mode: str) -> None:
    """Интерактивный режим вопрос-ответ"""
    logger.info("\n" + "=" * 60)
    logger.info("Режим вопрос-ответ (введите 'exit' для выхода)")
    logger.info("=" * 60 + "\n")
    
    while True:
        try:
            query = input("Ваш вопрос: ").strip()
            
            if query.lower() in ['exit', 'quit', 'выход', 'q']:
                logger.info("До свидания!")
                break
            
            if not query:
                continue

            _print_answer(ask(rag, query, top_k, min_score, answer_mode))
            
        except KeyboardInterrupt:
            logger.info("\n\nДо свидания!")
            break
        except Exception as e:
            logger.error(f"\nОшибка: {e}\n")


def single_query_mode(rag: RAGSystem, query: str, top_k: Optional[int], min_score: Optional[float], answer_mode: str) -> None:
    """Режим одиночного запроса"""
    _print_answer(ask(rag, query, top_k, min_score, answer_mode))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="CLI вопрос-ответ через текущий RAGSystem.query() и настройки проекта."
    )
    parser.add_argument("query", nargs="*", help="Вопрос. Если не задан, включается интерактивный режим.")
    parser.add_argument("--top-k", type=int, default=None, help="Количество источников для поиска")
    parser.add_argument("--min-score", type=float, default=None, help="Минимальный score источника")
    parser.add_argument(
        "--answer-mode",
        default="default",
        choices=["default", "brief", "detailed", "sources_only", "steps", "employee_instruction"],
        help="Стиль ответа, как в web/API",
    )
    return parser


def main(argv: Optional[Iterable[str]] = None) -> None:
    """Главная функция"""
    args = build_parser().parse_args(list(argv) if argv is not None else None)

    logger.info("=" * 60)
    logger.info("Вопрос-ответная система на базе знаний")
    logger.info("=" * 60)
    
    if not inference_server_reachable():
        logger.error(f"Сервер инференса недоступен: {settings.OLLAMA_URL}")
        logger.error("Проверьте INFERENCE_BACKEND (ollama | lmstudio) и запуск Ollama или LM Studio.")
        return
    logger.info(f"Сервер инференса отвечает: {settings.OLLAMA_URL}")
    
    # Подключаемся к текущему RAG, чтобы CLI совпадал с web/API retrieval.
    try:
        rag = RAGSystem(settings.CHROMA_COLLECTION_NAME)
        count = rag.collection.count()
        logger.info(f"Загружена векторная база данных: {count} документов")
    except Exception as e:
        logger.error(f"Ошибка при загрузке векторной базы данных: {e}")
        logger.error(f"Запустите сначала create_vector_db.py для создания базы")
        return
    
    # Определяем режим работы
    query = " ".join(args.query).strip()
    if query:
        single_query_mode(rag, query, args.top_k, args.min_score, args.answer_mode)
    else:
        interactive_mode(rag, args.top_k, args.min_score, args.answer_mode)


if __name__ == "__main__":
    main()
