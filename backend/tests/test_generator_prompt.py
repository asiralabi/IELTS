"""A fine-tuned generator must get the prompt shape it was trained on.

Every generator SFT record's user turn is topic/difficulty/types only — the
exporter rebuilds it via `_spec_user_message` rather than recording the
grounded runtime prompt. Appending a Cambridge exemplar therefore puts the
checkpoint off-distribution, and it answers by continuing the exemplar: a
reading set once came back with a passage on urban beekeeping and the
exemplar's own questions about ant taxonomy, which every structural validator
accepts. Nothing else would catch that.
"""

import asyncio

import pytest

from app.agents import listening_trainer, reading_trainer
from app.llm.client import LLMClient, get_llm_client, set_llm_client

GROUNDING_MARKER = "Real Cambridge IELTS"

READING_REPLY = {
    "title": "Urban Beekeeping",
    # Long enough that create_practice skips its expansion call.
    "passage": "Bees pollinate the city gardens of many temperate regions. " * 70,
    "questions": [
        {"number": 1, "type": "true_false_notgiven", "question": "Bees pollinate gardens."}
    ],
    "answer_key": {"1": "TRUE"},
}

LISTENING_REPLY = {
    "title": "Joining a Sports Centre",
    "audio_script": "AGENT: Good morning, how can I help you today? " * 130,
    "questions": [
        {"number": 1, "type": "form_completion", "question": "Membership starts on ..."}
    ],
    "answer_key": {"1": "Monday"},
}


class CapturingClient(LLMClient):
    """Records the user turn instead of generating."""

    def __init__(self, is_finetune: bool) -> None:
        self.is_finetune = is_finetune
        self.user_turns: list[str] = []

    async def complete(self, system, messages, **kw) -> str:
        raise AssertionError("generation must not fall back to free-text completion")

    async def complete_json(self, system, messages, **kw) -> dict:
        self.user_turns.append(messages[-1]["content"])
        if "Reading test writer" in system:
            return dict(READING_REPLY)
        return dict(LISTENING_REPLY)


@pytest.fixture()
def capture():
    previous = get_llm_client()

    def _install(is_finetune: bool) -> CapturingClient:
        client = CapturingClient(is_finetune)
        set_llm_client(client)
        return client

    yield _install
    set_llm_client(previous)


CALLS = {
    "reading_practice": lambda: reading_trainer.create_practice(topic="urban beekeeping"),
    "listening_practice": lambda: listening_trainer.create_practice(topic="a sports centre"),
    "listening_part": lambda: listening_trainer.create_part(1, topic="a sports centre"),
}


@pytest.mark.parametrize("name", list(CALLS), ids=list(CALLS))
def test_finetune_is_not_grounded(capture, name):
    client = capture(is_finetune=True)
    asyncio.run(CALLS[name]())

    turn = client.user_turns[0]
    assert GROUNDING_MARKER not in turn
    # conftest's vector store answers every query with this, so its absence
    # proves no retrieved text reached the prompt by another route.
    assert "band descriptor snippet" not in turn


@pytest.mark.parametrize("name", list(CALLS), ids=list(CALLS))
def test_general_model_keeps_its_grounding(capture, name):
    """Distillation pins the hosted teacher, which was never fine-tuned — it
    must keep the Cambridge exemplar that shaped the corpus."""
    client = capture(is_finetune=False)
    asyncio.run(CALLS[name]())

    assert GROUNDING_MARKER in client.user_turns[0]


LISTENING_CALLS = ["listening_practice", "listening_part"]

# Wording only build_dataset._listening_user_message produces.
CORPUS_SHAPE = ("Generate a Listening Test.", "Section: Part ", "Target Duration: 7 minutes")
# Wording the corpus never contains, which sent the checkpoint off-distribution.
PROSE_SHAPE = ("EXACTLY 10 questions", "TABLE figure")


@pytest.mark.parametrize("name", LISTENING_CALLS, ids=LISTENING_CALLS)
def test_finetune_gets_the_corpus_listening_shape(capture, name):
    """Listening's exporter was never brought in line with the runtime the way
    reading's was. Sent the runtime's prose prompt the checkpoint looped on a
    ~78-token cycle and ran to the token cap on 1 of 4 samples; sent this shape
    it closed the JSON on 6 of 6."""
    client = capture(is_finetune=True)
    asyncio.run(CALLS[name]())

    turn = client.user_turns[0]
    for fragment in CORPUS_SHAPE:
        assert fragment in turn
    for fragment in PROSE_SHAPE:
        assert fragment not in turn


