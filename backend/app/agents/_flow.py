"""The flow chart, shared by Reading and Listening.

Cambridge prints the process a passage or a discussion describes as a chain of
boxes read top to bottom, and numbers some of the words inside them. It is the
one figure the exam uses in BOTH papers and the pipeline could not draw at all:
the reading prompt allowed only a table or a plan, and `_PART_SPECS[3]` said in
so many words "No figure is needed".

Measured over the 77 parsed Cambridge tests (`tools/_diag_flow_chart_shape.py`,
12 real charts -- 6 reading, 6 listening):

  * every one of the 12 is a SINGLE chain. Two carry a side input or a pair of
    parallel theories, so branching is real but rare; a linear-only schema
    covers 10 of 12 and keeps the renderer derivable from the step list alone.
  * 4-10 boxes, 3-7 numbered gaps, gaps ascending down the chain.
  * some boxes carry no gap at all -- they are what tells the student where in
    the process they are.

The grid figures state where a thing IS and let the renderer derive the walls.
A flow chart states only the ORDER, and the arrows are derived from it, which
is the same bargain: nothing the generator can get wrong geometrically.
"""

import re

from app.agents._marking import norm
from app.llm.client import get_llm_client
from app.llm.prompts import FLOW_RESTEP_SYSTEM

FLOW_KIND = "flow"

# A gap the student writes into, anywhere inside a step's sentence. The plan
# grid can anchor its gaps because a whole cell IS the gap; a flow step is
# prose, so the marker has to be found mid-sentence.
FLOW_GAP_RE = re.compile(r"__(\d+)__")

# Ranges taken from the 12 real charts (4-10 boxes, 3-7 gaps), opened by a step
# at each end. A validator that refuses what Cambridge prints is wrong by
# definition, so the observed span is the floor for what is allowed, never the
# ceiling.
_MIN_STEPS = 3
_MAX_STEPS = 12
_MIN_GAPS = 3
_MAX_GAPS = 8


# Words that carry no content on their own. A real completion answer is a noun,
# an adjective or a number; a "answer" made of nothing but these is not an
# answer to anything, and matching one against a step's prose is meaningless
# because it appears everywhere.
#
# Live on 2026-08-25 a reading chart keyed its four gaps 'to create',
# 'to identify', 'that meets' and 'of the' — every gap placed after an already
# complete sentence, keyed with the fragment that would have begun the next
# clause. Two of them "matched" other boxes, which is a detector firing on a
# defect that belongs to the answer key.
_FUNCTION_WORDS = {
    "a", "an", "the", "and", "or", "but", "of", "to", "in", "on", "at", "by",
    "for", "from", "with", "into", "onto", "over", "under", "as", "is", "are",
    "was", "were", "be", "been", "being", "that", "which", "who", "this",
    "these", "those", "it", "its", "their", "his", "her", "not", "no", "then",
    "than", "so", "if", "up", "out", "off", "about", "after", "before",
}


def _has_content_word(text: str) -> bool:
    words = norm(text).split()
    return any(w not in _FUNCTION_WORDS for w in words)


# An answer opening with one of these is a CLAUSE continuing the step's
# sentence, not a word filling a slot in it. Deliberately narrower than "any
# sentence-continuing word": a prepositional answer is legitimate — "when
# should you book? / in advance" — and the wide form refuses two such answers
# in the corpus. Measured over all 1,337 open gap-fill answers in the two
# generator corpora, this narrow form flags 3, and all 3 are themselves broken
# ('to scatter sound waves', 'to compensate for the background noise', 'are
# often overlooked in conservation efforts'). See
# `tools/_diag_fragment_answers.py`.
_FRAGMENT_OPENERS = {
    "to", "that", "which", "and", "or", "but", "is", "are", "was", "were",
}


# The rewrite is a short call, so trying again is nearly free against the 151s
# a regeneration costs. It is needed: measured live, 2 of 3 attempts filled the
# `__n__` blank in rather than copying it through, and each attempt is an
# independent sample rather than a corrective retry.
_REWRITE_ATTEMPTS = 3


