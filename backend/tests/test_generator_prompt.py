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
import json

import pytest

from app.agents import listening_trainer, reading_trainer
from app.llm.client import LLMClient, get_llm_client, set_llm_client
from app.llm.prompts import LISTENING_TRAINER_SYSTEM

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
    # Ten questions because create_part takes no other length, and each carries
    # its own gap: these tests assert on the prompt, so the reply has to be a
    # set the generator accepts without repairing it first.
    "questions": [
        {"number": n, "type": "form_completion",
         "question": f"Membership detail {n} is ______"}
        for n in range(1, 11)
    ],
    "answer_key": {str(n): "Monday" for n in range(1, 11)},
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


class TestFigureWorkBypassesTheCheckpoint:
    """The checkpoint's corpus encodes a part's figure through its question
    types and never describes the figure itself, so asked for one it answers
    with its trained shape rather than the grid schema in the system prompt. A
    live run died in the runaway guard both ways round — the listening part
    stalled with the object still open, the reading passage repeated. So the
    calls that need a figure ask for the general model instead.
    """

    @pytest.fixture()
    def requested(self, monkeypatch, capture):
        """Every skip_finetune the agents ask "generator" for, in call order."""
        capture(is_finetune=False)
        asked: list[bool] = []

        for module in (listening_trainer, reading_trainer):
            real = module.get_llm_client

            def spy(task=None, *, skip_finetune=False, _real=real):
                if task == "generator":
                    asked.append(skip_finetune)
                return _real(task, skip_finetune=skip_finetune)

            monkeypatch.setattr(module, "get_llm_client", spy)
        return asked

    @pytest.mark.parametrize(
        "part_number, bypasses",
        [(1, True), (2, True), (3, False), (4, False)],
        ids=["part 1 table", "part 2 plan", "part 3 none", "part 4 none"],
    )
    def test_only_the_listening_parts_carrying_a_figure_bypass_it(
        self, requested, part_number, bypasses
    ):
        asyncio.run(listening_trainer.create_part(part_number))

        assert requested[0] is bypasses

    @pytest.mark.parametrize(
        "question_types, bypasses",
        [
            (["map_labelling"], True),
            (["Map Labelling", "multiple_choice"], True),
            (["form_completion", "short_answer"], False),
            (None, False),
        ],
        ids=["map", "display spelling", "prose only", "unsteered"],
    )
    def test_a_listening_set_bypasses_it_only_when_steered_to_a_plan(
        self, requested, question_types, bypasses
    ):
        """A single part comes from the same checkpoint part 2 of a full test
        does, so a student asking for map labelling here meets the same shape
        it cannot draw. Form and table completion stay on it: it couples the
        cells it does emit correctly, and the gap it drops is repaired in code.
        """
        asyncio.run(listening_trainer.create_practice(question_types=question_types))

        assert requested[0] is bypasses

    @pytest.mark.parametrize(
        "question_types, bypasses",
        [
            (["diagram_label_completion", "true_false_notgiven"], True),
            (["table_completion"], True),
            # The teacher's display spelling has to match too, or the steer
            # reaches the checkpoint unnoticed.
            (["Diagram Label Completion"], True),
            (["true_false_notgiven", "matching_headings"], False),
            (None, False),
        ],
        ids=["diagram", "table", "display spelling", "prose only", "unsteered"],
    )
    def test_a_reading_passage_bypasses_it_only_when_steered_to_a_figure(
        self, requested, question_types, bypasses
    ):
        asyncio.run(reading_trainer.create_practice(question_types=question_types))

        assert requested[0] is bypasses

    def test_a_full_test_lets_the_hosted_half_run_beside_the_local_one(
        self, monkeypatch
    ):
        '''gather_llm serialises against the model it is told about, and the
        local checkpoint answers one call at a time. Asked for all four parts
        in one list the hosted pair would wait behind that queue — and a
        hosted part is the slow half, ~20 minutes live against ~7 local.'''
        asked: list[tuple[bool, list[int]]] = []

        async def fake_part(number, difficulty=None, topic=None):
            return {"part": number}

        async def fake_gather(task, coros, *, skip_finetune=False):
            parts = [await c for c in coros]
            asked.append((skip_finetune, [p["part"] for p in parts]))
            return parts

        monkeypatch.setattr(listening_trainer, "create_part", fake_part)
        monkeypatch.setattr(listening_trainer, "gather_llm", fake_gather)

        result = asyncio.run(listening_trainer.create_full_test())

        assert sorted(asked) == [(False, [3, 4]), (True, [1, 2])]
        assert [p["part"] for p in result["parts"]] == [1, 2, 3, 4]

    def test_a_paper_lets_its_diagram_passage_run_beside_the_others(
        self, monkeypatch
    ):
        '''The same queue, on the reading side: one of the three passages is
        steered to a diagram and served hosted, and it is also the slow one.'''
        asked: list[tuple[bool, int]] = []

        async def fake_practice(question_types=None, difficulty=None, topic=None):
            return {"questions": [], "answer_key": {}}

        async def fake_gather(task, coros, *, skip_finetune=False):
            got = [await c for c in coros]
            asked.append((skip_finetune, len(got)))
            return got

        monkeypatch.setattr(reading_trainer, "create_practice", fake_practice)
        monkeypatch.setattr(reading_trainer, "gather_llm", fake_gather)

        result = asyncio.run(reading_trainer.create_full_test())

        assert sorted(asked) == [(False, 2), (True, 1)]
        assert [p["passage_number"] for p in result["passages"]] == [1, 2, 3]

    def test_one_half_failing_still_waits_for_the_other(
        self, capture, monkeypatch
    ):
        '''A generation failure is routine. Left unawaited the other half
        goes on writing into a test nobody will read, and surfaces later as a
        stray warning instead of the error that ended the run.'''
        capture(is_finetune=False)
        finished: list[int] = []

        async def fake_part(number, difficulty=None, topic=None):
            if number == 1:
                raise ValueError("the plan would not close")
            await asyncio.sleep(0)
            finished.append(number)
            return {"part": number}

        monkeypatch.setattr(listening_trainer, "create_part", fake_part)

        with pytest.raises(ValueError, match="would not close"):
            asyncio.run(listening_trainer.create_full_test())

        assert 3 in finished and 4 in finished

    def test_the_papers_figure_passage_is_one_of_the_steered_ones(self):
        """_PASSAGE_TYPES is what puts a figure in a generated paper at all;
        if its steer ever stopped naming a figure type the paper would come
        back figureless and still pass every structural check."""
        steered = set(reading_trainer._PASSAGE_TYPES)

        assert steered, "no passage is steered to a figure"
        for index in steered:
            types = reading_trainer._PASSAGE_TYPES[index]
            assert reading_trainer._FIGURE_TYPES.intersection(
                reading_trainer.canon(t) for t in types
            )


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


