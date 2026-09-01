"""Shared answerability checks for generated practice sets.

Both trainers pass these through `complete_json(validate=...)`, so a set that
reaches a student is held to this standard.

Export is aligned with generation: `build_dataset._is_answerable` runs each
section's own validator, so a set the runtime would have retried never becomes
a training target either. Listening ran on a weaker inline check until the
multi-task retrain, because the shipped single-task checkpoint had been trained
against what that looser filter produced and tightening it mid-life would have
desynced the committed jsonl from the model.
"""

import json
import re


class RefusedSet(ValueError):
    """A generated set a validator rejected, carried with the set itself.

    Subclasses `ValueError` because every caller already catches that and
    regenerates; nothing upstream needs to change. What it adds is `.result` --
    the rejected set, which until now was dropped on the floor at the `raise`.

    🔬 Why it exists: `figure_sweep.py` saves only the sets that PASS, so the
    one artifact that would diagnose a live refusal never survived the run.
    Two picture-choice sets died on "pictures A and B are the same drawing"
    (2026-09-01) with nothing left to look at, and the count rule that was
    supposed to close it was already proven reachable -- so the evidence, not
    another guess, is what was missing.
    """

    def __init__(self, message: str, result: dict | None = None) -> None:
        super().__init__(message)
        self.result = result

def canon(name: str) -> str:
    """Canonical key for a question type.

    The system prompts declare snake_case but the teacher also emits display
    forms like "True/False/Not Given", so anything short of stripping every
    non-alphanumeric leaves those unmatched — and an unmatched type silently
    skips the checks written for it.
    """
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


def qtype(q: dict) -> str:
    return canon(q.get("type"))


# Completion types the teacher writes as a printed block ("complete the notes
# below"). Nothing in the frontend renders such a block — `question-list.tsx`
# shows only question text plus options — so the context has to be inline.
STRUCTURE_TYPES = {canon(t) for t in (
    "summary_completion",
    "note_completion",
    "flow_chart_completion",
    "table_completion",
    "form_completion",
    "diagram_label_completion",
)}

# Labelling types the figure DEFINES rather than merely illustrates. A
# completion item can inline its own gap and survive without the block it
# names; these cannot, because the answer is a position on the drawing.
MAP_TYPES = {canon(t) for t in ("map_labelling", "plan_labelling")}

# Words a gap usually supplies for itself, so an answer that opens with one is
# the same answer without it.
_ARTICLES = {"a", "an", "the"}


def span_tokens(text: str) -> list[str]:
    """Words of `text` reduced to a comparable form: punctuation and casing
    dropped, "per cent"/"%" folded to one spelling, leading article stripped.

    Lives here rather than in either trainer because both sections ask the same
    question of their own source -- is this answer actually IN the passage /
    the script -- and two copies of "is this a span of that" is how one of them
    comes to accept what the other refuses.
    """
    lowered = str(text).lower().replace("per cent", "percent").replace("%", " percent ")
    words = re.sub(r"[^a-z0-9]+", " ", lowered).split()
    while words and words[0] in _ARTICLES:
        words = words[1:]
    return words


def loose_stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) > 4 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


# A time, a date, a price, a phone number, a quantity: what the speaker says in
# words and the student is expected to write in figures. Measured 2026-08-27
# over the listening corpus (`tools/_diag_listening_verbatim_cost.py`): these
# are 45.1% of everything a naive verbatim rule flags there, and every one of
# them is a CORRECT answer -- "six to eight" keyed '6:00-8:00', "March the
# tenth" keyed '10th March'. A rule that counted them would refuse what the
# exam itself prints.
_NUMBER_WORDS = {
    # cardinals
    "zero", "oh", "nought", "one", "two", "three", "four", "five", "six",
    "seven", "eight", "nine", "ten", "eleven", "twelve", "thirteen",
    "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen",
    "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty",
    "ninety", "hundred", "thousand", "million", "double", "and",
    # ordinals, which is how a spoken date reaches a written one
    "first", "second", "third", "fourth", "fifth", "sixth", "seventh",
    "eighth", "ninth", "tenth", "eleventh", "twelfth", "thirteenth",
    "twentieth", "thirtieth",
    # fractions and clock words
    "half", "quarter", "past", "to", "am", "pm", "oclock",
}


