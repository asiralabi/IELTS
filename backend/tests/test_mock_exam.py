"""Mock exam lifecycle: generate -> inspect -> submit -> score (LLM mocked).

With the conftest mocks every section resolves deterministically:
listening/reading check -> band 5.5, writing -> 6.5, speaking -> 6.0,
so the overall band is round_band((5.5 + 5.5 + 6.5 + 6.0) / 4) == 6.0.
"""

import pytest

ESSAY = (
    "Some people believe that technology has made our lives more complicated, "
    "while others argue it simplifies daily tasks. In my opinion, the benefits "
    "clearly outweigh the drawbacks, provided it is used sensibly."
)

TRANSCRIPT = "Well, I really enjoy reading because it helps me relax after work."


@pytest.fixture(scope="module")
def exam_headers(client):
    """Dedicated user so exam ownership and counts are deterministic."""
    from tests.conftest import _register_and_login

    return _register_and_login(client, "mock-exam-user@example.com")


@pytest.fixture(scope="module")
def exam_id(client, exam_headers) -> int:
    resp = client.post("/mock-exam/generate", headers=exam_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body["id"], int)
    return body["id"]


def _find_keys(obj, needles: set[str]) -> set[str]:
    found = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in needles:
                found.add(k)
            found |= _find_keys(v, needles)
    elif isinstance(obj, list):
        for item in obj:
            found |= _find_keys(item, needles)
    return found


def test_generate_covers_four_skills_and_hides_answers(client, exam_headers, exam_id):
    resp = client.get(f"/mock-exam/{exam_id}", headers=exam_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "generated"
    assert body["results"] is None
    assert body["overall_band"] is None

    exam = body["exam"]
    assert set(exam) == {"listening", "reading", "writing", "speaking"}
    assert exam["reading"]["passage"]
    assert exam["listening"]["audio_script"]
    assert exam["writing"]["task1"]["question"]
    assert exam["writing"]["task2"]["question"]
    assert exam["speaking"]["part1"] and exam["speaking"]["part2"]

    # No answer keys, answers or explanations may leak before scoring
    assert _find_keys(body, {"answer_key", "answers", "explanation"}) == set()


def test_submit_scores_all_sections(client, exam_headers, exam_id):
    resp = client.post(
        f"/mock-exam/{exam_id}/submit",
        json={
            "listening_answers": {"1": "6:00", "2": "SMITH"},
            "reading_answers": {"1": "TRUE", "2": "FALSE"},
            "essays": {"task1": ESSAY, "task2": ESSAY},
            "speaking_transcripts": {"part1": TRANSCRIPT, "part2": TRANSCRIPT},
        },
        headers=exam_headers,
    )
    assert resp.status_code == 200, resp.text
    results = resp.json()
    assert results["section_bands"] == {
        "listening": 5.5,
        "reading": 5.5,
        "writing": 6.5,
        "speaking": 6.0,
    }
    assert results["overall_band"] == 6.0
    assert results["listening"]["score"] == 1
    assert results["writing"]["task2"]["band_score"] == 6.5
    assert results["speaking"]["part1"]["band_score"] == 6.0


def test_scored_exam_reveals_answer_key_and_persists(client, exam_headers, exam_id):
    resp = client.get(f"/mock-exam/{exam_id}", headers=exam_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "scored"
    assert body["overall_band"] == 6.0
    assert body["results"]["overall_band"] == 6.0
    # After scoring the student may review the full exam, keys included
    assert body["exam"]["reading"]["answer_key"]


def test_resubmit_scored_exam_409(client, exam_headers, exam_id):
    resp = client.post(
        f"/mock-exam/{exam_id}/submit", json={}, headers=exam_headers
    )
    assert resp.status_code == 409


def test_other_users_exam_404(client, exam_id, make_user):
    other = make_user("exam-intruder")
    assert client.get(f"/mock-exam/{exam_id}", headers=other).status_code == 404
    resp = client.post(f"/mock-exam/{exam_id}/submit", json={}, headers=other)
    assert resp.status_code == 404


def test_unknown_exam_404(client, exam_headers):
    assert client.get("/mock-exam/999999", headers=exam_headers).status_code == 404
