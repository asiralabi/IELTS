import asyncio
import logging
import random
import re
from collections import Counter
from functools import partial

from app.agents._figure_pass import (
    repair_dangling_completions,
    redraw_diagram,
    repair_self_answering_callouts,
)
from app.agents._diagram import (
    gap_the_named_answers,
    blank_gapped_part_names,
    blank_self_answering_labels,
    diagram_error,
    inaudible_diagram_error,
    is_diagram,
    is_picture,
    normalize_diagram,
    drop_duplicate_pictures,
    normalize_picture,
    picture_error,
    pictureless_error,
    sparse_diagram_error,
)
from app.agents._flow import (
    flow_error,
    normalize_flow,
    repair_self_answering_steps,
)
from app.agents._notes import (
    fold_extra_sections,
    blank_self_answering_lines,
    is_notes,
    normalize_notes,
    notes_error,
)
from app.agents._marking import mark_answers, mark_full_test
from app.agents._numbering import renumber, renumber_checked
from app.agents._plan import normalize_plan
from app.agents.answerability import (
    MAP_TYPES,
    drop_letter_clash_names,
    RefusedSet,
    absent_answers,
    canon,
    chart_transcription_error,
    cross_section_error,
    dangling_completions,
    dangling_structure_error,
    missing_map_error,
    qtype,
    unlettered_map_error,
    unmarkable_matching_error,
    unnamed_place_error,
    word_limit_error,
)
from app.llm.client import gather_llm, get_llm_client
from app.llm.prompts import (
    EVALUATOR_SYSTEM,
    LISTENING_TRAINER_SYSTEM,
    SCRIPT_EXPANDER_SYSTEM,
)
from app.rag.figures import family_to_ground, figure_conventions
from app.rag.retriever import retrieve_context

logger = logging.getLogger(__name__)

# 🔬 Measured, not assumed. These used to read "7-8 minutes = 1200-1500 words",
# which is what the 30 minutes on the paper's cover suggests — but that half
# hour is four parts PLUS the instructions and the pauses for reading and
# checking answers, not four parts of talking. The 212 real parts in
# `data/datasets/listening_generator_sft.jsonl` say otherwise: median 833 words,
# p10 671, p90 1042, longest 1415.
#
# So the old floor of 1000 sat above the corpus MEDIAN and the expander pushed
# every short script past its p90. Live sets ran 1400-2300 words — half again as
# long as the longest real part — which is what a student notices first, and it
# doubles both the synthesis wait and the recording they have to sit through.
_MIN_SCRIPT_WORDS = 650

# Above the longest part in the corpus (1415). Not a style rule: a script this
# far over is a different exercise from the one the paper is built around, and
# by here it has already survived every other check.
_MAX_SCRIPT_WORDS = 1500

# An answer key that says the script does not answer the question. The model is
# declining, not answering, so the student can never be marked correct — and
# these train it to decline again. Reading is not given this check: 'NOT GIVEN'
# is a real verdict there, and its corpus carries 1 of these against
# Listening's 14.
_REFUSAL_ANSWER = re.compile(
    r"^(not\s+(provided|given|specified|mentioned|stated|available|applicable"
    r"|determined|answerable|clear|known|found|present|included)"
    r"|n/?a|none|unknown|unspecified|no\s+answer"
    r"|cannot\s+be\s+determined|not\s+enough\s+information)\.?$",
    re.IGNORECASE,
)

_BLANK_RE = re.compile(r"^__(\d+)__$")

# Each real IELTS Listening test has four parts of ten questions each, with a
# distinct register and typical figure per part.
_PART_SPECS: dict[int, dict[str, str]] = {
    1: {
        "format": (
            "Part 1: a two-speaker conversation in an everyday social or "
            "transactional context (booking a course, enquiring about a "
            "service, registering for membership). Label turns with character "
            "roles (e.g. 'AGENT:' / 'CALLER:')."
        ),
        "figure": (
            "Build the set around a form_completion or table_completion block "
            "so a TABLE figure is shown (include the `visual` table object). "
            "Fill the rest with short_answer or sentence_completion. Use AT "
            "MOST 2 multiple_choice questions."
        ),
        "types": "form_completion, table_completion, short_answer, multiple_choice",
    },
    2: {
        "format": (
            "Part 2: a single-speaker monologue — a talk, a guided tour, or a "
            "radio segment about a place, facility, or event. Label turns "
            "'SPEAKER:'."
        ),
        "figure": (
            "Include a map_labelling block so a PLAN figure is shown: emit the "
            "`visual` plan object as a grid, where every place a question asks "
            "about is a LETTERED room and its name appears nowhere on the "
            "grid. Only the orientation landmarks are named. Fill the "
            "remaining questions with sentence_completion or matching, plus AT "
            "MOST 2 multiple_choice. map_labelling answers are LETTERS, with "
            "no `options` array."
        ),
        "types": "map_labelling, multiple_choice, short_answer",
    },
    3: {
        "format": (
            "Part 3: an academic discussion between 2-3 speakers (students "
            "and/or a tutor) about an assignment, project, or study topic. "
            "Label each distinct speaker."
        ),
        "figure": (
            "Include a flow_chart_completion block so a FLOW CHART is shown: "
            "emit the `visual` flow object tracing the stages of the project "
            "the speakers discuss, as an ordered list of short steps with 3-7 "
            "of them carrying a `__<n>__` gap, ascending down the chain. The "
            "speakers must talk the plan through in that order. Fill the "
            "remaining questions with a matching block and AT MOST 4 "
            "multiple_choice."
        ),
        "types": "flow_chart_completion, multiple_choice, matching",
    },
    4: {
        "format": (
            "Part 4: a single-speaker academic monologue or lecture on a "
            "research or general-interest topic. Label turns 'LECTURER:'."
        ),
        "figure": (
            "Use note_completion, summary_completion and sentence_completion "
            "(lecture notes with numbered gaps). Do NOT use multiple_choice. "
            "No figure is needed — set `visual` to null."
        ),
        "types": "note_completion, summary_completion, sentence_completion",
    },
}


