"""Knowledge-base endpoints (vector store mocked; PDF path uses a real tiny PDF)."""

import pytest


def test_status_reports_document_count(client, auth_headers):
    resp = client.get("/knowledge/status", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"documents": 1}


def test_status_requires_auth(client):
    assert client.get("/knowledge/status").status_code == 401


def test_ingest_rejects_non_pdf(client, auth_headers):
    resp = client.post(
        "/knowledge/ingest",
        files={"file": ("notes.txt", b"plain text", "text/plain")},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_ingest_pdf_extracts_and_indexes(client, auth_headers):
    fitz = pytest.importorskip("fitz")

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(
        (72, 72),
        "IELTS reading strategy: skim the passage first, then scan for keywords.",
    )
    pdf_bytes = doc.tobytes()
    doc.close()

    resp = client.post(
        "/knowledge/ingest",
        files={"file": ("strategies.pdf", pdf_bytes, "application/pdf")},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["chunks_indexed"] >= 1


def test_reindex_reseeds_from_markdown(client, auth_headers):
    # MockVectorStore.count() is always 1, which makes seed_knowledge_base()
    # skip seeding; swap in an empty-looking store so reindex really re-ingests.
    from app.rag.store import get_vector_store, set_vector_store
    from tests.conftest import MockVectorStore

    class EmptyCountStore(MockVectorStore):
        def count(self) -> int:
            return 0

    previous = get_vector_store()
    set_vector_store(EmptyCountStore())
    try:
        resp = client.post("/knowledge/reindex", headers=auth_headers)
    finally:
        set_vector_store(previous)
    assert resp.status_code == 200, resp.text
    assert resp.json()["chunks_indexed"] >= 1
