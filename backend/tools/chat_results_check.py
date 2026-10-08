"""Does the tutor explain a student's own exam correctly?

A fresh student sits a full mock exam and makes the mistakes real candidates
make: times in the wrong form, misspellings, True and Not Given swapped, blank
answers, a thin Task 1 and a weak Task 2, short speaking answers. Then they
ask the tutor about it the way students do, typos included. Afterwards they
do a listening practice set and ask about "my recent exam" again, which must
now mean the practice set.

Every reply is checked against what was actually marked: the question numbers
it calls wrong must be wrong, the scores it quotes must exist, and a question
asked about by number must come back with its correct answer. The replies are
saved for reading, because no assertion can judge whether advice is good.

Runs in-process against the configured database and the real hosted model.
Stop any local uvicorn first: the embedded vector store allows one process.

Usage: PYTHONIOENCODING=utf-8 python tools/chat_results_check.py
"""

from __future__ import annotations

import json
import re
import sys
import time
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import GeneratedQuestion, MockExam  # noqa: E402

OUT = Path(__file__).resolve().parent / "_chat_results_check.md"

TFNG_SWAP = {"TRUE": "NOT GIVEN", "FALSE": "NOT GIVEN", "NOT GIVEN": "FALSE", "YES": "NOT GIVEN", "NO": "NOT GIVEN"}


def flawed(answer: str, n: int) -> str:
    """A student's answer to question n: right, blank, or wrong the usual way."""
    a = str(answer).strip()
    if n % 4 == 0:
        return ""  # ran out of time
    if n % 4 != 1:
        return a
    if a.upper() in TFNG_SWAP:
        return TFNG_SWAP[a.upper()]
    if re.fullmatch(r"[A-Ia-i]", a):
        return "C" if a.upper() != "C" else "B"
    if re.fullmatch(r"\d{1,2}:\d{2}", a):
        return a.split(":")[0] + " o'clock"  # time in the wrong form
    if re.search(r"\d", a):
        return re.sub(r"\d", lambda m: str((int(m.group()) + 1) % 10), a, count=1)
    if len(a) > 4:
        return a[:2] + a[3:]  # a dropped letter
    return a + "s"


def answer_sheet(paper: dict) -> tuple[dict[str, str], dict[str, str]]:
    key: dict[str, str] = {}
    for block in paper.get("parts") or paper.get("passages") or [paper]:
        key.update({str(k): str(v) for k, v in (block.get("answer_key") or {}).items()})
    return key, {n: flawed(a, int(n)) for n, a in key.items()}


TASK1 = (
    "The chart show the information about different things. In first year the number is high "
    "and then it go down. The second one is more bigger than first one. Overall the numbers "
    "changes a lot and some are increase and some are decrease in the period. In conclusion "
    "the chart is showing many changes and it is very interesting for see."
)
TASK2 = (
    "Nowadays technology is very important in our life and many people thinks that it make "
    "life more easy. In this essay I will discuss about this topic. Firstly, technology help "
    "people for communicate with family who live in abroad, for example my uncle live in "
    "London and we talk every day by video call. Secondly, online shopping is save time "
    "because people dont need to go market. However some people says technology is bad "
    "because children play games all day and they are not study. Also too much using of "
    "phone is harmful for eyes and health. In my opinion technology have more advantage than "
    "disadvantage, but goverment should make rules for children. In conclusion, technology "
    "is good if we use it in correct way and not too much. Everyone should be careful about "
    "it and use it for learning and working not only for entertainment and fun things."
)
SPEAKING = {
    "part1": "Yes I live in Dhaka with my family. It is flat. I like it because it is near my university. The area is very busy.",
    "part2": (
        "Okay so I want to talk about, um, a teacher who helped me. His name was Mr Rahman and "
        "he teached us English in school. He was very kind and he always, uh, give us extra "
        "time after the class. I remember once I was fail in exam and he say me not to worry. "
        "He help me for improve my writing. Because of him I start reading English books. I "
        "think he is the best teacher in my life."
    ),
    "part3": "I think teachers is important. Because they teach. Technology also can help but teacher is better.",
}

# Features the tutor invented in the first run; Oratio has none of them.
INVENTED_FEATURES = [r"grammar deck", r"\bquiz", r"model answers? (library|section|guide)",
                     r"structure guide", r"video lesson", r"writing only", r"academic word list"]

