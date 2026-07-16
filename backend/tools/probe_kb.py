"""Ad-hoc retrieval probe. Usage: python -m tools.probe_kb "query text" [top_k]"""

import sys

from app.rag.store import get_vector_store


def main() -> None:
    query = sys.argv[1] if len(sys.argv) > 1 else "true false not given migration"
    top_k = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    results = get_vector_store().search(query, top_k=top_k)
    print(f"Query: {query!r}")
    print(f"Returned {len(results)} hits (top_k={top_k})\n")

    for i, r in enumerate(results, start=1):
        score = r.get("score")
        score_str = f"{score:.3f}" if isinstance(score, float) else str(score)
        src = r.get("source", "?")
        qtype = r.get("question_type", "")
        book = r.get("book_id", "")
        text = (r.get("text") or "").strip().replace("\n", " ")
        snippet = text[:350] + ("..." if len(text) > 350 else "")
        print(f"[{i}] score={score_str} book={book} src={src} type={qtype}")
        print(f"    {snippet}\n")


if __name__ == "__main__":
    main()
