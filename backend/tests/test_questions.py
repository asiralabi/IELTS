"""Question generator endpoint (LLM mocked)."""

import pytest

SECTIONS = ["reading", "listening", "writing", "speaking"]


@pytest.mark.parametrize("section", SECTIONS)
def test_generate_each_section(client, auth_headers, section):
    resp = client.post(
        "/questions/generate", json={"section": section}, headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["id"], int)
    assert body["section"] == section
    assert body["question_type"]
    assert body["question"]


def test_invalid_section_422(client, auth_headers):
    resp = client.post(
        "/questions/generate", json={"section": "grammar"}, headers=auth_headers
    )
    assert resp.status_code == 422