def is_numeric_answer(answer: str) -> bool:
    """True if the answer is a figure the script would speak rather than spell."""
    text = str(answer)
    if any(ch.isdigit() for ch in text):
        return True
    words = span_tokens(text)
    return bool(words) and all(w in _NUMBER_WORDS for w in words)


def absent_answers(
    source: str,
    questions: list,
    answer_key: dict,
    *,
    skip_numeric: bool = False,
) -> list[tuple[str, str]]:
    """(question number, answer) for gap-fill answers not found in `source`.

    `source` is the passage for Reading and the audio script for Listening. A
    completion answer the student cannot find is one they cannot write, whether
    they were told to read it or to hear it.

    Matched on whole words after a loose stem, so "gaining"/"gain" agree. An
    answer offering its own word box is skipped -- it is answered from the box.
    `skip_numeric` drops figures, which Listening needs and Reading does not:
    measured over both corpora, numeric answers are 45.1% of listening flags
    and 0% of reading ones.
    """
    words = span_tokens(source or "")
    if not words:
        return []
    haystack = f" {' '.join(words)} "
    stemmed = f" {' '.join(loose_stem(w) for w in words)} "
    missing: list[tuple[str, str]] = []
    for q in questions or []:
        if not isinstance(q, dict) or qtype(q) not in GAP_FILL_TYPES:
            continue
        if isinstance(q.get("options"), list) and q["options"]:
            continue
        answer = (answer_key or {}).get(str(q.get("number")))
        if answer is None:
            continue
        for cand in (str(answer).split(";") if ";" in str(answer) else [str(answer)]):
            if skip_numeric and is_numeric_answer(cand):
                continue
            tokens = span_tokens(cand)
            if not tokens:
                continue
            span = f" {' '.join(tokens)} "
            span_stem = f" {' '.join(loose_stem(w) for w in tokens)} "
            if span not in haystack and span_stem not in stemmed:
                missing.append((str(q.get("number")), cand.strip()))
    return missing

# Figure kinds that carry a drawn layout, and both are generated again as of
# 2026-08-28. `plan` states which room owns which grid cell and lets the
# renderer derive the walls — right for the inside of a building, where rooms
# share walls. `map` places features at coordinates with paths between them —
# right for a park, a town or a site, where things stand apart. The map form
# had gone ungenerated for months while every outdoor place was drawn as a grid
# of touching rooms.
LAYOUT_KINDS = {"plan", "map"}

# A gap the student writes into: underscores, or the dotted leader a real exam
# paper prints. Three dots are an ellipsis, so a leader needs four.
GAP_MARKER = re.compile(r"__+|\.{4,}")

# Types whose answer the student types into a gap, so a word cap applies.
GAP_FILL_TYPES = {canon(t) for t in (
    "sentence_completion",
    "summary_completion",
    "short_answer",
    "note_completion",
    "table_completion",
    "form_completion",
    "flow_chart_completion",
    "diagram_label_completion",
)}


_WORD_TO_INT = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}


