import uuid
from functools import lru_cache
from typing import Any

from app.config import settings


class VectorStore:
    def __init__(self) -> None:
        self._client: Any = None
        self._embedder: Any = None
        self._dim: int | None = None
        self._cached_embed: Any = None

    @property
    def client(self) -> Any:
        if self._client is None:
            from qdrant_client import QdrantClient

            if settings.qdrant_url:
                self._client = QdrantClient(url=settings.qdrant_url)
            else:
                self._client = QdrantClient(path=settings.qdrant_path)
        return self._client

    @property
    def embedder(self) -> Any:
        if self._embedder is None:
            from fastembed import TextEmbedding

            self._embedder = TextEmbedding(model_name=settings.embedding_model)
        return self._embedder

    def _embed(self, texts: list[str]) -> list[list[float]]:
        return [vec.tolist() for vec in self.embedder.embed(texts)]

    def _embed_query(self, query: str) -> list[float]:
        """Cached single-query embedding path.

        Search-time queries are dominated by a handful of hot strings
        (band descriptors, common weakness phrases). fastembed cold-embed
        is ~50ms on CPU; the LRU makes repeat hits ~0ms.
        """
        if self._cached_embed is None:
            # Bind the lru_cache to the instance so cache lookups don't need
            # a hashable self, and swapping the store in tests drops the
            # cache with the instance.
            @lru_cache(maxsize=256)
            def _cached(q: str) -> tuple[float, ...]:
                return tuple(self._embed([q])[0])

            self._cached_embed = _cached
        return list(self._cached_embed(query))

    def _get_dim(self) -> int:
        if self._dim is None:
            self._dim = len(self._embed(["probe"])[0])
        return self._dim

    def warm(self) -> None:
        """Force embedder + client initialisation and prime the cache.

        Called from FastAPI lifespan so the first user request doesn't pay
        the model-load penalty (BGE-small is ~120ms to load).
        """
        _ = self._get_dim()
        # Populate the LRU with a known-hot probe query.
        self._embed_query("probe")

    def ensure_collection(self) -> None:
        from qdrant_client.models import Distance, VectorParams

        if not self.client.collection_exists(settings.qdrant_collection):
            self.client.create_collection(
                collection_name=settings.qdrant_collection,
                vectors_config=VectorParams(size=self._get_dim(), distance=Distance.COSINE),
            )

    def index_chunks(self, chunks: list[dict]) -> int:
        from qdrant_client.models import PointStruct

        if not chunks:
            return 0
        self.ensure_collection()
        vectors = self._embed([c["text"] for c in chunks])
        points = [
            PointStruct(
                id=str(uuid.uuid4()),
                vector=vec,
                payload={"text": c["text"], "source": c["source"], **c.get("metadata", {})},
            )
            for c, vec in zip(chunks, vectors)
        ]
        self.client.upsert(collection_name=settings.qdrant_collection, points=points)
        return len(points)

    def search(
        self, query: str, top_k: int | None = None, source: str | None = None
    ) -> list[dict]:
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        self.ensure_collection()
        query_filter = None
        if source:
            query_filter = Filter(
                must=[FieldCondition(key="source", match=MatchValue(value=source))]
            )
        result = self.client.query_points(
            collection_name=settings.qdrant_collection,
            query=self._embed_query(query),
            limit=top_k if top_k is not None else settings.rag_top_k,
            query_filter=query_filter,
            with_payload=True,
        )
        return [
            {
                "text": p.payload.get("text", ""),
                "source": p.payload.get("source", ""),
                "score": p.score,
            }
            for p in result.points
        ]

    def count(self) -> int:
        if not self.client.collection_exists(settings.qdrant_collection):
            return 0
        return self.client.count(collection_name=settings.qdrant_collection).count

    def clear(self) -> None:
        if self.client.collection_exists(settings.qdrant_collection):
            self.client.delete_collection(collection_name=settings.qdrant_collection)


_store: VectorStore | None = None


def get_vector_store() -> VectorStore:
    global _store
    if _store is None:
        _store = VectorStore()
    return _store


def set_vector_store(store: VectorStore | None) -> None:
    global _store
    _store = store


def warm_embedder() -> None:
    """Load the fastembed model once at process start to hide the cost.

    Called from FastAPI lifespan. No-ops for mock stores (they don't have
    a `warm` method).
    """
    store = get_vector_store()
    warm = getattr(store, "warm", None)
    if callable(warm):
        warm()
