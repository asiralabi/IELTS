"""The tutor's view of a student's own marked work."""

from app.agents.student_record import student_record
from app.database import SessionLocal
from app.models import MockExam, PracticeAttempt, User


def _user(db, email: str) -> User:
    return db.query(User).filter(User.email == email).one()


def test_record_says_when_there_is_nothing_yet(client):
    from tests.conftest import _register_and_login

    _register_and_login(client, "record-empty@example.com")
    with SessionLocal() as db:
        text = student_record(db, _user(db, "record-empty@example.com"))
    assert "Target band: 7.0" in text
    assert "No marked work yet" in text


def test_record_carries_the_latest_exam_and_its_wrong_answers(client):
    from tests.conftest import _register_and_login

    _register_and_login(client, "record-full@example.com")
    with SessionLocal() as db:
        user = _user(db, "record-full@example.com")
        db.add(MockExam(
            user_id=user.id, status="scored", overall_band=6.0,
            exam={"listening": {"questions": [
                {"number": 1, "type": "form completion", "question": "Name of the street"},
                {"number": 2, "type": "note completion", "question": "Day of the visit"},
            ]}},
            results={
                "listening": {"score": 1, "total": 2, "band_estimate": 5.0, "results": [
                    {"number": 1, "correct": True, "student_answer": "x", "correct_answer": "x"},
                    {"number": 2, "correct": False, "student_answer": "tuesday", "correct_answer": "Thursday"},
                ]},
                "writing": {"task2": {"band_score": 6.5, "lexical_resource": 6.0,
                                      "weaknesses": ["Repeats 'important'", "Weak conclusion"]}},
            },
        ))
        # An unscored exam must not displace the scored one.
        db.add(MockExam(user_id=user.id, status="generated", exam={}))
        db.add(PracticeAttempt(user_id=user.id, section="reading", answers={}, score=8, total=13,
                               result={"band_estimate": 6.0}))
        db.commit()
        text = student_record(db, user)

    assert "LATEST FULL MOCK EXAM" in text and "overall band 6.0" in text
    # The wrong answer arrives with its question, so the tutor can explain it.
    assert "Q2 [note completion] Day of the visit" in text
    assert "student wrote: tuesday | correct: Thursday" in text
    assert "Q1 " not in text  # right answers are not listed
    assert "Writing task2: band 6.5 (lexical resource 6.0)" in text
    assert "weakness: Repeats 'important'" in text
    assert "Reading practice set, 8/13 correct" in text
    assert "No marked work yet" not in text


def test_chat_reaches_the_model_with_the_record(client, make_user, monkeypatch):
    from app.llm import client as llm_client

    seen = {}
    original = llm_client.get_llm_client()

    class Spy:
        async def complete(self, system, messages, **kw):
            seen["system"] = system
            return "ok"

        def __getattr__(self, name):
            return getattr(original, name)

    monkeypatch.setattr("app.agents.instructor.get_llm_client", lambda: Spy())
    resp = client.post("/chat", json={"message": "check my recent exam"}, headers=make_user("rec"))
    assert resp.status_code == 200
    assert "STUDENT RECORD:" in seen["system"]
    assert "No marked work yet" in seen["system"]
