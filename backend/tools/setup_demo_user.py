"""Create a demo user, prime with 4 module runs + 1 mock exam, run study plan.

After this runs, the user can log in at the frontend with:
    email:    demo@ielts.local
    password: demo1234

The account already has one Writing / Speaking / Reading / Listening submission
persisted, plus one scored mock exam, so the Study Plan page will render
grounded suggestions immediately.
"""

import asyncio
import json
import sys
import time

from app.agents import (
    feedback,
    listening_trainer,
    orchestrator,
    reading_trainer,
    speaking_examiner,
    writing_examiner,
)
from app.auth import hash_password
from app.database import Base, SessionLocal, engine
from app.models import (
    MockExam,
    PracticeAttempt,
    SpeakingSubmission,
    User,
    WritingSubmission,
)

DEMO_EMAIL = "demo@example.com"
DEMO_PASSWORD = "demo1234"
DEMO_NAME = "Demo Learner"
DEMO_TARGET = 7.5

WRITING_PROMPT = (
    "Some people believe that unpaid community service should be a compulsory "
    "part of high school programmes. To what extent do you agree or disagree?"
)
WRITING_ESSAY = (
    "In recent years, many educators have argued that requiring high school "
    "students to perform unpaid community service would benefit both learners "
    "and society. I largely agree with this view, though I believe schools "
    "must design such programmes carefully.\n\n"
    "On the one hand, compulsory community service exposes young people to "
    "real-world problems that are rarely covered inside a classroom. When "
    "teenagers help at food banks, tutor younger children, or clean local "
    "parks, they develop empathy and a stronger sense of civic responsibility. "
    "In addition, these activities build practical skills such as teamwork, "
    "communication, and time management, which universities and employers "
    "consistently value.\n\n"
    "On the other hand, making service compulsory can undermine its purpose if "
    "students perceive it as another chore. Some may go through the motions "
    "just to satisfy a requirement, which reduces the benefit for the "
    "community they are supposed to serve. To avoid this, schools should let "
    "learners choose from a range of causes and cap the required hours.\n\n"
    "In conclusion, compulsory community service is a worthwhile policy "
    "because it broadens students' horizons and strengthens the community, "
    "provided schools implement it with flexibility."
)

SPEAKING_QUESTION = (
    "Describe a book that you have recently read and enjoyed. You should say: "
    "what the book was about, why you decided to read it, how it made you feel, "
    "and explain why you enjoyed it."
)
SPEAKING_TRANSCRIPT = (
    "Um, okay so recently I read a book called Atomic Habits by James Clear. "
    "It's about, uh, how small changes in your daily routine can lead to big "
    "results over time. I decided to read it because a colleague at work kept "
    "recommending it, and I was struggling to stick with my morning exercise "
    "routine. When I started reading it, I felt really motivated because the "
    "ideas are simple but they make a lot of sense. For example, he talks "
    "about habit stacking, which is when you attach a new habit to an existing "
    "one. Um, the reason I enjoyed it was because it gives you practical steps "
    "you can take immediately, and, yeah, since reading it I've kept up my "
    "exercise routine for about three months now."
)


def simulate_answers(answer_key: dict, correct_ratio: float = 0.6) -> dict:
    keys = sorted(answer_key.keys(), key=lambda k: (len(k), k))
    cutoff = int(len(keys) * correct_ratio)
    out: dict[str, str] = {}
    for i, k in enumerate(keys):
        real = answer_key[k]
        if isinstance(real, list):
            real = real[0] if real else ""
        out[k] = str(real) if i < cutoff else "WRONG"
    return out


