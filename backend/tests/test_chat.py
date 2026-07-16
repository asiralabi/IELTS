"""Chat with the instructor agent (LLM mocked)."""

import pytest

from tests.conftest import CANNED_CHAT_REPLY


@pytest.fixture(scope="module")
def chat_headers(client):
    """Dedicated user so session counts are deterministic."""
    from tests.conftest import _register_and_login

    return _register_and_login(client, "chat-user@example.com")


def test_chat_creates_session_and_two_exchanges(client, chat_headers):
    # First message creates a session
    resp = client.post(
        "/chat", json={"message": "How is Writing Task 2 scored?"}, headers=chat_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    session_id = body["session_id"]
    assert isinstance(session_id, int)
    assert body["reply"] == CANNED_CHAT_REPLY

    # Second message with session_id appends to the same session
    resp = client.post(
        "/chat",
        json={"message": "What about coherence?", "session_id": session_id},
        headers=chat_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["session_id"] == session_id

    # Exactly one session listed for this user
    resp = client.get("/chat/sessions", headers=chat_headers)
    assert resp.status_code == 200
    sessions = resp.json()
    assert len(sessions) == 1
    assert sessions[0]["id"] == session_id

    # 4 messages after 2 exchanges (user/assistant pairs), in order
    resp = client.get(f"/chat/sessions/{session_id}", headers=chat_headers)
    assert resp.status_code == 200
    messages = resp.json()
    assert len(messages) == 4
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
    assert messages[0]["content"] == "How is Writing Task 2 scored?"


def test_other_users_session_404(client, chat_headers, make_user):
    resp = client.get("/chat/sessions", headers=chat_headers)
    session_id = resp.json()[0]["id"]

    other_headers = make_user("intruder")
    resp = client.get(f"/chat/sessions/{session_id}", headers=other_headers)
    assert resp.status_code == 404