# The other figure Part 2 can print. The spec is a whole alternative rather
# than a swapped `figure` line, because the talk itself has to change: a
# monologue about a site gives the student nowhere to hang a cross-section, and
# a monologue about a device gives them nowhere to put a floor plan.
_PART2_DIAGRAM: dict[str, str] = {
    "format": (
        "Part 2: a single-speaker monologue about a DEVICE, an appliance or a "
        "piece of equipment — a demonstration, an induction talk, or a "
        "how-it-works segment. The speaker walks through the object part by "
        "part. Label turns 'SPEAKER:'."
    ),
    "figure": (
        "Include a diagram_label_completion block so a DIAGRAM is shown: emit "
        "the `visual` diagram object for the equipment the speaker describes, "
        "choosing the layout that fits it, with 3-6 of its parts numbered "
        "`__<n>__` and the rest carrying printed names that orient the "
        "student. The speaker must walk the parts through in the order they "
        "are listed. Fill the remaining questions with sentence_completion or "
        "short_answer, plus AT MOST 2 multiple_choice."
    ),
    "types": "diagram_label_completion, multiple_choice, short_answer",
}

# How often Part 2 draws the diagram instead of the plan.
#
# Measured over the 77 parsed Cambridge tests
# (`tools/_diag_listening_part2_figures.py`): Part 2 prints 16 figures — 10
# maps, 5 plans and **1 diagram**, so the exam's own rate is 6.2%.
#
# Shipped higher than measured, deliberately. At 1 paper in 16 a student
# practising twenty listening papers would meet an equipment diagram about
# once, and labelling a device from a monologue is a distinct skill from
# finding a room on a plan. A practice generator is judged on coverage, not on
# reproducing the exam's own sampling. One in four keeps the plan clearly
# dominant, which is the part of the measurement that matters.
_PART2_DIAGRAM_SHARE = 0.25


def _part_spec(part_number: int) -> dict[str, str]:
    """This paper's spec for one part, drawn fresh each time it is asked.

    Only Part 2 varies, and it varies per paper the way reading passage 2 does
    in `reading_trainer._passage_types`: both figures route hosted and cost the
    same, so nothing downstream has to know which one was drawn.
    """
    if part_number == 2 and random.random() < _PART2_DIAGRAM_SHARE:
        return _PART2_DIAGRAM
    return _PART_SPECS[part_number]


# Parts whose spec calls for a figure. The generator checkpoint cannot draw one
# — its corpus encodes a part's figure through question types alone and never
# describes the figure itself — so these parts go to the general model, which
# reads the figure schema out of the system prompt.
#
# Part 3 joined them when the flow chart landed. It is the strongest case of
# the three: 0 of the 212 listening SFT sets write a flow_chart_completion
# question at all, so the checkpoint has never seen one, while 6 of the real
# Cambridge Part 3s print a chart.
#
# Part 2 belongs here whichever way `_part_spec` falls: the checkpoint has
# drawn neither a plan nor a diagram.
_FIGURE_PARTS = frozenset({1, 2, 3})

# The same rule stated as question types, for the single-part path where the
# student names the type instead of the part.
# The same rule stated as question types, for the single-part path where the
# student names the type instead of the part. Every one of these prints a
# figure the checkpoint has never described, so an explicit request for one
# goes to the general model.
_FIGURE_ASK = MAP_TYPES | {
    canon("flow_chart_completion"),
    canon("diagram_label_completion"),
    canon("chart_completion"),
    canon("picture_choice"),
    canon("note_completion"),
    canon("summary_completion"),
}


def _finetune_user_message(
    section: int,
    difficulty: str | None,
    topic: str | None,
    question_types: list[str] | None = None,
) -> str:
    """The user turn shape every listening generator SFT record carries.

    Mirrors build_dataset._listening_user_message. Measured against the
    checkpoint: sent this shape it closed the JSON on 6 of 6 samples, peaking at
    2319 output tokens; sent the prose prompt below it looped on a ~78-token
    cycle 1 time in 4 and ran to the 4096-token cap with the object still open.
    The per-part `types` stand in for the `figure` instruction — the corpus
    encodes each part's figure through its question types, and never mentions a
    figure at all.
    """
    return "\n".join([
        "Generate a Listening Test.",
        f"Section: Part {section}",
        f"Difficulty: {difficulty or 'Medium'}",
        f"Topic: {topic or 'unspecified'}",
        "Question Types: "
        + (", ".join(question_types) if question_types else _PART_SPECS[section]["types"]),
        "Target Duration: 7 minutes",
    ])


# Standard Cambridge IELTS (Academic) Listening raw-score → band conversion,
# expressed as (minimum correct out of 40, band). Checked top-down.
_LISTENING_BAND_TABLE: list[tuple[int, float]] = [
    (39, 9.0),
    (37, 8.5),
    (35, 8.0),
    (32, 7.5),
    (30, 7.0),
    (26, 6.5),
    (23, 6.0),
    (18, 5.5),
    (16, 5.0),
    (13, 4.5),
    (10, 4.0),
    (8, 3.5),
    (6, 3.0),
    (4, 2.5),
]


