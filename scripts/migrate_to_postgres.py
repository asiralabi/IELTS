"""Copy the runtime database from SQLite to a managed Postgres.

`backend/data/ielts.db` is every account, attempt and band score anyone has
earned, plus the 77 parsed Cambridge tests the four modules are grounded on.
A serverless platform has no durable disk, so the file has to become a hosted
database before the app can run there at all.

Reads the target from `DATABASE_URL` (or `--url`). The secret is never printed:
the summary names the host only.

    python scripts/migrate_to_postgres.py            # reads .env.deploy
    python scripts/migrate_to_postgres.py --dry-run  # count rows, write nothing

Rows are copied in dependency order and the id sequences are reset afterwards,
because SERIAL does not know about ids that arrived by explicit INSERT -- skip
that and the first student to register collides with user 1.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

SQLITE = ROOT / "backend" / "data" / "ielts.db"
ENV_FILE = ROOT / ".env.deploy"

# Parents before children: every FK here points at a table listed above it.
# `feedback` is deliberately absent: this script seeds a fresh deployment FROM
# this laptop, and pilot feedback is written on the deployment, not here. Adding
# it would push local test notes into the real inbox and nothing the other way.
ORDER = [
    "users",
    "cambridge_tests",
    "pre_generated_practice",
    "chat_sessions",
    "generated_questions",
    "mock_exams",
    "speaking_submissions",
    "weakness_profiles",
    "writing_submissions",
    "chat_messages",
    "practice_attempts",
]


def target_url(explicit: str | None) -> str:
    if explicit:
        return explicit
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            key, _, value = line.strip().partition("=")
            if key.strip() == "DATABASE_URL":
                return value.strip().strip('"').strip("'")
    raise SystemExit(
        f"! No target. Put DATABASE_URL=... in {ENV_FILE.name}, or pass --url."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not SQLITE.exists():
        print(f"! {SQLITE} not found.")
        return 1

    url = target_url(args.url)
    import sqlalchemy as sa

    engine = sa.create_engine(url)
    print(f"target: {engine.url.host}/{engine.url.database} as {engine.url.username}")

    import sqlite3

    src = sqlite3.connect(f"file:{SQLITE}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row

    # JSON columns arrive from SQLite as TEXT. Postgres will not cast a string
    # into a json column, so they are handed over as raw SQL json literals.
    from sqlalchemy.dialects.postgresql import JSON as PG_JSON  # noqa: F401

    meta = sa.MetaData()
    meta.reflect(bind=engine, only=ORDER)

    total = 0
    with engine.begin() as conn:
        for name in ORDER:
            table = meta.tables[name]
            json_cols = {
                c.name for c in table.columns
                if c.type.__class__.__name__.upper().startswith("JSON")
            }
            rows = [dict(r) for r in src.execute(f'SELECT * FROM "{name}"')]
            if not rows:
                print(f"  {name:24}       0")
                continue
            if args.dry_run:
                print(f"  {name:24} {len(rows):7}  (dry run)")
                total += len(rows)
                continue

            existing = conn.execute(sa.text(f'SELECT COUNT(*) FROM "{name}"')).scalar()
            if existing:
                print(f"  {name:24} {existing:7} already there — skipped")
                continue

            for row in rows:
                for col in json_cols:
                    value = row.get(col)
                    if isinstance(value, (bytes, bytearray)):
                        value = value.decode("utf-8")
                    # 🚨 SQLite hands a JSON column back as TEXT. Passing that
                    # string to a SQLAlchemy JSON column serialises it AGAIN,
                    # so Postgres stores a json STRING containing json rather
                    # than the object -- and every reader downstream gets a str
                    # where it expects a dict. Found live: /cambridge/index died
                    # on `reading.get("passages")` with 'str' has no attribute
                    # 'get'. Decode here so the column holds what it claims to.
                    if isinstance(value, str):
                        try:
                            value = json.loads(value)
                        except ValueError:
                            pass  # not json after all; store it as it came
                    row[col] = value
            conn.execute(table.insert(), rows)
            print(f"  {name:24} {len(rows):7}  copied")
            total += len(rows)

        if not args.dry_run:
            # SERIAL is unaware of ids inserted explicitly. Without this the
            # next INSERT starts at 1 and collides with the rows just copied.
            for name in ORDER:
                conn.execute(sa.text(
                    "SELECT setval(pg_get_serial_sequence(:t, 'id'), "
                    "COALESCE((SELECT MAX(id) FROM \"%s\"), 1))" % name
                ), {"t": name})
            print("\n  id sequences reset to MAX(id)")

    src.close()
    print(f"\n{total} rows {'counted' if args.dry_run else 'copied'}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
