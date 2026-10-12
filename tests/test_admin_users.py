"""Тесты управления пользователями из админки и смены своего пароля."""

from werkzeug.security import generate_password_hash

import pytest


def create_admin(username: str = "admin", email: str = "admin@example.com"):
    from core.chat_history import get_chat_history

    return get_chat_history().create_user(
        username=username,
        email=email,
        password_hash=generate_password_hash("password123"),
        role="admin",
    )


def _login(client, identifier: str, password: str = "password123"):
    return client.post("/api/auth/login", json={"identifier": identifier, "password": password})


def _second_client():
    from web_app import app

    app.config["TESTING"] = True
    return app.test_client()


def _create_user(client, username: str, role: str = "user", email: str | None = None):
    rv = client.post(
        "/api/admin/users",
        json={
            "username": username,
            "email": email or f"{username}@example.com",
            "password": "password123",
            "role": role,
        },
    )
    assert rv.status_code == 201, rv.get_json()
    return rv.get_json()["user"]


# ---------- Доступ ----------

def test_guest_cannot_manage_users(client):
    assert client.get("/api/admin/users").status_code == 401
    assert client.post("/api/admin/users", json={}).status_code == 401


def test_non_admin_cannot_manage_users(client):
    client.post(
        "/api/auth/register",
        json={"username": "plain", "email": "plain@example.com", "password": "password123"},
    )
    assert client.get("/api/admin/users").status_code == 403
    assert client.post("/api/admin/users", json={"username": "x"}).status_code == 403


# ---------- Список и фильтры ----------

def test_admin_lists_and_filters_users(client):
    create_admin()
    _login(client, "admin")
    _create_user(client, "userone")
    _create_user(client, "usertwo", role="admin")

    data = client.get("/api/admin/users").get_json()
    assert data["total"] >= 3
    assert data["users"][0]["stats"]["chats"] == 0
    assert "password_hash" not in data["users"][0]

    admins = client.get("/api/admin/users?role=admin").get_json()
    assert admins["users"]
    assert all(u["role"] == "admin" for u in admins["users"])

    found = client.get("/api/admin/users?query=userone").get_json()
    assert any(u["username"] == "userone" for u in found["users"])

    active = client.get("/api/admin/users?status=active").get_json()
    assert all(u["is_active"] for u in active["users"])

    page = client.get("/api/admin/users?page=1&per_page=2").get_json()
    assert len(page["users"]) <= 2


def test_list_rejects_unknown_role(client):
    create_admin()
    _login(client, "admin")
    assert client.get("/api/admin/users?role=superuser").status_code == 400


# ---------- Создание ----------

def test_admin_creates_user_and_user_can_login(client):
    create_admin()
    _login(client, "admin")
    created = _create_user(client, "newbie")
    assert created["role"] == "user"
    assert created["is_active"] is True

    other = _second_client()
    assert _login(other, "newbie").status_code == 200


def test_create_rejects_duplicate(client):
    create_admin()
    _login(client, "admin")
    _create_user(client, "dup")
    rv = client.post(
        "/api/admin/users",
        json={"username": "dup", "email": "dup@example.com", "password": "password123"},
    )
    assert rv.status_code == 409


def test_create_rejects_bad_input(client):
    create_admin()
    _login(client, "admin")
    base = {"username": "okname", "email": "ok@example.com", "password": "password123"}

    assert client.post("/api/admin/users", json={**base, "role": "superuser"}).status_code == 400
    assert client.post("/api/admin/users", json={**base, "password": "1"}).status_code == 400
    assert client.post("/api/admin/users", json={**base, "email": "not-an-email"}).status_code == 400


def test_created_inactive_user_cannot_login(client):
    create_admin()
    _login(client, "admin")
    rv = client.post(
        "/api/admin/users",
        json={
            "username": "frozen",
            "email": "frozen@example.com",
            "password": "password123",
            "is_active": False,
        },
    )
    assert rv.status_code == 201
    assert rv.get_json()["user"]["is_active"] is False

    other = _second_client()
    assert _login(other, "frozen").status_code == 401


# ---------- Обновление ----------

def test_admin_updates_profile(client):
    create_admin()
    _login(client, "admin")
    user = _create_user(client, "target")

    rv = client.patch(
        f"/api/admin/users/{user['id']}",
        json={"email": "target2@example.com", "role": "admin"},
    )
    assert rv.status_code == 200
    updated = rv.get_json()["user"]
    assert updated["email"] == "target2@example.com"
    assert updated["role"] == "admin"


def test_update_rejects_duplicate_email(client):
    create_admin()
    _login(client, "admin")
    _create_user(client, "first", email="first@example.com")
    second = _create_user(client, "second", email="second@example.com")

    rv = client.patch(f"/api/admin/users/{second['id']}", json={"email": "first@example.com"})
    assert rv.status_code == 409