def _fragment_answer(text: str) -> bool:
    words = norm(text).split()
    return bool(words) and (
        words[0] in _FRAGMENT_OPENERS or not _has_content_word(text)
    )


def is_flow(visual: object) -> bool:
    return (
        isinstance(visual, dict)
        and str(visual.get("kind", "")).lower() == FLOW_KIND
    )


def flow_steps(visual: object) -> list[str]:
    """The chart's boxes as text, in order, blanks and all."""
    if not is_flow(visual):
        return []
    steps = visual.get("steps")
    if not isinstance(steps, list):
        return []
    return [str(s).strip() for s in steps if str(s or "").strip()]


def flow_gaps(visual: object) -> list[str]:
    """Gap numbers in the order the student meets them, top of the chart down."""
    return [
        n for step in flow_steps(visual) for n in FLOW_GAP_RE.findall(step)
    ]


def normalize_flow(visual: object) -> dict | None:
    """Clean a generated flow chart, or None if it is not one.

    Blank steps are dropped rather than rendered as an empty box, and a gap
    written `__ 6 __` or `___6___` is folded to the one form the renderer and
    `visual_slots` both read. Nothing structural is repaired here -- that is
    `flow_error`'s job, and a repair that quietly fixed a broken chart would
    hide the case the validator exists to catch.
    """
    if not is_flow(visual):
        return None
    steps = [
        re.sub(r"_+\s*(\d+)\s*_+", r"__\1__", step)
        for step in flow_steps(visual)
    ]
    out = {
        "kind": FLOW_KIND,
        "title": str(visual.get("title") or "").strip(),
        "steps": steps,
    }
    return out


def self_answering_steps(
    visual: object, answer_key: dict
) -> list[tuple[str, str, int]]:
    """(gap, answer, 1-based box) for every gap whose answer another box prints.

    The chart's version of the self-answering grid cell `65f38ab` fixed: the
    student works down the chain, meets a blank, and finds the word for it
    printed two boxes further on. Found live on the first reading chart the
    engine ever wrote (2026-08-25) — gap 2 keyed 'success' against a box
    opening "Despite its success".

    The single definition, shared by the repair, the audit tool and the live
    harnesses. Duplicating it is how a repair comes to fix a different set than
    the audit reports.

    A gap's OWN box is searched too, which is where this departs from
    `_blank_self_answering_cells`. A grid cell either IS the gap or is a label,
    so there is nothing else in it to give the answer away; a step is a whole
    sentence wrapped around its gap and can perfectly well print the word
    beside it — "The safety record, or __3__, was questioned" hands over gap 3
    without another box being involved. Only the `__n__` markers themselves are
    taken out of the text before matching, since they never carry answer words.

    Matched on whole words: an unpadded substring match finds "six" inside
    "sixteen", and the live listening chart keyed a gap 'six'.
    """
    steps = flow_steps(visual)
    out: list[tuple[str, str, int]] = []
    for gap in flow_gaps(visual):
        raw = str((answer_key or {}).get(gap) or "")
        want = norm(raw)
        # A fragment answer — 'of the', 'to identify', 'that meets' — is a
        # defect of the KEY, and `flow_error` refuses the whole set for it
        # before any repair runs. Matching one here would be meaningless
        # anyway: those words appear in almost any prose, and no rewrite can
        # take "of the" out of a step. Skipped so the measurement counts the
        # self-answering box and nothing else.
        if not want or _fragment_answer(raw):
            continue
        for i, step in enumerate(steps, start=1):
            prose = norm(FLOW_GAP_RE.sub(" ", step))
            if f" {want} " in f" {prose} ":
                out.append((gap, str((answer_key or {}).get(gap)).strip(), i))
    return out


def _word_re(word: str) -> re.Pattern:
    return re.compile(rf"(?<!\w){re.escape(word.strip())}(?!\w)", re.IGNORECASE)


