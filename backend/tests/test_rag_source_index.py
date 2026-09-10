"""A filtered retrieval needs its payload field indexed, or production 400s.

🔬 Found 2026-09-11 by running the pool warmer against the deployed stack:

    400 Index required but not found for "source" of one of the following
        types: [keyword]

An embedded Qdrant filters on any payload field whether it is indexed or not,
so `search(source=...)` passed every test and every local run. The managed
cluster refuses. Reading full tests could therefore never be generated in
production -- the mock exam's reading paper had been falling back to cold
generation since the day the KB moved to Qdrant Cloud, and nothing in the
suite could see it, because the suite runs against the permissive one.

So the rule under test is not "filtering works" -- it did. It is that the
store ASKS for the index, every time it ensures the collection.
"""

import pytest

from app.rag import store as store_mod


class _FakeClient:
    def __init__(self, exists: bool = True, index_raises: bool = False) -> None:
        self.exists = exists
        self.index_raises = index_raises
        self.created_collections: list[str] = []
        self.indexes: list[tuple[str, str, str]] = []

    def collection_exists(self, collection_name):
        return self.exists

    def create_collection(self, collection_name, vectors_config):
        self.created_collections.append(collection_name)
        self.exists = True

    def create_payload_index(self, collection_name, field_name, field_schema):
        if self.index_raises:
            raise RuntimeError("cluster said no")
        self.indexes.append((collection_name, str(field_name), str(field_schema)))


@pytest.fixture
def vs(monkeypatch):
    v = store_mod.VectorStore()
    fake = _FakeClient()
    monkeypatch.setattr(type(v), "client", property(lambda self: fake))
    monkeypatch.setattr(v, "_get_dim", lambda: 8)
    return v, fake


def test_ensuring_the_collection_asks_for_the_source_index(vs):
    v, fake = vs
    v.ensure_collection()
    assert len(fake.indexes) == 1
    _collection, field, schema = fake.indexes[0]
    assert field == "source"
    # keyword, specifically: that is the type the cluster named in its refusal.
    assert "keyword" in schema.lower()


def test_a_brand_new_collection_gets_the_index_too(monkeypatch):
    """The collection and its index are created in the same breath -- a fresh
    deployment must not need a human to remember this."""
    v = store_mod.VectorStore()
    fake = _FakeClient(exists=False)
    monkeypatch.setattr(type(v), "client", property(lambda self: fake))
    monkeypatch.setattr(v, "_get_dim", lambda: 8)

    v.ensure_collection()

    assert fake.created_collections, "collection was not created"
    assert fake.indexes, "a new collection was left without the source index"


def test_it_is_asked_for_once_per_process_not_once_per_search(vs):
    """ensure_collection runs on every search; re-creating the index each time
    would be a round trip per query for nothing."""
    v, fake = vs
    for _ in range(5):
        v.ensure_collection()
    assert len(fake.indexes) == 1


def test_an_index_failure_never_takes_down_search(monkeypatch):
    """An unfiltered query still works, so a cluster that refuses the index
    must not turn every retrieval into an exception."""
    v = store_mod.VectorStore()
    fake = _FakeClient(index_raises=True)
    monkeypatch.setattr(type(v), "client", property(lambda self: fake))
    monkeypatch.setattr(v, "_get_dim", lambda: 8)

    v.ensure_collection()  # must not raise
