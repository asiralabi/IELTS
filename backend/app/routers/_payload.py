"""What must never reach the client before a paper is graded.

Each router carried its own idea of which fields give the answers away, and
they disagreed. Reading dropped `answer_key` alone and shipped
`accepted_variants` and `answer_positions` to the browser — the accepted
spellings of every answer and, for the gap-fills, where in the passage each one
sits. Listening dropped all of them. One list is the only way that stays true.
"""

# `blueprint` is not an answer, but it is the exam's design: a student who reads
# it knows the shape of the paper before sitting it.
ANSWER_FIELDS = frozenset(
    {
        "answer_key",
        "accepted_variants",
        "answer_positions",
        "blueprint",
        "answers",
        "explanation",
    }
)


def public(payload: dict) -> dict:
    """One practice/part payload with the answer-bearing fields removed."""
    return {k: v for k, v in payload.items() if k not in ANSWER_FIELDS}


def strip_sections(test: dict, section_key: str) -> dict:
    """A full-test payload with every section's answer-bearing fields removed."""
    return {
        **{k: v for k, v in test.items() if k != section_key},
        section_key: [public(section) for section in test.get(section_key) or []],
    }
