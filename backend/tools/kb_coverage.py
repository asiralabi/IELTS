"""Report Cambridge KB coverage: per-source chunk counts vs FULL_CATALOG."""

from __future__ import annotations

from collections import Counter

from app.config import settings
from app.ingest.catalog import FULL_CATALOG
from app.rag.store import get_vector_store


def main() -> None:
    store = get_vector_store()
    total = store.count()
    print(f"Total points: {total}")

    counts: Counter[str] = Counter()
    kinds: Counter[str] = Counter()
    offset = None
    while True:
        pts, offset = store.client.scroll(
            collection_name=settings.qdrant_collection,
            with_payload=True,
            with_vectors=False,
            limit=1000,
            offset=offset,
        )
        for p in pts:
            src = p.payload.get("source", "?")
            counts[src] += 1
            kind = p.payload.get("kind") or p.payload.get("metadata", {}).get("kind", "?")
            kinds[f"{src}|{kind}"] += 1
        if offset is None:
            break

    catalog_ids = {e.book_id: e.book_title for e in FULL_CATALOG}
    print("\n== Per source (top 60) ==")
    for src, n in counts.most_common(60):
        print(f"  {src}: {n}")

    print("\n== Catalog coverage ==")
    for book_id, title in catalog_ids.items():
        n = counts.get(book_id, 0)
        flag = "OK" if n > 0 else "MISSING"
        print(f"  [{flag}] {book_id:16s} {n:5d} chunks  ({title})")

    print("\n== Non-catalog sources ==")
    for src, n in counts.items():
        if src not in catalog_ids:
            print(f"  {src}: {n}")


if __name__ == "__main__":
    main()
