"""The labelled diagram, shared by Reading and Listening.

Until now the engine had no diagram kind at all. `prompts.py` told the model to
answer `diagram_label_completion` with `kind: "plan"` -- the grid the floor plan
uses -- so a live reading set titled "Cross-section of a Sewing Machine" came
out as seven text boxes in a Tetris shape. A rectangle of cells is the right
figure for a building and the wrong one for everything else the exam draws.

Measured over the 77 parsed Cambridge tests (`tools/_diag_diagram_shape.py`,
44 real diagram rubrics -- 19 reading, 25 listening), what the exam actually
prints falls into a small number of families:

  * apparatus and mechanism cross-sections with leader-line callouts, ~9
    ("An Undersea Turbine", "How a boat is lifted on the Falkirk Wheel",
    "How the 1670 lever-based device worked", "One method of collecting ants")
  * outdoor site and town maps with lettered positions, ~14 -- the grid plan's
    territory, handled there
  * building floor plans, ~5 -- the grid plan again
  * strata and layer cross-sections, ~2 ("granite / mud / water / clay / sand")
  * cycles, ~2 ("THE OPERATIONAL CYCLE")
  * classification trees, ~2 ("Dung Beetle Types")
  * equipment control panels, ~2 ("Water Heater": on/off switch, reset button,
    time control, warning indicator)

So this module draws five layouts, and the bargain is the one the grid plan and
the flow chart already strike: **the model states only what the parts ARE and
what order they sit in; every coordinate is derived here.** The generator runs
on llama-3.1-70b, which cannot place a shape on a canvas -- but it can name the
parts of a thing in order, which is all a layout needs. Nothing the model
returns can come out overlapping, off-page or pointing at nothing.
"""

import re

from app.agents._marking import norm

DIAGRAM_KIND = "diagram"

# The same mid-text gap the flow chart uses. A diagram gap can sit in a callout
# ("__23__") or inside a part's printed name ("__4__ chamber"), so it is found
# mid-string rather than anchored like the grid's whole-cell blank.
DIAGRAM_GAP_RE = re.compile(r"__(\d+)__")

# ---------------------------------------------------------------------------
# The layouts, and the forms each one draws.
#
# A `form` is a shape the renderer knows how to draw in exam line art. The
# vocabulary is deliberately small and physical: the model picks the nearest
# one, and a form it invents falls back to the layout's default rather than
# failing the set, because refusing a figure costs a 14-25 minute hosted
# regeneration and a plain box in the right place still reads as the exam.
# ---------------------------------------------------------------------------

APPARATUS = "apparatus"
LAYERS = "layers"
CYCLE = "cycle"
TREE = "tree"
PANEL = "panel"

LAYOUTS = (APPARATUS, LAYERS, CYCLE, TREE, PANEL)

# Cross-section and mechanism parts. Every one is a shape with a real outline;
# `pipe` and `arrow` are the connective forms that make an assembly read as one
# machine rather than a pile of boxes.
_APPARATUS_FORMS = {
    "chamber",    # a vessel: rectangle with rounded shoulders
    "column",     # a tall narrow upright — tower, shaft, stem
    "tank",       # a cylinder, drawn with elliptical top and bottom
    "dome",       # a half-ellipse cap
    "funnel",     # a trapezoid narrowing downward — hopper, cone
    "pipe",       # a narrow connector
    "disc",       # a wheel or pulley: circle with a hub
    "rotor",      # a hub with radiating blades
    "coil",       # a spring or heating element
    "valve",      # opposed triangles
    "platform",   # a wide flat slab — deck, table, shelf
    "liquid",     # a filled region with a wavy top
    "ground",     # a hatched ground or seabed line
    "box",        # the fallback: a plain rectangle
}
_APPARATUS_DEFAULT = "box"

# Layer bands, top of the section down.
_LAYER_FORMS = {"rock", "soil", "sand", "clay", "water", "air", "band"}
_LAYER_DEFAULT = "band"

# Panel controls, laid out in reading order across the device face.
_PANEL_FORMS = {"button", "dial", "switch", "light", "display", "slot", "gauge"}
_PANEL_DEFAULT = "button"

