"""Sign in with Google: token verification, sign-up, linking, deletion."""

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from app import auth as auth_module
from app.config import settings

CLIENT_ID = "test-client.apps.googleusercontent.com"
_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class _FakeKeys:
    """Stands in for Google's JWKS endpoint, holding our test key."""

    def get_signing_key_from_jwt(self, token):
        return type("K", (), {"key": _KEY.public_key()})()


def _google_token(**overrides) -> str:
    claims = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": "google-sub-1",
        "email": "g.user@gmail.com",
        "email_verified": True,
        "name": "Google User",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    claims.update(overrides)
    return jwt.encode(claims, _KEY, algorithm="RS256")


@pytest.fixture(autouse=True)
def _google(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", CLIENT_ID)
    monkeypatch.setattr(auth_module, "_google_keys", _FakeKeys())


# --- verification ----------------------------------------------------------

def test_a_valid_token_yields_its_claims():
    claims = auth_module.verify_google_credential(_google_token())
    assert claims["sub"] == "google-sub-1"


@pytest.mark.parametrize(
    "overrides",
    [
        {"aud": "someone-elses-app.apps.googleusercontent.com"},
        {"iss": "https://evil.example.com"},
        {"exp": datetime.now(timezone.utc) - timedelta(minutes=5)},
    ],
)
def test_a_token_meant_for_elsewhere_is_refused(overrides):
    with pytest.raises(HTTPException) as exc:
        auth_module.verify_google_credential(_google_token(**overrides))
    assert exc.value.status_code == 401


def test_an_expired_token_says_so():
    stale = _google_token(exp=datetime.now(timezone.utc) - timedelta(minutes=5))
    with pytest.raises(HTTPException) as exc:
        auth_module.verify_google_credential(stale)
    assert exc.value.status_code == 401
    assert "expired" in exc.value.detail


def test_a_server_clock_slightly_behind_google_still_accepts():
    early = _google_token(iat=datetime.now(timezone.utc) + timedelta(seconds=30))
    assert auth_module.verify_google_credential(early)["sub"] == "google-sub-1"


def test_google_unreachable_is_a_503_not_a_bad_login(monkeypatch):
    class _Down:
        def get_signing_key_from_jwt(self, token):
            raise jwt.PyJWKClientConnectionError("network down")

    monkeypatch.setattr(auth_module, "_google_keys", _Down())
    with pytest.raises(HTTPException) as exc:
        auth_module.verify_google_credential(_google_token())
    assert exc.value.status_code == 503


def test_a_token_not_signed_by_google_is_refused():
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = jwt.encode(
        {"iss": "accounts.google.com", "aud": CLIENT_ID, "sub": "x"}, other, algorithm="RS256"
    )
    with pytest.raises(HTTPException):
        auth_module.verify_google_credential(forged)


def test_without_a_client_id_google_sign_in_is_off(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "")
    with pytest.raises(HTTPException) as exc:
        auth_module.verify_google_credential(_google_token())
    assert exc.value.status_code == 503


# --- the endpoint ----------------------------------------------------------

def _google_login(client, accept_terms=False, **claims):
    return client.post(
        "/auth/google",
        json={"credential": _google_token(**claims), "accept_terms": accept_terms},
    )


def test_first_sign_in_from_the_login_page_is_sent_to_sign_up(client):
    resp = _google_login(client, sub="new-1", email="new1@gmail.com")
    assert resp.status_code == 403


def test_sign_up_creates_a_passwordless_account(client):
    resp = _google_login(client, accept_terms=True, sub="new-2", email="new2@gmail.com")
    assert resp.status_code == 200
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {resp.json()['access_token']}"})
    body = me.json()
    assert body["email"] == "new2@gmail.com"
    assert body["full_name"] == "Google User"
    assert body["has_password"] is False

    # Signing in again finds the same account, consent or not.
    again = _google_login(client, sub="new-2", email="new2@gmail.com")
    assert again.status_code == 200


def test_an_unverified_email_never_opens_an_account(client):
    resp = _google_login(
        client, accept_terms=True, sub="new-3", email="new3@gmail.com", email_verified=False
    )
    assert resp.status_code == 401


def test_a_verified_email_links_to_the_existing_password_account(client):
    client.post(
        "/auth/register",
        json={"email": "Linked@gmail.com", "password": "password123", "accept_terms": True},
    )
    resp = _google_login(client, sub="link-1", email="linked@gmail.com")
    assert resp.status_code == 200
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {resp.json()['access_token']}"})
    assert me.json()["email"] == "Linked@gmail.com"
    assert me.json()["has_password"] is True
    # The password still works too.
    login = client.post("/auth/login", data={"username": "Linked@gmail.com", "password": "password123"})
    assert login.status_code == 200


def test_a_google_account_cannot_log_in_with_an_empty_password(client):
    _google_login(client, accept_terms=True, sub="nopw-1", email="nopw1@gmail.com")
    resp = client.post("/auth/login", data={"username": "nopw1@gmail.com", "password": "x"})
    assert resp.status_code == 401
    # ...and is told to use Google rather than that the password is wrong.
    assert "Google" in resp.json()["detail"]


def test_a_google_account_deletes_itself_by_typing_its_email(client):
    tokens = _google_login(client, accept_terms=True, sub="del-1", email="del1@gmail.com").json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    wrong = client.request("DELETE", "/auth/me", json={"email": "other@gmail.com"}, headers=headers)
    assert wrong.status_code == 403
    ok = client.request("DELETE", "/auth/me", json={"email": "DEL1@gmail.com"}, headers=headers)
    assert ok.status_code == 204
    assert client.get("/auth/me", headers=headers).status_code == 401
