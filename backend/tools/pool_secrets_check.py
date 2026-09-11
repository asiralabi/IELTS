"""Prove the five secrets the warm-pool workflow needs are actually right.

`.github/workflows/warm-pool.yml` runs unattended every 30 minutes against a
repository secret it cannot see and you cannot read back. Every way that goes
wrong in this project has gone wrong QUIETLY:

  * a missing DATABASE_URL made the tool generate into a throwaway SQLite on
    the runner and report success -- forever, on a free model quota;
  * an unindexed `source` field made every filtered retrieval fail in
    production while passing the whole local suite;
  * TTS was off by default in `warm_pool_once.py` and the workflow never
    turned it on, so the warmer pre-generated scripts and no sound at all.

None of those failed loudly. So this checks each value by USING it, and says
which one is wrong rather than that something is.

Run it before pasting the secrets into GitHub, reading them from the files
they already live in:

    python tools/pool_secrets_check.py --from-local

Or run it exactly as CI would, against the environment:

    python tools/pool_secrets_check.py

It prints no secret values -- only their source, their length, and what
answered. It generates nothing and writes nothing, except the one small blob
the storage check needs.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent

# secret name -> (file it lives in locally, key inside that file)
LOCAL_SOURCES = {
    "DATABASE_URL": (REPO / ".env.deploy", "DATABASE_URL"),
    "QDRANT_URL": (REPO / ".env.deploy", "QDRANT_URL"),
    "QDRANT_API_KEY": (REPO / ".env.deploy", "QDRANT_API_KEY"),
    "OPENAI_API_KEY": (BACKEND / ".env", "OPENAI_API_KEY"),
    "BLOB_READ_WRITE_TOKEN": (BACKEND / ".env.local", "BLOB_READ_WRITE_TOKEN"),
}

# What each one is called in the workflow, since the names deliberately differ:
# the pool's copies are prefixed so they can point at a staging database
# without touching the API's own environment.
AS_REPO_SECRET = {
    "DATABASE_URL": "POOL_DATABASE_URL",
    "QDRANT_URL": "POOL_QDRANT_URL",
    "QDRANT_API_KEY": "POOL_QDRANT_API_KEY",
    "OPENAI_API_KEY": "POOL_OPENAI_API_KEY",
    "BLOB_READ_WRITE_TOKEN": "BLOB_READ_WRITE_TOKEN",
}

# Not secrets, and duplicated from the workflow on purpose: a model that has
# been retired answers 410 on every call, and this is one of the two places
# that has to change when it happens again.
NON_SECRET = {
    "LLM_PROVIDER": "openai",
    "OPENAI_BASE_URL": "https://integrate.api.nvidia.com/v1",
    "OPENAI_MODEL": "nvidia/nemotron-3-super-120b-a12b",
}


def read_key(path: Path, key: str) -> str | None:
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        name, _, value = line.partition("=")
        if name.strip() == key:
            return value.strip().strip('"').strip("'") or None
    return None


def load(from_local: bool) -> list[str]:
    """Populate os.environ; return the names that could not be found."""
    missing = []
    for var, (path, key) in LOCAL_SOURCES.items():
        if os.environ.get(var):
            print(f"  {var:24s} from the environment ({len(os.environ[var])} chars)")
            continue
        value = read_key(path, key) if from_local else None
        if value:
            os.environ[var] = value
            rel = path.relative_to(REPO) if path.is_relative_to(REPO) else path
            print(f"  {var:24s} from {rel} ({len(value)} chars)")
        else:
            missing.append(var)
    for var, value in NON_SECRET.items():
        os.environ.setdefault(var, value)
    return missing


# --- the checks -------------------------------------------------------------


def check_database() -> bool:
    """Connect, and count the pool the way the warmer itself counts it.

    Deliberately no hand-written SQL: the first version of this asked for
    `pre_generated_practices` and the table is `pre_generated_practice`, which
    looks exactly like a broken database from the outside. Going through the
    app's own model and `count_available` means this cannot be wrong about a
    schema the app is right about.
    """
    url = os.environ["DATABASE_URL"]
    if url.startswith("sqlite"):
        print("FAIL  DATABASE_URL is SQLite. On a runner that is a file that")
        print("      gets deleted, so the run would fill it and throw it away.")
        return False

    from sqlalchemy import create_engine, func, select
    from sqlalchemy.orm import Session

    from app.models import User
    from app.services.practice_pool import BUCKETS, count_available

    engine = create_engine(
        url.replace("postgresql://", "postgresql+psycopg2://", 1), pool_pre_ping=True
    )
    with Session(engine) as db:
        users = db.execute(select(func.count()).select_from(User)).scalar()
        counts = {
            f"{b.section}/{b.question_type or '*'}": count_available(
                db, b.section, b.question_type
            )
            for b in BUCKETS
        }
    host = url.split("@")[-1].split("/")[0]
    print(f"      {host} -- {users} users, {sum(counts.values())} set(s) in the pool")
    empty = [k for k, v in counts.items() if v == 0]
    if empty:
        print(f"      EMPTY buckets: {', '.join(empty)}")
    return True


def check_qdrant() -> bool:
    from app.config import settings

    settings.qdrant_url = os.environ["QDRANT_URL"]
    settings.qdrant_api_key = os.environ["QDRANT_API_KEY"]
    from qdrant_client import QdrantClient

    client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
    name = settings.qdrant_collection
    info = client.get_collection(name)
    indexed = set((info.payload_schema or {}).keys())
    print(f"      {name} -- {info.points_count} points, indexed: {sorted(indexed) or 'none'}")
    if "source" not in indexed:
        print('FAIL  no payload index on "source". A managed Qdrant answers')
        print('      400 "Index required but not found" to every filtered')
        print("      search, and the caller reads that as 'generate without")
        print("      grounding' -- silently. See ensure_collection.")
        return False
    return True


async def check_model() -> bool:
    from app.config import settings

    settings.llm_provider = "openai"
    settings.openai_api_key = os.environ["OPENAI_API_KEY"]
    settings.openai_base_url = os.environ["OPENAI_BASE_URL"]
    settings.openai_model = os.environ["OPENAI_MODEL"]

    from app.llm.client import get_llm_client

    reply = await get_llm_client().complete(
        system="Reply with one word.",
        messages=[{"role": "user", "content": "Say OK."}],
        max_tokens=16,
    )
    print(f"      {settings.openai_model} answered {reply.strip()[:40]!r}")
    return True


async def check_blob() -> bool:
    from app.config import settings
    from app.services import blob_store

    settings.blob_read_write_token = os.environ["BLOB_READ_WRITE_TOKEN"]
    if not blob_store.enabled():
        print("FAIL  the token is malformed -- no store id in field 3.")
        return False
    written = await blob_store.put("probe/pool-secrets-check.txt", b"ok", "text/plain")
    if not written or not await blob_store.head("probe/pool-secrets-check.txt"):
        print("FAIL  could not write and read back a blob.")
        return False
    print(f"      {written.split('//')[1].split('.')[0]} -- put and head OK")
    return True


async def main(from_local: bool) -> int:
    print("values")
    missing = load(from_local)
    if missing:
        print("\nMISSING: " + ", ".join(missing))
        if not from_local:
            print("Pass --from-local to read them from .env.deploy / .env / .env.local.")
        return 1

    checks = [
        ("DATABASE_URL", check_database),
        ("QDRANT_URL + QDRANT_API_KEY", check_qdrant),
        ("OPENAI_API_KEY", check_model),
        ("BLOB_READ_WRITE_TOKEN", check_blob),
    ]
    print("\nchecks")
    bad = []
    for label, fn in checks:
        print(f"  {label}")
        try:
            ok = await fn() if inspect.iscoroutinefunction(fn) else fn()
        except Exception as exc:  # noqa: BLE001 -- the point is to name the culprit
            print(f"FAIL  {type(exc).__name__}: {str(exc)[:200]}")
            ok = False
        if not ok:
            bad.append(label)

    print()
    if bad:
        print("BROKEN: " + ", ".join(bad))
        return 1
    print("OK  all five values work. As repository secrets they are:")
    for var, secret in AS_REPO_SECRET.items():
        rel = LOCAL_SOURCES[var][0]
        rel = rel.relative_to(REPO) if rel.is_relative_to(REPO) else rel
        print(f"      {secret:24s} = {rel}:{LOCAL_SOURCES[var][1]}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--from-local",
        action="store_true",
        help="read any value the environment does not already set from the "
        "gitignored files it lives in locally",
    )
    raise SystemExit(asyncio.run(main(ap.parse_args().from_local)))
