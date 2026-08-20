"""Hold the warm pool to the validators the code enforces today.

A pool entry is generated once and served much later, so every validator added
after it was written is a rule it never had to pass. Measured on 2026-08-21, 8
of the 18 sets waiting to be served would have been refused by the code as it
now stands — a set with one matching_headings question where three are
required, an answer key breaking the word limit the student is shown, a
question with no text at all.

Reporting is the default. `--retire` stamps `consumed_at` on the offenders
rather than deleting them: the row survives for inspection, `pop` skips it
because it only claims rows whose `consumed_at` is NULL, and the pool worker
tops the bucket back up under current rules. Undo by setting `consumed_at`
back to NULL for the ids it prints.

    python tools/pool_health.py            # report
    python tools/pool_health.py --retire   # report, then take them out of service
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.agents.listening_trainer import validate_part  # noqa: E402
from app.agents.reading_trainer import validate_practice  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import PreGeneratedPractice  # noqa: E402


def practice_sets(payload: object, found: list[dict] | None = None) -> list[dict]:
    """Every question set inside a payload, whichever shape it came in.

    A full test nests one per part or per passage; a single practice is the set
    itself. Both are served to a student, so both are judged.
    """
    found = [] if found is None else found
    if isinstance(payload, dict):
        if isinstance(payload.get("questions"), list) and payload.get("answer_key"):
            found.append(payload)
        for value in payload.values():
            practice_sets(value, found)
    elif isinstance(payload, list):
        for value in payload:
            practice_sets(value, found)
    return found


def first_problem(section: str, payload: object) -> str | None:
    """The complaint the section's own validator would make, if any."""
    check = validate_part if section == "listening" else validate_practice
    for practice in practice_sets(payload):
        try:
            problem = check(practice)
        except Exception as exc:  # a validator raising is itself a refusal
            problem = f"{type(exc).__name__}: {exc}"
        if problem:
            return problem
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retire", action="store_true",
                        help="take the offenders out of service (reversible)")
    args = parser.parse_args()

    with SessionLocal() as db:
        rows = db.execute(
            select(PreGeneratedPractice)
            .where(PreGeneratedPractice.consumed_at.is_(None))
            .order_by(PreGeneratedPractice.id)
        ).scalars().all()

        offenders = []
        for row in rows:
            problem = first_problem(row.section, row.payload)
            if problem:
                offenders.append((row, problem))
                print(f"  id={row.id} [{row.section}] {problem[:140]}")

        print(f"\n{len(offenders)} of {len(rows)} waiting sets would be refused today")
        if not offenders:
            return 0
        if not args.retire:
            print("run again with --retire to take them out of service")
            return 1

        stamp = datetime.now(timezone.utc)
        for row, _ in offenders:
            row.consumed_at = stamp
        db.commit()
        ids = ", ".join(str(row.id) for row, _ in offenders)
        print(f"retired {len(offenders)}: {ids}")
        print(f"undo with: UPDATE pre_generated_practice SET consumed_at = NULL "
              f"WHERE id IN ({ids});")
    return 0


if __name__ == "__main__":
    sys.exit(main())