def validate_part(
    result: dict,
    *,
    judge_structure: bool = True,
    judge_matching: bool = True,
    judge_verbatim: bool = True,
    judge_diagram: bool = True,
    judge_picture_count: bool = True,
    judge_map: bool = True,
    judge_notes: bool = True,
) -> str | None:
    """Reject a part a student could not actually sit.

    Passed as the `validate` hook on complete_json so a broken set costs one
    corrective retry instead of reaching the student. The teacher's usual
    failure is emitting a block's shared rubric on its first question and
    leaving the rest with `"question": ""`, which renders as a blank prompt.

    `judge_structure=False` is for the callers that repair a dangling
    completion item afterwards. Measured live, the corrective retry does not
    rescue one — both attempts of both e2e runs failed on it — so spending a
    ~4k-token regeneration on a complaint the repair answers for a few hundred
    tokens buys nothing. Export keeps the default: it has no repair pass, so a
    record that dangles must not become a training target.

    `judge_diagram=False` says the same about the figure: the two faults
    `redraw_diagram` fixes for free — a question with no gap, and two callouts
    on one part — are left unsaid on the way in and judged at full strictness
    by `_gate_after_figure_work`, which runs after the redraw.

    `judge_picture_count=False` runs the other way round, and deliberately: the
    picture count is held at the exam's three on the way IN, where a corrective
    retry is cheap, and relaxed to two afterwards, because
    `drop_duplicate_pictures` may have deleted a twin to make the set markable
    at all. Strict in both places, that repair would refuse the set it fixed.
    """
    # Longer is not harder, it is a different exercise. Judged on the way IN as
    # well as at the gate, deliberately: a corrective retry can write a shorter
    # script for a few hundred tokens, where finding this at the gate throws the
    # questions and the answer key away with it. No trimming — cutting a script
    # down can cut out the sentence an answer is keyed to, and `_grow_script`
    # only ever pushed the other way.
    spoken = len(str(result.get("audio_script") or "").split())
    if spoken > _MAX_SCRIPT_WORDS:
        return (
            f"the script runs to {spoken} words; one Part of real IELTS "
            f"Listening is about 4-5 minutes of speech (median 833 words over "
            f"the corpus, longest 1415), so anything past {_MAX_SCRIPT_WORDS} "
            "is a recording no exam would play. Write the same testable detail "
            "in fewer turns."
        )

    cross_section = cross_section_error(result, "listening")
    if cross_section:
        return cross_section

    # A chart prints every value it holds, so a question keyed to one of them
    # is answered with the passage covered up. Two live sets wrote nine and
    # five of those and both validated clean.
    transcription = chart_transcription_error(result)
    if transcription:
        return transcription

    questions = result.get("questions") or []
    answer_key = result.get("answer_key") or {}
    if not questions or not answer_key:
        return "questions and answer_key must both be non-empty"

    numbers = []
    mc: list[dict] = []
    for q in questions:
        if not isinstance(q, dict):
            return "every entry in questions must be an object"
        if not str(q.get("question") or "").strip():
            return f"question {q.get('number')} has empty question text"
        numbers.append(str(q.get("number")))
        if qtype(q) == canon("multiple_choice"):
            mc.append(q)
    if set(numbers) != set(map(str, answer_key)):
        return "question numbers and answer_key keys must match exactly"

    # Checked before the structure rule below so a set whose real defect is a
    # missing answer is told that, rather than being sent to repair a question
    # whose gap has nothing to fill it. `_REFUSAL_ANSWER` does not match '', and
    # 0 of 3,965 corpus answers are blank, so this rejects nothing we train on.
    unanswered = sorted(num for num, ans in answer_key.items()
                        if not str(ans).strip())
    if unanswered:
        return (
            f"question(s) {', '.join(unanswered)} have no answer in answer_key — "
            "the student can never be marked correct. Key every question with "
            "the words the script actually says."
        )

    if judge_structure:
        dangling = dangling_structure_error(
            questions, result.get("visual"),
            "Membership form — Preferred start date: ______",
        )
        if dangling:
            return dangling

    mapless = missing_map_error(questions, result.get("visual"))
    if mapless:
        return mapless

    unlettered = unlettered_map_error(
        questions, result.get("visual"), answer_key, after_repairs=judge_map)
    if unlettered:
        return unlettered

    broken_flow = flow_error(result.get("visual"), questions, answer_key)
    if broken_flow:
        return broken_flow

    # Listening does not ASK for a drawn diagram yet — Part 2 always calls for
    # the grid plan. The check is wired anyway because `_diagram` is shared
    # with Reading and a figure that reached a part unvalidated is exactly how
    # the grid's renumbering bug survived: the guard costs nothing until the
    # day a part spec starts asking, and then it is already there.
    broken_diagram = diagram_error(
        result.get("visual"), questions, answer_key, after_repairs=judge_diagram
    )
    if broken_diagram:
        return broken_diagram

    broken_notes = notes_error(result.get("visual"), questions, answer_key,
                               after_repairs=judge_notes)
    if broken_notes:
        return broken_notes

    broken_picture = picture_error(result.get("visual"), questions, answer_key,
                                   exam_count=judge_picture_count)
    if broken_picture:
        return broken_picture

    pictureless = pictureless_error(questions, result.get("visual"))
    if pictureless:
        return pictureless

    sparse = sparse_diagram_error(
        [q for q in questions
         if isinstance(q, dict) and qtype(q) == canon("diagram_label_completion")]
    )
    if sparse:
        return sparse

    # The diagram's own rule runs first and at a threshold of one, because its
    # failure is systematic rather than stray: `id` is an internal slug sitting
    # in the payload beside the answer, and its message says so.
    inaudible = inaudible_diagram_error(
        result.get("visual"), answer_key, str(result.get("audio_script") or "")
    )
    if inaudible:
        return inaudible

    unnamed = unnamed_place_error(questions)
    if unnamed:
        return unnamed

    over_limit = word_limit_error(result)
    if over_limit:
        return over_limit

    refusals = [
        f"Q{num}={str(ans).strip()!r}"
        for num, ans in answer_key.items()
        if _REFUSAL_ANSWER.match(str(ans).strip())
    ]
    if refusals:
        return (
            f"these answers say the script does not answer the question: "
            f"{', '.join(sorted(refusals))}. Every question must be answerable "
            "from the audio script. Either add the missing detail to the script "
            "or replace the question with one the script already answers."
        )

    if judge_matching:
        unmarkable = unmarkable_matching_error(questions, answer_key)
        if unmarkable:
            return unmarkable

    for q in mc:
        opts = q.get("options")
        if not isinstance(opts, list) or not opts:
            return f"multiple_choice question {q.get('number')} is missing its options array"
        answer = str(answer_key.get(str(q.get("number"))) or "").strip()
        letters = {chr(ord("A") + i).lower() for i in range(len(opts))}
        if canon(answer) not in {canon(o) for o in opts} | letters:
            return (
                f"the answer to multiple_choice question {q.get('number')} is "
                f"{answer!r}, which is not one of its options "
                f"({', '.join(repr(str(o)) for o in opts)}). Key it to the exact "
                "text of the correct option — a position number cannot be marked."
            )
    # LAST of all the rules, deliberately. Every check above names a specific,
    # actionable fault -- an answer that refuses to answer, one over the word
    # limit, a matching pair whose option was never offered. "The script never
    # says it" is true of all of those as well, so running it first swallowed
    # the useful message: 28 tests asserting the refusal-answer wording started
    # reading this complaint instead.
    if judge_verbatim:
        unheard = _unheard_answers(result)
        if len(unheard) >= _MAX_UNHEARD:
            named = ", ".join(f"Q{n}={a!r}" for n, a in unheard)
            return (
                f"these gap-fill answers are never said in the script: {named}. "
                "A Listening answer is words the student HEARS, so an answer "
                "the recording does not contain cannot be produced or marked. "
                "Either have a speaker say the answer in those words, or key "
                "each gap to the wording already in the script."
            )

    if len(mc) >= 3:
        answers = {str(answer_key.get(str(q.get("number")))).strip().upper() for q in mc}
        if len(answers) == 1:
            return (
                f"all {len(mc)} multiple_choice answers are {answers.pop()!r}; "
                "spread the correct choices across the options"
            )
    return None


