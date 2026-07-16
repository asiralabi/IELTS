"""Reading and listening practice + answer checking (LLM mocked)."""


def _practice_and_check(client, auth_headers, section: str) -> None:
    resp = client.post(f"/{section}/practice", json={}, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    practice_id = body["practice_id"]
    assert isinstance(practice_id, int)
    assert body["title"]
    assert len(body["questions"]) == 2
    # The answer key must never be exposed to the student
    assert "answer_key" not in body
    if section == "reading":
        assert body["passage"]
    else:
        assert body["audio_script"]

    resp = client.post(
        f"/{section}/check",
        json={"practice_id": practice_id, "answers": {"1": "TRUE", "2": "FALSE"}},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    result = resp.json()
    assert result["score"] == 1
    assert result["total"] == 2
    assert result["band_estimate"] == 5.5
    assert len(result["results"]) == 2
    assert result["results"][0]["correct"] is True
    assert result["results"][1]["correct"] is False


def test_reading_practice_and_check(client, auth_headers):
    _practice_and_check(client, auth_headers, "reading")


def test_listening_practice_and_check(client, auth_headers):
    _practice_and_check(client, auth_headers, "listening")


def test_check_unknown_practice_404(client, auth_headers):
    resp = client.post(
        "/reading/check",
        json={"practice_id": 999999, "answers": {"1": "TRUE"}},
        headers=auth_headers,
    )
    assert resp.status_code == 404