def parse_word_limit(value: object) -> int | None:
    """Integer word cap from a `word_limit` field.

    Both contracts declare it an int, but the teacher often answers with the
    rubric sentence instead ('NO MORE THAN TWO WORDS AND/OR A NUMBER'). A bare
    int() on that raises, and the caller that swallows the error then skips the
    cap check entirely — so read the phrasing rather than trusting the type.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().lower()
    if not text:
        return None
    digits = re.search(r"\d+", text)
    if digits:
        return int(digits.group())
    for word, n in _WORD_TO_INT.items():
        if re.search(rf"\b{word}\b", text):
            return n
    return None


# Top-level keys that belong to exactly one section's contract. A multi-task
# fine-tune is trained on both schemas from one adapter, so the failure to
# catch is a Reading set that grows an `audio_script` — or a Listening set that
# answers with a `passage`. Either is unservable: the wrong page renders it.
_SECTION_KEYS = {
    "reading": {"passage"},
    "listening": {
        "blueprint", "audio_script", "speakers",
        "accepted_variants", "answer_positions",
    },
}


def _value_key(value: object) -> str:
    """A chart value and an answer reduced to the same comparable form.

    Numerically where both are numbers: a bar drawn at 58.0 and an answer
    written "58" are the same thing to a student and must be the same thing
    here, but `span_tokens` splits the decimal and they stop matching.
    """
    text = str(value if value is not None else "").strip()
    try:
        number = float(text.replace(",", ""))
    except ValueError:
        return " ".join(span_tokens(text))
    return f"{number:g}"


def chart_transcription_error(result: dict) -> str | None:
    """Reject chart questions answered by reading a number off the chart.

    A bar, line or pie chart prints every value it holds — unlike a table,
    whose whole point is the cell it leaves blank. So it is fatally easy to
    write "According to the chart, the average daily water use for bathing is
    ______" and key it to the number already drawn on the bar. The student
    answers it with the passage covered up, and the figure has replaced the
    text instead of supporting it.

    Measured live 2026-08-28: one reading set wrote NINE of these in a row, a
    second wrote five, and both validated clean. The prompt now forbids it;
    this is the half that cannot be skimmed.

    Tables are exempt: their answers are the cells the figure does NOT print,
    which is the opposite arrangement.
    """
    visual = result.get("visual")
    if not isinstance(visual, dict) or str(visual.get("kind", "")).lower() != "chart":
        return None
    if str(visual.get("chart_type", "")).lower() == "table":
        return None

    printed: set[str] = set()
    for row in visual.get("series") or []:
        if not isinstance(row, dict):
            continue
        for point in row.get("data") or []:
            if isinstance(point, (list, tuple)) and len(point) >= 2:
                printed.add(_value_key(point[1]))
    printed.discard("")
    if not printed:
        return None

    answer_key = result.get("answer_key") or {}
    copied = [
        str(q.get("number"))
        for q in result.get("questions") or []
        if isinstance(q, dict) and qtype(q) == canon("chart_completion")
        and _value_key(answer_key.get(str(q.get("number")))) in printed
    ]
    if len(copied) < 2:
        # One such question is a reading-off task the exam does set. A block of
        # them is a figure standing in for the passage.
        return None
    return (
        f"question(s) {', '.join(copied)} are answered by copying a number the "
        "chart already prints, so a student can answer them without opening "
        "the passage. A chart question must need the TEXT as well as the "
        "figure — ask for the reason behind a value, the name the passage "
        "gives a category, a trend in the passage's own words, or what the "
        "passage says follows from the figure."
    )


def cross_section_error(result: dict, section: str) -> str | None:
    """Reject a set that answers in the other section's schema."""
    foreign = sorted(
        key
        for other, keys in _SECTION_KEYS.items()
        if other != section
        for key in keys
        if result.get(key)
    )
    if foreign:
        return (
            f"this is an IELTS {section.title()} set but it carries "
            f"{', '.join(foreign)} — those belong to a different section's "
            f"contract. Return only the keys the {section.title()} schema "
            "declares."
        )
    # 🔬 This used to refuse `kind: "map"` outright in a Reading set, on the
    # grounds that "Reading never asks for a position on a map". That was true
    # only because nothing could DRAW an outdoor map — the renderer existed but
    # no prompt emitted one, so every open place came out as a grid of rooms
    # and an excavated Roman town was laid out like a floor plan.
    #
    # Reading does print a map: the route a migration took, the layout of an
    # excavated settlement, the grounds of a site the passage describes. It is
    # allowed from 2026-08-29, when `map_labelling` learned to choose between
    # the plan and the map. Removing the refusal without saying so would leave
    # the next reader wondering why the comment above disagreed with the code.
    return None


def visual_slots(visual: object) -> set[str]:
    """Question numbers the `visual` object supplies a fillable cell for."""
    if not visual:
        return set()
    return set(re.findall(r"__(\d+)__", json.dumps(visual, ensure_ascii=False)))


