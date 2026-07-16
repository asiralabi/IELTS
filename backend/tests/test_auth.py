"""Auth flow: register, duplicate, login, /auth/me, refresh."""

EMAIL = "auth-flow@example.com"
PASSWORD = "supersecret1"


def test_health_is_public(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_register_returns_user(client):
    resp = client.post(
        "/auth/register",
        json={"email": EMAIL, "password": PASSWORD, "full_name": "Auth Tester", "target_band": 7.5},
    )
    assert resp.status_code in (200, 201)
    body = resp.json()
    assert body["email"] == EMAIL
    assert body["full_name"] == "Auth Tester"
    assert body["is_active"] is True
    assert "hashed_password" not in body


def test_register_duplicate_email_409(client):
    resp = client.post(
        "/auth/register", json={"email": EMAIL, "password": PASSWORD}
    )
    assert resp.status_code == 409


def test_login_wrong_password_401(client):
    resp = client.post(
        "/auth/login", data={"username": EMAIL, "password": "wrong-password"}
    )
    assert resp.status_code == 401


def test_me_with_token(client):
    resp = client.post("/auth/login", data={"username": EMAIL, "password": PASSWORD})
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["email"] == EMAIL


def test_me_without_token_401(client):
    resp = client.get("/auth/me")
    assert resp.status_code == 401


def test_refresh_returns_new_token_pair(client):
    resp = client.post("/auth/login", data={"username": EMAIL, "password": PASSWORD})
    tokens = resp.json()
    resp = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert resp.status_code == 200
    new = resp.json()
    assert new["access_token"]
    assert new["refresh_token"]
    assert new["token_type"] == "bearer"
    # new access token must be usable
    resp = client.get(
        "/auth/me", headers={"Authorization": f"Bearer {new['access_token']}"}
    )
    assert resp.status_code == 200


def test_refresh_rejects_access_token(client):
    resp = client.post("/auth/login", data={"username": EMAIL, "password": PASSWORD})
    access = resp.json()["access_token"]
    resp = client.post("/auth/refresh", json={"refresh_token": access})
    assert resp.status_code == 401
