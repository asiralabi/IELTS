"""Writing examiner endpoint (LLM mocked)."""

import pytest

from app.agents import question_generator
from app.services import practice_pool

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


def test_full_test_serves_both_tasks_with_exam_timings(client, auth_headers):
    resp = client.post("/writing/full-test", json={}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    tasks = body["tasks"]
    assert [t["task"] for t in tasks] == ["task1", "task2"]
    # A student needs to know how the hour splits before starting to write.
    assert [(t["minutes"], t["min_words"]) for t in tasks] == [(20, 150), (40, 250)]
    # Task 1 Academic is a chart description — without the chart there is no task.
    assert tasks[0]["visual"]
    assert all(t["question"] for t in tasks)


def test_full_test_is_served_from_the_pool(client, auth_headers, monkeypatch):
    """Both tasks are already warm — the paper must not pay to write them again.

    The single-task page pops from these same buckets, so a student asking for
    the whole paper should wait no longer than one asking for half of it.
    """
    monkeypatch.setattr(
        question_generator,
        "generate",
        lambda *a, **k: pytest.fail("writing task generated instead of popping"),
    )
    monkeypatch.setattr(
        practice_pool, "pop", lambda *a, **k: {"question": "Pooled prompt"}
    )
    resp = client.post("/writing/full-test", json={}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert [t["question"] for t in resp.json()["tasks"]] == [
        "Pooled prompt",
        "Pooled prompt",
    ]


def test_full_test_submit_bands_the_paper_and_files_both_tasks(client, make_user):
    headers = make_user("writing-full")
    resp = client.post(
        "/writing/full-test/submit",
        json={
            "task1": {"prompt": "Describe the chart.", "essay": ESSAY},
            "task2": {"prompt": "Technology complicates life. Discuss.", "essay": ESSAY},
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body["tasks"]) == {"task1", "task2"}
    assert body["overall_band"] == 6.5
    # Each task also lands in the ordinary history, so a full paper feeds
    # progress the same way a single task does.
    history = client.get("/writing/history", headers=headers).json()
    assert sorted(r["task_type"] for r in history) == ["task1", "task2"]


def test_full_test_submit_bands_one_task_on_its_own(client, make_user):
    """A candidate who wrote only Task 2 is banded on Task 2, not averaged
    against the blank they were never asked to fill."""
    resp = client.post(
        "/writing/full-test/submit",
        json={"task2": {"prompt": "Discuss.", "essay": ESSAY}},
        headers=make_user("writing-partial"),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body["tasks"]) == {"task2"}
    assert body["overall_band"] == 6.5


def test_full_test_submit_rejects_an_empty_paper(client, auth_headers):
    resp = client.post("/writing/full-test/submit", json={}, headers=auth_headers)
    assert resp.status_code == 400


def test_history_shows_entry(client, auth_headers):
    resp = client.get("/writing/history", headers=auth_headers)
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) >= 1
    entry = rows[0]
    assert entry["task_type"] == "task2"
    assert entry["band_score"] == 6.5
    assert entry["word_count"] == len(ESSAY.split())
