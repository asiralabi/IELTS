"""Run one mock test per IELTS module and print AI suggestions after each.

Sections:
  1. Writing (task 2 essay)
  2. Speaking (part 2 transcript)
  3. Reading (generate passage + questions, answer half correctly)
  4. Listening (generate script + questions, answer half correctly)
  5. Study plan (RAG-grounded, consuming all 4 module results)
"""

import asyncio
import json
import sys
import time
from datetime import date

from app.agents import (
    listening_trainer,
    reading_trainer,
    speaking_examiner,
    writing_examiner,
)
from app.llm.client import get_llm_client
from app.llm.prompts import FEEDBACK_SYSTEM
from app.rag.retriever import retrieve_context

# --- Writing sample ---------------------------------------------------------
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

# --- Speaking sample --------------------------------------------------------
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


def simulate_answers(answer_key: dict, correct_ratio: float = 0.5) -> dict:
    """Answer the first `correct_ratio` fraction correctly, rest wrong."""
    keys = sorted(answer_key.keys(), key=lambda k: (len(k), k))
    cutoff = int(len(keys) * correct_ratio)
    student: dict[str, str] = {}
    for i, k in enumerate(keys):
        real = answer_key[k]
        if isinstance(real, list):
            real = real[0] if real else ""
        real = str(real)
        if i < cutoff:
            student[k] = real
        else:
            student[k] = "WRONG"
    return student


def print_header(title: str) -> None:
    bar = "=" * 78
    print(f"\n{bar}\n {title}\n{bar}")


def print_examiner_suggestions(result: dict) -> None:
    band = result.get("band_score")
    print(f"Overall band: {band}")
    strengths = result.get("strengths") or []
    weaknesses = result.get("weaknesses") or []
    feedback = result.get("feedback") or ""
    if strengths:
        print("\nStrengths:")
        for s in strengths:
            print(f"  + {s}")
    if weaknesses:
        print("\nWeaknesses:")
        for w in weaknesses:
            print(f"  - {w}")
    if feedback:
        print(f"\nFeedback:\n  {feedback}")
    errors = result.get("errors") or []
    if errors:
        print("\nError examples:")
        for e in errors[:2]:
            print(f"  \"{e.get('excerpt','')}\" -> {e.get('correction','')}")


def print_checker_suggestions(result: dict) -> None:
    print(f"Score: {result.get('score')}/{result.get('total')}  band est.: "
          f"{result.get('band_estimate')}")
    wrongs = [r for r in result.get("results", []) if not r.get("correct")]
    if wrongs:
        print(f"\nAI explanations for missed questions (showing up to 3 of {len(wrongs)}):")
        for r in wrongs[:3]:
            print(
                f"  Q{r.get('number')}: your answer '{r.get('student_answer')}' "
                f"-> correct '{r.get('correct_answer')}'\n"
                f"      {r.get('explanation','')}"
            )


async def run_writing() -> dict:
    print_header("1/4  WRITING (Task 2)")
    t0 = time.perf_counter()
    result = await writing_examiner.evaluate("task2", WRITING_PROMPT, WRITING_ESSAY)
    print(f"Elapsed: {time.perf_counter()-t0:.1f}s")
    print_examiner_suggestions(result)
    return result


async def run_speaking() -> dict:
    print_header("2/4  SPEAKING (Part 2)")
    t0 = time.perf_counter()
    result = await speaking_examiner.evaluate("part2", SPEAKING_QUESTION, SPEAKING_TRANSCRIPT)
    print(f"Elapsed: {time.perf_counter()-t0:.1f}s")
    print_examiner_suggestions(result)
    return result


async def run_reading() -> dict:
    print_header("3/4  READING")
    t0 = time.perf_counter()
    practice = await reading_trainer.create_practice(
        question_types=["true_false_notgiven", "sentence_completion"],
        difficulty="band 6-7",
        topic="urban gardening",
    )
    print(f"Generated: '{practice.get('title')}' with {len(practice.get('questions', []))} "
          f"questions in {time.perf_counter()-t0:.1f}s")
    answers = simulate_answers(practice.get("answer_key", {}), correct_ratio=0.5)
    t1 = time.perf_counter()
    result = await reading_trainer.check_answers(practice, answers)
    print(f"Graded in {time.perf_counter()-t1:.1f}s")
    print_checker_suggestions(result)
    return result