async def _rewrite_step(
    step: str, banned: list[str], title: str, answer_key: dict
) -> str | None:
    """One short call for one box, in the idiom of the other repairs.

    A regeneration costs a hosted passage of 2.5-25 minutes; rewording one
    sentence is a sub-task worth a few hundred tokens. Returns None whenever
    the reply is unusable, so the caller can leave the chart exactly as it
    found it — no worse than not having tried.

    **The model never sees the gap.** Every attempt to send it one came back
    with the blank filled in: `__4__` answered "safety" on 4 tries out of 4,
    and a `PLACEHOLDERX4` token invented to look like a word rather than a
    blank was resolved to "safety" just the same on 3 more. It is not
    disobeying an instruction — it is completing a sentence whose missing word
    the context makes obvious, and no wording stops that.

    So the gap is filled in with its own keyed answer before the call and
    blanked again afterwards. The model is handed an ordinary sentence, does
    the one job it is good at, and the coupling to the questions is restored
    here rather than trusted to survive the trip.
    """
    filled = step
    restore: list[tuple[str, str]] = []
    for gap in FLOW_GAP_RE.findall(step):
        answer = str((answer_key or {}).get(gap) or "").strip()
        # A gap whose OWN answer is the word being removed cannot be filled in:
        # both copies would read the same and the rewrite would take them both.
        # Left as a marker, and judged by the caller like any other reply.
        if not answer or any(_word_re(b).search(answer) for b in banned):
            continue
        filled = filled.replace(f"__{gap}__", answer, 1)
        restore.append((gap, answer))

    forbidden = "; ".join(sorted({b.strip() for b in banned if b.strip()}))
    prompt = (
        f"Flow chart title: {title}\n\n"
        f"The step to rewrite:\n{filled}\n\n"
        f"Words this step must NOT contain: {forbidden}\n\n"
        "Rewrite that one step."
    )
    try:
        # Hosted. `get_llm_client("generator")` lands on the local fine-tune,
        # whose SFT corpus never mentions a figure — the exact case
        # `skip_finetune` exists for, and this is figure text. Written before
        # the 2026-08-27 model swap, when the general model and the checkpoint
        # were closer in what they would attempt.
        #
        # The 256-token cap was suspected of the same fault and MEASURED
        # instead (`tools/_diag_token_cap_probe.py`, gpt-oss-120b): on a
        # one-sentence rewrite every cap from 256 up returns clean JSON in
        # under 4s, and only 128 comes back empty. A reasoning model does eat
        # its budget before it writes, but on an output this small it does not
        # get near it. The cap stays.
        reply = await get_llm_client(
            "generator", skip_finetune=True
        ).complete_json(
            FLOW_RESTEP_SYSTEM,
            [{"role": "user", "content": prompt}],
            required_keys=("step",),
            max_tokens=256,
        )
    except Exception:
        return None
    text = str(reply.get("step") or "").strip()
    if not text:
        return None

    # Put each gap back where its answer now sits. Exactly one occurrence, or
    # the blank would land on the wrong words — the caller's gap check would
    # catch a miss, but not a mislanding.
    for gap, answer in restore:
        found = _word_re(answer).findall(text)
        if len(found) != 1:
            return None
        text = _word_re(answer).sub(f"__{gap}__", text, count=1)
    return text


