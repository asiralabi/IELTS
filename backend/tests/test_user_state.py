"""Browser-side progress is mirrored per account and survives a sign-out."""


def _sign_in(client, email):
    client.post(
        "/auth/register",
        json={"email": email, "password": "correct-horse-1", "accept_terms": True},
    )
    tok = client.post(
        "/auth/login", data={"username": email, "password": "correct-horse-1"}
    ).json()
    return tok, {"Authorization": f"Bearer {tok['access_token']}"}


def test_sign_in_returns_the_user(client):
    tok, _ = _sign_in(client, "state-user@example.com")
    assert tok["user"]["email"] == "state-user@example.com"
    assert tok["user"]["has_password"] is True


def test_progress_survives_signing_out_and_back_in(client):
    _, headers = _sign_in(client, "state-keep@example.com")
    vocab = {"mitigate": "known", "paradigm": "learning"}
    assert client.put("/progress/state/vocab", json=vocab, headers=headers).status_code == 200
    cam = {"cambridge-19": {"1": {"reading": {"done": True, "timestamp": 1}}}}
    client.put("/progress/state/cambridge", json=cam, headers=headers)
    client.put("/progress/state/vocab", json={**vocab, "feasible": "known"}, headers=headers)

    # A fresh login is a fresh token: nothing carried over in the browser.
    _, again = _sign_in(client, "state-keep@example.com")
    state = client.get("/progress/state", headers=again).json()
    assert state["vocab"] == {**vocab, "feasible": "known"}
    assert state["cambridge"] == cam


def test_each_account_sees_only_its_own_progress(client):
    _, a = _sign_in(client, "state-a@example.com")
    _, b = _sign_in(client, "state-b@example.com")
    client.put("/progress/state/vocab", json={"mitigate": "known"}, headers=a)
    assert client.get("/progress/state", headers=b).json() == {}


def test_unknown_keys_and_anonymous_writes_are_refused(client):
    _, headers = _sign_in(client, "state-guard@example.com")
    assert client.put("/progress/state/other", json={}, headers=headers).status_code == 404
    assert client.put("/progress/state/vocab", json={}).status_code == 401


def test_saved_progress_is_exported_and_deleted_with_the_account(client):
    _, headers = _sign_in(client, "state-gone@example.com")
    client.put("/progress/state/vocab", json={"mitigate": "known"}, headers=headers)
    data = client.get("/auth/me/export", headers=headers).json()
    assert data["saved_progress"][0]["value"] == {"mitigate": "known"}
    resp = client.request(
        "DELETE", "/auth/me", json={"password": "correct-horse-1"}, headers=headers
    )
    assert resp.status_code == 204
