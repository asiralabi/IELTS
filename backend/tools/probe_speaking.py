"""Ad-hoc speaking-examiner probe. Runs one Part 2 evaluation end-to-end."""

import asyncio
import json
import time

from app.agents import speaking_examiner

QUESTION = (
    "Describe a book that you have recently read and enjoyed. You should say: "
    "what the book was about, why you decided to read it, how it made you feel, "
    "and explain why you enjoyed it."
)

TRANSCRIPT = (
    "Um, okay so recently I read a book called Atomic Habits by James Clear. "
    "It's about, uh, how small changes in your daily routine can lead to big "
    "results over time. Basically the author argues that if you improve by one "
    "percent every day, after a year you will be, like, thirty-seven times better. "
    "I decided to read it because a colleague at work kept recommending it, and "
    "I was struggling to stick with my morning exercise routine. I thought, you "
    "know, maybe this book will help me. When I started reading it, I felt "
    "really motivated because the ideas are simple but they make a lot of "
    "sense. For example, he talks about habit stacking, which is when you attach "
    "a new habit to an existing one. I found that quite useful actually. Um, "
    "the reason I enjoyed it was because it doesn't just give you theory, it "
    "gives you practical steps you can take immediately. And, yeah, since "
    "reading it, I've managed to keep up my exercise routine for about three "
    "months now, so I would definitely recommend it to anyone who wants to "
    "build better habits."
)


async def main() -> None:
    t0 = time.perf_counter()
    result = await speaking_examiner.evaluate("part2", QUESTION, TRANSCRIPT)
    dt = time.perf_counter() - t0
    print(f"Elapsed: {dt:.1f}s\n")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
