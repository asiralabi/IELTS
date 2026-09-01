"""What the exam's figures know, retrieved while the engine draws one.

The passage corpus already grounds the PROSE a set is built from. Nothing
grounded the FIGURE, so every convention the exam follows had to be guessed at,
hard-coded into a prompt by hand, or — as happened — asserted wrongly and left
in place for weeks. `tools/build_figure_knowledge.py` reads the OCR of every
figure page in the books and writes down the conventions; this is the other end
of that pipe.

Grounding, never content. A record says how long a callout runs, where the
blank sits in the sentence, what gets numbered and what gets named. The
subjects it mentions are a sample of what the exam covers, and the caller's
prompt says in so many words not to reuse them — the same bargain the passage
exemplars strike, and the reason a student never sees a Cambridge page.
"""

from __future__ import annotations

from app.agents._marking import norm

SOURCE = "figure-conventions"

# How much of one record reaches the prompt. Three full records ran to 6.3k
# characters, bolted onto a system prompt already thousands long — and a prompt
# the model skims is the fault this whole pipe exists to fix.
_MAX_RECORD_CHARS = 900

# The question type a student asks for -> the figure family the books call it.
# Several types share one family on purpose: a cross-section, a cycle and a
# piece of apparatus are all `diagram` to the exam, and their conventions are
# the same conventions.
FAMILY_BY_TYPE = {
    "diagram_label_completion": "diagram",
    "map_labelling": "plan",
    "flow_chart_completion": "flow_chart",
    "note_completion": "notes",
    "summary_completion": "notes",
    "table_completion": "table",
    "form_completion": "form",
    "picture_choice": "picture_choice",
    "chart_completion": "chart",
}

# What the payload calls it, for callers holding a built figure rather than a
# question type.
FAMILY_BY_KIND = {
    "diagram": "diagram",
    "plan": "plan",
    "map": "map",
    "flow": "flow_chart",
    "notes": "notes",
    "chart": "chart",
    "picture": "picture_choice",
}

# Families that answer for each other. One `map_labelling` request can end up
# as either an outdoor map or a building's floor plan, and the conventions for
# choosing between them live on both sides; a `summary` is a `notes` block set
# as prose. Retrieving only the exact family would hide half the evidence.
ALIASES = {
    "plan": ("plan", "map"),
    "map": ("map", "plan"),
    "notes": ("notes",),
}


# Families whose figure is drawn by a SECOND pass, so the one-pass generator
# must not be given their conventions as well.
#
# The reason is structural, not measured: the second pass exists BECAUSE the
# one-pass prompt is skimmed, so adding 2.1k characters to a diagram block
# already ~9,000 long — inside a prompt that must also produce a passage,
# questions and an answer key — works against the thing that fixed it. The
# conventions still reach the drawing; `_figure_pass` fetches them itself,
# where they are the only thing in the call.
#
# 🔬 The live numbers are consistent with that and do NOT establish it. Three
# gallery rounds of five diagram sets, richness as (forms, joins, callouts with
# context): without the block (4,7,3) (2,4,3) (8,5,3) (6,5,4); with it in the
# main prompt (2,5,3) (3,0,5) (2,0,6); with it gated off again (2,2,3) (5,4,4)
# (3,2,4). Joins are lowest in the middle row, but n=1 per configuration and
# the model is stochastic — do not quote this as a result. If the gating is
# ever questioned, measure it properly with several rounds per arm.
DRAWN_BY_SECOND_PASS = {"diagram"}


def family_for(question_types: list[str] | None) -> str | None:
    """The figure family a request is about, or None if it wants no figure."""
    for raw in question_types or ():
        family = FAMILY_BY_TYPE.get(norm(str(raw)).replace(" ", "_"))
        if family:
            return family
    return None


def family_to_ground(question_types: list[str] | None) -> str | None:
    """The family the ONE-PASS generator should be given conventions for.

    None for a figure a later pass redraws on its own — see
    `DRAWN_BY_SECOND_PASS`.
    """
    family = family_for(question_types)
    return None if family in DRAWN_BY_SECOND_PASS else family


def figure_conventions(
    family: str, module: str = "", subject: str = "", top_k: int = 2
) -> str:
    """Retrieved conventions for one figure family, ready to paste in a prompt.

    Searched, then filtered to the family by hand. Nearest-neighbour alone is
    not enough: asked for "diagram reading termite mound" the store's best
    match was a summary block about archaeology, because the subject words
    dominate the embedding and the corpus holds 148 notes records against 8
    diagrams. The family is in the first line of every record, so it can be
    insisted on rather than hoped for.

    The family's SUMMARY record leads when there is one — it carries the
    measured ranges (blanks per figure, words per item), which is the single
    most useful thing a generator can be told.

    Empty when nothing has been ingested, so every caller degrades to the
    behaviour it had before this existed rather than failing.
    """
    if not family:
        return ""
    query = " ".join(
        p for p in (family.replace("_", " "), module, subject) if p
    ).strip()
    from app.rag.store import get_vector_store

    # Over-fetched, because most of what comes back belongs to another family.
    hits = get_vector_store().search(query, top_k=top_k * 8, source=SOURCE)
    wanted = ALIASES.get(family, (family,))
    summary_tags = tuple(f"FIGURE FAMILY SUMMARY — {f}" for f in wanted)
    tags = tuple(f"— {f} " for f in wanted)

    def first_line(hit: dict) -> str:
        return str(hit.get("text", "")).split("\n", 1)[0]

    summaries = [h for h in hits if str(h.get("text", "")).startswith(summary_tags)]
    if not summaries:
        # Fetched deliberately when the subject query did not surface it. The
        # family summary carries the measured ranges — blanks per figure, words
        # per item — which is the single most useful thing to tell a generator,
        # and it is one record competing with 260 others for the top slots.
        summaries = [
            h
            for h in get_vector_store().search(
                f"FIGURE FAMILY SUMMARY {wanted[0]}", top_k=6, source=SOURCE
            )
            if str(h.get("text", "")).startswith(summary_tags)
        ]
    examples = [
        h
        for h in hits
        if h not in summaries and any(t in first_line(h) for t in tags)
    ]
    chosen = (summaries[:1] + examples)[:top_k]
    if not chosen:
        return ""
    # Trimmed: this is bolted onto a system prompt that already runs to
    # thousands of characters, and the whole reason the figure was being drawn
    # badly is that the model skims a prompt it cannot hold.
    body = "\n\n".join(
        f"[{i}] {str(h['text'])[:_MAX_RECORD_CHARS]}"
        for i, h in enumerate(chosen, start=1)
    )
    return (
        "\nHOW THE EXAM BUILDS THIS FIGURE — measured from real Cambridge "
        "papers. These are CONVENTIONS to follow: how long the items run, "
        "where the blank sits in the sentence, what is numbered and what is "
        "printed plainly, how many blanks a figure carries. The subjects named "
        "are a sample of what the exam covers — do NOT reuse a subject, a "
        "title or any wording from them.\n\n" + body
    )
