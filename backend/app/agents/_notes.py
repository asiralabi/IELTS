"""The printed notes block and the printed summary, shared by both papers.

Cambridge prints these constantly — "Complete the notes below", "Complete the
summary below" — and this engine could not draw either. The prompts said so in
as many words: "No summary or note block is printed on screen — only the
question text you write", so every note and summary item had to carry its own
context inline and the student never saw the block the rubric named. That is a
real gap against the exam, and the two types are among the commonest it prints.

They are one module because they are one shape with two typographies. A notes
block is headed groups of short lines; a summary is the same content set as
flowing prose. The exam gaps them identically, marks them identically, and the
student does the same job on both — so a second schema would only be a second
place for the numbering to go wrong.

The bargain is the one the flow chart strikes: the model writes the LINES in
the order the student reads them, and everything else — the box, the headings,
the numbering, the layout — is derived. A gap is `__<n>__` inside a line.
"""

import re

from app.agents._marking import norm

NOTES_KIND = "notes"

# The same mid-text gap the flow chart and the diagram use. Imported nowhere
# else from here, but written identically on purpose: three figures disagreeing
# about what a gap looks like is how one of them stops being renumbered.
NOTES_GAP_RE = re.compile(r"__(\d+)__")

NOTES_STYLE = "notes"
SUMMARY_STYLE = "summary"
_STYLES = (NOTES_STYLE, SUMMARY_STYLE)

# Shape taken from what the books print: a notes block runs to a handful of
# headed groups, and a summary is one or two paragraphs. The floors are what
# makes the figure worth printing at all rather than a sentence with a hole.
_MIN_LINES = 2
_MAX_LINES = 24
_MAX_SECTIONS = 6
_MIN_GAPS = 2
_MAX_GAPS = 10

# A line is a note, not an essay. Beyond this the model has started writing the
# passage again inside the figure.
_MAX_LINE_WORDS = 40


# The model writes the kind it thinks the block is called, and told a block
# whose `style` is "summary", it writes `"kind": "summary"` — which it did on
# the first live summary this engine ever generated. Folding the wording it
# reaches for is what `_plan._WALKWAY` already does for "path"/"road"/"street".
#
# 🚨 This is not cosmetic. `is_notes` gates the validator, the normaliser, the
# renumbering AND the repair, so an unfolded kind sails past every one of them
# and reaches the renderer as a shape it does not know.
_KIND_ALIASES = {NOTES_KIND, SUMMARY_STYLE, "note", "summary_block", "notes_block"}


def is_notes(visual: object) -> bool:
    return (
        isinstance(visual, dict)
        and str(visual.get("kind", "")).lower() in _KIND_ALIASES
    )


def _text(value: object) -> str:
    return str(value or "").strip()


def notes_style(visual: object) -> str:
    """Which typography this block prints in, defaulting to notes.

    An unknown style becomes `notes` rather than failing the set: headed short
    lines are readable whatever the content, where prose set as notes is not.
    """
    if not is_notes(visual):
        return ""
    want = _text(visual.get("style")).lower()
    if want in _STYLES:
        return want
    # A block that called ITSELF a summary is one, whatever its style said.
    if _text(visual.get("kind")).lower() == SUMMARY_STYLE:
        return SUMMARY_STYLE
    return NOTES_STYLE


def notes_sections(visual: object) -> list[dict]:
    """The headed groups, in the order the student reads them."""
    if not is_notes(visual):
        return []
    raw = visual.get("sections")
    if not isinstance(raw, list):
        return []
    return [s for s in raw if isinstance(s, dict)]


def notes_lines(visual: object) -> list[str]:
    """Every printed line, in reading order, headings excluded.

    The one definition, shared by the validator, the self-answer detector and
    the renumbering, so they cannot disagree about what the student sees.
    """
    out: list[str] = []
    for section in notes_sections(visual):
        raw = section.get("lines")
        if not isinstance(raw, list):
            continue
        out += [_text(line) for line in raw if _text(line)]
    return out


def notes_texts(visual: object) -> list[str]:
    """Every string on the block — headings as well as lines."""
    heads = [_text(s.get("heading")) for s in notes_sections(visual)]
    return [h for h in heads if h] + notes_lines(visual)


def notes_gaps(visual: object) -> list[str]:
    """Gap numbers in the order the student meets them, top of the block down."""
    return [n for line in notes_texts(visual) for n in NOTES_GAP_RE.findall(line)]


