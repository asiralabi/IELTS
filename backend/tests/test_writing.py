"""Writing examiner endpoint (LLM mocked)."""

ESSAY = (
    "Some people believe that technology has made our lives more complicated, "
    "while others argue it simplifies daily tasks. In my opinion, the benefits "
    "of technology clearly outweigh its drawbacks, provided it is used sensibly."
)


def test_submit_essay_returns_band_and_criteria(client, auth_headers):
    resp = client.post(
        "/writing/submit",
        json={
            "task_type": "task2",
            "prompt": "Technology makes life complicated. Discuss.",
            "essay": ESSAY,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["band_score"] == 6.5
    for criterion in (
        "task_response",
        "coherence_cohesion",
        "lexical_resource",
        "grammatical_range_accuracy",
    ):
        assert isinstance(body[criterion], float)
    assert body["word_count"] == len(ESSAY.split())
    assert "id" in body
    assert body["strengths"] and body["weaknesses"]
    assert isinstance(body["errors"], list)


def test_short_essay_422(client, auth_headers):
    resp = client.post(
        "/writing/submit",
        json={"task_type": "task2", "prompt": "A prompt", "essay": "too short"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


def test_history_shows_entry(client, auth_headers):
    resp = client.get("/writing/history", headers=auth_headers)
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) >= 1
    entry = rows[0]
    assert entry["task_type"] == "task2"
    assert entry["band_score"] == 6.5
    assert entry["word_count"] == len(ESSAY.split())
