"""A completion question that shows no gap is repaired, never regenerated.

Measured over 11 saved live artifacts: wherever the checkpoint emitted a
`visual` at all it coupled every cell to its question correctly, 24 of 24. What
it drops is the form itself, leaving the block's shared rubric behind as the
question — "Complete the membership details below." with `visual: null` and the
answer key still holding "John Smith". 8 of 47 live completion questions came
back that way, 3 of 9 sets were rejected for it, and the corrective retry does
not rescue one: both attempts of both e2e runs failed on it.

So the model is asked only for the half it does not drop — the name of the
field one answer fills — and the gap is placed here. These tests are about that
invariant, not about the wording of any label.
"""

import asyncio
import json

import pytest

from app.agents import listening_trainer
from app.llm.client import LLMClient, get_llm_client, set_llm_client
from app.llm.prompts import FORM_WRITER_SYSTEM

# Over _MIN_SCRIPT_WORDS, so nothing here depends on the expansion pass.
# The script says every answer the fixtures key: a listening answer the
# recording never contains is refused now (`_unheard_answers`), and these tests
# are about the form-label repair, not about answer content.
SCRIPT = (
    "AGENT: Good morning, Sports World. CUSTOMER: I would like to join. "
    "My name is John Smith and my number is 07798 563421. "
    "AGENT: And would you like the annual plan? CUSTOMER: Yes, annual please. "
) * 100

GOOD_LABELS = {"labels": {"1": "Full name", "3": "Payment plan"}}


def _set(**extra) -> dict:
    """The measured live failure: the rubric left behind as the question."""
    return {
        "title": "Joining a Sports Centre",
        "audio_script": SCRIPT,
        "visual": None,
        "questions": [
            {"number": 1, "type": "form_completion",
             "question": "Complete the membership details below."},
            {"number": 2, "type": "short_answer",
             "question": "What is the phone number?"},
            {"number": 3, "type": "form_completion",
             "question": "Complete the payment details below."},
        ],
        "answer_key": {"1": "John Smith", "2": "07798 563421", "3": "annual"},
        **extra,
    }


class FormClient(LLMClient):
    """Answers the set call, then the label-writing call."""

    is_finetune = True

    def __init__(self, reply: dict, labels: list[dict] | None = None,
                 writer_error: Exception | None = None) -> None:
        self.reply = reply
        self.labels = labels
        self.writer_error = writer_error
        self.writer_turns: list[str] = []
        self.complaints: list[str] = []

    async def complete(self, system, messages, **kw) -> str:
        raise AssertionError("the script must not need expanding in these tests")

    async def complete_json(self, system, messages, **kw) -> dict:
        if system is FORM_WRITER_SYSTEM:
            self.writer_turns.append(messages[-1]["content"])
            if self.writer_error:
                raise self.writer_error
            candidates = self.labels or [GOOD_LABELS]
        else:
            candidates = [json.loads(json.dumps(self.reply))]

        # The real complete_json runs the hook and retries on a complaint, so a
        # list of candidates is the retry sequence. Running out of them is the
        # state the real client reaches when its last retry is still refused.
        validate = kw.get("validate") or (lambda _: None)
        problem = None
        for candidate in candidates:
            problem = validate(candidate)
            if problem is None:
                return candidate
            self.complaints.append(problem)
        raise ValueError(problem)


@pytest.fixture()
def client():
    previous = get_llm_client()

    def _install(*args, **kw) -> FormClient:
        installed = FormClient(*args, **kw)
        set_llm_client(installed)
        return installed

    yield _install
    set_llm_client(previous)


def _practice() -> dict:
    return asyncio.run(listening_trainer.create_practice(topic="a sports centre"))


def test_rubric_question_becomes_a_labelled_gap(client):
    client(_set())
    result = _practice()

    assert result["questions"][0]["question"] == "Full name: ______"
    assert result["questions"][2]["question"] == "Payment plan: ______"
    # The repaired set is one the shipped validator accepts on its own terms.
    assert listening_trainer.validate_part(result) is None


