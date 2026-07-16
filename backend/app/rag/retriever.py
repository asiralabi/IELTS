from functools import lru_cache

from app.rag.store import get_vector_store


def retrieve_context(
    query: str, top_k: int | None = None, source: str | None = None
) -> str:
    # Cache the full formatted context per (store_id, query, top_k, source).
    # Same rationale as store._embed_query: the RAG hot set is small.
    store = get_vector_store()
    return _cached_context(id(store), query, top_k, source)


@lru_cache(maxsize=256)
def _cached_context(
    store_id: int, query: str, top_k: int | None, source: str | None
) -> str:
    results = get_vector_store().search(query, top_k=top_k, source=source)
    if not results:
        return ""
    return "\n\n".join(
        f"[{i}] ({r['source']}) {r['text']}" for i, r in enumerate(results, start=1)
    )