@pytest.mark.parametrize("name", LISTENING_CALLS, ids=LISTENING_CALLS)
def test_general_model_keeps_the_prose_listening_prompt(capture, name):
    """The hosted teacher was never trained on the corpus shape — its prompt
    carries the per-part register and figure instructions instead."""
    client = capture(is_finetune=False)
    asyncio.run(CALLS[name]())

    assert "Generate a Listening Test." not in client.user_turns[0]


def _part(question_count: int) -> dict:
    return {
        "title": "Joining a Sports Centre",
        "audio_script": "AGENT: Good morning. " * 10,
        "questions": [
            {"number": n, "type": "sentence_completion", "question": f"Gap {n} is ..."}
            for n in range(1, question_count + 1)
        ],
        "answer_key": {str(n): "Monday" for n in range(1, question_count + 1)},
    }


def test_full_test_part_requires_ten_questions():
    """_renumber numbers positionally from a fixed offset, so a short part
    leaves a hole at the seam between parts and a long one overlaps the next.
    The fine-tune's training shape states no count, so nothing else pins it."""
    assert listening_trainer._validate_full_test_part(_part(10)) is None
    assert "not 8" in listening_trainer._validate_full_test_part(_part(8))
    assert "not 11" in listening_trainer._validate_full_test_part(_part(11))
    # create_practice is a standalone set — it must not inherit the count rule.
    assert listening_trainer.validate_part(_part(8)) is None


def test_duplicate_heading_message_names_the_clash():
    """A reading set exceeds the size complete_json will echo back, so the
    validator's own string is all the retry gets. Told only that headings must
    differ, the checkpoint repeated the same duplicate twice in a row and the
    generation failed; the numbers and the reused heading give it a handle."""
    result = {
        "title": "t",
        "passage": "p",
        "questions": [
            {"number": n, "type": "matching_headings", "question": f"Paragraph {n}",
             "options": ["i", "ii", "iii", "iv", "v"]}
            for n in range(1, 4)
        ],
        "answer_key": {"1": "iv", "2": "ii", "3": "iv"},
    }
    problem = reading_trainer.validate_practice(result)
    assert "questions 1, 3" in problem
    assert "iv" in problem
    # Naming what is still free turns "reassign" into a choice it can make.
    assert "still unused: i, iii, v" in problem


def test_too_few_headings_is_reported_before_the_duplicates_it_forces():
    """Two live generations in a row failed on duplicates, retrying into the
    same clash. With fewer headings than paragraphs distinctness is impossible,
    so 'reassign' asks for something no retry can deliver — the missing
    headings have to be the complaint."""
    result = {
        "title": "t",
        "passage": "p",
        "questions": [
            {"number": n, "type": "matching_headings", "question": f"Paragraph {n}",
             "options": ["i", "ii"]}
            for n in range(1, 5)
        ],
        "answer_key": {"1": "i", "2": "ii", "3": "i", "4": "ii"},
    }
    problem = reading_trainer.validate_practice(result)
    assert "at least 6 headings" in problem
    assert "reassign" not in problem


def _keyed(answers: dict, questions: list[dict] | None = None) -> dict:
    return {
        "title": "Joining a Sports Centre",
        "audio_script": "AGENT: Good morning. " * 10,
        "questions": questions or [
            {"number": n, "type": "short_answer", "question": f"Question {n}?"}
            for n in answers
        ],
        "answer_key": answers,
    }


@pytest.mark.parametrize(
    "answer",
    ["not provided", "Not mentioned", "Not specified", "NOT GIVEN", "None",
     "No answer", "n/a", "unknown", "cannot be determined"],
)
def test_refusal_answers_are_rejected(answer):
    """A key that says the script does not answer the question is the model
    declining, not answering: the student can never be marked correct. The live
    set that first passed generation keyed 3 of 10 answers this way, and 13 of
    the 212 committed corpus records carry one."""
    problem = listening_trainer.validate_part(_keyed({"1": answer, "2": "Monday"}))
    assert problem is not None
    assert "does not answer the question" in problem
    assert f"Q1='{answer}'" in problem


def test_real_answers_that_merely_look_like_refusals_are_kept():
    """The rule matches a whole answer only. 'None of the above' is a real
    option, and a number or a phrase containing 'none' is a real answer."""
    for answer in ["None of the above", "no answer sheet", "9 unknown species"]:
        assert listening_trainer.validate_part(_keyed({"1": answer})) is None