def test_only_the_dangling_questions_are_sent(client):
    installed = client(_set())
    result = _practice()

    listed = installed.writer_turns[0].split("answers fills.")[-1]
    assert "1. John Smith" in listed
    assert "3. annual" in listed
    # Q2 answers itself with a '?', so asking for a label would invite the model
    # to rewrite a question that was never broken.
    assert "07798 563421" not in listed
    assert result["questions"][1]["question"] == "What is the phone number?"


def test_a_set_needing_no_repair_makes_no_call(client):
    reply = _set()
    for q in reply["questions"]:
        q["question"] = q["question"].replace("below.", "below: ______")
    installed = client(reply)

    _practice()

    assert installed.writer_turns == []


def test_a_question_the_form_already_covers_is_left_alone(client):
    visual = {"kind": "chart", "chart_type": "table", "title": "Membership",
              "series": [{"name": "Details",
                          "data": [["Name", "__1__"], ["Plan", "__3__"]]}]}
    installed = client(_set(visual=visual))

    result = _practice()

    assert installed.writer_turns == []
    assert result["questions"][0]["question"] == "Complete the membership details below."


def test_an_existing_visual_survives_the_repair(client):
    """The repair moves the question, never the figure.

    Rebuilding the form would put back the two-artifact coupling the checkpoint
    drops, and a set whose visual is a plan has no room for a second object.
    """
    visual = {"kind": "plan", "title": "Campus",
              "grid": [["A", "A", "corridor"], ["Hall", "Hall", "corridor"]]}
    client(_set(visual=visual))

    result = _practice()

    assert result["visual"]["kind"] == "plan"
    assert result["questions"][0]["question"] == "Full name: ______"


def test_a_failed_label_call_fails_the_set_loudly(client):
    """A question still pointing at nothing must not reach a student.

    The structure check is skipped on the way in on the promise that the repair
    answers it, so the promise is kept by re-validating rather than by trusting
    the repair to have worked.
    """
    client(_set(), writer_error=RuntimeError("ollama is down"))

    with pytest.raises(ValueError, match="the repaired listening set is invalid"):
        _practice()


def test_a_label_is_stripped_of_the_number_and_punctuation_it_carries(client):
    client(_set(), labels=[{"labels": {"1": "1. Full name:", "3": "Payment plan."}}])

    result = _practice()

    assert result["questions"][0]["question"] == "Full name: ______"
    assert result["questions"][2]["question"] == "Payment plan: ______"


@pytest.mark.parametrize(
    "bad, complaint",
    [
        ({"labels": {"1": "Full name"}}, "no label was written for gap 3"),
        ({"labels": {"1": "Full name", "3": "  "}}, "no label was written for gap 3"),
        ({"labels": {"1": "Full name",
                     "3": "The plan the customer said they would pay on"}},
         "too long"),
        ({"labels": {"1": "Membership", "3": "Membership"}},
         "two gaps were given the same label"),
    ],
    ids=["missing", "blank", "overlong", "duplicate"],
)
def test_a_label_reply_that_cannot_be_printed_is_refused(client, bad, complaint):
    """Each check is made to fire on purpose, then recovered from.

    A label that repeats another is the one worth spelling out: 44.8% of corpus
    forms carry a duplicate label, because a table's row tells two "Monthly Fee"
    cells apart. An inline gap has no row, so the same duplicate would leave two
    questions reading identically.
    """
    installed = client(_set(), labels=[bad, GOOD_LABELS])

    result = _practice()

    assert complaint in installed.complaints[0]
    assert result["questions"][0]["question"] == "Full name: ______"


def test_export_still_refuses_a_dangling_set():
    """Only the callers that repair may skip the check.

    build_dataset validates with the default, and it has no repair pass — a
    record that dangles must not become a training target.
    """
    dangling = _set()

    assert listening_trainer.validate_part(dangling) is not None
    assert listening_trainer.validate_part(dangling, judge_structure=False) is None


def test_a_gap_with_no_answer_is_reported_as_the_missing_answer(client):
    """Live `sft_01` keyed Q1 as '' and was rejected for dangling instead.

    Nothing matched a blank answer — `_REFUSAL_ANSWER` only matches words — so
    the set was sent to a repair that cannot name the field an empty answer
    fills, and the complaint the retry got named the wrong defect.
    """
    blank = _set()
    blank["answer_key"]["1"] = "  "

    problem = listening_trainer.validate_part(blank, judge_structure=False)

    assert problem is not None
    assert "question(s) 1 have no answer" in problem