async def create_practice(
    question_types: list[str] | None = None,
    difficulty: str | None = None,
    topic: str | None = None,
) -> dict:
    # A student can ask for map labelling or a flow chart on a single part just
    # as parts 2 and 3 of a full test ask for them, and the checkpoint cannot
    # draw either figure that way either — so the same routing applies. See
    # _FIGURE_PARTS.
    client = get_llm_client(
        "generator",
        skip_finetune=bool(
            _FIGURE_ASK.intersection(canon(t) for t in question_types or ())
        ),
    )
    if client.is_finetune:
        # Every corpus record is one numbered part, so the fine-tune needs a
        # section. Spread across all four or the warm pool fills with Part 1
        # transactional conversations.
        parts = [
            _finetune_user_message(
                random.randint(1, 4), difficulty, topic, question_types
            )
        ]
    else:
        parts = ["Generate an IELTS Listening practice set."]
        if question_types:
            parts.append("Question types: " + ", ".join(question_types) + ".")
        if difficulty:
            parts.append(f"Difficulty: {difficulty}.")
        if topic:
            parts.append(f"Topic: {topic}.")

        query = "IELTS Listening script " + (topic or "") + " " + (
            " ".join(question_types) if question_types else "form completion note completion map labelling multiple choice"
        )
        # top_k=1: same reasoning as reading — extra chunks cost input eval time
        # on CPU without a matching quality gain.
        context = retrieve_context(query.strip(), top_k=1)
        if context:
            parts.append(
                "\nReal Cambridge IELTS Listening exemplar — match this style, "
                "conversational register, question type mix, and answer-key format. "
                "Do NOT copy its phrasing, scenarios, or specific answers; use it "
                "as stylistic reference only.\n\n"
                + context
            )

    # How the exam builds this figure, distilled from the books' own figure
    # pages. The exemplar above grounds the script; nothing grounded the
    # figure until this existed. See `reading_trainer` for the longer note.
    figures = figure_conventions(
        family_to_ground(question_types) or "", module="listening", subject=topic or ""
    )
    if figures:
        parts.append(figures)

    result = await client.complete_json(
        LISTENING_TRAINER_SYSTEM,
        [{"role": "user", "content": "\n".join(parts)}],
        required_keys=("title", "audio_script", "questions", "answer_key"),
        validate=partial(
            validate_part,
            judge_structure=False,
            judge_matching=False,
            # Skipped on the way IN so `_repair_unheard_answers` gets its turn;
            # the gate below judges it at full strictness. Reading makes the
            # same promise with `judge_verbatim=False` and keeps it the same
            # way.
            judge_verbatim=False,
            # Likewise for the figure: `redraw_diagram` runs below and fixes
            # both of the faults this drops.
            judge_diagram=False,
        ),
        # A full part is a ~1.7-3.1k-token JSON object, but LLM_MAX_TOKENS is
        # 2048 locally — that truncates mid-JSON on the longer half of the
        # range, and each retry costs another ~5 min. The ~2.9k prompt plus
        # this still fits the checkpoint's 8192 context.
        #
        # That ceiling is the CHECKPOINT's, so it is applied only when the
        # checkpoint is what answers. A figure-bearing request skips the
        # fine-tune and lands on a reasoning model that spends the same budget
        # thinking before it writes — 4096 truncated it mid-JSON on a live
        # Part 2 diagram request (2026-08-28), which is the one path that
        # cannot afford the retry. Left to the configured budget there.
        max_tokens=4096 if client.is_finetune else None,
    )

    # Before the expansion, not after: a label names the field an answer fills
    # and the expander is forbidden to change an answer, so the longer script
    # would only cost input tokens on the repair call.
    await repair_dangling_completions(
        result, str(result.get("audio_script") or ""))
    _repair_compound_matching(result)
    # Skipped on the way in on the promise it would be repaired here.
    #
    # 🔬 Except the FIGURE, which this gate is too early to judge: every one of
    # the diagram repairs — the redraw, the two blankings, the callout rewrite
    # — happens below, and `_gate_after_figure_work` is the gate that holds
    # them to account. Judged here at full strictness it refused sets its own
    # pipeline was about to fix, twice over: "the figure prints 'Hopper' on
    # part 'hopper'" survived a whole sweep after the repair had been moved to
    # run last, because this gate never waited for it.
    problem = validate_part(result, judge_diagram=False, judge_map=False,
                             judge_notes=False)
    if problem:
        raise RefusedSet(
            f"the repaired listening set is invalid: {problem}", result)

    await _grow_script(result)

    _normalize_figure(result)
    # Before the redraw, deliberately: a printed answer whose question has no
    # gap is cured by making that name the gap, and a figure that becomes legal
    # here may skip the redraw altogether. Deterministic — the answer names
    # exactly one part, so there is nothing to infer.
    named_gaps = gap_the_named_answers(result)
    if named_gaps:
        logger.info("gapped the parts printing their own answer: %s",
                    ", ".join(f"{pid}=__{n}__" for pid, n in named_gaps))
    # After the normalisation, so the rewrite sees the boxes the student will.
    await repair_self_answering_steps(result)
    # The drawn figure's version of the same rule. Live Part 2, 2026-08-27:
    # the model named every part AND gave each one a numbered callout, so the
    # espresso machine printed "Water Tank" beside the blank keyed 'water
    # tank', four times over, and the part validated clean. The prompt already
    # says a part is named OR numbered, never both -- which is exactly why this
    # is fixed in code.
    # Draws the figure again in a call that does nothing else, before the
    # cleanups below: a redraw replaces the whole figure and would strand any
    # fix made to the one it replaces.
    await redraw_diagram(result, str(result.get("audio_script") or ""),
                         source_label="Audio script")
    _blank_diagram_answers(result)
    # A callout carrying its own gap cannot be deleted without orphaning a
    # question, and now that it holds a clause there IS something to reword.
    await repair_self_answering_callouts(result)
    # 🔬 LAST, after the rewrite above. `repair_self_answering_callouts`
    # rewords a callout through the model, and the wording it comes back
    # with can be the subject form this repair exists for — "The __1__
    # holds the beans" against a part still printing "Hopper". Run before
    # the rewrite it saw the old text, missed that, and the gate refused
    # the set: 3 of the 9 failures in the 36-set sweep of 2026-08-29.
    blank_gapped_part_names(result)
    _gate_after_figure_work(result)
    return result


