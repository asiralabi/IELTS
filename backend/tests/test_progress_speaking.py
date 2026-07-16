"""Speaking examiner + progress dashboard + weakness profile (LLM mocked)."""

TRANSCRIPT = (
    "Well, um, I really enjoy reading because it helps me relax after work, "
    "and I usually read novels, like, historical fiction mostly."
)


def test_speaking_submit_with_transcript(client, auth_headers):
    resp = client.post(
        "/speaking/submit",
        data={
            "part": "part1",
            "question": "Do you enjoy reading?",
            "transcript": TRANSCRIPT,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["band_score"] == 6.0
    assert body["transcript"] == TRANSCRIPT
    assert body["pronunciation"] is None  # transcript only, no audio
    assert isinstance(body["id"], int)


def test_speaking_submit_without_transcript_or_audio_400(client, auth_headers):
    resp = client.post(
        "/speaking/submit",
        data={"part": "part1", "question": "Do you enjoy reading?"},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_progress_returns_counts(client, auth_headers):
    resp = client.get("/progress", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    counts = body["counts"]
    for key in (
        "writing_submissions",
        "speaking_submissions",
        "reading_attempts",
        "listening_attempts",
        "mock_exams",
    ):
        assert key in counts
    assert counts["speaking_submissions"] >= 1
    assert body["target_band"] == 7.0
    assert "skills" in body
    assert "timeline" in body


def test_study_plan_returns_plan(client, auth_headers):
    resp = client.get("/progress/study-plan", headers=auth_headers)
    assert resp.status_code == 200
    plan = resp.json()
    assert plan["summary"]
    assert plan["priorities"]
    assert isinstance(plan["study_plan"], list)
    assert plan["study_plan"][0]["day"] == 1
    assert plan["resources"]


def test_weaknesses_returns_profile(client, auth_headers):
    resp = client.get("/progress/weaknesses", headers=auth_headers)
    assert resp.status_code == 200
    profile = resp.json()
    assert profile["grammar"] is True
    assert profile["vocabulary"] is False
    assert "details" in profile
    assert set(profile["details"]) >= {"grammar", "vocabulary", "pronunciation"}
