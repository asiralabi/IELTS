"""matching_headings is built in code, never taken from the model.

Two measurements force this. Asked to *match* the teacher's headings to the
teacher's paragraphs on 8 gold corpus sets, this checkpoint agreed with the key
23/43 times (53%) and got 0/8 sets fully right — so any design that reads a
heading key out of a reply ships a confident wrong answer. Asked to *write* a
set unaided it under-produces instead: 5 of 5 live generations emitted a single
matching_headings question, always keyed `i`, the first option in its own list.

So the model is asked only for the half it can do — a heading per paragraph it
can see — and which paragraph each heading was written for becomes the key. The
tests below are about that invariant, not about the wording of any reply.
"""

import asyncio
import json
import random
import re

import pytest

from app.agents import reading_trainer
from app.agents._marking import resolve_choice
from app.llm.client import LLMClient, get_llm_client, set_llm_client
from app.llm.prompts import HEADINGS_WRITER_SYSTEM

PARAGRAPHS = 8
# Over _MIN_PASSAGE_WORDS, so nothing here depends on the expansion pass.
BODY = "Paper spread along the trade routes and changed how records were kept. " * 12


def _passage(count: int = PARAGRAPHS, lettered: bool = True) -> str:
    return "\n\n".join(
        f"{chr(65 + i)}. Paragraph {chr(65 + i)}. {BODY}" if lettered
        else f"Then came stage {i + 1} of the story. {BODY}"
        for i in range(count)
    )


def _set(passage: str | None = None, **extra) -> dict:
    """The measured live failure: one headings question, keyed `i`."""
    return {
        "title": "The History of Paper",
        "passage": passage if passage is not None else _passage(),
        "questions": [
            {"number": 1, "type": "true_false_notgiven",
             "question": "Paper reached Europe before printing."},
            {"number": 2, "type": "matching_headings",
             "question": "Choose the correct heading for Paragraph A.",
             "options": ["i. A stale option", "ii. Another", "iii. A third",
                         "iv. A fourth", "v. A fifth"]},
            {"number": 3, "type": "multiple_choice", "question": "Which mill came first?",
             "options": ["A. Fabriano", "B. Xativa", "C. Baghdad", "D. Samarkand"]},
        ],
        "answer_key": {"1": "TRUE", "2": "i", "3": "B"},
        **extra,
    }


class HeadingsClient(LLMClient):
    """Answers the set call, then the heading-writing call.

    Each heading names the paragraph it was written for, which is what lets a
    test check the key without knowing the shuffle.
    """

    is_finetune = True

    def __init__(self, reply: dict, headings: dict | None = None) -> None:
        self.reply = reply
        self.headings = headings
        self.writer_turns: list[str] = []

    async def complete(self, system, messages, **kw) -> str:
        raise AssertionError("the passage must not need expanding in these tests")

    async def complete_json(self, system, messages, **kw) -> dict:
        turn = messages[-1]["content"]
        if system is HEADINGS_WRITER_SYSTEM:
            self.writer_turns.append(turn)
            letters = re.findall(r"(?m)^([A-Z])\. ", turn)
            reply = self.headings or {
                "headings": {x: f"What paragraph {x} is about" for x in letters}}
        else:
            reply = json.loads(json.dumps(self.reply))
        # The real complete_json runs the hook and retries once on a complaint.
        # This one has no second answer to give, so a complaint goes straight to
        # the caller — the state the retry would have reached anyway.
        problem = (kw.get("validate") or (lambda _: None))(reply)
        if problem:
            raise ValueError(problem)
        return reply


@pytest.fixture()
def practice():
    previous = get_llm_client()

    def _run(reply: dict, headings: dict | None = None) -> tuple[dict, HeadingsClient]:
        client = HeadingsClient(reply, headings)
        set_llm_client(client)
        # Fixed only so a failure names one shuffle instead of a new one each run.
        random.seed(11)
        return asyncio.run(reading_trainer.create_practice(topic="paper")), client

    yield _run
    set_llm_client(previous)


def _block(result: dict) -> list[dict]:
    return [q for q in result["questions"] if q["type"] == "matching_headings"]


def test_the_key_records_which_paragraph_each_heading_was_written_for(practice):
    """The invariant the whole design exists for. Each answer numeral must label
    the heading written for that question's own paragraph — not a heading that
    merely looks plausible, which is the 53% case."""
    result, _ = practice(_set())
    block = _block(result)
    assert len(block) >= reading_trainer._MIN_HEADINGS_BLOCK

    for q in block:
        letter = q["question"].split("Paragraph ")[1].rstrip(".")
        keyed = result["answer_key"][str(q["number"])]
        assert keyed in q["options"]
        assert keyed.endswith(f"What paragraph {letter} is about")


def test_every_paragraph_gets_a_different_heading(practice):
    """A bijection is a global constraint, and the checkpoint reliably breaks it
    — two live attempts in a row keyed `4,5,6,8` then `4,5,7,8`, reusing `i, ii`
    each time. Assigning numerals in code makes a clash unreachable."""
    result, _ = practice(_set())
    block = _block(result)
    answers = [result["answer_key"][str(q["number"])] for q in block]

    assert len(set(answers)) == len(answers)
    # More headings than paragraphs matched, so the last student to choose still
    # has a wrong option available.
    assert len(block[0]["options"]) == len(block) + reading_trainer._HEADINGS_DISTRACTORS


