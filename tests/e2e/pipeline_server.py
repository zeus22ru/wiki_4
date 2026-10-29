"""Isolated real application for manual browser verification of admin pipeline.

Run with --ready-file PATH. Only synthetic users and temporary storage are used;
no model, embedding provider or existing knowledge base is contacted.
"""

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
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    sandbox = Path(tempfile.mkdtemp(prefix="wiki4-pipeline-browser-"))
    for key, suffix in {
        "DATA_DIR": "data", "UPLOAD_DIR": "data/uploads", "LOG_DIR": "logs",
        "CHROMA_PERSIST_DIR": "chroma", "CACHE_DIR": "cache",
        "CHAT_ATTACHMENTS_DIR": "attachments", "KB_ASSETS_DIR": "assets",
    }.items():
        os.environ[key] = str(sandbox / suffix)
    os.environ.update(
        DATABASE_PATH=str(sandbox / "history.db"),
        SETTINGS_OVERRIDES_PATH=str(sandbox / "overrides.json"),
        API_KEY="", ADMIN_API_KEY="", FLASK_DEBUG="true",
        SECRET_KEY="isolated-pipeline-browser-test-only", LOG_LEVEL="ERROR",
        LLM_EXCHANGE_LOG_ENABLED="false", RAG_MULTI_QUERY_COUNT="3",
        RAG_MULTI_QUERY_ENABLED="false", RAG_CHITCHAT_SKIP_RETRIEVAL="true",
        ANONYMIZED_TELEMETRY="false",
    )
    import web_app
    import api.routes.admin as admin
    from core.chat_history import get_chat_history
    from werkzeug.security import generate_password_hash
    from werkzeug.serving import make_server

    web_app.initialize_database = lambda: (None, None)
    web_app.inference_server_reachable = lambda *a, **kw: False
    admin.inference_server_reachable = lambda *a, **kw: False
    admin.fetch_remote_model_ids = lambda *a, **kw: []
    admin._chroma_status = lambda: {"ok": False, "error": "Изолированная проверка интерфейса"}
    for role in ("admin", "user"):
        get_chat_history().create_user(
            username=f"pipeline-{role}", email=f"{role}@example.invalid",
            password_hash=generate_password_hash("local-browser-test-only"), role=role,
        )
    server = make_server("127.0.0.1", 0, web_app.app, threaded=True)
    Path(args.ready_file).write_text(json.dumps({
        "url": f"http://127.0.0.1:{server.server_port}", "sandbox": str(sandbox),
    }), encoding="utf-8")
    server.serve_forever()


if __name__ == "__main__":
    main()
