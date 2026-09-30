"""Импорт core.rag не создаёт каталоги логов; LLM-лог не пишет полный промпт по умолчанию."""

import os
import subprocess
import sys
from pathlib import Path


def test_fresh_import_does_not_create_log_dirs(tmp_path):
    """Чистый процесс: import core.rag не создаёт LOG_DIR/rag и LOG_DIR/llm."""
    log_dir = tmp_path / "logs"
    env = os.environ.copy()
    env.update({
        "PYTHONDONTWRITEBYTECODE": "1",
        "LOG_DIR": str(log_dir),
        "CACHE_DIR": str(tmp_path / "cache"),
        "CHROMA_PERSIST_DIR": str(tmp_path / "chroma"),
        "DATA_DIR": str(tmp_path / "data"),
        "DATABASE_PATH": str(tmp_path / "db.sqlite"),
        "UPLOAD_DIR": str(tmp_path / "up"),
        "CHAT_ATTACHMENTS_DIR": str(tmp_path / "chat_attachments"),
        "TELEGRAM_OFFSET_PATH": str(tmp_path / "tg.json"),
        "BITRIX24_EVENT_OFFSET_PATH": str(tmp_path / "bx.json"),
        "SETTINGS_OVERRIDES_PATH": str(tmp_path / "ov.json"),
    })
    code = (
        "from pathlib import Path\n"
        "import core.rag\n"
        f"log_dir = Path({str(log_dir)!r})\n"
        "assert not (log_dir / 'rag').exists(), log_dir / 'rag'\n"
        "assert not (log_dir / 'llm').exists(), log_dir / 'llm'\n"
        "assert core.rag._RAG_LOGGING_READY is False\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout


def test_setup_rag_logging_creates_dirs_once(tmp_path, monkeypatch):
    import core.rag as rag

    log_dir = tmp_path / "logs"
    monkeypatch.setattr(rag.settings, "LOG_DIR", str(log_dir))
    monkeypatch.setattr(rag, "_RAG_LOGGING_READY", False)
    rag.rag_logger.handlers.clear()
    rag.deep_retrieval_logger.handlers.clear()
    rag.llm_exchange_logger.handlers.clear()

    rag._setup_rag_logging()
    assert (log_dir / "rag").is_dir()
    assert (log_dir / "llm").is_dir()
    n_handlers = len(rag.rag_logger.handlers)
    rag._setup_rag_logging()
    assert len(rag.rag_logger.handlers) == n_handlers


def test_prompt_for_llm_log_truncated_by_default(monkeypatch):
    import core.rag as rag

    monkeypatch.setattr(rag.settings, "LLM_EXCHANGE_LOG_FULL", False, raising=False)
    long_prompt = "А" * 2000
    payload = rag._prompt_for_llm_log(long_prompt)
    assert payload["prompt_chars"] == 2000
    assert payload["prompt_preview"] == "А" * 500
    assert "prompt" not in payload

    monkeypatch.setattr(rag.settings, "LLM_EXCHANGE_LOG_FULL", True, raising=False)
    payload_full = rag._prompt_for_llm_log(long_prompt)
    assert "prompt" in payload_full
