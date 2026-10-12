"""HTTP API for employee-confirmed, admin-reviewed solutions."""
from flask import Blueprint, jsonify, request

from api.middleware.auth import can_access_chat, current_user_id, ensure_guest_id, is_admin
from core.chat_history import get_chat_history
from core.solutions import SolutionError, SolutionService

solutions_bp = Blueprint("solutions", __name__, url_prefix="/api/solutions")


def _payload() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise SolutionError("Ожидается JSON-объект")
    return data


def _positive(data: dict, key: str) -> int:
    value = data.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise SolutionError(f"{key} должен быть положительным числом")
    return value


def _actor():
    user_id = current_user_id()
    return user_id, None if user_id is not None else ensure_guest_id()


def _service() -> SolutionService:
    return SolutionService(get_chat_history())


def _owned_chat(session_id: int):
    chat = get_chat_history().get_session(session_id)
    if not chat or not can_access_chat(chat):
        raise SolutionError("Чат не найден или недоступен", 404)
    return chat


def _owned_solution(resolution_id: int):
    """A deleted chat keeps its snapshot for reviewers, never for its former owner."""
    user_id, guest_id = _actor()
    item = _service().get(resolution_id, user_id, guest_id)
    _owned_chat(item["session_id"])
    return user_id, guest_id


@solutions_bp.errorhandler(SolutionError)
def _solution_error(error):
    return jsonify({"error": str(error)}), error.status


@solutions_bp.route("", methods=["GET"])
def list_solutions():
    raw = request.args.get("session_id")
    try:
        session_id = int(raw or "")
    except ValueError:
        raise SolutionError("session_id должен быть положительным числом")
    if session_id <= 0:
        raise SolutionError("session_id должен быть положительным числом")
    _owned_chat(session_id)
    user_id, guest_id = _actor()
    return jsonify({"solutions": _service().list_for_session(session_id, user_id, guest_id)})


@solutions_bp.route("", methods=["POST"])
def create_solution():
    data = _payload()
    session_id, message_id = _positive(data, "session_id"), _positive(data, "message_id")
    _owned_chat(session_id)
    user_id, guest_id = _actor()
    solution, created = _service().confirm(session_id, message_id, user_id, guest_id)
    return jsonify({"solution": solution, "created": created}), 201 if created else 200


@solutions_bp.route("/<int:resolution_id>", methods=["GET"])
def get_solution(resolution_id: int):
    user_id, guest_id = _actor()
    if is_admin():
        return jsonify({"solution": _service().get(resolution_id, user_id, guest_id, True)})
    user_id, guest_id = _owned_solution(resolution_id)
    return jsonify({"solution": _service().get(resolution_id, user_id, guest_id)})


@solutions_bp.route("/<int:resolution_id>/draft", methods=["POST"])
def prepare_draft(resolution_id: int):
    data = _payload()
    kind = data.get("kind")
    clarification = data.get("clarification", "")
    if not isinstance(kind, str) or not isinstance(clarification, str):
        raise SolutionError("kind и clarification должны быть строками")
    user_id, guest_id = _owned_solution(resolution_id)
    solution, notice = _service().prepare_draft(resolution_id, kind, clarification, user_id, guest_id)
    return jsonify({"solution": solution, "notice": notice})


@solutions_bp.route("/<int:resolution_id>", methods=["PATCH"])
def update_solution(resolution_id: int):
    data = _payload()
    version = _positive(data, "version")
    fields = data.get("fields")
    if not isinstance(fields, dict):
        raise SolutionError("fields должен быть объектом")
    user_id, guest_id = _owned_solution(resolution_id)
    return jsonify({"solution": _service().update_draft(resolution_id, fields, version, user_id, guest_id)})


@solutions_bp.route("/<int:resolution_id>/submit", methods=["POST"])
def submit_solution(resolution_id: int):
    data = _payload()
    user_id, guest_id = _owned_solution(resolution_id)
    return jsonify({"solution": _service().submit(resolution_id, _positive(data, "version"), user_id, guest_id)})


@solutions_bp.route("/review", methods=["GET"])
def review_list():
    if not is_admin():
        raise SolutionError("Требуется роль admin", 403)
    status = request.args.get("status", "pending")
    return jsonify({"solutions": _service().review_list(status)})


@solutions_bp.route("/<int:resolution_id>/review", methods=["POST"])
def review_solution(resolution_id: int):
    if not is_admin():
        raise SolutionError("Требуется роль admin", 403)
    data = _payload()
    fields = data.get("fields", {})
    if not isinstance(fields, dict):
        raise SolutionError("fields должен быть объектом")
    action = data.get("action")
    note, document_path = data.get("review_note", ""), data.get("document_path", "")
    if not isinstance(action, str) or not isinstance(note, str) or not isinstance(document_path, str):
        raise SolutionError("Некорректные данные проверки")
    result = _service().review(resolution_id, _positive(data, "version"), action, fields, current_user_id(), note, document_path)
    return jsonify({"solution": result})