def normalize_notes(visual: object) -> dict | None:
    """Clean a generated block, or None if it is not one.

    Blank lines and empty sections are dropped rather than printed as gaps in
    the layout, and `__ 6 __` is folded to the one gap spelling the renderer and
    `visual_slots` both read. Nothing structural is repaired — that is
    `notes_error`'s job, and a normaliser that quietly fixed a broken block
    would hide the case the validator exists to catch.
    """
    if not is_notes(visual):
        return None
    sections = []
    for section in notes_sections(visual):
        lines = [
            re.sub(r"_+\s*(\d+)\s*_+", r"__\1__", _text(line))
            for line in (section.get("lines") or [])
            if _text(line)
        ]
        heading = re.sub(r"_+\s*(\d+)\s*_+", r"__\1__", _text(section.get("heading")))
        if lines or heading:
            sections.append({"heading": heading, "lines": lines})
    return {
        "kind": NOTES_KIND,
        "style": notes_style(visual),
        "title": _text(visual.get("title")),
        "sections": sections,
    }


def renumber_notes(visual: object, mapping: dict[str, str]) -> None:
    """Move every gap on the block to its question's new number, in place.

    The failure this prevents is the one a live paper already shipped with a
    grid (`b089b4a`): the block printing gaps 1, 2, 3 beside questions 14, 15,
    16. Rewritten in a single pass off the mapping so a chain like 1->2, 2->3
    cannot move a gap twice.
    """
    if not is_notes(visual):
        return

    def move(text: str) -> str:
        return NOTES_GAP_RE.sub(
            lambda m: f"__{mapping.get(m.group(1), m.group(1))}__", text
        )

    for section in notes_sections(visual):
        if section.get("heading"):
            section["heading"] = move(str(section["heading"]))
        lines = section.get("lines")
        if isinstance(lines, list):
            section["lines"] = [
                move(str(line)) if isinstance(line, str) else line for line in lines
            ]


def self_answering_lines(
    visual: object, answer_key: dict
) -> list[tuple[str, str, str]]:
    """(gap, answer, the line that gives it away) for every gap the block answers.

    The fourth costume of the defect the grid, the flow chart and the diagram
    each wore. A notes block is denser than any of them — a dozen short lines
    about one topic — so the odds of one line printing the word another line
    asks for are higher here than anywhere else.

    A gap's OWN line is searched too, matching the flow chart rather than the
    grid: a line is a sentence wrapped around its gap and can perfectly well
    print the word beside it.

    Matched on padded whole words, because an unpadded substring finds "six"
    inside "sixteen".
    """
    lines = notes_texts(visual)
    out: list[tuple[str, str, str]] = []
    for gap in notes_gaps(visual):
        raw = _text((answer_key or {}).get(gap))
        want = norm(raw)
        if not want:
            continue
        for line in lines:
            prose = norm(NOTES_GAP_RE.sub(" ", line))
            if f" {want} " in f" {prose} ":
                out.append((gap, raw, line))
                break
    return out


def fold_extra_sections(result: dict) -> int:
    """Merge a notes block's overflow headings down to the printable limit.

    Lossless where it matters: every LINE and every gap survives, in order. All
    that goes is a heading, which is orientation — the same bargain
    `blank_gapped_part_names` strikes on a diagram, and the same one
    `notes_error` states for itself: "the bar is unusable, never improvable".
    Seven headed groups is untidy, not unreadable, and refusing it costs a
    whole regeneration.

    🔬 Live 2026-09-02, the one failure in a 25-type sweep: a listening
    note_completion set came back with 7 sections and died on the way in — "a
    notes block cannot carry 7 sections legibly (at most 6)" — taking the
    script, the questions and the key with it.

    Returns how many sections were folded away.
    """
    visual = result.get("visual")
    if not is_notes(visual):
        return 0
    sections = notes_sections(visual)
    if len(sections) <= _MAX_SECTIONS:
        return 0
    kept = [dict(s) for s in sections[:_MAX_SECTIONS - 1]]
    tail = sections[_MAX_SECTIONS - 1:]
    merged = {
        "heading": _text(tail[0].get("heading")),
        "lines": [line for section in tail for line in (section.get("lines") or [])],
    }
    visual["sections"] = kept + [merged]
    return len(sections) - _MAX_SECTIONS


