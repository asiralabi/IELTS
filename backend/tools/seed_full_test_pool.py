"""Put a full listening and a full reading paper into the warm pool.

The warmer reaches the full-test buckets only once every cheap bucket is full,
and a paper is seven heavy local generations — over an hour before the mock
exam can serve a real one. This assembles both papers from sets the generator
has already written to disk so the pooled path can be exercised now.

The content is real generator output; what is synthetic is only that the same
set is repeated across parts. That is enough to check numbering, rendering,
submission and marking end to end — it is not a check of content variety.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents._numbering import renumber  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.services import practice_pool  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
LISTENING_SRC = ROOT / "tools" / "_smoke_multitask_listening.json"
READING_SRC = ROOT / "data" / "_e2e" / "reading.json"


def build(source: Path, count: int, kind: str, list_key: str, index_key: str) -> dict:
    practice = json.loads(source.read_text(encoding="utf-8"))
    sections = []
    offset = 0
    for index in range(count):
        section = renumber(copy.deepcopy(practice), offset)
        offset += len(section.get("questions") or [])
        section[index_key] = index + 1
        sections.append(section)
    return {"title": f"Seeded {kind}", "kind": kind, list_key: sections}


def main() -> int:
    papers = [
        ("listening", "parts", build(LISTENING_SRC, 4, "full_listening_test", "parts", "part")),
        (
            "reading",
            "passages",
            build(READING_SRC, 3, "full_reading_test", "passages", "passage_number"),
        ),
    ]
    with SessionLocal() as db:
        for section, list_key, paper in papers:
            practice_pool.insert(db, section, practice_pool.FULL_TEST, paper)
            questions = sum(len(s.get("questions") or []) for s in paper[list_key])
            print(f"seeded {section} full test: {questions} questions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
