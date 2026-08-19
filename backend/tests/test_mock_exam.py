"""Mock exam lifecycle: generate -> inspect -> submit -> score (LLM mocked).

A real mock exam serves two whole papers, and neither can be written inside a
request — seven heavy local generations. They come from the warm pool instead,
so these tests seed the pool by hand rather than racing the background warmer
into it.

With the conftest mocks every section resolves deterministically:
listening/reading check -> band 5.5, writing -> 6.5, speaking -> 6.0,
so the overall band is round_band((5.5 + 5.5 + 6.5 + 6.0) / 4) == 6.0.
"""

import copy

import pytest

from app.agents._numbering import renumber
from app.services import practice_pool
from tests.conftest import LISTENING_PRACTICE, READING_PRACTICE

ESSAY = (
    "Some people believe that technology has made our lives more complicated, "
    "while others argue it simplifies daily tasks. In my opinion, the benefits "
    "clearly outweigh the drawbacks, provided it is used sensibly."
)

TRANSCRIPT = "Well, I really enjoy reading because it helps me relax after work."


def _paper(
    practice: dict, count: int, kind: str, section_key: str, index_key: str
) -> dict:
    """A full-test payload built from the two-question practice fixture.

    Built here rather than through `create_full_test` because the real
    listening builder insists on ten questions a part, which the fixture is
    not; what these tests need is only the pooled *shape*.
    """
    sections = []
    for index in range(count):
        section = copy.deepcopy(practice)
        renumber(section, index * len(practice["questions"]))
        section[index_key] = index + 1
        sections.append(section)
    return {"title": "Paper", "kind": kind, section_key: sections}


@pytest.fixture(scope="module")
def exam_headers(client):
    """Dedicated user so exam ownership and counts are deterministic."""
    from tests.conftest import _register_and_login

    return _register_and_login(client, "mock-exam-user@example.com")


@pytest.fixture(scope="module")
def exam_id(client, exam_headers) -> int:
    from app.database import SessionLocal

    with SessionLocal() as db:
        practice_pool.insert(
            db,
            "listening",
            practice_pool.FULL_TEST,
            _paper(LISTENING_PRACTICE, 4, "full_listening_test", "parts", "part"),
        )
        practice_pool.insert(
            db,
            "reading",
            practice_pool.FULL_TEST,
            _paper(
                READING_PRACTICE, 3, "full_reading_test", "passages", "passage_number"
            ),
        )

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
    # Whole papers, numbered straight through, not one practice set per section.
    assert [p["passage_number"] for p in exam["reading"]["passages"]] == [1, 2, 3]
    assert [p["part"] for p in exam["listening"]["parts"]] == [1, 2, 3, 4]
    numbers = [q["number"] for p in exam["reading"]["passages"] for q in p["questions"]]
    assert numbers == [1, 2, 3, 4, 5, 6]
    assert exam["listening"]["parts"][0]["audio_script"]
    assert exam["writing"]["task1"]["question"]
    assert exam["writing"]["task2"]["question"]
    assert exam["speaking"]["part1"] and exam["speaking"]["part2"]

    # No answer keys, answers or explanations may leak before scoring
    assert _find_keys(body, {"answer_key", "answers", "explanation"}) == set()


def test_submit_scores_all_sections(client, exam_headers, exam_id):
    resp = client.post(
        f"/mock-exam/{exam_id}/submit",
        json={
            # Both papers are answered end to end, so a section that silently
            # marked only its first part would come back short.
            "listening_answers": {
                str(n): ("6:00" if n % 2 else "SMITH") for n in range(1, 9)
            },
            "reading_answers": {
                str(n): ("TRUE" if n % 2 else "FALSE") for n in range(1, 7)
            },
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
    # Half of each whole paper, not half of one part of it.
    assert (results["listening"]["score"], results["listening"]["total"]) == (4, 8)
    assert (results["reading"]["score"], results["reading"]["total"]) == (3, 6)
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
    assert body["exam"]["reading"]["passages"][0]["answer_key"]


def test_a_cold_pool_still_yields_an_exam(client, exam_headers, monkeypatch):
    """A student who clicks "mock exam" gets an exam, not an error.

    Two whole papers cannot be written inside a request, so when the warmer has
    not reached the full-test buckets yet the exam falls back to one practice
    set per section — shorter than the real thing, but `band_from_40` scales it.
    """
    monkeypatch.setattr(practice_pool, "pop", lambda *a, **k: None)
    resp = client.post("/mock-exam/generate", headers=exam_headers)
    assert resp.status_code == 200, resp.text
    exam = resp.json()["exam"]
    assert set(exam) == {"listening", "reading", "writing", "speaking"}
    assert exam["reading"]["passage"] and "passages" not in exam["reading"]
    assert exam["listening"]["audio_script"]


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
