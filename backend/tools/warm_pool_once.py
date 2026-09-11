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

🔊 A note on audio. Whether a warmed listening set carries its recording
depends on whether there is anywhere durable to put it, so this decides for
itself: audio is ON when BLOB_READ_WRITE_TOKEN names a Blob store and OFF when
it does not. Without one, `_warm_audio` would spend ~100s a set writing MP3s
onto the runner's own disk, which is deleted when the job ends -- a cache
nobody can ever read. With one, that ~100s is the wait a student would
otherwise spend staring at a dead player, which is the whole reason this job
exists. Override either way with --with-audio / --no-audio.

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
    ap.add_argument(
        "--with-audio",
        dest="audio",
        action="store_true",
        default=None,
        help="pre-render TTS even with no Blob store (a host with a real disk)",
    )
    ap.add_argument(
        "--no-audio",
        dest="audio",
        action="store_false",
        help="skip TTS and spend the whole budget on scripts",
    )
    args = ap.parse_args()

    from app.config import settings
    from app.services import blob_store

    # See the module docstring: ~100s a set is worth spending only if the
    # result outlives this runner. Turning TTS off is what makes `_warm_audio`
    # short-circuit -- it raises, and the pool already treats that as "the set
    # is still worth keeping".
    audio = blob_store.enabled() if args.audio is None else args.audio
    settings.tts_enabled = audio

    # 🚨 Refuse to generate into a throwaway database.
    #
    # `database_url` defaults to a local SQLite file, so a scheduled run whose
    # DATABASE_URL secret is missing or misspelled does not fail -- it creates
    # an empty SQLite on the runner, reports every bucket as empty, spends the
    # whole budget filling it, and throws it away. Every thirty minutes,
    # forever, against a free model quota, with a green tick on every run. A
    # scheduler must not be able to fail this quietly.
    database_url = settings.database_url.strip()
    if os.environ.get("CI") and (not database_url or database_url.startswith("sqlite")):
        print(
            "\nFAIL: DATABASE_URL is empty or not set, so this would generate into a\n"
            "      throwaway SQLite on the runner and discard the result.\n"
            "      Set the POOL_DATABASE_URL secret on the repository.",
            file=sys.stderr,
        )
        return 2

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

    why = "" if args.audio is not None else (
        " (blob store)" if audio else " (no blob store: BLOB_READ_WRITE_TOKEN unset)"
    )
    print(f"\ntopping up (budget {args.budget_seconds:.0f}s, audio "
          f"{'on' if audio else 'off'}{why})")
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
