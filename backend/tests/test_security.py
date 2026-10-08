"""The protections in app.security: who may change the shared knowledge base,
how fast a caller may hit the expensive routes, and what every response says
about itself."""

import pytest

from app.config import settings
from app.security import limiter


@pytest.fixture
def limits_on(monkeypatch):
    limiter.reset()
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    yield
    limiter.reset()


# ── the knowledge base is the team's, not every user's ──


def test_ordinary_user_cannot_wipe_the_knowledge_base(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "feedback_admin_token", "real-token")
    resp = client.post("/knowledge/reindex", headers=auth_headers)
    assert resp.status_code == 403


def test_ordinary_user_cannot_inject_into_the_knowledge_base(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "feedback_admin_token", "real-token")
    resp = client.post(
        "/knowledge/ingest",
        files={"file": ("x.pdf", b"%PDF-1.4 hello", "application/pdf")},
        headers={**auth_headers, "X-Admin-Token": "guess"},
    )
    assert resp.status_code == 403


def test_unset_admin_token_closes_the_route(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "feedback_admin_token", "")
    assert client.post("/knowledge/reindex", headers=auth_headers).status_code == 403


def test_a_file_named_pdf_that_is_not_one_is_refused(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "feedback_admin_token", "t")
    resp = client.post(
        "/knowledge/ingest",
        files={"file": ("evil.pdf", b"<script>alert(1)</script>", "application/pdf")},
        headers={**auth_headers, "X-Admin-Token": "t"},
    )
    assert resp.status_code == 400


# ── rate limits ──


def test_password_guessing_is_slowed(client, limits_on):
    codes = [
        client.post("/auth/login", data={"username": "nobody@example.com", "password": "wrong-pass"}).status_code
        for _ in range(12)
    ]
    assert codes[:10] == [401] * 10
    assert codes[10] == 429


def test_a_random_bearer_header_does_not_reset_the_login_budget(client, limits_on):
    for i in range(10):
        client.post(
            "/auth/login",
            data={"username": "nobody@example.com", "password": "wrong-pass"},
            headers={"Authorization": f"Bearer fake-token-number-{i:04d}-padding"},
        )
    resp = client.post("/auth/login", data={"username": "nobody@example.com", "password": "wrong-pass"})
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers


def test_a_rate_limited_reply_still_carries_cors_headers(client, limits_on):
    for _ in range(11):
        resp = client.post(
            "/auth/login",
            data={"username": "a@example.com", "password": "wrong-pass"},
            headers={"Origin": "https://oratio-ielts.vercel.app"},
        )
    assert resp.status_code == 429
    assert "access-control-allow-origin" in {k.lower() for k in resp.headers}


# ── sizes and shapes ──


def test_oversized_json_is_refused_before_it_is_read(client, auth_headers):
    resp = client.post(
        "/chat",
        content=b"{" + b" " * (2 * 1024 * 1024) + b"}",
        headers={**auth_headers, "Content-Type": "application/json"},
    )
    assert resp.status_code == 413


def test_chat_message_has_a_ceiling(client, auth_headers):
    resp = client.post("/chat", json={"message": "x" * 5000}, headers=auth_headers)
    assert resp.status_code == 422


def test_overlong_password_is_a_validation_error_not_a_crash(client):
    resp = client.post(
        "/auth/register",
        json={"email": "long@example.com", "password": "p" * 200},
    )
    assert resp.status_code == 422


def test_token_with_garbage_subject_is_401_not_500(client):
    import jwt

    token = jwt.encode({"sub": "not-a-number", "type": "access", "exp": 9999999999}, settings.jwt_secret, algorithm="HS256")
    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


# ── response headers ──


def test_responses_carry_security_headers(client):
    resp = client.get("/health")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert "max-age" in resp.headers["Strict-Transport-Security"]


def test_auth_responses_are_never_cached(client):
    resp = client.post("/auth/login", data={"username": "x@example.com", "password": "wrong-pass"})
    assert resp.headers["Cache-Control"] == "no-store"


def test_cors_does_not_offer_credentials(client):
    resp = client.options(
        "/auth/me",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert resp.headers.get("access-control-allow-credentials") != "true"


# ── a student's own data ──


def _new_user(client, email):
    client.post("/auth/register", json={"email": email, "password": "correct-horse-1", "accept_terms": True})
    tok = client.post("/auth/login", data={"username": email, "password": "correct-horse-1"}).json()
    return {"Authorization": f"Bearer {tok['access_token']}"}


def test_student_can_export_their_data_without_the_password_hash(client):
    headers = _new_user(client, "export@example.com")
    data = client.get("/auth/me/export", headers=headers).json()
    assert data["account"]["email"] == "export@example.com"
    assert "hashed_password" not in data["account"]
    for key in ("writing_submissions", "speaking_submissions", "chat_messages", "mock_exams"):
        assert key in data


def test_deleting_needs_the_password(client):
    headers = _new_user(client, "keep@example.com")
    resp = client.request("DELETE", "/auth/me", json={"password": "wrong-one"}, headers=headers)
    assert resp.status_code == 403
    assert client.get("/auth/me", headers=headers).status_code == 200


def test_deleted_account_is_gone_and_cannot_sign_in(client):
    headers = _new_user(client, "gone@example.com")
    resp = client.request("DELETE", "/auth/me", json={"password": "correct-horse-1"}, headers=headers)
    assert resp.status_code == 204
    assert client.get("/auth/me", headers=headers).status_code == 401
    login = client.post("/auth/login", data={"username": "gone@example.com", "password": "correct-horse-1"})
    assert login.status_code == 401


def test_registration_needs_explicit_consent(client):
    resp = client.post("/auth/register", json={"email": "noconsent@example.com", "password": "correct-horse-1"})
    assert resp.status_code == 422


def test_consent_is_recorded_with_the_policy_version(client):
    headers = _new_user(client, "consent@example.com")
    data = client.get("/auth/me/export", headers=headers).json()
    assert len(data["consents"]) == 1
    assert data["consents"][0]["policy_version"] == settings.legal_policy_version
