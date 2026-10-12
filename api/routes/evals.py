#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Админские прогоны проверки ответов."""

from flask import Blueprint, jsonify, request

from api.middleware.auth import current_user_id, require_admin_access
from core import answer_benchmark as bench

evals_bp = Blueprint("evals", __name__, url_prefix="/api/admin/evals")


@evals_bp.before_request
def require_admin_role():
    return require_admin_access()


@evals_bp.route("/cases", methods=["GET"])
def list_cases():
    return jsonify({"cases": bench.list_cases()})


@evals_bp.route("/cases", methods=["POST"])
def create_case():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Нужен JSON-объект"}), 400
    try:
        case = bench.create_case(data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"case": case}), 201


@evals_bp.route("/cases/<int:case_id>", methods=["PATCH"])
def update_case(case_id: int):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Нужен JSON-объект"}), 400
    try:
        case = bench.update_case(case_id, data)
    except LookupError:
        return jsonify({"error": "Вопрос не найден"}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"case": case})


@evals_bp.route("/cases/import", methods=["POST"])
def import_cases():
    text = ""
    if request.files.get("file"):
        raw = request.files["file"].read()
        text = raw.decode("utf-8", errors="replace")
    else:
        data = request.get_json(silent=True)
        if isinstance(data, dict):
            text = str(data.get("jsonl") or "")
        elif request.data:
            text = request.get_data(as_text=True)
    try:
        result = bench.import_jsonl(text)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(result)


@evals_bp.route("/runs", methods=["GET"])
def list_runs():
    return jsonify({"runs": bench.list_runs()})


@evals_bp.route("/runs", methods=["POST"])
def start_run():
    try:
        run, busy = bench.start_run(current_user_id())
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if busy:
        return jsonify({
            "error": "eval_already_running",
            "message": "Проверка уже выполняется",
            "run": run,
        }), 409
    return jsonify({"run": run}), 202


@evals_bp.route("/runs/<int:run_id>", methods=["GET"])
def get_run(run_id: int):
    run = bench.get_run(run_id)
    if not run:
        return jsonify({"error": "Прогон не найден"}), 404
    return jsonify({"run": run})


@evals_bp.route("/compare", methods=["GET"])
def compare_runs():
    try:
        before_id = int(request.args["before"])
        after_id = int(request.args["after"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "Нужны before и after"}), 400
    if before_id == after_id:
        return jsonify({"error": "Нужны два разных прогона"}), 400
    try:
        report = bench.compare_runs(before_id, after_id)
    except LookupError:
        return jsonify({"error": "Прогон не найден"}), 404
    return jsonify(report)
