"""Top the warm practice pool up once, then exit. Built for a scheduled job.

The pool's own `PoolWarmer` is a loop that never ends, which is right for a
process that stays alive and wrong for everywhere this app actually runs now:
a Vercel function is frozen the moment it answers a request and killed when it
goes idle, so the loop starts on every cold start, generates against a shared
model quota and is killed mid-set. That is why `PRACTICE_POOL_ENABLED` is off
in production, and why turning it on would not have helped.

This is the shape a scheduler wants instead: check the catalog, fill what is
short, report, exit. Run it from CI on a cron.

    DATABASE_URL=... OPENAI_API_KEY=... python tools/warm_pool_once.py
    python tools/warm_pool_once.py --budget-seconds 900 --max-sets 4
    python tools/warm_pool_once.py --report-only

🔊 A note on audio. A warmed listening set carries its script but NOT its
recording, because `_warm_audio` caches MP3s on local disk keyed by script --
and a CI runner throws that disk away, exactly as a serverless instance does.
Warming it here would burn ~100s a set building a cache nobody can read. So
this runs with TTS off by default and the student still pays synthesis on
first play. Making that wait disappear needs the cache to live somewhere
shared (Blob storage), which is a separate piece of work.

Output is ASCII: the log lands in a CI viewer and in Windows terminals that
still use a legacy codepage, and a report you cannot read is not a report.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _bar(n: int, target: int) -> str:
    full = min(n, target)
    return "[" + "#" * full + "." * max(0, target - full) + "]"


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--budget-seconds",
        type=float,
        default=float(os.environ.get("POOL_BUDGET_SECONDS", 2400)),
        help="wall-clock ceiling for generation (default 2400)",
    )
    ap.add_argument(
        "--max-sets",
        type=int,
        default=int(os.environ.get("POOL_MAX_SETS", 0)) or None,
        help="stop after this many sets (default: as many as the budget allows)",
    )
    ap.add_argument("--report-only", action="store_true", help="show the pool, generate nothing")
    ap.add_argument("--with-audio", action="store_true", help="also pre-render TTS (see module docstring)")
    args = ap.parse_args()

    # Off before the app imports settings, so `_warm_audio` short-circuits on
    # the RuntimeError synthesize_script raises when TTS is disabled -- which
    # the pool already catches and treats as "set is still worth keeping".
    if not args.with_audio:
        os.environ.setdefault("TTS_ENABLED", "false")

    from app.database import SessionLocal
    from app.services.practice_pool import BUCKETS, PoolWarmer, count_available

    def snapshot() -> list[tuple[str, int, int]]:
        rows = []
        with SessionLocal() as db:
            for b in BUCKETS:
                rows.append(
                    (f"{b.section}/{b.question_type or '*'}",
                     count_available(db, b.section, b.question_type),
                     b.target_size)
                )
        return rows

    print("pool before")
    before = snapshot()
    short = 0
    for label, have, target in before:
        gap = max(0, target - have)
        short += gap
        flag = "  <-- EMPTY" if have == 0 else ("  <-- short" if gap else "")
        print(f"  {label:38s} {have}/{target} {_bar(have, target)}{flag}")
    print(f"  {short} set(s) short of target")

    if args.report_only:
        return 0
    if short == 0:
        print("\nnothing to do.")
        return 0

    print(f"\ntopping up (budget {args.budget_seconds:.0f}s, audio "
          f"{'on' if args.with_audio else 'off'})")
    warmer = PoolWarmer()
    report = await warmer.top_up_once(
        budget_s=args.budget_seconds,
        max_sets=args.max_sets,
        on_event=lambda m: print(f"  {m}", flush=True),
    )

    print("\npool after")
    for label, have, target in snapshot():
        flag = "  <-- STILL EMPTY" if have == 0 else ""
        print(f"  {label:38s} {have}/{target} {_bar(have, target)}{flag}")

    print(
        f"\nproduced {report['produced']}, failed {report['failed']}, "
        f"left for next run {report['skipped_budget']}, in {report['elapsed_s']}s"
    )
    # A run that produced nothing while the pool was short is a real failure:
    # it means every producer errored, and a green tick would hide that.
    if report["produced"] == 0 and report["failed"] > 0:
        print("\nFAIL: every producer errored -- pool is unchanged.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