def test_an_unanswered_gap_is_refused_instead_of_repaired(client):
    """No label call is spent on a set the repair could never rescue.

    The label call is all-or-nothing, so one unlabelable gap would take every
    repairable one down with it — measured on `sft_01`, where 1 blank answer
    left 3 otherwise-fixable questions unrepaired after 47s. Rejecting on the
    way in costs nothing and names the defect the retry has to fix.
    """
    reply = _set()
    reply["answer_key"]["1"] = ""
    installed = client(reply)

    with pytest.raises(ValueError, match="have no answer"):
        _practice()

    assert installed.writer_turns == []


# ---------------------------------------------------------------------------
# Reading shares the repair
#
# 🔬 2026-09-01. The repair above was written for listening and reading never
# got it — only the gate. So a reading set whose completion question showed no
# gap spent a ~4k-token corrective retry on a complaint that has never been
# rescued by one, and was then refused anyway: two of the three refusals in a
# 36-set diagram sweep (`r_diagram_apparatus_r3`, `r_diagram_cycle_r5`).
# ---------------------------------------------------------------------------

READING_PASSAGE = (
    "Beekeeping in cities has grown quickly over the past decade. " * 100
)


def _reading_set() -> dict:
    """A reading set whose table question is the block's rubric, with no table."""
    return {
        "title": "Urban Beekeeping",
        "passage": READING_PASSAGE,
        "visual": None,
        "questions": [
            {"number": 1, "type": "table_completion",
             "question": "Complete the table below."},
            {"number": 2, "type": "short_answer",
             "question": "Where has beekeeping grown?"},
        ],
        "answer_key": {"1": "decade", "2": "cities"},
    }


def test_reading_skips_the_structure_rule_on_the_way_in():
    """The gate still refuses it — but not on the reply, where retrying is what
    was measured not to work."""
    from app.agents import reading_trainer

    dangling = _reading_set()
    assert reading_trainer.validate_practice(dangling) is not None
    assert reading_trainer.validate_practice(
        dangling, judge_structure=False) is None


def test_reading_repairs_a_dangling_completion(client):
    """The same repair listening has always had, on a reading set."""
    from app.agents import reading_trainer

    installed = client(_reading_set(), labels=[{"labels": {"1": "Years of growth"}}])
    result = asyncio.run(reading_trainer.create_practice(topic="urban beekeeping"))

    assert result["questions"][0]["question"] == "Years of growth: ______"
    # Repaired, so the shipped validator accepts it on its own terms.
    assert reading_trainer.validate_practice(result) is None
    # Only the dangling one was sent; the short answer carries its own question.
    assert "2." not in installed.writer_turns[0]


def test_a_label_may_not_print_its_own_answer(client):
    """🔬 A reading gap is keyed to the part's own name often enough that the
    model reaches for it — "Firn zone: ______" keyed 'firn zone' answers itself.

    The listening copy never hit this: a form field names a category and the
    answer fills it.
    """
    installed = client(
        _reading_set(),
        labels=[{"labels": {"1": "Growth over the past decade"}},
                {"labels": {"1": "Years of growth"}}],
    )
    from app.agents import reading_trainer
    result = asyncio.run(reading_trainer.create_practice(topic="urban beekeeping"))

    assert "contains that gap's own answer" in " ".join(installed.complaints)
    assert result["questions"][0]["question"] == "Years of growth: ______"


def test_a_label_is_not_refused_for_a_word_that_merely_contains_the_answer():
    """'ice' does not leak through 'device'. Matching on the raw substring said
    it did, which would have cost a retry on a sound label."""
    from app.agents._figure_pass import _contains_words

    assert _contains_words("Firn zone", "firn")
    assert _contains_words("the Firn Zone!", "firn zone")
    assert not _contains_words("Device position", "ice")
    assert not _contains_words("Preferred start date", "12 March")
