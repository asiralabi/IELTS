"""The whole Speaking interview as one sitting (LLM mocked)."""

import pytest

from app.agents import question_generator
from app.services import practice_pool

TRANSCRIPT = (
    "I would say the place that impressed me most was a small fishing village "
    "on the west coast, which I visited with my family a couple of summers ago."
)


def test_full_test_serves_all_three_parts_in_order(client, auth_headers):
    resp = client.post("/speaking/full-test", json={}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    parts = resp.json()["parts"]
    assert [p["part"] for p in parts] == ["part1", "part2", "part3"]
    # A candidate needs to know the interview is ~14 minutes, split unevenly.
    assert [p["minutes"] for p in parts] == [5, 4, 5]
    # Part 2 is a cue card, not a question — the long turn has no shape without it.
    assert set(parts[1]["question"]) >= {"topic", "bullets", "closing"}


def test_full_test_is_served_from_the_pool(client, auth_headers, monkeypatch):
    monkeypatch.setattr(
        question_generator,
        "generate",
        lambda *a, **k: pytest.fail("speaking part generated instead of popping"),
    )
    monkeypatch.setattr(
        practice_pool, "pop", lambda *a, **k: {"question": "Pooled question"}
    )
    resp = client.post("/speaking/full-test", json={}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert [p["question"] for p in resp.json()["parts"]] == ["Pooled question"] * 3


def test_full_test_submit_bands_the_interview_and_files_every_part(client, make_user):
    headers = make_user("speaking-full")
    resp = client.post(
        "/speaking/full-test/submit",
        json={
            "part1": {"question": "Where do you live?", "transcript": TRANSCRIPT},
            "part2": {
                # A cue card round-trips as the object it was generated as.
                "question": {
                    "topic": "Describe a place you visited.",
                    "bullets": ["where", "when", "what"],
                    "closing": "and explain why.",
                },
                "transcript": TRANSCRIPT,
            },
            "part3": {"question": ["Why do people travel?"], "transcript": TRANSCRIPT},
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body["parts"]) == {"part1", "part2", "part3"}
    assert body["overall_band"] == 6.0

    history = client.get("/speaking/history", headers=headers).json()
    assert sorted(r["part"] for r in history) == ["part1", "part2", "part3"]


def test_full_test_submit_rejects_an_empty_interview(client, auth_headers):
    resp = client.post("/speaking/full-test/submit", json={}, headers=auth_headers)
    assert resp.status_code == 400