def notes_error(
    visual: object, questions: list, answer_key: dict, *, after_repairs: bool = True
) -> str | None:
    """Why this block is not a printable IELTS notes or summary, or None if it is.

    Refuses only what cannot be read or cannot be answered. The cost of a
    refusal is a whole regeneration, so the bar is "unusable", never
    "improvable".
    """
    if not is_notes(visual):
        return None

    sections = notes_sections(visual)
    if not sections:
        return "the notes block has no sections, so there is nothing to print"
    # `after_repairs=False` says nothing about the count on the way in:
    # `fold_extra_sections` merges the overflow during normalisation, and
    # complaining here spends a retry of the whole set on a fault one merge
    # cures. Judged at the final gate, where a block still over the limit means
    # that repair did not run.
    if len(sections) > _MAX_SECTIONS and after_repairs:
        return (
            f"a notes block cannot carry {len(sections)} sections legibly "
            f"(at most {_MAX_SECTIONS})"
        )

    lines = notes_lines(visual)
    if not _MIN_LINES <= len(lines) <= _MAX_LINES:
        return (
            f"a notes block needs {_MIN_LINES}-{_MAX_LINES} lines to be worth "
            f"printing, not {len(lines)}"
        )
    for line in lines:
        words = len(NOTES_GAP_RE.sub(" ", line).split())
        if words > _MAX_LINE_WORDS:
            return (
                f"a line of the notes block is {words} words long; it is a note, "
                f"not a paragraph (at most {_MAX_LINE_WORDS})"
            )

    gaps = notes_gaps(visual)
    if not _MIN_GAPS <= len(gaps) <= _MAX_GAPS:
        return (
            f"the notes block carries {len(gaps)} gaps; a printed block is worth "
            f"showing only for {_MIN_GAPS}-{_MAX_GAPS} of them"
        )
    if len(gaps) != len(set(gaps)):
        dupe = next(g for g in gaps if gaps.count(g) > 1)
        return f"the notes block prints gap {dupe} twice, so one question has two boxes"

    # The student reads the block from the top down, so a gap numbered out of
    # order sends them backwards — the same rule the flow chart enforces on its
    # chain, and for the same reason.
    numeric = [int(g) for g in gaps]
    if numeric != sorted(numeric):
        return (
            "the notes block numbers its gaps out of order "
            f"({', '.join(gaps)}); the student reads top to bottom, so the "
            "numbers must ascend down the block"
        )

    # A line whose entire content is its gap gives the student nothing to
    # answer from — the flow chart's "a step must say something besides its
    # gap", which a notes block breaks more easily because its lines are short.
    for line in lines:
        if not NOTES_GAP_RE.sub("", line).strip(" .,:;-—"):
            return (
                f"the notes line {line!r} is nothing but its gap, so it says "
                "nothing the student can answer from"
            )

    asked = {
        str(q.get("number"))
        for q in (questions or [])
        if isinstance(q, dict) and q.get("number") is not None
    }
    orphan = [g for g in gaps if g not in asked]
    if orphan:
        return f"the notes block prints gap {orphan[0]}, which no question asks about"

    keyed = {str(k) for k in (answer_key or {})}
    unkeyed = [g for g in gaps if g not in keyed]
    if unkeyed:
        return f"notes gap {unkeyed[0]} has no answer in the key"

    return None


def blank_self_answering_lines(result: dict) -> list[tuple[str, str, str]]:
    """Rub out block text that prints another gap's answer. Returns what went.

    Deliberately narrower than the diagram's version: a notes line is content,
    not a label, so deleting the whole line would take the student's context
    with it. Only a HEADING is blanked — a heading is an orientation label in
    exactly the way a diagram callout is, and losing one costs a signpost
    rather than a sentence.

    A line that gives an answer away is left for `notes_error`'s caller to
    decide about, because the honest repair there is to reword the line, and
    that needs a model call this deterministic pass does not make.
    """
    visual = result.get("visual")
    if not is_notes(visual):
        return []
    hits = self_answering_lines(visual, result.get("answer_key") or {})
    if not hits:
        return []
    headings = {
        _text(s.get("heading")) for s in notes_sections(visual) if _text(s.get("heading"))
    }
    guilty = {
        text for _, _, text in hits
        if text in headings and not NOTES_GAP_RE.search(text)
    }
    if not guilty:
        return []
    for section in notes_sections(visual):
        if _text(section.get("heading")) in guilty:
            section["heading"] = ""
    return [h for h in hits if h[2] in guilty]
