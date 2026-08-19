"""Reading and listening practice + answer checking (LLM mocked)."""


def _practice_and_check(client, auth_headers, section: str) -> None:
    resp = client.post(f"/{section}/practice", json={}, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    practice_id = body["practice_id"]
    assert isinstance(practice_id, int)
    assert body["title"]
    assert len(body["questions"]) == 2
    # Nothing that gives the answers away may reach the student. The two
    # routers kept separate lists of what that means and disagreed: reading
    # dropped `answer_key` alone, so anything listening-shaped it ever grew
    # would have gone straight to the browser.
    for leak in ("answer_key", "accepted_variants", "answer_positions", "blueprint"):
        assert leak not in body
    if section == "reading":
        assert body["passage"]
    else:
        assert body["audio_script"]

    # One right, one wrong — answers must suit the section's own key, because
    # listening now marks each answer against it for real.
    answers = (
        {"1": "TRUE", "2": "FALSE"}
        if section == "reading"
        else {"1": "6:00", "2": "SMITH"}
    )
    resp = client.post(
        f"/{section}/check",
        json={"practice_id": practice_id, "answers": answers},
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