# The separator between a matched pair's two halves: a colon, or a dash with
# spaces around it. Searched rather than split on, so the first one wins and a
# value carrying its own colon ("Route A: $10 million") stays intact.
_PAIR_SEP = re.compile(r"\s*(?::|\s[-–—]\s)\s*")


def _matching_pairs(answer: object) -> list[tuple[str, str]]:
    """Split "Emma: Introduction, Jack: Data analysis" into its pairs.

    A fragment carrying no separator is the tail of the value before it — a
    right-hand side with a comma in it — rather than a pair of its own.
    """
    chunks = [c.strip() for c in re.split(r"[;,]", str(answer)) if c.strip()]
    merged: list[str] = []
    for chunk in chunks:
        if _PAIR_SEP.search(chunk):
            merged.append(chunk)
        elif merged:
            merged[-1] += ", " + chunk
    pairs: list[tuple[str, str]] = []
    for chunk in merged:
        sep = _PAIR_SEP.search(chunk)
        left, right = chunk[: sep.start()].strip(), chunk[sep.end():].strip()
        if left and right:
            pairs.append((left, right))
    return pairs


def _repair_compound_matching(result: dict) -> None:
    """Give each matching question ONE pair to answer.

    The teacher writes a whole matching block as a single question and keys the
    entire mapping against it: 58 of 89 corpus matching answers read like
    "Emma: Introduction, Jack: Data analysis, Sarah: Drafting the report". The
    student has one box, so not one of those questions can be marked — and 43
    of the 66 units carrying a matching block have exactly one question in it,
    so this is the shape rather than an accident.

    The pairing itself is sound; only the packing is wrong, and unpacking it
    needs no model call. Each question in the block keeps one pair and the
    other right-hand sides become the options it chooses between, which is what
    a real paper prints. The script still describes every pair, exactly as a
    real recording carries more than it asks about.

    Where the options are the LEFT column — "which speaker said this" — the
    question is turned round instead, so the answer stays inside the list the
    student is shown.

    Left alone when the answer cannot be split, or when the block has more
    questions than pairs. The caller re-validates, so anything unmarkable fails
    loudly rather than reaching a student.
    """
    questions = [q for q in (result.get("questions") or [])
                 if isinstance(q, dict) and qtype(q) == canon("matching")]
    if not questions:
        return
    answer_key = result.get("answer_key") or {}
    variants = result.get("accepted_variants")

    blocks: dict[str, list[dict]] = {}
    for q in questions:
        answer = str(answer_key.get(str(q.get("number"))) or "").strip()
        if answer:
            blocks.setdefault(answer, []).append(q)

    for answer, block in blocks.items():
        pairs = _matching_pairs(answer)
        if len(pairs) < len(block):
            continue
        options = [str(o) for o in (block[0].get("options") or [])]
        # The options list the left column when every pair's left side is in
        # it; then the student is picking the speaker, not the statement.
        inverted = bool(options) and all(
            left in options for left, _ in pairs
        )
        if not inverted:
            options = list(dict.fromkeys(right for _, right in pairs))
        if len(options) < 2:
            continue

        for q, (left, right) in zip(block, pairs):
            number = str(q.get("number"))
            item, keyed = (right, left) if inverted else (left, right)
            rubric = str(q.get("question") or "").strip()
            # The rubric is the block's shared instruction; the item is what
            # this one question asks about. Both, or the question says only how
            # to answer.
            q["question"] = f"{rubric} {item}".strip()
            q["options"] = list(options)
            answer_key[number] = keyed
            if isinstance(variants, dict):
                # Written against the whole mapping, so they describe an answer
                # that no longer exists.
                variants.pop(number, None)
    result["answer_key"] = answer_key


# The expansion gets more than one go at the floor.
#
# 🔬 Measured over the 342-part corpus of 2026-08-29: 21 of them (6%) shipped
# UNDER `_MIN_SCRIPT_WORDS`, the shortest at 395 words — two and a half minutes
# of audio carrying ten questions, where the real exam gives four or five.
# The call site asked once and accepted any growth at all, so a script that
# went 395 -> 500 counted as repaired and shipped a long way under the bar.
# That is the same fault `_repair_unheard_answers` had before `ff549fa`:
# a repair judged against its own progress rather than against the threshold
# it exists to reach.
_EXPAND_TRIES = 3


