"""The pilot feedback box: public to write, token-guarded to read."""

import pytest

from app.config import settings

MESSAGE = "The listening audio would not play on my phone."


def test_a_stranger_can_leave_feedback(client):
    resp = client.post(
        "/feedback",
        json={"email": "tester@gmail.com", "message": MESSAGE, "rating": 4, "page": "/"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["email"] == "tester@gmail.com"
    assert body["message"] == MESSAGE
    assert body["rating"] == 4
    assert body["user_id"] is None


def test_a_signed_in_sender_is_attributed_to_their_account(client, auth_headers):
    resp = client.post(
        "/feedback",
        json={"email": "typo@example.com", "message": "Speaking timer is great."},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    # The account address wins over the one in the form: that one is verified.
    assert body["email"] == "tester@example.com"
    assert body["user_id"] is not None


def test_a_stale_session_does_not_block_the_form(client):
    """An expired tab is the tester's least interesting problem, not a 401."""
    resp = client.post(
        "/feedback",
        json={"email": "expired@gmail.com", "message": MESSAGE},
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["user_id"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "not-an-email", "message": MESSAGE},
        {"email": "tester@gmail.com", "message": ""},
        {"email": "tester@gmail.com", "message": "   "},
        {"email": "tester@gmail.com", "message": MESSAGE, "rating": 9},
    ],
    ids=["bad-email", "empty", "whitespace-only", "rating-out-of-range"],
)
def test_junk_is_rejected(client, payload):
    assert client.post("/feedback", json=payload).status_code == 422


def test_listing_is_closed_when_no_admin_token_is_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "feedback_admin_token", "")
    resp = client.get("/feedback", headers={"X-Admin-Token": "anything"})
    assert resp.status_code == 403


def test_listing_rejects_a_wrong_token(client, monkeypatch):
    monkeypatch.setattr(settings, "feedback_admin_token", "the-real-token")
    assert client.get("/feedback").status_code == 403
    resp = client.get("/feedback", headers={"X-Admin-Token": "guess"})
    assert resp.status_code == 403


@pytest.mark.parametrize(
    "guess",
    ["café", "tok🔑", "ünicode-guess"],
    ids=["accented", "emoji", "umlaut"],
)
def test_a_non_ascii_guess_is_refused_not_a_crash(client, monkeypatch, guess):
    """A wrong token must look wrong, not knock the server over.

    🔬 Live 2026-09-06: `X-Admin-Token: café` answered 500 "Internal Server
    Error" from production. compare_digest on `str` raises TypeError the moment
    either side holds a non-ASCII character, and a header arrives decoded as
    latin-1, so any accented guess reached that comparison as non-ASCII.

    Sent as BYTES because that is what a client actually puts on the wire —
    httpx refuses to encode a non-ASCII `str` header at all, so passing one
    would test the test client rather than the route.
    """
    monkeypatch.setattr(settings, "feedback_admin_token", "the-real-token")
    resp = client.get("/feedback", headers={"X-Admin-Token": guess.encode("utf-8")})
    assert resp.status_code == 403, resp.text


def test_listing_returns_newest_first_with_the_token(client, monkeypatch):
    monkeypatch.setattr(settings, "feedback_admin_token", "the-real-token")
    client.post("/feedback", json={"email": "a@gmail.com", "message": "first note"})
    client.post("/feedback", json={"email": "b@gmail.com", "message": "second note"})

    resp = client.get("/feedback", headers={"X-Admin-Token": "the-real-token"})
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert rows[0]["message"] == "second note"
    assert "first note" in [r["message"] for r in rows]