async def repair_self_answering_steps(
    result: dict,
) -> list[tuple[int, str, str]]:
    """Reword a box that prints the answer another box asks for.

    A repair rather than a refusal, decided the way the grid figure's guard
    was: refusing costs a whole hosted generation, and the offending box
    usually carries a gap of its own, so it cannot simply be dropped either.

    Re-keying the gap — the cure `_repair_duplicate_diagram_answers` uses — is
    wrong here. The live case keyed gap 2 'success' against "its maiden flight,
    which was a ___", where 'success' is the RIGHT answer; what is wrong is the
    later box saying it. So the box moves, not the key.

    Every rewrite is judged before it is kept: it must still be a usable step,
    must not have swallowed or invented a `__n__` gap, and must not print any
    other gap's answer either. Returns the (box, before, after) triples the
    caller can log.
    """
    visual = result.get("visual")
    if not is_flow(visual):
        return []
    answer_key = result.get("answer_key") or {}
    clashes = self_answering_steps(visual, answer_key)
    if not clashes:
        return []

    steps = flow_steps(visual)
    title = str(visual.get("title") or "")
    changed: list[tuple[int, str, str]] = []

    # One call per offending box, not per clash — a single box can print two
    # different gaps' answers, and rewriting it twice would undo the first fix.
    by_box: dict[int, list[str]] = {}
    for _, answer, box in clashes:
        by_box.setdefault(box, []).append(answer)

    for box, banned in sorted(by_box.items()):
        original = steps[box - 1]
        # Measured against the chart as it stands NOW, not as it arrived: an
        # earlier box may already have been reworded, and comparing against the
        # original clash list would then reject a good fix for having removed
        # a clash that was already gone.
        before = self_answering_steps({**visual, "steps": steps}, answer_key)
        want = [c for c in before if c[2] != box]

        for _ in range(_REWRITE_ATTEMPTS):
            rewritten = await _rewrite_step(original, banned, title, answer_key)
            if not rewritten:
                continue
            # The gaps are the chart's coupling to the questions, and the model
            # habitually ANSWERS one instead of copying it through — measured
            # 2 times out of 3 on the live chart, "the aircraft's __4__"
            # coming back as "the aircraft's safety". Rejecting that is the
            # whole reason a rewrite is judged rather than trusted.
            if FLOW_GAP_RE.findall(original) != FLOW_GAP_RE.findall(rewritten):
                continue
            trial = [*steps]
            trial[box - 1] = rewritten
            if self_answering_steps({**visual, "steps": trial}, answer_key) != want:
                # Either the word survived the rewrite or the new wording
                # printed some other gap's answer. Both leave it no better.
                continue
            steps = trial
            changed.append((box, original, rewritten))
            break

    if changed:
        visual["steps"] = steps
    return changed