async def _grow_script(result: dict) -> None:
    """Lengthen a short script until it clears the floor, or run out of tries."""
    for _ in range(_EXPAND_TRIES):
        script = str(result.get("audio_script") or "")
        if len(script.split()) >= _MIN_SCRIPT_WORDS:
            return
        expanded = await _expand_script(script, str(result.get("title") or ""))
        if not expanded or len(expanded.split()) <= len(script.split()):
            return
        # 🔬 Asked for 850 words, a model can hand back 1800. This used to keep
        # whatever came back so long as it was LONGER, so a part that arrived
        # short shipped at twice the length of the longest real one — measured
        # 2026-09-02 on a generated paper whose four parts totalled 5816 words
        # against the ~3300 the exam plays. An overshoot is not growth towards
        # the floor, it is a different fault, and there are tries left to spend.
        if len(expanded.split()) > _MAX_SCRIPT_WORDS:
            logger.info(
                "expansion overshot to %d words; asking again",
                len(expanded.split()))
            continue
        # Kept even when it is still short: each round expands what the last
        # one produced, so two partial gains compound into a whole one.
        result["audio_script"] = expanded


async def _expand_script(
    script: str, title: str, must_say: list[str] | None = None
) -> str | None:
    """Single-call expansion — asks the model to lengthen without changing what
    the speakers established.

    `must_say` is wording the recording has to contain because an answer is
    keyed to it. Reading's `_expand_passage` strikes the identical bargain with
    `must_name`: when the answer is right but unwritten, the SOURCE is made to
    contain it rather than the answer re-keyed to something weaker.
    """
    if not script.strip():
        return None
    prompt = (
        f"Scenario title: {title}\n\nScript to expand:\n{script}\n\n"
        f"Extend this listening script to at least {_MIN_SCRIPT_WORDS + 200} "
        "words — one Part of real IELTS Listening runs about 4-5 minutes of "
        "speech, around 850 words. Keep every "
        "existing turn, speaker label, testable detail, and correction. Add "
        "more turns of natural conversation OR additional monologue detail "
        "as appropriate for the scenario. Do NOT change any answers that "
        "have already been introduced in the script. Return ONLY the "
        "expanded script text with speaker labels — no JSON, no commentary."
    )
    if must_say:
        listed = "; ".join(sorted({str(w).strip() for w in must_say if str(w).strip()}))
        prompt += (
            "\n\nA speaker MUST say each of these wordings aloud, exactly as "
            "written, in a natural sentence: "
            f"{listed}. Work them into what the speakers are already talking "
            "about — do not list them, and never mention questions, diagrams "
            "or answers."
        )
    try:
        expanded = await get_llm_client().complete(
            SCRIPT_EXPANDER_SYSTEM,
            [{"role": "user", "content": prompt}],
        )
    except Exception:
        return None
    expanded = expanded.strip()
    return expanded or None


# ---------------------------------------------------------------------------
# Full 4-part / 40-question test


_renumber = renumber


def _num(value: object, default: float) -> float:
    try:
        f = float(str(value))
        return f if f == f else default  # reject NaN
    except (TypeError, ValueError):
        return default


def _clampi(value: float, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(round(value))))


def _normalize_figure(result: dict) -> None:
    """Clean this part's figure in place, dropping it if nothing is left.

    The plan and the flow chart are both shared with Reading, which draws the
    same shapes with a passage around them instead of a script; only the "put
    it back on the set" half belongs here.
    """
    visual = result.get("visual")
    if not isinstance(visual, dict):
        return
    # Before anything judges the map: a name printed on the letter the student
    # is asked to find is one deletion from legal, and refusing it costs the
    # script, the questions and the key as well.
    clashes = drop_letter_clash_names(result)
    if clashes:
        logger.info("dropped place name(s) printed on a letter: %s",
                    ", ".join(clashes))
    if visual.get("kind") == "plan":
        result["visual"] = normalize_plan(visual)
    elif visual.get("kind") == "flow":
        result["visual"] = normalize_flow(visual)
    elif is_diagram(visual):
        result["visual"] = normalize_diagram(visual)
    elif is_notes(visual):
        result["visual"] = normalize_notes(visual)
        folded = fold_extra_sections(result)
        if folded:
            logger.info("folded %d overflowing notes section(s)", folded)
    elif is_picture(visual):
        result["visual"] = normalize_picture(visual)
        # A picture that repeats another has two correct answers and cannot be
        # marked, so `picture_error` refuses the whole set. Deleting the twin
        # costs one of three drawings and saves the generation.
        gone = drop_duplicate_pictures(result)
        if gone:
            logger.info("dropped duplicate picture(s) %s", ", ".join(gone))


# One stray answer the recording does not say is teacher noise and costs a
# retry for little gain; two in the same set is a habit. The threshold reading
# has used since `84c426c`, kept identical so the two sections are not tuned
# against each other by accident.
_MAX_UNHEARD = 2

# How many times the script expansion is asked to name the answers it missed.
# Three, because each attempt is told only what is STILL unheard, so they are
# corrective rather than repeats — the same reasoning as the figure redraw's
# retries. One attempt let a set die after a repair that had "succeeded".
_UNHEARD_ATTEMPTS = 3


def _unheard_answers(result: dict) -> list[tuple[str, str]]:
    """(question number, answer) for gap-fill answers the script never says.

    A Listening answer is words the student HEARS. Reading has enforced the
    same thing against its passage since `84c426c`; the listening side has
    never had the rule for any question type, which is how a live Part 2 keyed
    'grouphead' against a script saying "group head".

    📏 Measured before it was built, over the 144 gap-fill sets of the
    listening SFT corpus (`tools/_diag_listening_verbatim_cost.py`, which calls
    THIS function rather than restating it). A naive rule flags 82 answers
    across 34.0% of sets, but under half of those flags are the defect:

      46.3%  a number, date, time or price -- '6:00-8:00' for "six to eight",
             '10th March' for "March the tenth". CORRECT answers, and refusing
             them would refuse what the exam itself prints. Skipped.
      12.2%  an answer that is a comma-separated list of items. A different
             defect, and not this rule's business. Skipped.
      41.5%  plain wording. The target.

    Scoped that way, and at the `_MAX_UNHEARD` threshold below, the rule
    **refuses 4.9% of listening sets (7 of 144)** -- and that is before
    `_repair_unheard_answers` gets a chance to rescue any of them. The same
    rule refuses 0% of the reading corpus, because reading's flags fall one to
    a set; listening's cluster.
    """
    return [
        (number, answer)
        for number, answer in absent_answers(
            str(result.get("audio_script") or ""),
            result.get("questions") or [],
            result.get("answer_key") or {},
            skip_numeric=True,
        )
        # A list of items is a different fault; `word_limit_error` and the
        # matching rules are what catch those.
        if "," not in answer
    ]