def is_self_contained(text: str) -> bool:
    """True if the item can be answered without the printed block it names.

    Either it shows its own gap, or it is a direct question ("What did the
    Greeks add to the alphabet?") — mistyped as a completion type, but the
    student can still answer it from the passage or script alone.
    """
    return bool(GAP_MARKER.search(text)) or text.rstrip().endswith("?")


def answer_word_count(answer: object) -> int:
    """Words in an answer, treating pure numbers as 0 — the IELTS rubric does
    not count a number toward the word cap."""
    tokens = [t for t in str(answer).strip().split() if t]
    return sum(0 if t.replace(",", "").replace(".", "").isdigit() else 1 for t in tokens)


# The teacher habitually states "ONE WORD" then keys a two- or three-word
# answer, and build_dataset._reconcile_word_limits forgives exactly that by
# raising the cap. Measured on raw pre-reconciliation output, an overrun of 1-2
# words covers 35.3% of listening units and 9.6% of reading ones, so rejecting
# it would cost a regeneration for what is only clumsy phrasing. Beyond that
# margin the answer has stopped being a gap filling at all.
_WORD_LIMIT_SLACK = 2


def word_limit_error(result: dict) -> str | None:
    """Reject an answer key the student is forbidden to write.

    `word_limit` is shown as the rubric, so an answer longer than it can never
    be entered: the student obeys "NO MORE THAN TWO WORDS" and is marked wrong
    no matter what they know. A live set keyed Q1 as an entire blank form
    template against word_limit=2 and only produced a log line, because this
    check used to warn instead of failing.
    """
    answer_key = result.get("answer_key") or {}
    problems: list[str] = []
    for q in result.get("questions") or []:
        if not isinstance(q, dict) or qtype(q) not in GAP_FILL_TYPES:
            continue
        answer = answer_key.get(str(q.get("number")))
        if answer is None:
            continue
        text = str(answer)
        number = q.get("number")
        # An answer containing the gap is the blank itself, not a filling for
        # it — unmarkable at any cap, and absent from 583 raw teacher units.
        if GAP_MARKER.search(text):
            problems.append(f"Q{number} answers with the blank itself")
            continue
        limit = parse_word_limit(q.get("word_limit"))
        if limit is None:
            continue
        longest = max((answer_word_count(c) for c in text.split(";")), default=0)
        if longest > limit + _WORD_LIMIT_SLACK:
            problems.append(f"Q{number} keys {longest} words against word_limit={limit}")
    if not problems:
        return None
    return (
        "the answer key breaks the word limit the student is shown: "
        + "; ".join(problems)
        + ". Shorten each of those answers to fit its own word_limit, or raise "
        "that question's word_limit to the number of words its answer needs."
    )


def missing_map_error(questions: list, visual: object) -> str | None:
    """Reject map/plan labelling with no map to label.

    `dangling_structure_error` lets a question off if it ends in '?', which is
    right for a completion item mistyped as one but wrong here: "What is the
    location marked as point C?" is circular without the drawing, and the
    corpus keys it 'C'. So there is no escape hatch.
    """
    if isinstance(visual, dict) and str(visual.get("kind", "")).lower() in LAYOUT_KINDS:
        return None
    numbers = [str(q.get("number")) for q in questions
               if isinstance(q, dict) and qtype(q) in MAP_TYPES]
    if not numbers:
        return None
    return (
        f"question(s) {', '.join(numbers)} ask the student to label a map or "
        "plan, but `visual` carries no plan — there is nothing to read a "
        "position off, so they cannot be answered. Emit a plan `visual` whose "
        "lettered rooms are the ones the questions ask about, or use a "
        "question type that needs no drawing."
    )


