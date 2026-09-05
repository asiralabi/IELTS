"""Copy the embedded Qdrant collection to a managed Qdrant.

The knowledge base is what every generation is grounded on -- the Cambridge
corpus, chunked and embedded. Locally it is a DIRECTORY (`backend/data/qdrant`)
that the embedded client opens single-writer; a serverless platform has no such
directory, so the points have to live in a cluster the function can reach.

🚨 The local store is single-writer: stop anything else holding it (the backend
container included) or this cannot open it.

Reads QDRANT_URL / QDRANT_API_KEY from `.env.deploy`, the environment, or flags.
Vectors are copied as they are -- NOT re-embedded, so the model that produced
them stays the model that answers against them.

    python scripts/push_knowledge_base.py --dry-run
    python scripts/push_knowledge_base.py
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
ENV_FILE = ROOT / ".env.deploy"
LOCAL_PATH = ROOT / "backend" / "data" / "qdrant"
BATCH = 128


def from_env(key: str, explicit: str | None) -> str:
    if explicit:
        return explicit
    if os.environ.get(key):
        return os.environ[key]
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            name, _, value = line.strip().partition("=")
            if name.strip() == key:
                return value.strip().strip('"').strip("'")
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url")
    ap.add_argument("--api-key")
    ap.add_argument("--collection")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from app.config import settings
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qm

    collection = args.collection or settings.qdrant_collection
    if not LOCAL_PATH.exists():
        print(f"! {LOCAL_PATH} not found.")
        return 1

    local = QdrantClient(path=str(LOCAL_PATH))
    try:
        info = local.get_collection(collection)
    except Exception as exc:
        print(f"! local collection {collection!r} unreadable: {str(exc)[:160]}")
        return 1

    params = info.config.params.vectors
    size = params.size if hasattr(params, "size") else None
    distance = params.distance if hasattr(params, "distance") else None
    count = local.count(collection, exact=True).count
    print(f"local  {collection}: {count} points, dim={size}, distance={distance}")

    if args.dry_run:
        print("(dry run — nothing sent)")
        return 0

    url = from_env("QDRANT_URL", args.url)
    api_key = from_env("QDRANT_API_KEY", args.api_key)
    if not url:
        raise SystemExit(f"! No QDRANT_URL. Put it in {ENV_FILE.name} or pass --url.")

    remote = QdrantClient(url=url, api_key=api_key or None, timeout=120)
    print(f"remote {url.split('@')[-1][:60]}")

    existing = [c.name for c in remote.get_collections().collections]
    if collection in existing:
        there = remote.count(collection, exact=True).count
        if there:
            print(f"! remote already holds {there} points in {collection!r}. "
                  "Delete it first if you meant to replace it.")
            return 1
    else:
        remote.create_collection(
            collection,
            vectors_config=qm.VectorParams(size=size, distance=distance),
        )
        print(f"created remote collection {collection!r}")

    sent, offset = 0, None
    while True:
        points, offset = local.scroll(
            collection, limit=BATCH, offset=offset,
            with_payload=True, with_vectors=True,
        )
        if not points:
            break
        remote.upsert(collection, points=[
            qm.PointStruct(id=p.id, vector=p.vector, payload=p.payload)
            for p in points
        ])
        sent += len(points)
        print(f"  {sent}/{count}", end="\r", flush=True)
        if offset is None:
            break

    final = remote.count(collection, exact=True).count
    print(f"\nsent {sent}; remote now holds {final} points.")
    return 0 if final == count else 1


if __name__ == "__main__":
    sys.exit(main())