def test_single_question_headings_block_is_rejected():
    """The multi-task checkpoint's real headings failure is under-production,
    not duplication: three live generations in a row emitted a set of 8 with a
    single matching_headings question keyed 'i'. That block passes both other
    rules for free — one question needs only 3 options and is a bijection by
    construction — so without a size floor an unrealistic set ships as valid."""
    result = {
        "title": "t",
        "passage": "p",
        "questions": [
            {"number": 1, "type": "matching_headings", "question": "Paragraph A",
             "options": ["i", "ii", "iii", "iv", "v"]},
        ],
        "answer_key": {"1": "i"},
    }
    problem = reading_trainer.validate_practice(result)
    assert "only 1 matching_headings question" in problem
    assert "at least 3" in problem
    # The block is a valid bijection, so neither existing rule has anything to
    # say — the complaint must be the missing paragraphs.
    assert "reassign" not in problem


def test_three_question_headings_block_is_accepted():
    """The floor is 3, not the 5 READING_TRAINER_SYSTEM asks for: 26 of the 54
    committed headings sets carry exactly 3, so a stricter rule would reject
    11.5% of the corpus the checkpoint was trained on."""
    result = {
        "title": "t",
        "passage": "p",
        "questions": [
            {"number": n, "type": "matching_headings", "question": f"Paragraph {n}",
             "options": ["i", "ii", "iii", "iv", "v"]}
            for n in range(1, 4)
        ],
        "answer_key": {"1": "i", "2": "iii", "3": "v"},
    }
    assert reading_trainer.validate_practice(result) is None


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
MAP_VISUAL = {"kind": "plan", "title": "Campus",
              "grid": [["C", "C", "corridor"], ["Hall", "Hall", "corridor"]]}


def test_map_labelling_without_a_map_is_rejected():
    """dangling_structure_error lets anything ending in '?' through, which is
    how two corpus records shipped a map question with no map — one keys the
    answer 'C', the letter its own text quotes. A position cannot be read off a
    drawing the student never sees, so there is no self-contained form."""
    problem = listening_trainer.validate_part(_keyed({"1": "Library"}, MAP_Q))
    assert "carries no plan" in problem
    assert listening_trainer.validate_part(
        {**_keyed({"1": "C"}, MAP_Q), "visual": MAP_VISUAL}
    ) is None