def test_multiple_choice_answer_must_be_one_of_its_options():
    """mark_answers compares strings, so an answer keyed by position ('2') or
    carried over from another question can never be marked correct. Three
    corpus records do this, one of them across nine questions."""
    options = ["Air pollution only", "Water pollution only", "Both"]
    question = [{"number": 1, "type": "multiple_choice",
                 "question": "What does the speaker discuss?", "options": options}]

    assert listening_trainer.validate_part(
        _keyed({"1": "Water pollution only"}, question)
    ) is None
    # A letter is accepted: it is what the frontend submits, and one corpus
    # record keys this way.
    assert listening_trainer.validate_part(_keyed({"1": "B"}, question)) is None

    problem = listening_trainer.validate_part(_keyed({"1": "2"}, question))
    assert "not one of its options" in problem
    assert "Water pollution only" in problem


def _gapfill(number: int, limit: int) -> dict:
    return {"number": number, "type": "sentence_completion",
            "question": f"Item {number} costs ______ per month.", "word_limit": limit}


def test_an_answer_longer_than_its_own_rubric_is_rejected():
    """word_limit is printed to the student as the rubric, so an answer that
    breaks it can never be entered — they obey 'NO MORE THAN TWO WORDS' and are
    marked wrong however much they know. This used to be a log line only."""
    problem = listening_trainer.validate_part(
        _keyed({"1": "one two three four five"}, [_gapfill(1, 2)])
    )
    assert "Q1 keys 5 words against word_limit=2" in problem


def test_a_one_or_two_word_overrun_is_forgiven():
    """build_dataset._reconcile_word_limits already treats this as teacher
    noise and just raises the cap. On raw pre-reconciliation output it is 35.3%
    of listening units and 9.6% of reading ones, so rejecting it would buy a
    5-15 min regeneration for nothing but clumsy phrasing."""
    assert listening_trainer.validate_part(
        _keyed({"1": "the main sports hall"}, [_gapfill(1, 2)])
    ) is None


def test_an_answer_that_is_itself_the_blank_is_rejected_at_any_cap():
    """The live set keyed Q1 as the form it was supposed to fill in. No word
    cap catches that — here the cap is generous and the answer still cannot be
    marked. 0 of 583 raw teacher units do this, so there is no cost."""
    problem = listening_trainer.validate_part(
        _keyed({"1": "Membership Type: ______"}, [_gapfill(1, 9)])
    )
    assert "Q1 answers with the blank itself" in problem


def test_reading_enforces_the_word_limit_too():
    """The two sections run separate validators, so wiring one proves nothing
    about the other."""
    problem = reading_trainer.validate_practice({
        "title": "t",
        "passage": "The centre opens at nine in the morning. " * 30,
        "questions": [_gapfill(1, 2)],
        "answer_key": {"1": "one two three four five"},
    })
    assert "Q1 keys 5 words against word_limit=2" in problem


def test_a_number_does_not_count_toward_the_cap():
    """The IELTS rubric excludes figures, so '£35 per month' is 3 words against
    a 2-word cap, not 4 — inside the slack, and correctly kept."""
    assert listening_trainer.validate_part(
        _keyed({"1": "35 per month"}, [_gapfill(1, 1)])
    ) is None


MAP_Q = [{"number": 1, "type": "map_labelling",
          "question": "What is the location marked as point C?"}]
MAP_VISUAL = {"kind": "map", "title": "Campus", "features": [{"label": "C", "x": 2, "y": 3}]}


def test_map_labelling_without_a_map_is_rejected():
    """dangling_structure_error lets anything ending in '?' through, which is
    how two corpus records shipped a map question with no map — one keys the
    answer 'C', the letter its own text quotes. A position cannot be read off a
    drawing the student never sees, so there is no self-contained form."""
    problem = listening_trainer.validate_part(_keyed({"1": "Library"}, MAP_Q))
    assert "carries no map" in problem
    assert listening_trainer.validate_part(
        {**_keyed({"1": "Library"}, MAP_Q), "visual": MAP_VISUAL}
    ) is None


def test_a_table_visual_does_not_satisfy_a_map_question():
    """The Listening contract allows either kind, so presence alone is not
    enough — only a map renders lettered positions."""
    table = {"kind": "chart", "chart_type": "table", "title": "t",
             "series": [{"name": "r", "data": [["c", "__1__"]]}]}
    problem = listening_trainer.validate_part(
        {**_keyed({"1": "Library"}, MAP_Q), "visual": table}
    )
    assert "carries no map" in problem