def get_or_create_demo(db) -> User:
    user = db.query(User).filter(User.email == DEMO_EMAIL).first()
    if user:
        print(f"Reusing existing demo user id={user.id}")
        return user
    user = User(
        email=DEMO_EMAIL,
        hashed_password=hash_password(DEMO_PASSWORD),
        full_name=DEMO_NAME,
        target_band=DEMO_TARGET,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    print(f"Created demo user id={user.id}")
    return user


async def prime_writing(db, user: User) -> None:
    t0 = time.perf_counter()
    result = await writing_examiner.evaluate("task2", WRITING_PROMPT, WRITING_ESSAY)
    sub = WritingSubmission(
        user_id=user.id,
        task_type="task2",
        prompt=WRITING_PROMPT,
        essay=WRITING_ESSAY,
        word_count=result.get("word_count") or len(WRITING_ESSAY.split()),
        result=result,
        band_score=result.get("band_score"),
    )
    db.add(sub)
    db.commit()
    print(f"  Writing done  band={result.get('band_score')}  ({time.perf_counter()-t0:.1f}s)")


async def prime_speaking(db, user: User) -> None:
    t0 = time.perf_counter()
    result = await speaking_examiner.evaluate("part2", SPEAKING_QUESTION, SPEAKING_TRANSCRIPT)
    sub = SpeakingSubmission(
        user_id=user.id,
        part="part2",
        question=SPEAKING_QUESTION,
        transcript=SPEAKING_TRANSCRIPT,
        result=result,
        band_score=result.get("band_score"),
    )
    db.add(sub)
    db.commit()
    print(f"  Speaking done  band={result.get('band_score')}  ({time.perf_counter()-t0:.1f}s)")


async def prime_reading(db, user: User) -> None:
    t0 = time.perf_counter()
    practice = await reading_trainer.create_practice(
        question_types=["true_false_notgiven", "sentence_completion"],
        difficulty="band 6-7",
        topic="urban gardening",
    )
    answers = simulate_answers(practice.get("answer_key", {}), correct_ratio=0.6)
    result = await reading_trainer.check_answers(practice, answers)
    attempt = PracticeAttempt(
        user_id=user.id,
        section="reading",
        answers=answers,
        score=result.get("score"),
        total=result.get("total"),
        result=result,
    )
    db.add(attempt)
    db.commit()
    print(f"  Reading done  {result.get('score')}/{result.get('total')}  "
          f"band est.={result.get('band_estimate')}  ({time.perf_counter()-t0:.1f}s)")


async def prime_listening(db, user: User) -> None:
    t0 = time.perf_counter()
    practice = await listening_trainer.create_practice(
        question_types=["form_completion", "multiple_choice"],
        difficulty="band 6",
        topic="library membership registration",
    )
    answers = simulate_answers(practice.get("answer_key", {}), correct_ratio=0.6)
    result = await listening_trainer.check_answers(practice, answers)
    attempt = PracticeAttempt(
        user_id=user.id,
        section="listening",
        answers=answers,
        score=result.get("score"),
        total=result.get("total"),
        result=result,
    )
    db.add(attempt)
    db.commit()
    print(f"  Listening done  {result.get('score')}/{result.get('total')}  "
          f"band est.={result.get('band_estimate')}  ({time.perf_counter()-t0:.1f}s)")


async def prime_mock_exam(db, user: User) -> None:
    t0 = time.perf_counter()
    exam_payload = await orchestrator.build_mock_exam(user.target_band)
    exam = MockExam(user_id=user.id, exam=exam_payload)
    db.add(exam)
    db.commit()
    db.refresh(exam)
    print(f"  Mock exam generated  id={exam.id}  ({time.perf_counter()-t0:.1f}s)")

    # Fake a semi-realistic submission using the exam's answer keys
    def keys_of(section: dict) -> dict[str, str]:
        return simulate_answers(section.get("answer_key", {}), correct_ratio=0.6)

    submission = {
        "listening_answers": keys_of(exam_payload.get("listening", {})),
        "reading_answers": keys_of(exam_payload.get("reading", {})),
        "essays": {
            "task1": (
                "The chart shows sales of electric vehicles between 2015 and "
                "2023, with steady growth overall and a sharp rise after 2020."
            ),
            "task2": WRITING_ESSAY,
        },
        "speaking_transcripts": {
            "part1": "I live in a small coastal town and I enjoy walking by the sea.",
            "part2": SPEAKING_TRANSCRIPT,
            "part3": (
                "I think reading habits have shifted a lot because people now read "
                "shorter articles online rather than long books, but audiobooks are "
                "growing quickly and that helps busy commuters."
            ),
        },
    }
    t1 = time.perf_counter()
    scored = await orchestrator.score_mock_exam(db, user, exam, submission)
    print(f"  Mock exam scored  overall={scored.get('overall_band')}  "
          f"({time.perf_counter()-t1:.1f}s)")


async def show_study_plan(db, user: User) -> None:
    t0 = time.perf_counter()
    plan = await feedback.study_plan(db, user)
    print(f"\nStudy plan generated in {time.perf_counter()-t0:.1f}s\n")
    payload = json.dumps(plan, indent=2, ensure_ascii=False)
    with open("tools/demo_study_plan.json", "w", encoding="utf-8") as f:
        f.write(payload)
    print(payload)


async def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        total = time.perf_counter()
        user = get_or_create_demo(db)
        print(f"\nPriming account for '{user.email}' (target band {user.target_band}):")
        await prime_writing(db, user)
        await prime_speaking(db, user)
        await prime_reading(db, user)
        await prime_listening(db, user)
        await prime_mock_exam(db, user)
        await show_study_plan(db, user)
        print(f"\nDemo setup complete in {time.perf_counter()-total:.1f}s.")
        print("\n" + "=" * 62)
        print(f"  Demo login\n    email:    {DEMO_EMAIL}\n    password: {DEMO_PASSWORD}")
        print("=" * 62)
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
