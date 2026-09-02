"""A printed summary the model wrote ONE question for.

🔬 `r_summary_r2`, 2026-09-02. The block was perfect — four sentences carrying
`__1__` to `__7__` — and the key held all seven answers, but the questions were
a single item whose text was the whole summary reprinted. The set was refused
on "question numbers and answer_key keys must match exactly", having got
everything right except how many questions a printed block is, and a retry has
to rewrite the passage, the block and the key to say what they already said.

The line holding `__N__` is the line question N asks about, so the split is
deterministic and belongs in code.
"""

from app.agents import listening_trainer as lt
from app.agents import reading_trainer as rt
from app.agents.answerability import (
    split_block_carrier,
    splittable_block_carrier,
)


def _summary_set() -> dict:
    """The refused artifact, trimmed to what the repair reads."""
    return {
        "title": "The story of rubber",
        "passage": "Natural rubber came to Europe with Charles de La Condamine. "
        "In 1839 Charles Goodyear discovered vulcanisation, which gave the "
        "material elasticity and heat resistance, and by the early twentieth "
        "century rubber was essential for automobile tyres. Most rubber is "
        "grown in Southeast Asia today, where disease outbreaks and the rise "
        "of synthetic rubber shape its future.",
        "visual": {
            "kind": "notes",
            "style": "summary",
            "title": "Summary of the passage",
            "sections": [
                {
                    "heading": "",
                    "lines": [
                        "Natural rubber was introduced to Europe in the 18th "
                        "century by __1__.",
                        "The breakthrough came in __2__ when Charles Goodyear "
                        "discovered __3__.",
                        "By the early 20th century rubber became essential "
                        "for __4__.",
                        "Today most rubber is produced in __5__, but concerns "
                        "over __6__ and the rise of __7__ shape its future.",
                    ],
                }
            ],
        },
        "questions": [
            {
                "number": 1,
                "type": "summary_completion",
                "question": (
                    "NO MORE THAN THREE WORDS. Complete the summary below.\n"
                    "Natural rubber was introduced to Europe in the 18th "
                    "century by __1__.\nThe breakthrough came in __2__ when "
                    "Charles Goodyear discovered __3__.\nBy the early 20th "
                    "century rubber became essential for __4__.\nToday most "
                    "rubber is produced in __5__, but concerns over __6__ and "
                    "the rise of __7__ shape its future."
                ),
                "options": None,
                "word_limit": 3,
            }
        ],
        "answer_key": {
            "1": "Charles de La Condamine",
            "2": "1839",
            "3": "vulcanisation",
            "4": "automobile tyres",
            "5": "Southeast Asia",
            "6": "disease outbreaks",
            "7": "synthetic rubber",
        },
    }


def test_every_gap_of_the_block_gets_a_question():
    r = _summary_set()
    assert split_block_carrier(r) == ["1", "2", "3", "4", "5", "6", "7"]
    assert [q["number"] for q in r["questions"]] == [1, 2, 3, 4, 5, 6, 7]
    # The carrier is replaced, not kept beside them: two questions numbered 1
    # is the fault this repair exists to remove.
    assert len(r["questions"]) == 7


def test_each_question_asks_about_its_own_line():
    r = _summary_set()
    split_block_carrier(r)
    by_number = {q["number"]: q["question"] for q in r["questions"]}
    assert "introduced to Europe" in by_number[1]
    assert "Goodyear" in by_number[3]
    assert "concerns over" in by_number[6]
    # One line, not the whole block: the student reads the summary once, in the
    # figure, and the question restates the sentence it asks about.
    assert "introduced to Europe" not in by_number[6]


def test_the_gap_asked_about_is_the_open_one():
    r = _summary_set()
    split_block_carrier(r)
    by_number = {q["number"]: q["question"] for q in r["questions"]}
    # Gaps 2 and 3 share a sentence, so each question has to say which blank it
    # wants. Its own prints open; the other prints the way the block prints it.
    assert "came in ______ when" in by_number[2]
    assert "2 ............" in by_number[3]
    assert "discovered ______" in by_number[3]
    assert "__2__" not in by_number[3]


