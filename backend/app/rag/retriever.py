import logging
from functools import lru_cache

from app.rag.store import get_vector_store

logger = logging.getLogger(__name__)


def retrieve_context(
    query: str, top_k: int | None = None, source: str | None = None
) -> str:
    # Cache the full formatted context per (store_id, query, top_k, source).
    # Same rationale as store._embed_query: the RAG hot set is small.
    #
    # Grounding is an extra, not a requirement: when the vector store is down
    # (a suspended Qdrant Cloud cluster resets every connection), marking and
    # chat answer from the model alone instead of failing the student's
    # request. Caught out here, not inside the cache, so an outage is never
    # remembered as an empty answer once the store is back.
    try:
        store = get_vector_store()
        return _cached_context(id(store), query, top_k, source)
    except Exception as exc:
        logger.warning("knowledge base unavailable, answering ungrounded: %s", exc)
        return ""


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
