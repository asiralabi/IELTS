"""Does the tutor explain a student's own speaking test correctly?

A throwaway student sits a full speaking interview with the usual problems
(Part 1 answers too short, a Part 2 talk that drifts off the cue card and
stops early, Part 3 opinions with no reasons), then practises Part 2 once
more, then asks the tutor about it, typos included. Run against a deployment
(default: production); the account is deleted at the end. The replies are
written to _chat_speaking_check.md for reading: whether advice is good is
not something an assertion can judge.

Usage: PYTHONIOENCODING=utf-8 python tools/chat_speaking_check.py [api-url]
"""

from __future__ import annotations

import re
import sys
import time
import uuid
from pathlib import Path

import httpx

API = (sys.argv[1] if len(sys.argv) > 1 else "https://oratio-api.vercel.app").rstrip("/")
OUT = Path(__file__).resolve().parent / "_chat_speaking_check.md"

PART1 = "Yes. I live in Dhaka. It is busy. I like it."
PART2 = (
    "Okay so, um, I want to talk about my phone. It is Samsung. I use it every day for "
    "facebook and youtube. Actually my brother also have same phone, he buy it last year "
    "from Bashundhara city and he is working in a bank, his office is very far. So "
    "yes, phone is useful. That's all."
)
PART3 = "I think technology is good. Old people don't like it. Young people like it more."
PART2_AGAIN = (
    "I want to describe my smartphone, which I bought two years ago. I use it mostly for "
    "study, for example I watch IELTS lessons and I use dictionary app. It is very "
    "helpful because I can learn anywhere, like on the bus. But sometimes I spend too "
    "much time on social media, so I try to control it. Overall I think it is the most "
    "useful thing I have."
)

QUESTIONS = [
    "check my speaking test, what i did wrong and how to fix it",
    "what is my overall speaking band?",
    "is my pronounciation bad?",
    "give me a better answer for my part 2 cue card",
    "how i can talk 2 minute in part 2? i always stop early",
    "which part is my weakest and what i practise first",
]


def question_text(part: dict) -> str:
    q = part.get("question")
    if isinstance(q, str):
        return q
    if isinstance(q, dict):
        return " / ".join(str(v) for v in q.values() if isinstance(v, (str, list)))
    if isinstance(q, list):
        flat = []
        for item in q:
            flat += item.get("questions", []) if isinstance(item, dict) else [str(item)]
        return " / ".join(map(str, flat))
    return str(q)


def main() -> int:
    failures: list[str] = []
    report = ["# Tutor vs the student's own speaking test\n"]
    c = httpx.Client(base_url=API, timeout=320)
    email = f"speakchat-{uuid.uuid4().hex[:8]}@gmail.com"
    pw = "speakchat-123"
    assert c.post("/auth/register", json={"email": email, "password": pw, "accept_terms": True,
                                          "target_band": 7.0}).status_code == 201
    c.headers["Authorization"] = "Bearer " + c.post(
        "/auth/login", data={"username": email, "password": pw}).json()["access_token"]
    try:
        t = time.time()
        test = c.post("/speaking/full-test").json()
        parts = {p["part"]: p for p in test["parts"]}
        print(f"[test] interview served in {time.time() - t:.0f}s")
        body = {
            key: {"question": parts[key].get("question"), "transcript": said}
            for key, said in (("part1", PART1), ("part2", PART2), ("part3", PART3))
        }
        t = time.time()
        r = c.post("/speaking/full-test/submit", json=body)
        assert r.status_code == 200, r.text[:300]
        marked = r.json()
        bands = {k: v.get("band_score") for k, v in marked["parts"].items()}
        overall = marked["overall_band"]
        print(f"[test] marked in {time.time() - t:.0f}s: {bands}, overall {overall}")
        report.append(f"Interview: overall {overall}, parts {bands}\n")
        for key in ("part1", "part2", "part3"):
            report.append(f"- {key} asked: {question_text(parts[key])[:300]}")
            report.append(f"  weaknesses: {marked['parts'][key].get('weaknesses')}")

        # A second go at Part 2, the way a student practises after a test.
        t = time.time()
        r = c.post("/speaking/submit", data={"part": "part2", "question": question_text(parts["part2"]),
                                             "transcript": PART2_AGAIN})
        assert r.status_code == 200, r.text[:300]
        again = r.json().get("band_score")
        print(f"[practice] part 2 again in {time.time() - t:.0f}s: band {again}")
        report.append(f"\nPart 2 practised again afterwards: band {again}\n")

        session: dict = {}
        replies: dict[str, str] = {}
        for q in QUESTIONS:
            t = time.time()
            r = c.post("/chat", json={"message": q, "session_id": session.get("id")})
            if r.status_code != 200:
                failures.append(f"chat {q[:30]!r} -> {r.status_code}")
                continue
            session["id"] = r.json()["session_id"]
            reply = replies[q] = r.json()["reply"]
            print(f"  [{time.time() - t:4.0f}s] {q[:55]!r} -> {len(reply)} chars")
            report.append(f"\n## Student: {q}\n\n{reply}\n")

        allowed = {f"{b:g}" for b in [*bands.values(), overall, again, 7.0] if b is not None}
        allowed |= {f"{float(b):.1f}" for b in allowed}
        for q, reply in replies.items():
            for m in re.finditer(r"[Yy]our[^.\n|]{0,40}?[Bb]and(?: score)?(?: of| was| is)?\s*\**\s*(\d(?:\.\d)?)", reply):
                if m.group(1) not in allowed:
                    failures.append(f"{q[:30]!r}: quotes band {m.group(1)}, not one they were given")
        overall_reply = replies.get(QUESTIONS[1], "")
        if overall is not None and f"{overall:g}" not in overall_reply and f"{overall:.1f}" not in overall_reply:
            failures.append(f"overall-band answer never states {overall}")
        pron = replies.get(QUESTIONS[2], "").lower()
        if not re.search(r"transcript|typed|text|recording|audio|cannot|can't|not (?:able|possible)", pron):
            failures.append("pronunciation answer does not say a transcript cannot show pronunciation")
        if "dhaka" not in replies.get(QUESTIONS[0], "").lower() and "is busy" not in replies.get(QUESTIONS[0], "").lower():
            failures.append("main answer never quotes what the student actually said in Part 1")
    finally:
        c.request("DELETE", "/auth/me", json={"password": pw})
        OUT.write_text("\n".join(report), encoding="utf-8")

    print(f"\nreplies saved to {OUT}")
    print("FAIL" if failures else "PASS", *failures, sep="\n  - ")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