def test_update_missing_user_returns_404(client):
    create_admin()
    _login(client, "admin")
    assert client.patch("/api/admin/users/9999", json={"role": "user"}).status_code == 404


# ---------- Защита от блокировки ----------

def test_admin_cannot_block_or_demote_self(client):
    admin = create_admin()
    _login(client, "admin")

    assert client.patch(f"/api/admin/users/{admin.id}", json={"is_active": False}).status_code == 400
    assert client.patch(f"/api/admin/users/{admin.id}", json={"role": "user"}).status_code == 400
    assert client.get("/api/auth/me").get_json()["role"] == "admin"


def test_cannot_lock_out_last_admin(client):
    admin = create_admin()
    _login(client, "admin")
    other = _create_user(client, "admin2", role="admin")

    # Двух админов можно разжаловать одного.
    assert client.patch(f"/api/admin/users/{other['id']}", json={"role": "user"}).status_code == 200
    # Теперь admin — последний: себя разжаловать/заблокировать нельзя.
    assert client.patch(f"/api/admin/users/{admin.id}", json={"role": "user"}).status_code == 400
    assert client.patch(f"/api/admin/users/{admin.id}", json={"is_active": False}).status_code == 400
    assert client.get("/api/auth/me").get_json()["role"] == "admin"


def test_admin_blocks_other_admin(client):
    create_admin()
    _login(client, "admin")
    other = _create_user(client, "admin2", role="admin")

    rv = client.patch(f"/api/admin/users/{other['id']}", json={"is_active": False})
    assert rv.status_code == 200
    assert rv.get_json()["user"]["is_active"] is False


# ---------- Блокировка завершает сессию ----------

def test_blocked_user_session_is_invalidated(client):
    create_admin()
    _login(client, "admin")
    victim = _create_user(client, "blockme")

    victim_client = _second_client()
    assert _login(victim_client, "blockme").status_code == 200
    assert victim_client.get("/api/auth/me").get_json()["authenticated"] is True

    rv = client.patch(f"/api/admin/users/{victim['id']}", json={"is_active": False})
    assert rv.status_code == 200

    assert victim_client.get("/api/auth/me").get_json()["authenticated"] is False
    assert _login(victim_client, "blockme").status_code == 401


# ---------- Сброс пароля админом ----------

def test_admin_resets_password(client):
    create_admin()
    _login(client, "admin")
    user = _create_user(client, "resetme")

    rv = client.post(f"/api/admin/users/{user['id']}/password", json={"new_password": "brandnew123"})
    assert rv.status_code == 200

    other = _second_client()
    assert _login(other, "resetme", "brandnew123").status_code == 200
    assert _login(other, "resetme", "password123").status_code == 401


def test_reset_password_validates_length(client):
    create_admin()
    _login(client, "admin")
    user = _create_user(client, "shortpw")
    rv = client.post(f"/api/admin/users/{user['id']}/password", json={"new_password": "1"})
    assert rv.status_code == 400


# ---------- Самостоятельная смена пароля ----------

def test_user_changes_own_password(client):
    client.post(
        "/api/auth/register",
        json={"username": "pwduser", "email": "pwd@example.com", "password": "password123"},
    )
    rv = client.post(
        "/api/auth/password",
        json={"current_password": "password123", "new_password": "newpassword456"},
    )
    assert rv.status_code == 200

    client.post("/api/auth/logout")
    assert _login(client, "pwduser", "password123").status_code == 401
    assert _login(client, "pwduser", "newpassword456").status_code == 200


def test_change_password_rejects_wrong_current(client):
    client.post(
        "/api/auth/register",
        json={"username": "wrongpw", "email": "wrong@example.com", "password": "password123"},
    )
    rv = client.post(
        "/api/auth/password",
        json={"current_password": "nope-nope", "new_password": "newpassword456"},
    )
    assert rv.status_code == 400


def test_change_password_requires_auth(client):
    rv = client.post(
        "/api/auth/password",
        json={"current_password": "x", "new_password": "newpassword456"},
    )
    assert rv.status_code == 401


# ---------- Тумблер регистрации ----------

def test_registration_can_be_disabled(client, monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "ENABLE_REGISTRATION", False, raising=False)
    rv = client.post(
        "/api/auth/register",
        json={"username": "latecomer", "email": "late@example.com", "password": "password123"},
    )
    assert rv.status_code == 403


@pytest.mark.parametrize("enabled", [True])
def test_registration_stays_enabled_by_default(client, enabled):
    from config import settings

    assert settings.ENABLE_REGISTRATION is enabled
    rv = client.post(
        "/api/auth/register",
        json={"username": "early", "email": "early@example.com", "password": "password123"},
    )
    assert rv.status_code == 201