async def _repair_unheard_answers(result: dict) -> None:
    """Make the recording say the answers it was keyed to but never spoke.

    The cure reading already proved (`c293479`): when the answer is RIGHT and
    the source simply never says it, rewriting the source is cheaper and better
    than re-keying the gap to whatever the source happens to contain. A live
    Part 2 keyed 'group head' off a script that described the part without ever
    naming it; re-keying would have produced a vaguer question, not a better
    one.

    One call, and only for the ~1 set in 6 the rule flags. Verified before it
    is kept: an expansion that does not actually reduce the unheard answers is
    discarded, so a model that ignored the instruction cannot make things worse.
    """
    before = _unheard_answers(result)
    if len(before) < _MAX_UNHEARD:
        return

    # Tried more than once, and judged against the bar that actually refuses
    # the set rather than against "any improvement at all".
    #
    # It used to make ONE call and keep the result whenever it reduced the
    # count. Going from three unheard answers to two is a reduction — and
    # `_MAX_UNHEARD` is 2, so the set was refused anyway and the whole
    # generation was thrown away after a repair that had reported success. A
    # live Part 1 form died exactly that way on 2026-08-29 with Q26='types',
    # Q27='weight', Q28='marker'.
    #
    # Each attempt is told only what is STILL missing, so a second call is
    # corrective rather than another roll of the same dice.
    for _ in range(_UNHEARD_ATTEMPTS):
        missing = _unheard_answers(result)
        if len(missing) < _MAX_UNHEARD:
            return
        expanded = await _expand_script(
            str(result.get("audio_script") or ""),
            str(result.get("title") or ""),
            must_say=[answer for _, answer in missing],
        )
        if not expanded:
            return
        trial = {**result, "audio_script": expanded}
        after = _unheard_answers(trial)
        if len(after) >= len(missing):
            # No progress; another identical call will not make any either.
            logger.info(
                "script expansion made no progress on %d unheard answer(s)",
                len(missing),
            )
            return
        result["audio_script"] = expanded


def _gate_after_figure_work(result: dict) -> None:
    """Judge the set once more, after the figure has been normalised.

    The gate above runs BEFORE `_normalize_figure` and the figure repairs, so
    until now whatever they introduced shipped unchecked. That is the same hole
    `renumber_checked` exists to close on the full-test path: the last step a
    set takes was the one nothing validated.

    🔬 Found live 2026-08-27. A picture-choice came back with pictures A and C
    identical — two correct answers, neither markable. `picture_error` catches
    it exactly, and never ran, because normalisation happened afterwards.
    """
    problem = validate_part(result, judge_picture_count=False)
    if problem:
        raise RefusedSet(
            f"the normalised listening set is invalid: {problem}", result)


def _blank_diagram_answers(result: dict) -> None:
    """Rub out figure text that prints the answer to one of its own gaps.

    Deterministic and cheap, so it runs on every part rather than only when
    something suspects a problem. `diagram_error` deliberately does NOT refuse
    this -- refusing costs a whole regeneration for a fault one deletion fixes,
    the same bargain `_blank_self_answering_cells` strikes on the grid.
    """
    if is_diagram(result.get("visual")):
        blank_self_answering_labels(result)
    blank_self_answering_lines(result)


def _validate_full_test_part(
    result: dict,
    *,
    judge_structure: bool = True,
    judge_matching: bool = True,
    judge_verbatim: bool = True,
    judge_diagram: bool = True,
    judge_map: bool = True,
    judge_notes: bool = True,
) -> str | None:
    """validate_part, plus the count a full test depends on.

    _renumber assigns global numbers positionally as `offset + i + 1`, so a part
    that comes back with nine questions leaves a hole at the seam and one with
    eleven overlaps the next part. The fine-tune is asked in its training shape,
    which states no count, and returned eight questions on 1 of 6 samples.

    The count is judged either way — the repair rewrites a question, it never
    adds one, so a short part still has to be regenerated.
    """
    problem = validate_part(
        result,
        judge_structure=judge_structure,
        judge_verbatim=judge_verbatim,
        judge_diagram=judge_diagram,
        judge_map=judge_map,
        judge_notes=judge_notes,
    )
    if problem:
        return problem
    count = len(result.get("questions") or [])
    if count != 10:
        return f"a full-test part needs exactly 10 questions, not {count}"
    return None