_FORMS = {
    APPARATUS: (_APPARATUS_FORMS, _APPARATUS_DEFAULT),
    LAYERS: (_LAYER_FORMS, _LAYER_DEFAULT),
    PANEL: (_PANEL_FORMS, _PANEL_DEFAULT),
    # A cycle stage and a tree node are drawn identically whatever they hold —
    # the layout, not the part, is what gives them their shape.
    CYCLE: (set(), "stage"),
    TREE: (set(), "node"),
}

_SIDES = ("left", "right", "top", "bottom")

# Ranges taken from the real figures. The counts are floors and ceilings on
# what can be DRAWN legibly, not on what Cambridge prints: a section with two
# bands is a real section, and one with fourteen parts cannot be labelled on a
# screen the width of a practice page.
_MIN_PARTS = 2
_MAX_PARTS = 12
_MAX_LABELS = 10

# A callout is a noun phrase pointing at a part, the way the exam prints one
# ("Thread guide", "Hydraulic Motors"). A sentence in a callout means the model
# has written prose into the drawing, which no exam diagram does.
_MAX_LABEL_WORDS = 6


def is_diagram(visual: object) -> bool:
    return (
        isinstance(visual, dict)
        and str(visual.get("kind", "")).lower() == DIAGRAM_KIND
    )


def _text(value: object) -> str:
    return str(value or "").strip()


def _slug(value: object, fallback: str) -> str:
    """A part id the labels can point at, however the model wrote it."""
    out = re.sub(r"[^a-z0-9]+", "_", _text(value).lower()).strip("_")
    return out or fallback


def diagram_layout(visual: object) -> str:
    """The layout this figure draws, defaulting to the commonest one.

    An unknown layout becomes `apparatus` rather than failing the set: it is
    the general case — an assembly of named parts with callouts — and every
    other layout is a specialisation of it.
    """
    if not is_diagram(visual):
        return ""
    want = _text(visual.get("layout")).lower().replace("-", "_").replace(" ", "_")
    return want if want in LAYOUTS else APPARATUS


def diagram_parts(visual: object) -> list[dict]:
    """The drawn parts, in the order the model listed them.

    Order is the whole geometry for four of the five layouts: an apparatus
    stacks top to bottom, a section's bands run down, a cycle goes clockwise
    and a panel reads left to right. A tree is the exception and carries
    `parent` instead.
    """
    if not is_diagram(visual):
        return []
    raw = visual.get("parts")
    if not isinstance(raw, list):
        return []
    return [p for p in raw if isinstance(p, dict)]


def diagram_labels(visual: object) -> list[dict]:
    """The leader-line callouts, in the order they were written."""
    if not is_diagram(visual):
        return []
    raw = visual.get("labels")
    if not isinstance(raw, list):
        return []
    return [lb for lb in raw if isinstance(lb, dict)]


def diagram_texts(visual: object) -> list[str]:
    """Every string the student reads on the figure — part names and callouts.

    One list so the self-answer detector and the validators can never disagree
    about what counts as printed on the drawing.
    """
    out = [_text(p.get("name")) for p in diagram_parts(visual)]
    out += [_text(lb.get("text")) for lb in diagram_labels(visual)]
    return [t for t in out if t]


def diagram_gaps(visual: object) -> list[str]:
    """Gap numbers in the order the student meets them on the figure."""
    return [n for t in diagram_texts(visual) for n in DIAGRAM_GAP_RE.findall(t)]