def test_the_rubric_survives_the_split():
    r = _summary_set()
    split_block_carrier(r)
    for q in r["questions"]:
        assert q["question"].startswith("NO MORE THAN THREE WORDS.")
        assert q["type"] == "summary_completion"
        assert q["word_limit"] == 3


def test_the_split_set_passes_the_gate_that_refused_it():
    r = _summary_set()
    assert rt.validate_practice(r) == (
        "question numbers and answer_key keys must match exactly"
    )
    split_block_carrier(r)
    assert rt.validate_practice(r) is None


def _listening_set() -> dict:
    """The same fault in a Listening part: a block, and one question for it.

    Built from the reading fixture minus its passage, because a Listening set
    carrying one is refused for that alone — the sections do not share a
    contract.
    """
    r = {k: v for k, v in _summary_set().items() if k != "passage"}
    # Long enough to clear the script floor, which is judged on the way in.
    r["audio_script"] = " ".join(["rubber"] * 700)
    return r


def test_the_carrier_costs_no_retry_on_the_way_in():
    """The hook splits before it judges, so the reply is accepted rather than
    sent back. Judged first, this set dies holding a perfect block — and its
    retry has to write the passage, the block and the key again."""
    assert rt._judge_reply(_summary_set()) is None
    assert lt._judge_reply(_listening_set()) is None


def test_the_split_reaches_the_caller():
    """`complete_json` judges the same dict it hands back, which is the whole
    reason the repair can live in the hook."""
    r = _summary_set()
    rt._judge_reply(r)
    assert [q["number"] for q in r["questions"]] == [1, 2, 3, 4, 5, 6, 7]


def test_the_full_test_part_is_split_before_its_questions_are_counted():
    """A part written as one carrier has ONE question where the paper needs
    ten, so the count rule refuses it too — after the split it is judged on the
    ten it actually asks."""
    r = _listening_set()
    # Judged as it arrives, the carrier never reaches the count at all.
    assert lt._validate_full_test_part(r) == (
        "question numbers and answer_key keys must match exactly"
    )
    # Split first, it is judged on the seven questions it really asks — still
    # short of the paper's ten, and now short for a reason a retry can act on.
    assert lt._judge_full_test_reply(r) == (
        "a full-test part needs exactly 10 questions, not 7"
    )


def test_a_real_mismatch_is_still_refused_on_the_way_in():
    """The hook repairs one shape; it does not stop judging. A key with a
    number no question asks and no block gap to explain it is broken either
    way."""
    r = _summary_set()
    split_block_carrier(r)
    r["answer_key"]["8"] = "latex"
    assert rt._judge_reply(r) == (
        "question numbers and answer_key keys must match exactly"
    )


def test_a_gap_with_no_answer_is_left_alone():
    """All of them or none. A partial split spends the one question holding the
    context and still fails the gate it was trying to pass."""
    r = _summary_set()
    del r["answer_key"]["7"]
    assert splittable_block_carrier(r) is False
    assert split_block_carrier(r) == []
    assert len(r["questions"]) == 1


def test_a_bare_cell_is_left_to_the_field_writer():
    """A table cell that is nothing but its gap says nothing the student can
    answer from; naming that column is a model call, not a split."""
    r = _summary_set()
    r["visual"] = {
        "kind": "table",
        "title": "Rubber production",
        "rows": [["Country", "__1__"], ["Year", "__2__"]],
    }
    r["questions"][0]["question"] = "Complete the table: __1__ and __2__"
    r["answer_key"] = {"1": "Malaysia", "2": "1839"}
    assert splittable_block_carrier(r) is False


def test_a_set_with_a_question_per_gap_is_untouched():
    r = _summary_set()
    split_block_carrier(r)
    before = [dict(q) for q in r["questions"]]
    assert split_block_carrier(r) == []
    assert r["questions"] == before