def test_the_letter_a_student_clicks_marks_correct_without_an_evaluator(practice):
    """question-list.tsx labels options A, B, C by position and submits that
    letter, and resolve_choice turns it back into the option text. Keyed the
    bare numeral the system prompt asks for, every headings question would miss
    the exact-match branch and be sent to the LLM to judge "iii. Soil erosion"
    against "iii" — a paid call per question, on a comparison it can lose."""
    result, _ = practice(_set())

    for q in _block(result):
        official = result["answer_key"][str(q["number"])]
        clicked = chr(65 + q["options"].index(official))
        assert resolve_choice(q, clicked) == resolve_choice(q, official)


def test_the_options_the_model_wrote_are_thrown_away(practice):
    """Rebuilding only broken-looking blocks would leave the silent failure in
    place: a block can satisfy every structural rule and still be keyed wrong,
    and nothing downstream can tell. So the model's block never survives."""
    result, _ = practice(_set())

    offered = " ".join(o for q in _block(result) for o in q["options"])
    assert "stale option" not in offered


def test_the_model_is_asked_to_write_headings_never_to_match_them(practice):
    """The distinction is the finding: writing is the half it can do. If the
    stale list reached this turn the call would be a matching task again."""
    _, client = practice(_set())

    turn = client.writer_turns[0]
    assert len(re.findall(r"(?m)^[A-Z]\. ", turn)) == PARAGRAPHS
    for letter in "ABCDEFGH":
        assert f"{letter}. Paragraph {letter}." in turn
    assert "stale option" not in turn


def test_unlettered_paragraphs_are_lettered_so_the_questions_can_name_them(practice):
    """One live generation returned a 484-word passage with no labels at all. A
    question naming Paragraph C is unanswerable against a passage that shows no
    letters, so the passage is written back with them."""
    result, _ = practice(_set(passage=_passage(lettered=False)))

    assert len(_block(result)) >= reading_trainer._MIN_HEADINGS_BLOCK
    assert result["passage"].startswith("A. Then came stage 1 of the story.")
    assert "\n\nD. Then came stage 4 of the story." in result["passage"]


def test_a_passage_with_too_few_paragraphs_drops_the_block(practice):
    """Distractors come from the paragraphs left unkeyed, so a short passage
    cannot offer more headings than it matches. A set one question short is
    still sittable; a headings block with nothing wrong to choose is not."""
    result, _ = practice(_set(passage=_passage(count=4)))

    assert _block(result) == []
    assert [q["number"] for q in result["questions"]] == [1, 2]
    assert set(result["answer_key"]) == {"1", "2"}
    assert result["answer_key"]["2"] == "B"


def test_a_headings_reply_that_repeats_itself_drops_the_block(practice):
    """One heading on two paragraphs makes both questions unanswerable. The
    writer call gets its own corrective retry for this; if that also fails the
    block goes, rather than shipping an ambiguous key."""
    result, _ = practice(_set(), headings={"headings": {chr(65 + i): "The same heading"
                                                        for i in range(PARAGRAPHS)}})

    assert _block(result) == []


def test_a_table_cell_follows_its_question_through_the_renumbering(practice):
    """Replacing one question with five moves every question after it. A visual
    addresses its gap by number, so renumbering without carrying the cell along
    silently unhooks the table from the question that fills it."""
    visual = {"kind": "chart", "chart_type": "table", "title": "Mills",
              "x_label": "City, Year",
              "series": [{"name": "Fabriano", "data": [["City", "Fabriano"],
                                                       ["Year", "__3__"]]}]}
    reply = _set(visual=visual)
    reply["questions"][2] = {"number": 3, "type": "table_completion", "word_limit": 1,
                             "question": "NO MORE THAN ONE WORD. The mill opened in ______.",
                             "options": None}
    reply["answer_key"]["3"] = "1276"
    result, _ = practice(reply)

    moved = next(q for q in result["questions"] if q["type"] == "table_completion")
    assert moved["number"] != 3
    assert f"__{moved['number']}__" in json.dumps(result["visual"])


def test_a_set_without_headings_is_untouched(practice):
    """Most sets carry no headings block at all — the pool path sends no
    question_types line, so the type only appears when the model reaches for it.
    Those must not pay for a second call."""
    reply = _set()
    reply["questions"].pop(1)
    reply["answer_key"].pop("2")
    result, client = practice(reply)

    assert client.writer_turns == []
    assert [q["number"] for q in result["questions"]] == [1, 3]


def test_a_label_wins_over_a_line_break():
    """Paragraphs are the author's division, not the wrapping. 74% of the
    headings corpus letters them and 3 of 3 live multitask generations did too,
    but one corpus record splits 9 lettered paragraphs across 17 lines."""
    passage = "A. First line.\nStill paragraph A.\n\nB. Second.\n\nC. Third.\n\nD. Fourth."
    assert reading_trainer._paragraph_bodies(passage) == [
        "First line. Still paragraph A.", "Second.", "Third.", "Fourth."]


def test_an_opening_capital_is_not_read_as_a_label():
    """"A new study..." starts with a letter and a space. Requiring punctuation
    after the letter is what stops a paragraph being beheaded by its own first
    word."""
    passage = "A new study of paper.\n\nBetter mills followed.\n\nThen came print."
    assert reading_trainer._paragraph_bodies(passage)[0] == "A new study of paper."