async def run_listening() -> dict:
    print_header("4/4  LISTENING")
    t0 = time.perf_counter()
    practice = await listening_trainer.create_practice(
        question_types=["form_completion", "multiple_choice"],
        difficulty="band 6",
        topic="library membership registration",
    )
    print(f"Generated: '{practice.get('title')}' with {len(practice.get('questions', []))} "
          f"questions in {time.perf_counter()-t0:.1f}s")
    answers = simulate_answers(practice.get("answer_key", {}), correct_ratio=0.5)
    t1 = time.perf_counter()
    result = await listening_trainer.check_answers(practice, answers)
    print(f"Graded in {time.perf_counter()-t1:.1f}s")
    print_checker_suggestions(result)
    return result


def build_summary(writing: dict, speaking: dict, reading: dict, listening: dict) -> str:
    today = date.today().isoformat()
    lines = ["Target band: 7.5"]
    lines.append(
        f"Writing task2 ({today}): band {writing.get('band_score')}, "
        f"{writing.get('word_count')} words, weaknesses: "
        + ", ".join((writing.get('weaknesses') or [])[:3])
    )
    lines.append(
        f"Speaking part2 ({today}): band {speaking.get('band_score')}, "
        "weaknesses: "
        + ", ".join((speaking.get('weaknesses') or [])[:3])
    )
    wrong_r = [
        f"Q{r.get('number')}: {(r.get('explanation') or '')[:120]}"
        for r in reading.get("results", [])
        if not r.get("correct")
    ][:3]
    lines.append(
        f"Reading practice ({today}): {reading.get('score')}/{reading.get('total')} "
        f"(band est. {reading.get('band_estimate')}). "
        + ("Missed: " + " | ".join(wrong_r) if wrong_r else "All correct.")
    )
    wrong_l = [
        f"Q{r.get('number')}: {(r.get('explanation') or '')[:120]}"
        for r in listening.get("results", [])
        if not r.get("correct")
    ][:3]
    lines.append(
        f"Listening practice ({today}): {listening.get('score')}/{listening.get('total')} "
        f"(band est. {listening.get('band_estimate')}). "
        + ("Missed: " + " | ".join(wrong_l) if wrong_l else "All correct.")
    )
    return "\n".join(lines)


async def run_study_plan(summary: str) -> None:
    print_header("5/5  STUDY PLAN (RAG-grounded)")
    print("Summary fed to the coach:")
    for line in summary.splitlines():
        print(f"  {line}")
    t0 = time.perf_counter()
    context = retrieve_context(summary, top_k=8)
    print(f"\nRetrieved KB context in {time.perf_counter()-t0:.1f}s "
          f"({len(context.splitlines())} lines)")
    t1 = time.perf_counter()
    result = await get_llm_client().complete_json(
        FEEDBACK_SYSTEM.format(context=context or "No reference material retrieved."),
        [{"role": "user", "content": f"Student performance summary:\n{summary}"}],
        required_keys=("summary", "priorities", "study_plan"),
    )
    print(f"LLM elapsed: {time.perf_counter()-t1:.1f}s\n")
    payload = json.dumps(result, indent=2, ensure_ascii=False)
    with open("tools/mock_study_plan_out.json", "w", encoding="utf-8") as f:
        f.write(payload)
    print(payload)


async def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    total = time.perf_counter()
    w = await run_writing()
    s = await run_speaking()
    r = await run_reading()
    l = await run_listening()
    summary = build_summary(w, s, r, l)
    await run_study_plan(summary)
    print(f"\nAll five stages done in {time.perf_counter()-total:.1f}s.")


if __name__ == "__main__":
    asyncio.run(main())
