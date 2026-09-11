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


def _missing_secret(settings) -> str | None:
    """The reason this run must not start, phrased as the thing to go fix.

    Returns None when the environment is good enough to generate into. Every
    message names the REPOSITORY SECRET rather than the environment variable,
    because the variable is what the workflow calls it and the secret is what
    a human has to go and set.
    """
    from sqlalchemy.engine import make_url

    in_ci = bool(os.environ.get("CI"))

    url = (settings.database_url or "").strip()
    if not url:
        return """DATABASE_URL is empty, so there is no database to fill.
      The POOL_DATABASE_URL secret is unset, misnamed, or saved with an
      empty value. An unset secret interpolates to "" -- it does not
      leave the variable alone, which is why this is not a DSN problem.
      Prove the value first: python tools/pool_secrets_check.py"""
    if url.startswith("sqlite") and in_ci:
        return """DATABASE_URL is SQLite, so this would generate into a throwaway
      file on the runner and discard every set it paid for.
      Set the POOL_DATABASE_URL secret on the repository."""
    try:
        parsed = make_url(url)
    except Exception as exc:  # noqa: BLE001 -- any parse failure is the same fix
        return f"""DATABASE_URL is not a connection string SQLAlchemy can read
      ({type(exc).__name__}). Check POOL_DATABASE_URL for a truncated
      paste or a stray line break."""

    # A truncated paste still PARSES -- chop this URL anywhere after the scheme
    # and `make_url` is perfectly happy with it. Only opening the connection
    # tells the difference, and one extra connect is nothing next to a run that
    # would otherwise die mid-report with a stack trace.
    if not url.startswith("sqlite"):
        from sqlalchemy import create_engine

        try:
            create_engine(url, connect_args={"connect_timeout": 10}).connect().close()
        except Exception as exc:  # noqa: BLE001 -- the fix is the same either way
            return f"""DATABASE_URL parses but will not connect to {parsed.host}
      ({type(exc).__name__}). Check POOL_DATABASE_URL for a truncated
      paste, a rotated password, or a paused database."""

    if in_ci and not (settings.qdrant_url or "").strip():
        return """QDRANT_URL is empty, so retrieval would fall back to an EMBEDDED
      Qdrant on this runner's own disk -- every set would generate
      ungrounded and look completely normal.
      Set the POOL_QDRANT_URL secret on the repository."""
    if in_ci and not (settings.openai_api_key or "").strip():
        return """OPENAI_API_KEY is empty, so every producer would error after the
      run had already spent its time getting there.
      Set the POOL_OPENAI_API_KEY secret on the repository."""
    return None


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

    # 🚨 Refuse to start on a secret that is not there.
    #
    # A scheduler must not be able to fail quietly, and the three checked here
    # each fail quietly in their own way: an absent database becomes a
    # throwaway SQLite on the runner that gets filled and deleted; an absent
    # QDRANT_URL becomes an EMBEDDED Qdrant on that same disposable disk, so
    # every set generates ungrounded and looks fine; an absent key just errors
    # every producer after the budget has already been spent getting there.
    #
    # 🔬 And the first version of this guard never once fired. It tested
    # `database_url.startswith("sqlite")`, reasoning that a missing secret
    # leaves the default in place. It does not: a workflow that says
    # `DATABASE_URL: ${{ secrets.POOL_DATABASE_URL }}` with that secret unset
    # does not leave the variable unset, it sets it to the EMPTY STRING, and
    # pydantic takes "" over the default. So the run died four frames deep in
    # SQLAlchemy with `Could not parse SQLAlchemy URL from given URL string`,
    # which reads exactly like a malformed connection string and is not one --
    # it cost a round of chasing the DSN format instead of the missing secret.
    # Measured on runs #1-#7, every one of which failed this way.
    if problem := _missing_secret(settings):
        print(f"\nFAIL: {problem}", file=sys.stderr)
        return 2

    # 🚨 Imported AFTER the guard, and that is the whole point. `app.database`
    # calls `create_engine(settings.database_url)` at MODULE IMPORT time, so
    # with an empty DATABASE_URL the import itself raises before any check in
    # this file can speak. The guard used to sit below these lines and could
    # therefore never run on the failure it was written for.
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
