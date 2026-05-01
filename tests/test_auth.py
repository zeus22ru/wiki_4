"""Тесты регистрации, входа и ролевого доступа."""

from werkzeug.security import generate_password_hash


def create_admin():
    from core.chat_history import get_chat_history

    return get_chat_history().create_user(
        username="admin",
        email="admin@example.com",
        password_hash=generate_password_hash("password123"),
        role="admin",
    )


def test_register_login_me_logout(client):
    rv = client.get("/api/auth/me")
    assert rv.status_code == 200
    assert rv.get_json()["role"] == "guest"

    rv = client.post(
        "/api/auth/register",
        json={"username": "alice", "email": "alice@example.com", "password": "password123"},
    )
    assert rv.status_code == 201
    data = rv.get_json()
    assert data["authenticated"] is True
    assert data["role"] == "user"
    assert "password_hash" not in data["user"]

    rv = client.post("/api/auth/logout")
    assert rv.status_code == 200
    assert rv.get_json()["role"] == "guest"

    rv = client.post("/api/auth/login", json={"identifier": "alice", "password": "password123"})
    assert rv.status_code == 200
    assert rv.get_json()["user"]["email"] == "alice@example.com"


def test_register_rejects_duplicate_user(client):
    payload = {"username": "bob", "email": "bob@example.com", "password": "password123"}
    assert client.post("/api/auth/register", json=payload).status_code == 201
    rv = client.post("/api/auth/register", json=payload)
    assert rv.status_code == 409


def test_register_accepts_short_non_empty_password(client):
    rv = client.post(
        "/api/auth/register",
        json={"username": "shortpass", "email": "short@example.com", "password": "1"},
    )
    assert rv.status_code == 201


def test_login_rejects_bad_password(client):
    client.post(
        "/api/auth/register",
        json={"username": "carol", "email": "carol@example.com", "password": "password123"},
    )
    rv = client.post("/api/auth/login", json={"identifier": "carol", "password": "wrong-password"})
    assert rv.status_code == 401


def test_guest_cannot_access_documents_or_admin(client):
    assert client.get("/api/auth/me").get_json()["role"] == "guest"
    assert client.get("/api/documents").status_code == 401
    assert client.get("/api/admin/overview").status_code == 401


def test_admin_can_access_documents_and_admin(client):
    create_admin()
    rv = client.post("/api/auth/login", json={"identifier": "admin", "password": "password123"})
    assert rv.status_code == 200
    assert client.get("/api/documents").status_code == 200


def test_user_sees_only_own_chats(client):
    rv = client.post(
        "/api/auth/register",
        json={"username": "alice", "email": "alice@example.com", "password": "password123"},
    )
    assert rv.status_code == 201
    alice_chat = client.post("/api/chats", json={"title": "Alice chat"}).get_json()

    client.post("/api/auth/logout")
    rv = client.post(
        "/api/auth/register",
        json={"username": "bob", "email": "bob@example.com", "password": "password123"},
    )
    assert rv.status_code == 201

    rv = client.get(f"/api/chats/{alice_chat['id']}")
    assert rv.status_code == 403

    rv = client.get("/api/chats")
    assert rv.status_code == 200
    assert rv.get_json()["chats"] == []


def test_guest_chat_is_bound_to_current_cookie_session(client):
    rv = client.post("/api/chats", json={"title": "Guest chat"})
    assert rv.status_code == 201
    guest_chat = rv.get_json()

    assert client.get(f"/api/chats/{guest_chat['id']}").status_code == 200

    with client.session_transaction() as flask_session:
        flask_session["guest_chat_ids"] = []

    assert client.get(f"/api/chats/{guest_chat['id']}").status_code == 403