def drop_letter_clash_names(result: dict) -> list[str]:
    """Rub out a place NAME printed at the same spot as a letter.

    The student is asked which letter marks a place; printing that place's name
    on the letter hands the answer over. Repaired rather than refused, and
    deterministically — there is one right answer, the name goes and the letter
    stays — which is the bargain `blank_self_answering_labels` strikes on the
    diagram: blanking costs one orientation label, leaving it costs the
    question.

    🔬 Live 2026-09-01, `l_map_r2`: refused on the way in, one corrective retry
    spent, the retry failed the same way and the whole set died. The retry has
    never rescued this — the model puts the name back — and one deletion cures
    it for nothing.

    Returns the names removed, for the caller to log.
    """
    visual = result.get("visual")
    if not isinstance(visual, dict) or str(visual.get("kind", "")).lower() != "map":
        return []
    features = [f for f in (visual.get("features") or []) if isinstance(f, dict)]

    def spot(feature: dict) -> tuple[float, float] | None:
        try:
            return (float(feature.get("x")), float(feature.get("y")))
        except (TypeError, ValueError):
            return None

    lettered = {
        spot(f)
        for f in features
        if len(str(f.get("label") or "").strip()) == 1
        and str(f.get("label") or "").strip().isalpha()
        and spot(f) is not None
    }
    if not lettered:
        return []
    dropped = [
        str(f.get("label")).strip()
        for f in features
        if spot(f) in lettered
        and len(str(f.get("label") or "").strip()) > 1
    ]
    if not dropped:
        return []
    visual["features"] = [
        f for f in features
        if not (spot(f) in lettered and len(str(f.get("label") or "").strip()) > 1)
    ]
    return dropped


def unlettered_map_error(
    questions: list, visual: object, answer_key: dict, *, after_repairs: bool = True
) -> str | None:
    """Reject a plan whose letters do not carry the answers keyed against it.

    `missing_map_error` only asks that a plan exists. This catches the plan
    existing and being useless: the teacher prints the real name of every place
    a question asks about and keys letters it never drew, so the figure answers
    the questions it was meant to pose. Measured on the first hosted part 2 —
    A, E and F keyed against a grid holding only A.

    Both layouts are judged. The coordinate `map` keeps its letters in
    `features` rather than in a grid, and it went from ungenerated to
    generated on 2026-08-28 — this docstring used to say "nothing generates one
    any more", and the first live map walked straight through the hole: every
    lettered point sat on the exact coordinates of a named feature, so the plan
    printed "Car park" on top of the A the student was asked to find.
    """
    if not isinstance(visual, dict):
        return None
    kind = str(visual.get("kind", "")).lower()
    if kind not in ("plan", "map"):
        return None

    if kind == "map":
        letters = set()
        named: dict[tuple[float, float], str] = {}
        for feature in visual.get("features") or []:
            if not isinstance(feature, dict):
                continue
            label = str(feature.get("label") or "").strip()
            try:
                spot = (float(feature.get("x")), float(feature.get("y")))
            except (TypeError, ValueError):
                continue
            if len(label) == 1 and label.isalpha():
                letters.add(label.upper())
            elif label:
                named[spot] = label
        # A letter printed on top of a named place hands over the answer.
        clashes = [
            f"{str(f.get('label')).strip().upper()} sits on {named[(float(f['x']), float(f['y']))]!r}"
            for f in visual.get("features") or []
            if isinstance(f, dict)
            and len(str(f.get("label") or "").strip()) == 1
            and str(f.get("label") or "").strip().isalpha()
            and (float(f.get("x", -1)), float(f.get("y", -1))) in named
        ]
        # `after_repairs=False` says nothing about the clash on the way in:
        # `drop_letter_clash_names` deletes the offending name during
        # normalisation, and complaining here buys a retry of the whole set
        # that has never once rescued it. The other half — letters keyed but
        # never drawn — no repair can invent, so it is judged either way.
        if clashes and after_repairs:
            return (
                "the map prints a place's NAME at the same spot as the letter "
                f"the student is asked to find: {'; '.join(clashes[:4])}. A "
                "lettered point marks a place the map does NOT name — the "
                "naming is left to the script. Move each letter to its own "
                "position and delete the named feature that shares it, keeping "
                "only the landmarks no question asks about."
            )
    else:
        grid = visual.get("grid")
        if not isinstance(grid, list):
            return None
        letters = {
            cell.strip().upper()
            for row in grid if isinstance(row, list)
            for cell in row
            if isinstance(cell, str)
            and len(cell.strip()) == 1
            and cell.strip().isalpha()
        }

    prose: list[str] = []
    missing: dict[str, str] = {}
    for q in questions:
        if not isinstance(q, dict) or qtype(q) not in MAP_TYPES:
            continue
        number = str(q.get("number"))
        answer = str((answer_key or {}).get(number) or "").strip()
        if len(answer) != 1 or not answer.isalpha():
            prose.append(number)
        elif answer.upper() not in letters:
            missing[number] = answer.upper()

    if prose:
        return (
            f"question(s) {', '.join(sorted(prose))} label the plan, so each is "
            "answered with the letter of a room rather than with words. Letter "
            "the room each one asks about and key that letter."
        )
    if missing:
        keyed = ", ".join(f"Q{n} keys {a}" for n, a in sorted(missing.items()))
        drawn = ", ".join(sorted(letters)) or "no letters at all"
        # Worded for the figure in hand. A plan holds its letters in a grid of
        # rooms and a map marks them at points, so one sentence covering both
        # ends up describing neither.
        if kind == "map":
            return (
                f"the answer key points at letters the map never draws: "
                f"{keyed}, while the map marks {drawn}. Every place a question "
                "asks about is a lettered point whose name appears nowhere on "
                "the map — mark the missing letters and leave the naming to "
                "the script."
            )
        return (
            f"the answer key points at letters the plan never draws: {keyed}, "
            f"while the grid holds {drawn}. Every place a question asks about "
            "is a lettered cell whose name appears nowhere on the grid — draw "
            "the missing letters as rooms and leave the naming to the script."
        )
    return None