def normalize_diagram(visual: object) -> dict | None:
    """Clean a generated diagram, or None if it is not one.

    Nothing structural is repaired here — that is `diagram_error`'s job, and a
    normaliser that quietly fixed a broken figure would hide the case the
    validator exists to catch. What it does do is settle the vocabulary: ids
    are slugged so a label can find its part however the model capitalised it,
    a form outside the layout's vocabulary falls back rather than reaching the
    renderer as an unknown shape, and `__ 6 __` is folded to the one gap form
    `visual_slots` and the renderer both read.
    """
    if not is_diagram(visual):
        return None
    layout = diagram_layout(visual)
    known, default = _FORMS.get(layout, (set(), _APPARATUS_DEFAULT))

    parts: list[dict] = []
    seen: set[str] = set()
    for i, raw in enumerate(diagram_parts(visual)):
        pid = _slug(raw.get("id") or raw.get("name"), f"part{i + 1}")
        while pid in seen:
            pid += "_2"
        seen.add(pid)
        form = _text(raw.get("form")).lower().replace("-", "_").replace(" ", "_")
        part = {
            "id": pid,
            "form": form if (not known or form in known) else default,
            "name": _gap_form(_text(raw.get("name"))),
        }
        # An apparatus part may hang off the side of the spine instead of
        # sitting in it, and a tree node names its parent. Both are carried
        # only when they resolve, so a dangling reference cannot reach the
        # renderer as a part attached to nothing.
        for key in ("attach", "to", "parent"):
            val = raw.get(key)
            if val is None:
                continue
            part[key] = _text(val).lower() if key == "attach" else _slug(val, "")
        if part.get("attach") not in (None, *_SIDES):
            part.pop("attach", None)
            part.pop("to", None)
        parts.append(part)

    ids = {p["id"] for p in parts}
    for p in parts:
        if p.get("to") not in ids:
            p.pop("to", None)
            p.pop("attach", None)
        if p.get("parent") not in ids:
            p.pop("parent", None)

    labels: list[dict] = []
    for raw in diagram_labels(visual):
        at = _slug(raw.get("at") or raw.get("target") or raw.get("part"), "")
        text = _gap_form(_text(raw.get("text") or raw.get("label")))
        if not text or at not in ids:
            continue
        side = _text(raw.get("side")).lower()
        labels.append(
            {"at": at, "text": text, "side": side if side in _SIDES else ""}
        )

    return {
        "kind": DIAGRAM_KIND,
        "title": _text(visual.get("title")),
        "layout": layout,
        "parts": parts,
        "labels": labels,
    }


def _gap_form(text: str) -> str:
    return re.sub(r"_+\s*(\d+)\s*_+", r"__\1__", text)


def renumber_diagram(visual: object, mapping: dict[str, str]) -> None:
    """Move every gap on the figure to its question's new number, in place.

    A full test renumbers each part after it is generated, and a gap left at
    local numbering is how a live paper came to draw gaps 1, 2, 3 beside
    questions 14, 15, 16 (`b089b4a`). The diagram has the same exposure in two
    places rather than one — a callout and a part's printed name — so both are
    walked. Rewritten in a single pass off the mapping so a chain like 1->2,
    2->3 cannot renumber a gap twice.
    """
    if not is_diagram(visual):
        return

    def move(text: str) -> str:
        return DIAGRAM_GAP_RE.sub(
            lambda m: f"__{mapping.get(m.group(1), m.group(1))}__", text
        )

    for part in diagram_parts(visual):
        if part.get("name"):
            part["name"] = move(str(part["name"]))
    for label in diagram_labels(visual):
        if label.get("text"):
            label["text"] = move(str(label["text"]))


def self_answering_labels(
    visual: object, answer_key: dict
) -> list[tuple[str, str, str]]:
    """(gap, answer, the text that gives it away) for every gap the figure answers.

    The diagram's version of the self-answering grid cell `65f38ab` fixed and
    the self-answering flow box `652cb48` fixed. A drawing carries printed
    orientation labels beside the numbered ones — "Thread guide" and "Bobbin"
    sit on the sewing machine so the student knows which way up it is — and
    nothing stops the model printing the very word another gap is keyed to.

    A gap's OWN text is searched too, matching the flow chart rather than the
    grid: a callout is a phrase, not a bare cell, and "the __3__, or bobbin,"
    hands over gap 3 on its own.

    Matched on padded whole words, because an unpadded substring finds "six"
    inside "sixteen".
    """
    texts = diagram_texts(visual)
    out: list[tuple[str, str, str]] = []
    for gap in diagram_gaps(visual):
        raw = _text((answer_key or {}).get(gap))
        want = norm(raw)
        if not want:
            continue
        for text in texts:
            prose = norm(DIAGRAM_GAP_RE.sub(" ", text))
            if f" {want} " in f" {prose} ":
                out.append((gap, raw, text))
                break
    return out


