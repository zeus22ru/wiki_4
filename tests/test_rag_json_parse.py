"""Парсинг JSON-массивов запросов и сохранение массива в strip_model_reasoning."""

from core.rag import _parse_json_array_of_strings
from utils.embeddings import strip_model_reasoning


def test_parse_full_json_array():
    raw = '["Добавить пользователя", "Регистрация сотрудника"]'
    assert _parse_json_array_of_strings(raw) == [
        "Добавить пользователя",
        "Регистрация сотрудника",
    ]


def test_parse_truncated_array_missing_bracket_prefix():
    raw = (
        'Добавить нового пользователя в базу",\n'
        '  "Регистрация нового сотрудника в системе",\n'
        '  "Создать учетную запись для нового пользователя"\n]'
    )
    out = _parse_json_array_of_strings(raw)
    assert len(out) == 3
    assert "Добавить нового пользователя в базу" in out[0]


def test_strip_preserves_json_array():
    raw = '["Добавить пользователя", "Регистрация"]'
    assert strip_model_reasoning(raw) == raw