async def create_part(
    part_number: int,
    difficulty: str | None = None,
    topic: str | None = None,
) -> dict:
    """Generate ONE part of a full test (10 questions), globally renumbered."""
    spec = _part_spec(part_number)
    client = get_llm_client(
        "generator", skip_finetune=part_number in _FIGURE_PARTS
    )
    if client.is_finetune:
        parts = [_finetune_user_message(part_number, difficulty, topic)]
    else:
        parts = [
            f"Generate ONE part of an IELTS Listening test. {spec['format']}",
            "Produce EXACTLY 10 questions, numbered 1 to 10.",
            spec["figure"],
        ]
        if difficulty:
            parts.append(f"Difficulty: {difficulty}.")
        if topic:
            parts.append(f"Topic: {topic}.")

        query = f"IELTS Listening Part {part_number} script " + (topic or "")
        context = retrieve_context(query.strip(), top_k=1)
        if context:
            parts.append(
                "\nReal Cambridge IELTS Listening exemplar — match this style, "
                "register, and answer-key format. Do NOT copy its phrasing, "
                "scenario, or answers; use it as stylistic reference only.\n\n"
                + context
            )

    result = await client.complete_json(
        LISTENING_TRAINER_SYSTEM,
        [{"role": "user", "content": "\n".join(parts)}],
        required_keys=("title", "audio_script", "questions", "answer_key"),
        validate=partial(
            _validate_full_test_part,
            judge_structure=False,
            judge_matching=False,
            judge_verbatim=False,
            judge_diagram=False,
        ),
        # A full part is a ~1.7-3.1k-token JSON object, but LLM_MAX_TOKENS is
        # 2048 locally — that truncates mid-JSON on the longer half of the
        # range, and each retry costs another ~5 min. The ~2.9k prompt plus
        # this still fits the checkpoint's 8192 context.
        #
        # That ceiling is the CHECKPOINT's, so it is applied only when the
        # checkpoint is what answers. A figure-bearing request skips the
        # fine-tune and lands on a reasoning model that spends the same budget
        # thinking before it writes — 4096 truncated it mid-JSON on a live
        # Part 2 diagram request (2026-08-28), which is the one path that
        # cannot afford the retry. Left to the configured budget there.
        max_tokens=4096 if client.is_finetune else None,
    )

    # Before _renumber, so the labels are keyed by the numbers the questions
    # still carry.
    await repair_dangling_completions(
        result, str(result.get("audio_script") or ""))
    _repair_compound_matching(result)
    # The same relaxations `create_practice` passes at the same point in its
    # chain, and for the same reason: `_normalize_figure` and every figure
    # repair run BELOW this line, so judging the figure here holds it to a
    # standard nothing has had the chance to meet yet.
    #
    # 🔬 Live 2026-09-02: a whole listening paper was thrown away on "the figure
    # prints 'Power LED' on part 'power' while gap 1 asks the student to name
    # that very part" — the fault `blank_gapped_part_names` deletes for free a
    # few lines further down. That rule's own comment says reaching a gate with
    # one still on the drawing means the repair did not take; here the repair
    # had not RUN. The single-part path has been lenient here since the redraw
    # landed and this path was never brought along.
    problem = _validate_full_test_part(
        result, judge_diagram=False, judge_map=False, judge_notes=False)
    if problem:
        raise RefusedSet(
            f"the repaired listening part is invalid: {problem}", result)

    await _grow_script(result)

    # Checked: the only step a part takes after the gate above, and the one
    # that shipped a reading diagram numbered against the wrong questions.
    renumber_checked(result, (part_number - 1) * 10,
                     _validate_full_test_part)
    _normalize_figure(result)
    # After the renumbering, because the gap numbers it compares against are
    # the ones the part now carries, and after the normalisation, so the
    # rewrite sees the boxes the student will.
    await repair_self_answering_steps(result)
    await redraw_diagram(result, str(result.get("audio_script") or ""),
                         source_label="Audio script")
    _blank_diagram_answers(result)
    await repair_self_answering_callouts(result)
    # 🔬 LAST, after the rewrite above. `repair_self_answering_callouts`
    # rewords a callout through the model, and the wording it comes back
    # with can be the subject form this repair exists for — "The __1__
    # holds the beans" against a part still printing "Hopper". Run before
    # the rewrite it saw the old text, missed that, and the gate refused
    # the set: 3 of the 9 failures in the 36-set sweep of 2026-08-29.
    blank_gapped_part_names(result)
    # The gate the practice path has had since the redraw landed, and this one
    # never grew. Everything above — the expansion, the normalisation, the
    # redraw, the two blankings, the callout rewrite — ran with nothing
    # checking what it produced, which is the same hole `renumber_checked`
    # exists to close: the last step a part takes was the one nothing judged.
    #
    # 🔬 It let a 1820-word script through on 2026-09-02. `_grow_script` had
    # overshot and no one asked again.
    problem = _validate_full_test_part(result)
    if problem:
        raise RefusedSet(
            f"the repaired listening part is invalid: {problem}", result)
    result["part"] = part_number
    return result


async def create_full_test(difficulty: str | None = None) -> dict:
    """Assemble a complete 4-part / 40-question IELTS Listening test.

    The figure parts are served hosted and the rest by the local checkpoint,
    so the two halves genuinely overlap. Asking for all four in one
    gather_llm would put the hosted pair in the local queue, which is
    serialised because ollama answers one call at a time — and a hosted part
    is the slow half of the test, measured at ~20 minutes against ~7 for a
    local one."""
    figure = sorted(_FIGURE_PARTS)
    prose = [n for n in (1, 2, 3, 4) if n not in _FIGURE_PARTS]
    groups = await asyncio.gather(
        gather_llm(
            "generator", [create_part(n, difficulty) for n in figure],
            skip_finetune=True,
        ),
        gather_llm("generator", [create_part(n, difficulty) for n in prose]),
        # Without this the first failure leaves the other half generating
        # unattended, which surfaces later as a stray warning rather than as
        # the error that actually ended the test.
        return_exceptions=True,
    )
    for group in groups:
        if isinstance(group, BaseException):
            raise group
    done = dict(zip(figure, groups[0])) | dict(zip(prose, groups[1]))
    parts = [done[n] for n in (1, 2, 3, 4)]
    return {
        "title": "IELTS Listening Practice Test",
        "kind": "full_listening_test",
        "parts": parts,
    }


async def check_answers(practice: dict, answers: dict) -> dict:
    """Mark a Listening part answer-by-answer with the fine-tuned evaluator."""
    return await mark_answers(
        practice, answers, EVALUATOR_SYSTEM, _LISTENING_BAND_TABLE
    )


async def check_full_test(test_payload: dict, answers: dict) -> dict:
    """Mark all 40 answers part by part, then aggregate."""
    return await mark_full_test(
        test_payload.get("parts") or [],
        answers,
        check_answers,
        _LISTENING_BAND_TABLE,
        "part",
        "parts",
    )
