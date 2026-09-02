"""A Listening answer has to be words the student HEARS.

Reading has enforced "the answer is a span of the passage" since `84c426c`.
The listening side never had the rule at all, for any question type — which is
how a live Part 2 came to key 'grouphead' against a script saying "group head",
and 'Mode dial' against one saying "rotary dial" four times.

📏 Measured before it was built (`tools/_diag_listening_verbatim_cost.py`, over
the 144 gap-fill sets of the listening SFT corpus). A naive rule flags 82
answers across 34.0% of sets, but only 42.7% of those flags are the defect:
45.1% are numbers, dates and times the speaker says aloud and the student
writes in figures, and 12.2% are comma-separated lists. Scoped past both, the
rule flags **17.4% of listening sets — against the 17.7% the identical reading
rule already flags and ships with.**
"""

import asyncio

import pytest

from app.agents import listening_trainer as lt
from app.agents.answerability import absent_answers, is_numeric_answer, span_tokens


SCRIPT = (
    "AGENT: Good morning, Sports World. The pool opens at six thirty. "
    "CUSTOMER: And how much is the annual membership? "
    "AGENT: It is ninety pounds, and you will need photo identification. "
    "CUSTOMER: My name is John Smith. "
)


def part(answers: dict, script: str = SCRIPT) -> dict:
    return {
        "title": "Joining a Sports Centre",
        "audio_script": script,
        "questions": [
            {"number": int(n), "type": "sentence_completion",
             "question": f"NO MORE THAN TWO WORDS. Gap {n} is ______."}
            for n in answers
        ],
        "answer_key": answers,
    }


# ---------------------------------------------------------------------------
# The matcher itself
# ---------------------------------------------------------------------------


def test_an_answer_the_script_says_is_not_flagged():
    assert lt._unheard_answers(part({"1": "annual membership"})) == []


def test_a_paraphrase_is_flagged():
    assert [n for n, _ in lt._unheard_answers(part({"1": "yearly membership"}))] == ["1"]


def test_a_loose_stem_still_counts_as_heard():
    """"opens" in the script answers a gap keyed 'open'. Reading's matcher has
    always forgiven that and this is the same matcher."""
    assert lt._unheard_answers(part({"1": "open"})) == []


def test_a_leading_article_is_ignored():
    assert lt._unheard_answers(part({"1": "the pool"})) == []


@pytest.mark.parametrize(
    "answer", ["6:00-8:00", "10th March", "90", "ninety", "three", "7:00-9:00 pm"]
)
def test_a_figure_is_never_flagged(answer):
    """45.1% of everything a naive rule flags in listening is a number, a date
    or a time — "six to eight" keyed '6:00-8:00', "March the tenth" keyed
    '10th March'. Every one is a CORRECT answer, and refusing them would refuse
    what the exam itself prints."""
    assert is_numeric_answer(answer)
    assert lt._unheard_answers(part({"1": answer})) == []


def test_a_list_of_items_is_left_to_another_rule():
    """12.2% of the flags. A different defect, and not this rule's business."""
    assert lt._unheard_answers(
        part({"1": "swimming pool, gym, sauna"})) == []


def test_reading_does_not_skip_figures():
    """Measured over both corpora: numeric answers are 45.1% of listening flags
    and 0% of reading ones, because a passage spells its numbers out where a
    speaker says them aloud. Reading's behaviour must not change."""
    questions = [{"number": 1, "type": "sentence_completion", "question": "x ______"}]
    hits = absent_answers("The tower is thirty metres tall.", questions,
                          {"1": "30"}, skip_numeric=False)
    assert [a for _, a in hits] == ["30"]


def test_an_answer_with_its_own_word_box_is_answered_from_the_box():
    questions = [{"number": 1, "type": "sentence_completion", "question": "x ______",
                  "options": ["alpha", "beta"]}]
    assert absent_answers(SCRIPT, questions, {"1": "alpha"}, skip_numeric=True) == []