# The words a map question's rubric is built from. A question made of nothing
# but these has said how to answer without saying what to answer — and that
# rubric is shared by every question in the block, so it names no place.
_RUBRIC_WORDS = frozenset("""
a an and answer appropriate below box boxes choose complete correct diagram
each following for from in into label letter letters list location locations
map next of on onto or plan question questions right select shown that the
their them then to use with write your
""".split())


def _names_a_place(text: str) -> bool:
    """True if the question says anything its block's rubric does not."""
    words = re.findall(r"[a-z']+", str(text or "").lower())
    return any(word not in _RUBRIC_WORDS for word in words)


def unnamed_place_error(questions: list) -> str | None:
    """Reject a map question that never says which place the student is finding.

    `unlettered_map_error` guarantees the plan carries the keyed letters; this
    guarantees the question carries a place to look for. Shown a plan and told
    only "Complete the plan below. Write the correct letter for each location",
    the student has no way to know whether question 11 wants the café or the
    library — and a second question saying exactly the same thing is not a
    second question at all. A hosted part 2 came back with both.

    Of 321 corpus map questions exactly one is bare and none repeat another's
    wording, so this rejects what the teacher does not do rather than a shape
    the checkpoint was trained on.
    """
    seen: dict[str, str] = {}
    bare: list[str] = []
    repeated: list[tuple[str, str]] = []
    for q in questions:
        if not isinstance(q, dict) or qtype(q) not in MAP_TYPES:
            continue
        number = str(q.get("number"))
        text = str(q.get("question") or "")
        if not _names_a_place(text):
            bare.append(number)
            continue
        key = re.sub(r"\s+", " ", text.strip().lower())
        if key in seen:
            repeated.append((seen[key], number))
        else:
            seen[key] = number

    if bare:
        return (
            f"question(s) {', '.join(sorted(bare))} give only the block's "
            "instruction, so the student is never told which place to find on "
            "the plan. Write each map question as the place itself — "
            '"11  the café ......" — one place per question.'
        )
    if repeated:
        clash = ", ".join(f"{a} and {b}" for a, b in repeated)
        return (
            f"map question(s) {clash} ask for the same place in the same "
            "words, so they are one question printed twice. Give each its own "
            "place, and key the letter of the room that place is in."
        )
    return None


# The two verdict types, whose question text is a claim rather than a question.
VERDICT_TYPES = {canon(t) for t in ("true_false_notgiven", "yes_no_notgiven")}

