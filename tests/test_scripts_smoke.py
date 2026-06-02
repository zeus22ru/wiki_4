# -*- coding: utf-8 -*-
"""Smoke-тесты вспомогательных CLI без обращения к LLM/Chroma."""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _run_help(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=PROJECT_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
        check=False,
    )


def test_script_modules_import_without_side_effects():
    for module_name in [
        "qa_system",
        "scripts.eval_coverage_basket",
        "scripts.extract_long_paths",
        "scripts.test_ollama_api",
        "scripts.test_available_models",
    ]:
        importlib.import_module(module_name)


def test_cli_help_smoke():
    commands = [
        ("qa_system.py", "--help"),
        ("scripts/eval_coverage_basket.py", "--help"),
        ("scripts/eval_coverage_basket.py", "export", "--help"),
        ("scripts/eval_coverage_basket.py", "run", "--help"),
        ("scripts/extract_long_paths.py", "--help"),
    ]
    for command in commands:
        result = _run_help(*command)
        assert result.returncode == 0, result.stderr
        assert "usage:" in result.stdout.lower()


def test_extract_long_paths_default_input_uses_project_data():
    module = importlib.import_module("scripts.extract_long_paths")
    args = module.build_parser().parse_args([])
    input_path = Path(args.input).resolve()

    assert input_path.name == "data"
    assert input_path.parent == PROJECT_ROOT
    assert input_path != (PROJECT_ROOT / "scripts" / "data").resolve()


def test_eval_coverage_export_and_run_dispatch(monkeypatch, tmp_path):
    module = importlib.import_module("scripts.eval_coverage_basket")
    export_mock = Mock()
    run_mock = Mock()
    monkeypatch.setattr(module, "export_basket", export_mock)
    monkeypatch.setattr(module, "run_basket", run_mock)

    export_path = tmp_path / "basket.jsonl"
    monkeypatch.setattr(
        sys,
        "argv",
        ["eval_coverage_basket.py", "export", "--out", str(export_path), "--limit", "7"],
    )
    module.main()
    export_mock.assert_called_once_with(export_path, limit=7)

    input_path = tmp_path / "input.jsonl"
    report_path = tmp_path / "report.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "eval_coverage_basket.py",
            "run",
            "--in",
            str(input_path),
            "--out",
            str(report_path),
            "--deep",
            "true",
            "--top-k",
            "3",
            "--min-score",
            "0.25",
        ],
    )
    module.main()
    run_mock.assert_called_once_with(
        input_path,
        report_path,
        deep=True,
        top_k=3,
        min_score=0.25,
    )