def test_no_script_means_the_rule_cannot_run():
    assert lt._unheard_answers(part({"1": "anything"}, script="")) == []


# ---------------------------------------------------------------------------
# The threshold, and where the rule sits
# ---------------------------------------------------------------------------


def test_one_stray_answer_is_tolerated():
    """One is teacher noise and costs a retry for little gain; two is a habit.
    The threshold reading has used since `84c426c`, kept identical so the two
    sections are not tuned against each other by accident."""
    assert lt._MAX_UNHEARD == 2
    assert lt.validate_part(
        part({"1": "yearly membership", "2": "annual"}),
        judge_structure=False, judge_matching=False) is None


def test_two_stray_answers_are_refused():
    problem = lt.validate_part(
        part({"1": "yearly membership", "2": "monthly fee"}),
        judge_structure=False, judge_matching=False)
    assert "never said in the script" in (problem or "")


def test_a_more_specific_rule_still_wins():
    """Every rule above this one names an actionable fault — an answer that
    refuses to answer, one over the word limit, a matching pair whose option
    was never offered. "Not in the script" is true of those as well, so running
    it first swallowed the useful message: 28 tests asserting the
    refusal-answer wording started reading this complaint instead."""
    problem = lt.validate_part(
        part({"1": "not provided", "2": "cannot be determined"}),
        judge_structure=False, judge_matching=False)
    assert "does not answer the question" in (problem or "")


def test_the_generation_gate_does_not_judge_it():
    """Skipped on the way IN so the repair gets its turn, exactly as reading
    promises with judge_verbatim=False. A gate that refused here would throw
    away a set the repair can fix."""
    assert lt.validate_part(
        part({"1": "yearly membership", "2": "monthly fee"}),
        judge_structure=False, judge_matching=False, judge_verbatim=False) is None


# ---------------------------------------------------------------------------
# The repair
# ---------------------------------------------------------------------------


def test_the_repair_makes_the_script_say_the_answers(monkeypatch):
    """When the answer is RIGHT and the recording simply never says it, the
    SCRIPT is rewritten rather than the gap re-keyed — the cure `c293479`
    proved for reading, where re-keying produced a vaguer question."""
    asked = {}

    async def fake_expand(script, title, must_say=None):
        asked["must_say"] = must_say
        return script + " AGENT: The yearly membership and the monthly fee apply."

    monkeypatch.setattr(lt, "_expand_script", fake_expand)
    result = part({"1": "yearly membership", "2": "monthly fee"})
    asyncio.run(lt._repair_unheard_answers(result))

    assert sorted(asked["must_say"]) == ["monthly fee", "yearly membership"]
    assert lt._unheard_answers(result) == []


def test_an_expansion_that_does_not_help_is_discarded(monkeypatch):
    """A model that ignored the instruction must not be able to make things
    worse — the trial is verified before it is kept."""
    async def useless(script, title, must_say=None):
        return "AGENT: Completely unrelated chatter about the weather."

    monkeypatch.setattr(lt, "_expand_script", useless)
    result = part({"1": "yearly membership", "2": "monthly fee"})
    before = result["audio_script"]
    asyncio.run(lt._repair_unheard_answers(result))
    assert result["audio_script"] == before


def test_the_repair_does_not_run_below_the_threshold(monkeypatch):
    called = []

    async def spy(script, title, must_say=None):
        called.append(must_say)
        return script

    monkeypatch.setattr(lt, "_expand_script", spy)
    asyncio.run(lt._repair_unheard_answers(part({"1": "yearly membership"})))
    assert called == []


def test_expand_script_carries_must_say_into_its_prompt():
    """The instruction has to reach the model, or the repair is a no-op that
    still costs a call."""
    sent = {}

    class Fake:
        async def complete(self, system, messages, **kw):
            sent["prompt"] = messages[-1]["content"]
            return "AGENT: expanded."

    from app.llm import client as client_module
    previous = client_module.get_llm_client()
    client_module.set_llm_client(Fake())
    try:
        asyncio.run(lt._expand_script("AGENT: hi.", "Title",
                                      must_say=["group head", "steam wand"]))
    finally:
        client_module.set_llm_client(previous)
    assert "group head" in sent["prompt"]
    assert "steam wand" in sent["prompt"]
    assert "MUST say" in sent["prompt"]


