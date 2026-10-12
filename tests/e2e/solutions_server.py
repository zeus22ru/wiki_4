"""Isolated real Flask backend for solutions_flow.cjs; never uses the live corpus.

Run with --ready-file PATH. The ready file contains the ephemeral localhost URL
and the temporary data directory. All accounts and articles are synthetic.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ready-file", required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo))
    sandbox = Path(tempfile.mkdtemp(prefix="wiki4-solutions-browser-"))
    for setting, suffix in {
        "DATA_DIR": "data", "UPLOAD_DIR": "data/uploads", "LOG_DIR": "logs",
        "CHROMA_PERSIST_DIR": "chroma", "CACHE_DIR": "cache",
        "CHAT_ATTACHMENTS_DIR": "attachments",
    }.items():
        os.environ[setting] = str(sandbox / suffix)
    os.environ.update(
        DATABASE_PATH=str(sandbox / "history.db"), API_KEY="", ADMIN_API_KEY="",
        SECRET_KEY="isolated-solutions-browser-test-only", FLASK_DEBUG="true",
        LLM_EXCHANGE_LOG_ENABLED="false", LOG_LEVEL="ERROR",
    )

    from utils import embeddings

    def unavailable_model(*_args, **_kwargs):
        raise RuntimeError("Synthetic model outage: browser test exercises fallback")

    embeddings.chat_completion = unavailable_model

    from web_app import app
    from core.chat_history import get_chat_history
    from werkzeug.security import generate_password_hash
    from werkzeug.serving import make_server

    get_chat_history().create_user(
        username="review-admin", email="review@example.invalid",
        password_hash=generate_password_hash("local-browser-test-only"), role="admin",
    )
    source = sandbox / "data" / "uploads" / "printer-guide.txt"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("Тестовая инструкция: проверить очередь печати и выполнить пробную печать.", encoding="utf-8")
    server = make_server("127.0.0.1", 0, app, threaded=True)
    Path(args.ready_file).write_text(json.dumps({
        "url": f"http://127.0.0.1:{server.server_port}",
        "sandbox": str(sandbox),
    }), encoding="utf-8")
    server.serve_forever()


if __name__ == "__main__":
    main()