def flow_error(visual: object, questions: list, answer_key: dict) -> str | None:
    """Reject a flow chart the student could not work down.

    Structural only, on purpose. The self-answering failure the grid figure has
    -- one box printing the word another box's gap asks for -- is asked for in
    the prompt but not refused here, because the shape of that guard should be
    decided on live evidence the way `_blank_self_answering_cells` was: three
    hosted samples did it three times out of three, and a hard check written
    before that measurement would have made the path ungeneratable.
    """
    if not is_flow(visual):
        return None

    steps = flow_steps(visual)
    if len(steps) < _MIN_STEPS:
        return (
            f"the flow chart has only {len(steps)} step(s). A chart is a chain "
            f"of at least {_MIN_STEPS} boxes read top to bottom; with fewer "
            "there is no process for the student to follow. Write the stages "
            "the passage describes as an ordered list of short lines."
        )
    if len(steps) > _MAX_STEPS:
        return (
            f"the flow chart has {len(steps)} steps, more than the {_MAX_STEPS} "
            "a printed chart holds. Merge the stages that belong together."
        )

    bare = [i + 1 for i, s in enumerate(steps) if not FLOW_GAP_RE.sub("", s).strip()]
    if bare:
        return (
            f"step(s) {', '.join(map(str, bare))} of the flow chart contain "
            "nothing but their own gap. A box has to say what stage it is, or "
            "the student is asked to fill a blank with no context at all — "
            'write it as e.g. "the resin is cooled until __5__".'
        )

    gaps = flow_gaps(visual)
    if len(gaps) != len(set(gaps)):
        repeated = sorted({g for g in gaps if gaps.count(g) > 1}, key=int)
        return (
            f"the flow chart draws gap {', '.join(repeated)} more than once. "
            "One question is one box to write in, so each number may appear at "
            "exactly one point in the chain."
        )
    if len(gaps) < _MIN_GAPS:
        return (
            f"the flow chart numbers only {len(gaps)} gap(s); number at least "
            f"{_MIN_GAPS}. A chart with fewer is a drawing rather than a "
            "question block, and Cambridge never prints one."
        )
    if len(gaps) > _MAX_GAPS:
        return (
            f"the flow chart numbers {len(gaps)} gaps, more than the "
            f"{_MAX_GAPS} a printed chart carries. Leave more of the stages "
            "complete so the student can see where they are in the process."
        )

    ordered = sorted(gaps, key=int)
    if gaps != ordered:
        return (
            f"the flow chart's gaps run {', '.join(gaps)} down the chain. The "
            "student works from the top box to the bottom one, so the numbers "
            f"must ascend with them: renumber them {', '.join(ordered)} in that "
            "order, and key the answers to match."
        )

    # A gap is a box on the page; a question is what the student is asked. One
    # without the other is unanswerable in one direction or unmarkable in the
    # other, and both have shipped from the equivalent table and grid figures.
    numbered = {str(q.get("number")) for q in questions if isinstance(q, dict)}
    orphan = [g for g in gaps if g not in numbered]
    if orphan:
        return (
            f"the flow chart numbers gap(s) {', '.join(orphan)}, but the set "
            "has no question with those numbers. Every numbered gap is one "
            "question; either ask it or fill the box in."
        )

    keys = {str(k) for k in (answer_key or {})}
    unkeyed = [g for g in gaps if g not in keys]
    if unkeyed:
        return (
            f"the flow chart's gap(s) {', '.join(unkeyed)} have no answer_key "
            "entry, so nothing marks them."
        )

    # The gap has to be a slot INSIDE the step, not a tail hanging off the end
    # of one. A live chart (2026-08-25) put every gap after an already complete
    # sentence and keyed the fragment that would have begun the next clause —
    # "The team defines the initial aim of the project ______" answered "to
    # create". Structurally that set is perfect: 4 gaps, ascending, each with a
    # question and a key. It is only the answers that give it away.
    #
    # Refused rather than repaired, unlike the self-answering box: re-keying a
    # gap whose POSITION is wrong does not fix the step, and there is nothing
    # else to move. Scoped to the chart, so it refuses nothing that was ever
    # trained on — no corpus set carries a flow `visual` at all.
    # A gap answered from a LETTERED BOX is exempt. Cambridge prints the flow
    # chart both ways — "Choose FIVE answers from the box and write the correct
    # letter, A-H" as often as "Choose NO MORE THAN TWO WORDS" — and the
    # corpus bears it out: of the 12 real charts distilled into
    # `data/figure_knowledge/`, 5 are `lettered_box` against 5
    # `words_from_text`. The model kept producing the lettered form and this
    # check kept refusing it as a fragment, because a bare "A" has no content
    # word; two live listening sets died that way on 2026-08-28.
    #
    # Exempt only when the QUESTION actually offers the letters. A lettered
    # answer with no options printed is still broken — the student would see a
    # blank with nothing to choose from — and that is what the refusal is for.
    lettered = {
        str(q.get("number"))
        for q in questions or []
        if q.get("options")
    }
    fragments = [
        (g, str((answer_key or {}).get(g)).strip())
        for g in gaps
        if g not in lettered
        and _fragment_answer(str((answer_key or {}).get(g) or ""))
    ]
    if fragments:
        named = ", ".join(f"gap {g} is answered {a!r}" for g, a in fragments)
        return (
            f"these flow chart answers are sentence fragments, not answers: "
            f"{named}. A gap is a slot inside a step — the step reads as a "
            "whole sentence with one word or phrase missing from the MIDDLE of "
            'it, e.g. "The stage one resin, called __4__, is cooled". Putting '
            "the gap after a step that is already complete leaves the student "
            "nothing to write, so move each gap into its step and key it to "
            "the word or short phrase that belongs there."
        )
    return None
