from conftest import EMAIL, PASSWORD
from sqlalchemy import create_engine, text


def test_login_sets_httponly_session_and_returns_csrf(anon):
    r = anon.post("/api/auth/login", json={"email": EMAIL.upper(), "password": PASSWORD})
    assert r.status_code == 200
    assert r.json()["user"]["email"] == EMAIL
    cookies = r.headers.get_list("set-cookie")
    session = next(c for c in cookies if c.startswith("shop_session="))
    assert "HttpOnly" in session and "Secure" in session and "SameSite=strict" in session
    csrf = next(c for c in cookies if c.startswith("shop_csrf="))
    assert "HttpOnly" not in csrf


def test_wrong_password_and_unknown_email_look_identical(anon):
    a = anon.post("/api/auth/login", json={"email": EMAIL, "password": "nope-nope-nope"})
    b = anon.post("/api/auth/login", json={"email": "nobody@example.com", "password": "x"})
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


def test_lockout_after_repeated_failures(anon):
    for _ in range(10):
        anon.post("/api/auth/login", json={"email": EMAIL, "password": "wrong-password"})
    r = anon.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert r.status_code == 429


def test_session_token_is_not_stored_in_plaintext(client):
    token = client.cookies.get("shop_session")
    from conftest import TEST_DB

    with create_engine(TEST_DB).connect() as conn:
        stored = conn.execute(text("SELECT token_hash FROM sessions")).scalar_one()
    assert stored != token and len(stored) == 64


def test_protected_routes_require_login(anon):
    for path in ("/api/customers", "/api/dashboard", "/api/settings", "/api/audit"):
        assert anon.get(path).status_code == 401


def test_state_changes_require_csrf_header(client):
    token = client.headers.pop("X-CSRF-Token")
    r = client.post("/api/customers", json={"first_name": "A", "phone": "555"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf"
    client.headers["X-CSRF-Token"] = "wrong"
    assert (
        client.post("/api/customers", json={"first_name": "A", "phone": "555"}).status_code == 403
    )
    client.headers["X-CSRF-Token"] = token
    assert (
        client.post("/api/customers", json={"first_name": "A", "phone": "555"}).status_code == 201
    )


def test_logout_revokes_session(client):
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_change_password(client, anon):
    r = client.post(
        "/api/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "a-brand-new-password"},
    )
    assert r.status_code == 204
    client.cookies.clear()
    assert (
        client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD}).status_code
        == 401
    )
    assert (
        client.post(
            "/api/auth/login", json={"email": EMAIL, "password": "a-brand-new-password"}
        ).status_code
        == 200
    )


def test_short_new_password_rejected(client):
    r = client.post(
        "/api/auth/change-password", json={"current_password": PASSWORD, "new_password": "short"}
    )
    assert r.status_code == 422


def test_origin_secret_blocks_direct_access(monkeypatch):
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import create_app

    monkeypatch.setenv("ORIGIN_SECRET", "cf-secret")
    get_settings.cache_clear()
    try:
        with TestClient(create_app(), base_url="https://testserver") as c:
            assert c.get("/api/health").status_code == 403
            assert c.get("/api/health", headers={"x-origin-secret": "cf-secret"}).status_code == 200
    finally:
        monkeypatch.setenv("ORIGIN_SECRET", "")
        get_settings.cache_clear()
