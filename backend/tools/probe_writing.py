"""Ad-hoc writing-examiner probe. Runs one Task 2 evaluation end-to-end."""

import asyncio
import json
import time

from app.agents import writing_examiner

PROMPT = (
    "Some people believe that unpaid community service should be a compulsory "
    "part of high school programmes. To what extent do you agree or disagree?"
)

ESSAY = (
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
    "consistently value. My own experience volunteering at a neighbourhood "
    "library taught me more about accountability than any textbook.\n\n"
    "On the other hand, making service compulsory can undermine its purpose if "
    "students perceive it as another chore. Some may go through the motions "
    "just to satisfy a requirement, which reduces the benefit for the "
    "community they are supposed to serve. To avoid this, schools should let "
    "learners choose from a range of causes, integrate reflection into the "
    "curriculum, and cap the required hours so the workload remains "
    "manageable.\n\n"
    "In conclusion, compulsory community service is a worthwhile policy "
    "because it broadens students' horizons and strengthens the community, "
    "provided schools implement it with flexibility and thoughtful guidance."
)


async def main() -> None:
    t0 = time.perf_counter()
    result = await writing_examiner.evaluate("task2", PROMPT, ESSAY)
    dt = time.perf_counter() - t0
    print(f"Elapsed: {dt:.1f}s\n")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