# Wording that reports the passage's silence instead of asserting anything.
# "The passage neither confirms nor contradicts X" IS the definition of NOT
# GIVEN, so a statement written that way hands over its own answer. It is also
# how NOTGIVEN_WRITER_SYSTEM explains the verdict, which is how it reached a
# live statement. 0 of 553 corpus statements read this way, while 1.6% do say
# "the author believes ..." — a real YES/NO shape this must not touch.
_SELF_ANSWERING = re.compile(
    r"neither confirms nor"
    r"|(passage|text|article)[^.]{0,40}(does not|doesn.t|never)[^.]{0,20}(say|state|mention|confirm|discuss|address)"
    r"|is not (mentioned|stated|given|discussed) (in|anywhere|by) the (passage|text|article)"
    r"|no information (is given|about)",
    re.I,
)


def self_answering_error(questions: list) -> str | None:
    """Reject a verdict statement that describes the passage rather than the
    subject.

    A student meeting "The passage neither confirms nor contradicts that the
    machine was widely adopted" writes NOT GIVEN without reading a word: the
    statement has announced its own verdict. Measured live on a hosted reading
    set, written by the repair whose own prompt uses that phrasing."""
    guilty = [
        str(q.get("number")) for q in questions
        if isinstance(q, dict) and qtype(q) in VERDICT_TYPES
        and _SELF_ANSWERING.search(str(q.get("question") or ""))
    ]
    if not guilty:
        return None
    return (
        f"statement(s) {', '.join(guilty)} say what the passage does not "
        "state instead of claiming anything about its subject, which hands "
        "the student NOT GIVEN before they have read it. Write each one as a "
        "plain assertion, the way the person making the claim would put it."
    )

def unmarkable_matching_error(questions: list, answer_key: dict) -> str | None:
    """Reject a matching question whose answer is not one of its own options.

    A matching item is one pair: the student picks from a printed list, so an
    answer outside that list can never be marked. The teacher's habit is to
    key an entire mapping against a single question — 58 of 89 corpus answers
    read that way — and listening_trainer unpacks those before this runs. What
    is left is an item whose correct choice was never offered, which no code
    can guess. 82 of the 89 pass this once repaired, against 31 before.
    """
    for q in questions:
        if not isinstance(q, dict) or qtype(q) != canon("matching"):
            continue
        number = q.get("number")
        options = q.get("options")
        if not isinstance(options, list) or not options:
            return (
                f"matching question {number} has no options array. The student "
                "chooses from a printed list, so every question must carry that "
                "list in full."
            )
        answer = str((answer_key or {}).get(str(number)) or "").strip()
        letters = {chr(ord("A") + i).lower() for i in range(len(options))}
        if canon(answer) in {canon(o) for o in options} | letters:
            continue
        return (
            f"the answer to matching question {number} is {answer!r}, which is "
            f"not one of its options ({', '.join(repr(str(o)) for o in options)}). "
            "One question is ONE pair: name the item it asks about, offer the "
            "candidates as options, and key the single one that matches."
        )
    return None

def dangling_completions(questions: list, visual: object) -> list[dict]:
    """Completion items that point at a block the student never sees.

    Shared with the repair that rewrites them, so the two cannot disagree about
    which questions are broken — a repair that fixed a different set than the
    validator rejects would loop until the retries ran out.
    """
    slots = visual_slots(visual)
    dangling = []
    for q in questions:
        if not isinstance(q, dict) or qtype(q) not in STRUCTURE_TYPES:
            continue
        if q.get("options") or str(q.get("number")) in slots:
            continue
        if is_self_contained(str(q.get("question") or "")):
            continue
        dangling.append(q)
    return dangling


def dangling_structure_error(questions: list, visual: object, source: str) -> str | None:
    """Reject a completion item that points at a block the student never sees."""
    for q in dangling_completions(questions, visual):
        return (
            f"question {q.get('number')} ({q.get('type')}) points at a summary/note/"
            "table/flow chart that the student never sees — nothing renders one. "
            "Rewrite it to carry its own context with the gap shown as ______, "
            f"e.g. \"NO MORE THAN TWO WORDS. {source}\". Or emit a `visual` table "
            f"with a matching __{q.get('number')}__ cell."
        )
    return None
