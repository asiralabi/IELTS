"""Reading and listening practice + answer checking (LLM mocked)."""

import pytest

from app.services import practice_pool


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


def _reading_full_test(client, auth_headers) -> dict:
    resp = client.post("/reading/full-test", json={}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_reading_full_test_numbers_questions_across_passages(client, auth_headers):
    """The whole paper is one continuous run of numbers, not three that restart.

    Listening can precompute its offsets because a part is always ten
    questions; a reading passage returns whatever count it wrote, so the offset
    has to accumulate. Three two-question passages must come back 1-6.
    """
    body = _reading_full_test(client, auth_headers)
    passages = body["passages"]
    assert len(passages) == 3
    assert [p["passage_number"] for p in passages] == [1, 2, 3]

    numbers = [q["number"] for p in passages for q in p["questions"]]
    assert numbers == [1, 2, 3, 4, 5, 6]
    for passage in passages:
        for leak in ("answer_key", "accepted_variants", "answer_positions"):
            assert leak not in passage


def test_reading_full_test_bands_the_paper_as_a_whole(client, auth_headers):
    """Banding the aggregate, not averaging three per-passage bands.

    Each passage is handed only the numbers it owns, so a passage must not
    report a total that counts questions belonging to another.
    """
    body = _reading_full_test(client, auth_headers)
    # Right on every passage's first question, wrong on its second.
    answers = {"1": "TRUE", "2": "FALSE", "3": "TRUE", "4": "FALSE",
               "5": "TRUE", "6": "FALSE"}
    resp = client.post(
        "/reading/full-test/check",
        json={"practice_id": body["practice_id"], "answers": answers},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()
    assert result["score"] == 3
    assert result["total"] == 6
    assert [p["total"] for p in result["passages"]] == [2, 2, 2]
    assert [r["number"] for r in result["results"]] == [1, 2, 3, 4, 5, 6]
    # 3/6 scales to 20/40, which is Band 5.5 on the Academic Reading table.
    assert result["band_estimate"] == 5.5


@pytest.mark.parametrize(
    "section,list_key",
    [("reading", "passages"), ("listening", "parts")],
)
def test_a_full_test_is_served_from_the_pool(
    client, auth_headers, monkeypatch, section, list_key
):
    """A whole paper is 3-4 heavy generations — half an hour or more.

    No request can wait that out, so the warmer builds them ahead of time and
    the route pops. Generating here at all would mean a student sat watching a
    spinner for the length of the exam they were about to take.
    """
    from app.agents import listening_trainer, reading_trainer

    trainer = reading_trainer if section == "reading" else listening_trainer
    monkeypatch.setattr(
        trainer,
        "create_full_test",
        lambda *a, **k: pytest.fail(f"{section} generated instead of popping"),
    )
    monkeypatch.setattr(
        practice_pool,
        "pop",
        lambda *a, **k: {"title": "Pooled", list_key: [{"questions": []}]},
    )
    resp = client.post(f"/{section}/full-test", json={}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["title"] == "Pooled"


def test_a_full_test_cannot_be_marked_as_a_single_practice(client, auth_headers):
    """/check would find no questions at the top level and answer 0/0.

    A confident zero is worse than an error: the student is told they got
    everything wrong rather than that the wrong endpoint was called.
    """
    body = _reading_full_test(client, auth_headers)
    resp = client.post(
        "/reading/check",
        json={"practice_id": body["practice_id"], "answers": {"1": "TRUE"}},
        headers=auth_headers,
    )
    assert resp.status_code == 404