def test_span_tokens_is_the_one_shared_definition():
    """Two copies of "is this a span of that" is how one section comes to
    accept what the other refuses."""
    from app.agents import reading_trainer
    assert reading_trainer._span_tokens is span_tokens


# ---------------------------------------------------------------------------
# The script-length floor
# ---------------------------------------------------------------------------


def test_the_expansion_keeps_going_until_the_script_clears_the_floor(monkeypatch):
    """🔬 21 of the 342 parts in the 2026-08-29 corpus shipped UNDER
    `_MIN_SCRIPT_WORDS`, the shortest at 395 words — two and a half minutes of
    audio carrying ten questions where the exam gives seven or eight. The call
    site asked ONCE and accepted any growth at all, so 395 -> 500 counted as
    repaired. Same fault `_repair_unheard_answers` had: judged against its own
    progress rather than the threshold it exists to reach."""
    import asyncio

    from app.agents import listening_trainer as lt

    calls = []

    async def fake_expand(script, title, must_say=None, *, overshot=0):
        calls.append(len(script.split()))
        # A third of the floor per round, from half of it — so one call cannot
        # get there and two can. Expressed against the floor rather than in
        # absolute words: it was written as 400 + 500 against a floor of 1000,
        # and reading the corpus moved that floor to 650, at which point one
        # call cleared it and the test was asserting nothing.
        return " ".join(["word"] * (len(script.split()) + lt._MIN_SCRIPT_WORDS // 3))

    monkeypatch.setattr(lt, "_expand_script", fake_expand)
    result = {"audio_script": " ".join(["word"] * (lt._MIN_SCRIPT_WORDS // 2)),
              "title": "t"}
    asyncio.run(lt._grow_script(result))

    assert len(result["audio_script"].split()) >= lt._MIN_SCRIPT_WORDS
    assert len(calls) > 1, "one call cannot reach the floor from half of it"


def test_the_expansion_gives_up_rather_than_looping_forever(monkeypatch):
    """A model that will not lengthen the script must not cost an unbounded
    number of calls — the short part ships and the corpus records it."""
    import asyncio

    from app.agents import listening_trainer as lt

    calls = []

    async def stuck(script, title, must_say=None, *, overshot=0):
        calls.append(1)
        return script  # no growth at all

    monkeypatch.setattr(lt, "_expand_script", stuck)
    result = {"audio_script": " ".join(["word"] * 400), "title": "t"}
    asyncio.run(lt._grow_script(result))
    assert len(calls) == 1
    assert len(result["audio_script"].split()) == 400


# ---------------------------------------------------------------------------
# Script length, measured against the corpus rather than against the cover
# ---------------------------------------------------------------------------


def test_the_length_bounds_match_the_real_corpus():
    """The bounds used to read "7-8 minutes = 1200-1500 words", which is what
    the 30 minutes printed on the paper's cover suggests — but that half hour
    is four parts PLUS the instructions and the pauses for reading and checking
    answers, not four parts of talking.

    The 212 real parts in `data/datasets/listening_generator_sft.jsonl` say:
    median 833 words, p10 671, p90 1042, longest 1415. So the old floor of 1000
    sat above the corpus MEDIAN and the expander pushed every short script past
    its p90 — which is why live sets were running 1400-2300 words.
    """
    from app.agents import listening_trainer as lt

    assert lt._MIN_SCRIPT_WORDS <= 700, "the floor is above the corpus p10"
    assert lt._MIN_SCRIPT_WORDS >= 400, "a floor this low is not a Part at all"
    # Above the longest real part, so only a runaway script trips it.
    assert lt._MAX_SCRIPT_WORDS > 1415
    assert lt._MAX_SCRIPT_WORDS <= 1600


def test_a_runaway_script_is_refused():
    from app.agents import listening_trainer as lt

    result = {
        "title": "t",
        "audio_script": " ".join(["word"] * (lt._MAX_SCRIPT_WORDS + 1)),
        "questions": [{"number": 1, "type": "short_answer", "question": "Who?"}],
        "answer_key": {"1": "Emma"},
    }
    problem = lt.validate_part(result) or ""
    assert "words" in problem and "no exam would play" in problem


def test_a_script_the_length_of_the_real_ones_passes():
    """The corpus median must not be what the validator turns away."""
    from app.agents import listening_trainer as lt

    result = {
        "title": "t",
        "audio_script": " ".join(["word"] * 833),
        "questions": [{"number": 1, "type": "short_answer", "question": "Who?"}],
        "answer_key": {"1": "Emma"},
    }
    problem = lt.validate_part(result) or ""
    assert "no exam would play" not in problem


def test_an_expansion_that_overshoots_is_asked_again(monkeypatch):
    """🔬 A generated paper on 2026-09-02 totalled 5816 words across four parts
    against the ~3300 the exam plays, and two parts were over the ceiling on
    their own. `_grow_script` kept whatever came back so long as it was LONGER,
    so a part that arrived short shipped at twice the length of the longest
    real one. An overshoot is not growth towards the floor."""
    import asyncio

    from app.agents import listening_trainer as lt

    replies = [
        " ".join(["word"] * (lt._MAX_SCRIPT_WORDS + 500)),   # wild overshoot
        " ".join(["word"] * 900),                            # sensible
    ]
    asked = []
    told = []

    async def fake_expand(script, title, must_say=None, *, overshot=0):
        asked.append(len(script.split()))
        told.append(overshot)
        return replies[len(asked) - 1] if len(asked) <= len(replies) else script

    monkeypatch.setattr(lt, "_expand_script", fake_expand)
    result = {"audio_script": " ".join(["word"] * 300), "title": "t"}
    asyncio.run(lt._grow_script(result))

    kept = len(result["audio_script"].split())
    assert kept == 900, f"kept {kept} words instead of asking again"
    assert len(asked) == 2, "the overshoot was accepted rather than retried"
    # 🔬 And the second ask has to KNOW. Live 2026-09-02, `l_chart_r3`: the
    # prompt said "at least 850 words" and named no ceiling, so 1745 words was
    # obedience, and the identical retry obeyed identically at 1706. Three
    # tries, three overshoots, and the part shipped at its original 441 words.
    assert told == [0, lt._MAX_SCRIPT_WORDS + 500]


def test_the_full_test_part_is_judged_after_its_figure_work(monkeypatch):
    """The practice path has ended with a gate since the redraw landed; the
    full-test path returned straight after the last repair, so everything the
    figure pass produced shipped unchecked."""
    import inspect

    from app.agents import listening_trainer as lt

    src = inspect.getsource(lt.create_part)
    tail = src[src.rindex("blank_gapped_part_names"):]
    assert "_validate_full_test_part(result)" in tail, (
        "create_part returns without re-judging what its figure pass produced")


def test_the_expansion_prompt_states_the_range_it_wants():
    """A floor with no ceiling is an instruction to overshoot, and it was
    obeyed three times running on one live part."""
    import asyncio

    from app.agents import listening_trainer as lt

    sent = []

    class _Stub:
        is_finetune = False

        async def complete(self, system, messages, **kw):
            sent.append(messages[0]["content"])
            return "TUTOR: and so on."

    lt_client = lt.get_llm_client
    try:
        lt.get_llm_client = lambda *a, **k: _Stub()
        asyncio.run(lt._expand_script("TUTOR: hello.", "Title"))
        asyncio.run(lt._expand_script("TUTOR: hello.", "Title", overshot=1745))
    finally:
        lt.get_llm_client = lt_client

    assert str(lt._MAX_SCRIPT_WORDS) in sent[0], "no ceiling was named"
    assert "1745 words" in sent[1], "the retry did not carry the overshoot"