def test_a_table_visual_does_not_satisfy_a_map_question():
    """The Listening contract allows either kind, so presence alone is not
    enough — only a plan renders lettered rooms."""
    table = {"kind": "chart", "chart_type": "table", "title": "t",
             "series": [{"name": "r", "data": [["c", "__1__"]]}]}
    problem = listening_trainer.validate_part(
        {**_keyed({"1": "Library"}, MAP_Q), "visual": table}
    )
    assert "carries no plan" in problem


def test_a_letter_the_plan_never_draws_is_rejected():
    """The first hosted part 2 keyed A, E and F against a grid holding only A:
    it printed the real name of every place the questions asked about and
    invented letters for them. A plan that answers its own questions leaves the
    student nothing to write, and `missing_map_error` waves it through because
    a plan is present."""
    grid = [["A", "A", "corridor"], ["Reception", "Reception", "corridor"]]
    problem = listening_trainer.validate_part({
        **_keyed({"1": "A", "2": "F"}, [
            {"number": 1, "type": "map_labelling", "question": "Café"},
            {"number": 2, "type": "map_labelling", "question": "IT Suite"},
        ]),
        "visual": {"kind": "plan", "title": "Centre", "grid": grid},
    })
    assert "Q2 keys F" in problem
    assert "the grid holds A" in problem


def test_a_plan_question_answered_in_words_is_rejected():
    """Naming the room is the same failure read from the other end — the
    student writes a letter into the answer sheet, so a keyed room name can
    never be marked correct however well they read the plan."""
    problem = listening_trainer.validate_part(
        {**_keyed({"1": "the Library"}, MAP_Q), "visual": MAP_VISUAL}
    )
    assert "answered with the letter of a room" in problem


def test_the_letter_check_ignores_a_part_with_no_plan_question():
    """Parts 1 and 2 both route past the checkpoint, so a plan can ride along
    beside ordinary gap-fill questions. Only map_labelling answers are letters;
    holding the rest to that would reject every one of them."""
    assert listening_trainer.validate_part({
        **_keyed({"1": "9.30 am"}, [_gapfill(1, 2)]),
        "visual": MAP_VISUAL,
    }) is None


def _example_plan_grid() -> list[list[str]]:
    """The plan grid LISTENING_TRAINER_SYSTEM shows the model."""
    text = LISTENING_TRAINER_SYSTEM
    start = text.index('"grid": [', text.index('"kind": "plan"'))
    depth, i = 0, text.index("[", start)
    for end in range(i, len(text)):
        depth += {"[": 1, "]": -1}.get(text[end], 0)
        if depth == 0:
            return json.loads(text[i:end + 1])
    raise AssertionError("the plan example's grid is not bracket-balanced")


def test_the_plan_example_obeys_the_rules_printed_beside_it():
    """A worked example outranks the prose around it — the model copies what it
    can see. The example shipped with 4 lettered rooms while the text demanded
    6-8, which is the shape the first hosted part 2 came back with: a grid of
    named rooms and letters in the key that were never drawn."""
    grid = _example_plan_grid()
    assert len({len(row) for row in grid}) == 1, "rows are ragged"
    assert 4 <= len(grid) <= 6 and 6 <= len(grid[0]) <= 9

    rows, cols = len(grid), len(grid[0])
    def around(r, c):
        for nr, nc in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
            if 0 <= nr < rows and 0 <= nc < cols:
                yield nr, nc

    def region(value):
        cells = {(r, c) for r, row in enumerate(grid)
                 for c, v in enumerate(row) if v == value}
        seen, stack = {min(cells)}, [min(cells)]
        while stack:
            for n in around(*stack.pop()):
                if n in cells and n not in seen:
                    seen.add(n)
                    stack.append(n)
        return cells, seen

    values = {v for row in grid for v in row if v}
    letters = {v for v in values if len(v) == 1 and v.isalpha()}
    assert len(letters) >= 6, f"only {sorted(letters)} lettered — the text asks 6-8"
    assert 2 <= len(values - letters - {"corridor"}) <= 4, "2-4 named landmarks"

    corridor_cells, corridor_seen = region("corridor")
    assert corridor_cells == corridor_seen, "the corridor is not one walkway"
    for value in values - {"corridor"}:
        cells, seen = region(value)
        assert cells == seen, f"{value!r} sits in two unconnected places"
        assert len(cells) >= 2, f"{value!r} is a single-cell room"
        assert any(grid[nr][nc] == "corridor" for cell in cells
                   for nr, nc in around(*cell)), f"{value!r} has no door"