QUESTIONS = [
    ("main", "check the recent exam and tell me what mistake I made, how I solve them and how to learn those specific things"),
    ("main", "explain more about my listening mistakes"),
    ("main", "why my reading question {reading_wrong} is wrong?"),
    ("typo", "wat my band in writng task 2 n how i get 7??"),
    ("plan", "which section i am weakest? make me 7 day plan from my exam"),
    ("blank", "i left some answer empty, is that bad? what should i do"),
    ("speak", "how was my speaking, what i do wrong"),
]


def main() -> int:
    failures: list[str] = []
    report: list[str] = ["# Tutor vs the student's own exam\n"]
    c = TestClient(app)
    email = f"chatcheck-{uuid.uuid4().hex[:8]}@gmail.com"
    pw = "chatcheck-123"
    assert c.post("/auth/register", json={"email": email, "password": pw, "accept_terms": True,
                                          "target_band": 7.0, "full_name": "Chat Check"}).status_code == 201
    c.headers["Authorization"] = "Bearer " + c.post(
        "/auth/login", data={"username": email, "password": pw}).json()["access_token"]

    # --- 1. sit the mock exam ------------------------------------------------
    t = time.time()
    r = c.post("/mock-exam/generate", timeout=600)
    assert r.status_code == 200, r.text[:300]
    exam_id = r.json()["id"]
    with SessionLocal() as db:
        paper = db.get(MockExam, exam_id).exam
    _, listening = answer_sheet(paper["listening"])
    _, reading = answer_sheet(paper["reading"])
    print(f"[exam] generated #{exam_id} in {time.time() - t:.0f}s: "
          f"{len(listening)} listening, {len(reading)} reading questions")
    t = time.time()
    r = c.post(f"/mock-exam/{exam_id}/submit", json={
        "listening_answers": listening, "reading_answers": reading,
        "essays": {"task1": TASK1, "task2": TASK2}, "speaking_transcripts": SPEAKING,
    }, timeout=900)
    assert r.status_code == 200, r.text[:300]
    with SessionLocal() as db:
        scored = db.get(MockExam, exam_id)
        results, overall = scored.results, scored.overall_band
    wrong = {
        sec: {str(x["number"]): x for x in results[sec]["results"] if not x.get("correct")}
        for sec in ("listening", "reading")
    }
    right = {
        sec: {str(x["number"]) for x in results[sec]["results"] if x.get("correct")}
        for sec in ("listening", "reading")
    }
    bands = {overall, results["listening"]["band_estimate"], results["reading"]["band_estimate"]}
    bands |= {p.get("band_score") for p in results["writing"].values()}
    bands |= {p.get("band_score") for p in results["speaking"].values()}
    bands |= set((results.get("section_bands") or {}).values())
    print(f"[exam] scored in {time.time() - t:.0f}s: overall {overall}, "
          f"listening {results['listening']['score']}/{results['listening']['total']}, "
          f"reading {results['reading']['score']}/{results['reading']['total']}, "
          f"writing {[p.get('band_score') for p in results['writing'].values()]}, "
          f"speaking {[p.get('band_score') for p in results['speaking'].values()]}")
    report.append(f"Mock exam #{exam_id}: overall {overall}; bands {sorted(b for b in bands if b is not None)}\n")

    reading_wrong = next(iter(n for n, x in wrong["reading"].items() if x.get("student_answer")), next(iter(wrong["reading"])))

    def ask(session: dict, message: str) -> str:
        t0 = time.time()
        body = {"message": message, "session_id": session.get("id")}
        r = c.post("/chat", json=body, timeout=300)
        if r.status_code != 200:
            failures.append(f"chat {message[:40]!r} -> {r.status_code} {r.text[:120]}")
            return ""
        session["id"] = r.json()["session_id"]
        reply = r.json()["reply"]
        print(f"  [{time.time() - t0:4.0f}s] {message[:60]!r} -> {len(reply)} chars")
        report.append(f"\n## Student: {message}\n\n{reply}\n")
        return reply

    def check_numbers(label: str, reply: str, section: str | None = None) -> None:
        """Question numbers called wrong must be wrong; quoted bands must exist."""
        allowed = {f"{b:g}" for b in bands if b is not None} | {f"{b:.1f}" for b in bands if b is not None}
        allowed |= {"7", "7.0", "7.5", "8", "8.0", "6.5", "9", "9.0"}  # targets and goals
        # Only claims about THEIR result; "Band 0 is for a memorised essay" is a fact.
        for m in re.finditer(r"[Yy]our[^.\n|]{0,40}?[Bb]and(?: score)?(?: of| was| is)?\s*\**\s*(\d(?:\.\d+)?)", reply):
            if m.group(1) not in allowed:
                failures.append(f"{label}: quotes band {m.group(1)} which is not in the record")
        for fake in INVENTED_FEATURES:
            if re.search(fake, reply, re.I):
                failures.append(f"{label}: sends the student to a feature Oratio lacks: {fake!r}")
        if section:
            for n in set(re.findall(r"\bQ(?:uestion)?\s*(\d{1,2})\b", reply)):
                if n in right[section] and n not in wrong[section]:
                    ctx = reply[max(0, reply.find(n) - 80): reply.find(n) + 80]
                    if re.search(r"wrong|incorrect|mistake|missed", ctx, re.I):
                        failures.append(f"{label}: calls {section} Q{n} wrong but it was right")

    # --- 2. ask about it ------------------------------------------------------
    print("[chat] about the mock exam")
    sessions: dict[str, dict] = {}
    replies: dict[str, str] = {}
    for key, template in QUESTIONS:
        msg = template.format(reading_wrong=reading_wrong)
        reply = ask(sessions.setdefault(key, {}), msg)
        replies[msg] = reply
        check_numbers(msg[:30], reply)

    main_reply = replies[QUESTIONS[0][1]]
    if f"{overall:g}" not in main_reply and f"{overall:.1f}" not in main_reply:
        failures.append(f"main answer never states the overall band {overall}")
    # "Q4", "Question 4", or a table row that starts with the number.
    named = set(re.findall(r"\bQ(?:uestions?)?\s*(\d{1,2})", main_reply))
    named |= set(re.findall(r"^\|\s*\**(\d{1,2})\b", main_reply, re.M))
    all_wrong = set(wrong["listening"]) | set(wrong["reading"])
    if len(named & all_wrong) < min(3, len(all_wrong)):
        failures.append(f"main answer names too few of the wrong questions {sorted(all_wrong)}: {sorted(named)}")
    check_numbers("listening follow-up", replies[QUESTIONS[1][1]], "listening")
    why = replies[QUESTIONS[2][1].format(reading_wrong=reading_wrong)]
    correct = str(wrong["reading"][reading_wrong]["correct_answer"])
    if correct.lower()[:25] not in why.lower():
        failures.append(f"'why Q{reading_wrong}' never gives the correct answer {correct!r}")
    t2 = results["writing"]["task2"].get("band_score")
    if t2 is not None and f"{t2:g}" not in replies[QUESTIONS[3][1]] and f"{t2:.1f}" not in replies[QUESTIONS[3][1]]:
        failures.append(f"typo'd writing question never states the Task 2 band {t2}")

    # --- 3. a newer practice set must become "the recent exam" ---------------
    print("[practice] listening set after the exam")
    r = c.post("/listening/practice", json={}, timeout=600)
    assert r.status_code == 200, r.text[:300]
    pid = r.json().get("practice_id") or r.json().get("id")
    with SessionLocal() as db:
        practice = db.get(GeneratedQuestion, pid).payload
    _, sheet = answer_sheet(practice)
    r = c.post("/listening/check", json={"practice_id": pid, "answers": sheet}, timeout=300)
    assert r.status_code == 200, r.text[:300]
    title = practice.get("title") or ""
    print(f"[practice] {title!r}: {r.json()['score']}/{r.json()['total']}")
    reply = ask({}, "check my recent exam")
    # Both were sat today, so covering either is defensible; ignoring the
    # newer one is not.
    if "practice" not in reply.lower() and title.lower()[:20] not in reply.lower():
        failures.append("'recent exam' never mentions the newer listening set done the same day")
    check_numbers("recent after practice", reply)

    # --- 4. clean up ----------------------------------------------------------
    c.request("DELETE", "/auth/me", json={"password": pw})
    OUT.write_text("\n".join(report), encoding="utf-8")
    print(f"\nreplies saved to {OUT}")
    print("FAIL" if failures else "PASS", *failures, sep="\n  - ")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
