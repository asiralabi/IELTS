"""A paragraph LABEL is not a paragraph.

🔬 Live 2026-09-02, in 2 of the 5 reading sets sitting in the warm pool. The
model labelled its paragraphs on their own lines, `_PARAGRAPH_LABEL` did not
match them because it demands punctuation after the letter, so every LINE
became a paragraph. `_rebuild_headings` then re-lettered fourteen of them and
the student was handed:

    A. Paragraph A
    B. The rapid expansion of wind and solar generation has...
    C. Paragraph B

with five heading questions keyed to A, B and C — one of which was the literal
text "Paragraph A". Unanswerable, and it shipped.
"""

from app.agents import reading_trainer as rt

LABELLED = (
    "Paragraph A\n"
    "The rapid expansion of wind and solar generation has highlighted a "
    "fundamental weakness in modern power systems, namely storage.\n\n"
    "Paragraph B\n"
    "One of the oldest and most widely deployed storage methods is "
    "pumped-hydroelectric power, which drives turbines uphill.\n\n"
    "Paragraph C\n"
    "Compressed air energy storage offers another large-scale option for "
    "grids that must ride through a still, dark week.\n"
)


def test_a_bare_label_line_does_not_become_a_paragraph():
    bodies = rt._paragraph_bodies(LABELLED)
    assert len(bodies) == 3
    assert not any(b.lower().startswith("paragraph") for b in bodies)
    assert bodies[0].startswith("The rapid expansion")


def test_the_lettered_form_still_works():
    """74% of the headings corpus letters its paragraphs; that path is the one
    this must not disturb. Three of them, because the label split only wins
    once there are enough to be a block -- `_MIN_HEADINGS_BLOCK`."""
    bodies = rt._paragraph_bodies(
        "A. The first paragraph runs on for a good while about paper.\n\n"
        "B. The second paragraph says something else entirely about ink.\n\n"
        "C. The third returns to paper, and to the mills that made it.\n"
    )
    assert bodies == [
        "The first paragraph runs on for a good while about paper.",
        "The second paragraph says something else entirely about ink.",
        "The third returns to paper, and to the mills that made it.",
    ]


def test_section_and_part_are_labels_too():
    bodies = rt._paragraph_bodies(
        "Section 1\nRivers carried more freight than roads for a thousand years.\n\n"
        "Section 2\nThe railway ended that in the space of two decades flat.\n"
    )
    assert len(bodies) == 2
    assert bodies[0].startswith("Rivers carried")


def test_a_real_paragraph_is_never_mistaken_for_a_label():
    bodies = rt._paragraph_bodies(
        "A paragraph of prose that merely begins with the word paragraph is "
        "still a paragraph and must survive.\n"
    )
    assert len(bodies) == 1
    assert bodies[0].startswith("A paragraph of prose")


def test_a_stub_gets_no_heading_question_even_when_it_arrives_lettered():
    """The already-broken shape: re-lettered, so every other check sees a
    legitimate paragraph. `_rebuild_headings` drops it from the block AND from
    the passage the student reads."""
    import asyncio

    written = {}

    async def headings(letters, bodies):
        written["bodies"] = bodies
        return {letter: f"Heading for {letter}" for letter in letters}

    rt._write_headings = headings
    result = {
        "passage": (
            "A. Paragraph A\n\n"
            "B. The rapid expansion of wind and solar generation has "
            "highlighted a fundamental weakness in modern power systems.\n\n"
            "C. Paragraph B\n\n"
            "D. One of the oldest storage methods is pumped-hydroelectric "
            "power, which drives turbines uphill when demand is low.\n\n"
            "E. Compressed air storage offers another large-scale option for "
            "grids that must ride through a still and windless week.\n\n"
            "F. Flow batteries separate the energy store from the power stage, "
            "which lets each be sized on its own terms entirely.\n\n"
            "G. Thermal storage in molten salt is integral to solar plants "
            "that must go on generating after the sun has set.\n"
        ),
        "questions": [
            {"number": n, "type": "matching_headings",
             "question": f"Choose the correct heading for Paragraph {chr(64+n)}."}
            for n in (1, 2, 3)
        ],
        "answer_key": {"1": "i", "2": "ii", "3": "iii"},
    }
    asyncio.run(rt._rebuild_headings(result))
    assert not any("Paragraph A" == b for b in written["bodies"])
    assert "Paragraph A" not in result["passage"]
    assert "Paragraph B" not in result["passage"]