def diagram_error(visual: object, questions: list, answer_key: dict) -> str | None:
    """Why this figure is not a printable IELTS diagram, or None if it is.

    Refuses only what cannot be drawn or cannot be answered. A figure the
    student can read but that is merely plain is not an error — the cost of a
    refusal is a full hosted regeneration, so the bar is "unusable", never
    "improvable".
    """
    if not is_diagram(visual):
        return None

    parts = diagram_parts(visual)
    if not _MIN_PARTS <= len(parts) <= _MAX_PARTS:
        return (
            f"a labelled diagram needs {_MIN_PARTS}-{_MAX_PARTS} parts to draw, "
            f"not {len(parts)}"
        )

    labels = diagram_labels(visual)
    if len(labels) > _MAX_LABELS:
        return (
            f"a diagram cannot carry {len(labels)} callouts legibly "
            f"(at most {_MAX_LABELS})"
        )

    ids = {_slug(p.get("id") or p.get("name"), "") for p in parts}
    for label in labels:
        at = _slug(label.get("at") or label.get("target") or label.get("part"), "")
        if at not in ids:
            return (
                "a diagram callout points at a part the figure does not draw "
                f"({at or 'unnamed'})"
            )
        words = len(_text(label.get("text")).split())
        if words > _MAX_LABEL_WORDS:
            return (
                "a diagram callout is a sentence, not a label "
                f"({words} words; a printed label is at most {_MAX_LABEL_WORDS})"
            )

    # Nothing on the drawing is readable if the parts have no names and no
    # callouts. That is a picture, not a labelling task.
    if not diagram_texts(visual):
        return "the diagram prints no labels at all, so there is nothing to read"

    gaps = diagram_gaps(visual)
    if len(gaps) != len(set(gaps)):
        dupe = next(g for g in gaps if gaps.count(g) > 1)
        return f"the diagram prints gap {dupe} twice, so one question has two boxes"

    # Every gap must be a question, and every diagram question must be a gap.
    # This is the invariant that became audit check #24 after a live paper drew
    # gaps the questions did not point at.
    asked = {
        str(q.get("number"))
        for q in (questions or [])
        if isinstance(q, dict) and q.get("number") is not None
    }
    orphan = [g for g in gaps if g not in asked]
    if orphan:
        return (
            f"the diagram prints gap {orphan[0]}, which no question asks about"
        )

    keyed = {str(k) for k in (answer_key or {})}
    unkeyed = [g for g in gaps if g not in keyed]
    if unkeyed:
        return f"diagram gap {unkeyed[0]} has no answer in the key"

    return None


def blank_self_answering_labels(result: dict) -> list[tuple[str, str, str]]:
    """Rub out figure text that prints another gap's answer. Returns what went.

    The diagram's version of `_blank_self_answering_cells`, and it takes the
    same deterministic shape rather than the flow chart's rewrite: a callout is
    a short noun phrase, so there is nothing in it to reword — either it gives
    the answer away or it does not. Blanking costs the student one orientation
    label; leaving it costs them the question.

    A text carrying its OWN gap is left alone. Blanking it would take the gap
    with it and leave the question pointing at a part with no box, which is a
    worse figure than the one it started from — the same reason the grid only
    ever blanks a label cell and never a gap cell.
    """
    visual = result.get("visual")
    if not is_diagram(visual):
        return []
    answer_key = result.get("answer_key") or {}
    hits = self_answering_labels(visual, answer_key)
    if not hits:
        return []

    guilty = {
        text for _, _, text in hits if not DIAGRAM_GAP_RE.search(text)
    }
    if not guilty:
        return []

    for part in diagram_parts(visual):
        if _text(part.get("name")) in guilty:
            part["name"] = ""
    visual["labels"] = [
        lb for lb in diagram_labels(visual) if _text(lb.get("text")) not in guilty
    ]
    return [h for h in hits if h[2] in guilty]
