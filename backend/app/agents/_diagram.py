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
from collections import Counter

from app.agents._marking import norm
from app.agents.answerability import canon, qtype

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

SCENE = "scene"
APPARATUS = "apparatus"
LAYERS = "layers"
CYCLE = "cycle"
TREE = "tree"
PANEL = "panel"

LAYOUTS = (SCENE, APPARATUS, LAYERS, CYCLE, TREE, PANEL)

# Cross-section and mechanism parts. Every one is a shape with a real outline;
# `pipe` and `arrow` are the connective forms that make an assembly read as one
# machine rather than a pile of boxes.
# 🔬 Widened 2026-08-27 after checking what the exam actually draws. Past
# papers print a beehive, a soda can, a fire extinguisher, a Ferris wheel, a
# zip fastener, a solar heating system, an undersea turbine, soil layers, an
# egg cross-section and a Mars probe -- every one a RECOGNISABLE object. A
# vocabulary of vessels renders all of them as the same tower of tanks, which
# is exactly the complaint the first pictures drew.
_APPARATUS_FORMS = {
    # vessels and structure
    "chamber",    # a vessel: rectangle with rounded shoulders
    "column",     # a tall narrow upright — tower, shaft, stem
    "tank",       # a cylinder, drawn with elliptical top and bottom
    "canister",   # a can or extinguisher: rounded shoulder and a rim
    "oval",       # a body seen whole — an egg, a seed, a cell
    "dome",       # a half-ellipse cap
    "cone",
    "funnel",     # a trapezoid narrowing downward — hopper
    "stack",      # boxes stacked — beehive supers, crates
    "frame",      # an open rectangle — a window, a screen, a hive frame
    "platform",   # a wide flat slab — deck, table, shelf
    "stand",      # splayed legs with a brace
    "mound",      # a heap — a cow pat, spoil, a hill
    "box",        # the fallback: a plain rectangle
    # working parts
    "pipe",       # a narrow connector
    "hose",       # a flexible tube
    "nozzle",     # a tapering spout
    "cap",        # a lid
    "valve",      # opposed triangles
    "disc",       # a pulley: circle with a hub
    "wheel",      # a spoked wheel — a Ferris wheel, a gear
    "rotor",      # a hub with radiating blades
    "blade",
    "coil",       # a heating element
    "spring",
    "lever",      # a bar on a pivot
    "handle",
    "arm",        # a jointed arm — an instrument arm, a crane jib
    "antenna",    # a mast with a dish
    "panel",      # a ruled rectangle — a solar array, a screen
    # environment
    "liquid",     # a filled region with a wavy top
    "ground",     # a hatched ground or seabed line
}
_APPARATUS_DEFAULT = "box"

# Scenery, not parts of the OBJECT. Kept out of the box-rule's count for the
# reason that rule documents, and out of `named_form` for the same one: a part
# called "Breeding ground" is a place, and drawing it as the hatched ground line
# would both lose the part and let a figure of nothing but boxes past the rule
# by looking like it had scenery in it.
_ENVIRONMENT_FORMS = {"ground", "liquid"}

# The words a part is CALLED, mapped to the shape that draws it.
#
# Not a new policy: this is the vocabulary's own documentation made
# machine-readable. Every entry is a word already offered as an example of its
# form — by the comments above (`column` "a tall narrow upright — tower, shaft,
# stem", `funnel` "a trapezoid narrowing downward — hopper") or by the prose the
# draw prompt states in `FIGURE_DRAW_SYSTEM` ("a reservoir is a `tank`; a tray
# or deck is a `platform`; a duct is a `pipe`; a filter or tap is a `valve`") —
# plus the words live figures actually used and got a plain rectangle for.
#
# 🔬 Why it is consulted at all: `box` is documented as "the fallback for a part
# no other form fits, never the default", and a figure drawn entirely from it is
# REFUSED. In the 60-set sweep of 2026-09-01 that refusal was the biggest single
# class, 3 of 7 — and one of them was a termite mound whose parts were a
# chimney, a shaft, a tunnel and a reservoir. The vocabulary has a shape for
# every one of those. Nothing was missing but the lookup.
_FORM_WORDS = {
    # tall narrow uprights
    "tower": "column", "shaft": "column", "stem": "column", "chimney": "column",
    "flue": "column", "mast": "column", "trunk": "column",
    # vessels
    "vessel": "chamber", "cavity": "chamber", "compartment": "chamber",
    "motor": "chamber", "compressor": "chamber", "housing": "chamber",
    "casing": "chamber", "reservoir": "tank", "cistern": "tank",
    "cylinder": "tank", "drum": "tank", "can": "canister",
    "extinguisher": "canister", "cartridge": "canister",
    # bodies seen whole
    "egg": "oval", "seed": "oval", "cell": "oval", "grain": "oval",
    # connectors
    "duct": "pipe", "tunnel": "pipe", "channel": "pipe", "conduit": "pipe",
    "passage": "pipe", "tube": "hose", "tubing": "hose", "spout": "nozzle",
    "jet": "nozzle",
    # controls and closures
    "tap": "valve", "filter": "valve", "sluice": "valve", "lid": "cap",
    "cover": "cap", "gate": "frame", "window": "frame", "mesh": "frame",
    "grille": "frame",
    # turning parts
    "pulley": "disc", "pump": "disc", "fan": "rotor", "propeller": "rotor",
    "impeller": "rotor", "turbine": "rotor", "gear": "wheel", "cog": "wheel",
    # flats and frames
    "deck": "platform", "table": "platform", "shelf": "platform",
    "tray": "platform", "floor": "platform", "array": "panel",
    "screen": "panel", "display": "panel", "solar": "panel",
    # heaps, heat and reach
    "hill": "mound", "heap": "mound", "pile": "mound", "spoil": "mound",
    "element": "coil", "heater": "coil", "filament": "coil",
    "jib": "arm", "boom": "arm", "crane": "arm", "dish": "antenna",
    "aerial": "antenna", "hopper": "funnel", "crate": "stack",
    "tripod": "stand", "roof": "dome", "cupola": "dome",
}


def named_form(part: object, known: set) -> str:
    """The shape this part's OWN words name, or "" if they name none.

    The id first — it is the model's own tag for the thing (`chimney`,
    `balance_cavity`) — then the printed name, which on a broken figure is
    often just the gap. A word that IS a form wins outright: a part tagged
    `filling_valve` and drawn as a `box` was already telling us what it is.
    """
    if not isinstance(part, dict):
        return ""
    for source in (part.get("id"), part.get("name")):
        for word in re.split(r"[^a-z]+", _text(source).lower()):
            if word in known and word not in _ENVIRONMENT_FORMS:
                return word
            form = _FORM_WORDS.get(word)
            if form in known and form not in _ENVIRONMENT_FORMS:
                return form
    return ""


# Layer bands, top of the section down.
_LAYER_FORMS = {"rock", "soil", "sand", "clay", "water", "air", "band"}
_LAYER_DEFAULT = "band"

# Panel controls, laid out in reading order across the device face.
_PANEL_FORMS = {"button", "dial", "switch", "light", "display", "slot", "gauge"}
_PANEL_DEFAULT = "button"

_FORMS = {
    # A scene draws the same vocabulary as an assembly; the difference is
    # WHERE it puts them, not what it can draw.
    SCENE: (_APPARATUS_FORMS, _APPARATUS_DEFAULT),
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

# A callout carries a CLAUSE from the passage, which is what makes a diagram a
# reading question instead of a picture. Measured against the books in
# `books/ielts book/` (render them with `tools/cambridge_figure_atlas.py`):
#
#   Cambridge 9 T3, "An Undersea Turbine"
#     "Whole tower can be raised for __23__ and the extraction of seaweed
#      from the blades"                                          15 words
#     "Air bubbles result from the __25__ behind blades. This is
#      known as __26__"                                           14 words
#   Cambridge 11 T1, "How a boat is lifted on the Falkirk Wheel"
#     "A pair of __20__ are lifted in order to shut out water from
#      canal basin"                                               17 words
#   Cambridge 7 T2, "The Operational Cycle" (Listening)
#     "Float dropped into ocean and __23__ by satellite"           8 words
#
# This constant used to read 6, with a comment asserting that "no exam diagram"
# prints a sentence. It does — in both papers — and the cap was the reason our
# figures carried no passage context: the model was forced to write "__23__"
# where Cambridge writes a clause the student has to match against the text.
# 20 leaves headroom over the longest measured (17).
_MAX_LABEL_WORDS = 20

# Cambridge does also print a bare "__11__" on a leader line, but only where a
# lettered answer box supplies the options (Cambridge 9 T2 "Water Heater"). Our
# diagram labelling asks the student for words FROM the passage, so a figure of
# nothing but bare blanks tells them nothing about what to write. At least half
# the callouts must carry context; the 1670-clock figure in Cambridge 8, the
# thinnest real example, passes at exactly half.
_MIN_CONTEXT_WORDS = 2

# An answer and the word printed beside it differ by a plural more often than
# by anything else: a part named "Ventilation shaft" beside the answer
# `ventilation shafts` handed the student gap 1 and matched no rule, because
# every check here compares `norm`ed text and `norm` does not stem. Live
# 2026-08-29, in 2 of 16 figures. The stem is deliberately crude — it exists to
# close singular/plural, not to do morphology — and it only ever makes a match
# MORE likely, so the worst it can cost is one blanked orientation label.
_PLURALS = ("ies", "es", "s")
_MIN_STEM = 4

# The one question type that answers itself on a drawn figure.
_LABELLING = canon("diagram_label_completion")

# A blank the model wrote without the number in it — "The _______ on the deck".
# Only ever consulted for a callout that carries no `__N__` of its own, so the
# underscores of a real gap cannot match it.
_BARE_BLANK_RE = re.compile(r"_{2,}|\.{4,}")

# An answer that names no thing: an ordinal plus a generic noun, or a numbered
# stage. Anchored whole-string so "pupal stage" — a term a passage really can
# supply — is untouched.
_EMPTY_ANSWER_RE = re.compile(
    r"^(?:the )?"
    r"(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth"
    r"|next|final|last|initial)"
    r" (?:stage|step|phase|part|piece|item|process|section|component|element)s?$"
    r"|^(?:stage|step|phase|part|item|number) ?\d+$"
)


# 🔬 The model answers `layout` with `scene` whatever it is drawing: 31 of the
# 33 figures in the 2026-08-29 sweep, including every one of six runs that was
# asked in so many words for "the life cycle of the monarch butterfly" and
# every ice core. Its choice carries no information, so the layouts built for
# a cycle and for strata were never once exercised live and a life cycle drew
# as a row of boxes standing on a lawn. Read off the subject here instead.
#
# Only ever OVERRIDES `scene`. A model that names a different layout has said
# something, and this does not argue with it.
#
# 🔬 The model writes titles with TYPOGRAPHIC hyphens — "life‑cycle" is
# U+2011, not "-", and so are "Cross‑section" and "Hand‑operated". An
# ASCII-only character class matched none of them and the first version of
# this chooser reassigned nothing at all.
_DASHES = re.compile(r"[‐-―−]")
_CYCLE_SUBJECT_RE = re.compile(
    r"\blife[\s\-]?cycles?\b|\bcycle of\b|\bcyclical\b|\breproductive cycle\b",
    re.I,
)
_LAYERS_SUBJECT_RE = re.compile(
    r"\blayers?\b|\bstrata\b|\bstratigraph\w*\b|\bice core\b|\bsoil profile\b"
    r"|\bhorizons\b|\bseams\b",
    re.I,
)
# A part called "Dust layer" or "Bubble-rich zone" says stratum even when the
# title does not.
_LAYER_PART_RE = re.compile(r"\b(layer|zone|band|stratum|seam|horizon)s?\b", re.I)
_MIN_LAYER_PARTS = 3


def choose_layout(visual: object) -> str:
    """The layout the SUBJECT calls for, when the model has not chosen one.

    Deliberately narrow: a wrong layout draws a worse figure than a dull one,
    so each rule needs a signal that means only one thing. Everything else
    stays `scene`, which is the general case and the one that degrades best.
    """
    layout = diagram_layout(visual)
    if layout != SCENE:
        return layout
    parts = diagram_parts(visual)
    title = _DASHES.sub("-", _text(isinstance(visual, dict) and visual.get("title")))
    if len(parts) >= 3 and _CYCLE_SUBJECT_RE.search(title):
        return CYCLE
    stratified = sum(
        1
        for p in parts
        if _LAYER_PART_RE.search(_DASHES.sub("-", _text(p.get("name"))))
    )
    if _LAYERS_SUBJECT_RE.search(title) or stratified >= _MIN_LAYER_PARTS:
        # A cross-section of strata is only a `layers` figure while the parts
        # really do stack. One that nests a part inside another is a scene
        # drawn in section — an ice core inside its drill barrel — and the
        # band renderer has nowhere to put the contents.
        if len(parts) >= 3 and not any(p.get("in") for p in parts):
            return LAYERS
    return SCENE


def labelling_numbers(questions: list) -> list[str]:
    """The question numbers a drawn diagram has to carry a gap for.

    Shared with the redraw, which needs them for the figure that came back
    with no gaps at all: the numbers cannot be read off a drawing that never
    printed any, so they come from the questions instead.
    """
    return [
        str(q.get("number"))
        for q in (questions or [])
        if isinstance(q, dict)
        and qtype(q) == _LABELLING
        # `str(x or "")` would drop a question numbered 0, and the headings
        # rebuild really does write one as a placeholder.
        and str(q.get("number")).isdigit()
    ]


def stem_words(text: str) -> str:
    """`norm`ed text with a trailing plural taken off each word."""
    out = []
    for word in norm(text).split():
        for suffix in _PLURALS:
            if len(word) - len(suffix) >= _MIN_STEM and word.endswith(suffix):
                word = word[: -len(suffix)] + ("y" if suffix == "ies" else "")
                break
        out.append(word)
    return " ".join(out)


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

    An unknown layout becomes `scene` rather than failing the set: placing
    parts in two dimensions is the general case, and an assembly is the
    special case where every part happens to sit in one column.
    """
    if not is_diagram(visual):
        return ""
    want = _text(visual.get("layout")).lower().replace("-", "_").replace(" ", "_")
    return want if want in LAYOUTS else SCENE


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


def diagram_links(visual: object) -> list[dict]:
    """The drawn connections between parts, in the order they were written."""
    if not is_diagram(visual):
        return []
    raw = visual.get("links")
    if not isinstance(raw, list):
        return []
    return [lk for lk in raw if isinstance(lk, dict)]


def diagram_texts(visual: object) -> list[str]:
    """Every string the student reads on the figure — part names, callouts and
    the labels written along the links.

    One list so the self-answer detector and the validators can never disagree
    about what counts as printed on the drawing. A link label is printed text
    like any other: it can carry a gap, and it can give another gap away.
    """
    out = [_text(p.get("name")) for p in diagram_parts(visual)]
    out += [_text(lb.get("text")) for lb in diagram_labels(visual)]
    out += [_text(lk.get("label")) for lk in diagram_links(visual)]
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
    # Before the vocabulary is read, because the layout is what decides which
    # forms are legal.
    layout = choose_layout(visual)
    known, default = _FORMS.get(layout, (set(), _APPARATUS_DEFAULT))

    parts: list[dict] = []
    seen: set[str] = set()
    for i, raw in enumerate(diagram_parts(visual)):
        pid = _slug(raw.get("id") or raw.get("name"), f"part{i + 1}")
        while pid in seen:
            pid += "_2"
        seen.add(pid)
        form = _text(raw.get("form")).lower().replace("-", "_").replace(" ", "_")
        settled = form if (not known or form in known) else default
        # A part that comes out as the FALLBACK has not been given a shape —
        # whether the model wrote nothing, wrote something the renderer does not
        # know, or wrote `box` itself, which is documented as the fallback and
        # never the default. Before settling for it, read what the part is
        # called: the vocabulary usually has the very shape its own name says.
        if known and settled == default:
            settled = named_form(raw, known) or default
        part = {
            "id": pid,
            "form": settled,
            "name": _gap_form(_text(raw.get("name"))),
        }
        # An apparatus part may hang off the side of the spine instead of
        # sitting in it, and a tree node names its parent. Both are carried
        # only when they resolve, so a dangling reference cannot reach the
        # renderer as a part attached to nothing.
        # Scene placement. Clamped rather than refused: a part outside the
        # grid is a part the renderer would drop, and a clamped one is still
        # in roughly the right place.
        for key, lo, hi in (("col", 0, 5), ("row", 0, 4), ("w", 1, 6), ("h", 1, 5)):
            if raw.get(key) is not None:
                try:
                    part[key] = max(lo, min(hi, int(float(str(raw[key])))))
                except (TypeError, ValueError):
                    pass
        for key in ("attach", "to", "parent", "in"):
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
        # A container that does not exist, or a part inside itself, would reach
        # the renderer as a part drawn nowhere.
        if p.get("in") not in ids or p.get("in") == p["id"]:
            p.pop("in", None)

    # ONE level of nesting. A part inside a part that is itself inside
    # something has no box to be drawn in, and both would vanish; the exam
    # never draws a cross-section three deep either.
    holders = {p["id"] for p in parts if p.get("in")}
    for p in parts:
        if p.get("in") in holders:
            p.pop("in", None)

    if layout == SCENE:
        _settle_scene_cells(parts)

    links = []
    for raw in (visual.get("links") or []) if isinstance(visual.get("links"), list) else []:
        if not isinstance(raw, dict):
            continue
        a = _slug(raw.get("from"), "")
        b = _slug(raw.get("to"), "")
        if a not in ids or b not in ids or a == b:
            continue
        style = _text(raw.get("style")).lower()
        links.append({
            "from": a,
            "to": b,
            "style": style if style in ("pipe", "arrow", "line") else "line",
            "label": _gap_form(_text(raw.get("label"))),
        })

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
        "links": links,
    }


_SCENE_COLS = 6
_SCENE_ROWS = 5


def _settle_scene_cells(parts: list[dict]) -> None:
    """Stop two parts of a scene being drawn on top of each other, in place.

    The prompt says "two parts must never be given the same cell" and the
    renderer trusted it. Live 2026-08-28: a vertical-farm cross-section put a
    `valve` over its water tank, so "Water tank" and "Sensor unit" printed
    across each other, and a `ground` part landed inside the foundation slab so
    "Sea bed" was written in the middle of it.

    This is the same bargain every other figure strikes -- the grid plan states
    which room is where and the renderer derives the walls; a flow chart states
    only the order. Geometry the generator can get wrong is geometry the
    generator should not be trusted with, so a collision is settled here rather
    than refused: refusing costs a whole hosted regeneration, and a part nudged
    one cell along is still in roughly the right place.

    Nested parts are settled too, but against their CONTAINER's 3x3 sub-grid
    rather than this one -- a yolk moved on the scene's grid would leave its
    shell. The live vertical farm put a `valve` sensor and a `tank` reservoir
    on the same sub-cells inside one column, and the bowtie was drawn straight
    through the tank's name.

    `ground` is not nudged sideways: it is the surface the drawing stands on,
    so it is dropped to its own row below everything else and spans the full
    width, which is where the exam draws it.
    """
    placed = [p for p in parts if not p.get("in")]
    ground = [p for p in placed if p.get("form") == "ground"]
    standing = [p for p in placed if p.get("form") != "ground"]

    taken: set[tuple[int, int]] = set()

    def cells(col: int, row: int, w: int, h: int):
        return {(c, r) for c in range(col, col + w) for r in range(row, row + h)}

    for part in standing:
        col = int(part.get("col", 0) or 0)
        row = int(part.get("row", 0) or 0)
        w = max(1, int(part.get("w", 1) or 1))
        h = max(1, int(part.get("h", 1) or 1))
        w = min(w, _SCENE_COLS)
        h = min(h, _SCENE_ROWS)
        if not (cells(col, row, w, h) & taken):
            taken |= cells(col, row, w, h)
            part["col"], part["row"], part["w"], part["h"] = col, row, w, h
            continue
        # Scan from where it asked to be: along its own row first, so a part
        # meant to sit beside another still does, then down.
        spot = None
        for r in range(row, _SCENE_ROWS):
            for c in range(0, _SCENE_COLS):
                if c + w > _SCENE_COLS or r + h > _SCENE_ROWS:
                    continue
                if not (cells(c, r, w, h) & taken):
                    spot = (c, r)
                    break
            if spot:
                break
        if spot is None:
            # Nowhere at its own size: shrink to one cell and take the first
            # free one. A part drawn small is still drawn; a part drawn over
            # its neighbour loses both.
            w = h = 1
            spot = next(
                (
                    (c, r)
                    for r in range(_SCENE_ROWS)
                    for c in range(_SCENE_COLS)
                    if (c, r) not in taken
                ),
                (0, 0),
            )
        taken |= cells(spot[0], spot[1], w, h)
        part["col"], part["row"], part["w"], part["h"] = spot[0], spot[1], w, h

    if ground:
        floor = max((p["row"] + p["h"] for p in standing), default=0)
        floor = min(floor, _SCENE_ROWS - 1)
        for part in ground:
            part["col"], part["row"] = 0, floor
            part["w"], part["h"] = _SCENE_COLS, 1

    # Each container's contents, on its own 3x3 sub-grid.
    inside: dict[str, list[dict]] = {}
    for part in parts:
        if part.get("in"):
            inside.setdefault(part["in"], []).append(part)
    for held in inside.values():
        used: set[tuple[int, int]] = set()
        for part in held:
            col = max(0, min(2, int(part.get("col", 1) or 0)))
            row = max(0, min(2, int(part.get("row", 1) or 0)))
            w = max(1, min(3 - col, int(part.get("w", 1) or 1)))
            h = max(1, min(3 - row, int(part.get("h", 1) or 1)))
            want = {(c, r) for c in range(col, col + w) for r in range(row, row + h)}
            if want & used:
                spot = next(
                    (
                        (c, r)
                        for r in range(3)
                        for c in range(3)
                        if c + w <= 3
                        and r + h <= 3
                        and not (
                            {
                                (cc, rr)
                                for cc in range(c, c + w)
                                for rr in range(r, r + h)
                            }
                            & used
                        )
                    ),
                    None,
                )
                if spot is None:
                    # No room at this size: one sub-cell, or the first free one.
                    w = h = 1
                    spot = next(
                        (
                            (c, r)
                            for r in range(3)
                            for c in range(3)
                            if (c, r) not in used
                        ),
                        (col, row),
                    )
                col, row = spot
                want = {
                    (c, r) for c in range(col, col + w) for r in range(row, row + h)
                }
            used |= want
            part["col"], part["row"], part["w"], part["h"] = col, row, w, h


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
    for link in diagram_links(visual):
        if link.get("label"):
            link["label"] = move(str(link["label"]))


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
    inside "sixteen" — and on the stem, because the figure gives the answer
    away just as completely when it prints the singular of it.
    """
    texts = diagram_texts(visual)
    out: list[tuple[str, str, str]] = []
    for gap in diagram_gaps(visual):
        raw = _text((answer_key or {}).get(gap))
        want = stem_words(raw)
        if not want:
            continue
        for text in texts:
            prose = stem_words(DIAGRAM_GAP_RE.sub(" ", text))
            if f" {want} " in f" {prose} ":
                out.append((gap, raw, text))
                break
    return out


def diagram_error(
    visual: object, questions: list, answer_key: dict, *, after_repairs: bool = True
) -> str | None:
    """Why this figure is not a printable IELTS diagram, or None if it is.

    Refuses only what cannot be drawn or cannot be answered. A figure the
    student can read but that is merely plain is not an error — the cost of a
    refusal is a full hosted regeneration, so the bar is "unusable", never
    "improvable".

    `after_repairs=False` drops the two faults the redraw pass fixes for free —
    a question with no gap, and two callouts on one part. Both are worth
    refusing at the final gate and worth saying nothing about on the way in:
    complaining to the model buys a retry of the whole set where
    `redraw_diagram` buys the same figure back for one call. Measured
    2026-08-29: judged on the way in, both faults killed their set outright
    because the hook fires before the repair pipeline the rescue lives in.
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
                "a diagram callout runs longer than the exam prints one "
                f"({words} words; at most {_MAX_LABEL_WORDS})"
            )

    # A callout that is only its blank points a leader at a shape and asks the
    # student to name it from nothing. The exam does that only when a lettered
    # box supplies the options, which this task type has not got.
    numbered = [
        label for label in labels if DIAGRAM_GAP_RE.search(_text(label.get("text")))
    ]
    if len(numbered) >= 3:
        with_context = [
            label
            for label in numbered
            if len(DIAGRAM_GAP_RE.sub(" ", _text(label.get("text"))).split())
            >= _MIN_CONTEXT_WORDS
        ]
        if len(with_context) * 2 < len(numbered):
            return (
                f"{len(numbered) - len(with_context)} of {len(numbered)} numbered "
                "callouts are a bare blank with no words around them, so the "
                "figure gives the student nothing to match against the passage. "
                "Write the callout the way the exam does — a clause the passage "
                "supports, with the blank inside it (\"Air bubbles result from "
                "the __25__ behind blades\")"
            )

    # 🔬 The same fault reached through a part's NAME instead of a callout,
    # which the rule above cannot see because it reads only `labels`. Live
    # 2026-08-29: a coffee grinder drawn as a `panel` whose five parts were
    # named nothing but `__1__`..`__5__`, with no callouts at all — and whose
    # hopper, handle, chamber and container had every one been flattened to the
    # panel vocabulary's `button`. FIVE IDENTICAL CIRCLES, numbered, with the
    # student asked to name them from nothing. Every answer was the part's own
    # id. It passed every check there was.
    #
    # What makes that unanswerable is not the bare number — Cambridge 9 T2's
    # "Water Heater" numbers its controls bare and is a real exam figure. It is
    # that nothing on the drawing tells one numbered part from another. The
    # Water Heater's are a button, a switch and a light; the grinder's were
    # four of the same circle. So the rule is about how many of the bare
    # numbered parts SHARE a shape, and a figure whose callouts carry the
    # context instead is left alone.
    bare = [
        part
        for part in parts
        if DIAGRAM_GAP_RE.search(_text(part.get("name")))
        and len(DIAGRAM_GAP_RE.sub(" ", _text(part.get("name"))).split())
        < _MIN_CONTEXT_WORDS
    ]
    # A callout that POINTS AT one of those parts and says something about it
    # answers the objection, whether or not it carries a gap of its own: the
    # student has a clause to match against the passage and a leader line
    # saying which shape it belongs to. That is the sewing machine, where the
    # numbers ride on the parts and the callouts explain them.
    bare_ids = {_slug(p.get("id") or p.get("name"), "") for p in bare}
    explained = [
        label
        for label in labels
        if _slug(label.get("at") or label.get("target") or label.get("part"), "")
        in bare_ids
        and len(DIAGRAM_GAP_RE.sub(" ", _text(label.get("text"))).split())
        >= _MIN_CONTEXT_WORDS
    ]
    # Exempt where the figure's STRUCTURE tells one part from another: a cycle
    # and a tree order their nodes and layers stack top to bottom, so a bare
    # number there still has the passage's own sequence to be matched against —
    # and `_FORMS` gives those layouts no vocabulary at all, so every part
    # shares a shape by construction and this rule would refuse every one of
    # them. A scene, an assembly and a panel place parts where the model put
    # them, and identical shapes there tell the student nothing.
    ordered = choose_layout(visual) in (CYCLE, TREE, LAYERS)
    if len(bare) >= 3 and not explained and not ordered:
        shapes = Counter(_text(p.get("form")) for p in bare)
        commonest, count = shapes.most_common(1)[0]
        # More than half sharing one shape. Three DIFFERENT controls pass; four
        # of five the same do not.
        if count * 2 > len(bare):
            return (
                f"{count} of the {len(bare)} numbered parts are drawn as the "
                f"same `{commonest}` and carry a bare number and nothing else, "
                "so the student is asked to tell identical shapes apart with "
                "nothing to go on. Either draw each numbered part as the thing "
                "it really is, or put its number in a callout that states what "
                "the passage says about it."
            )

    ids_set = {_slug(p.get("id") or p.get("name"), "") for p in parts}
    for link in diagram_links(visual):
        for end in ("from", "to"):
            if _slug(link.get(end), "") not in ids_set:
                return (
                    "a diagram link joins a part the figure does not draw "
                    f"({_text(link.get(end)) or 'unnamed'})"
                )

    # Nothing on the drawing is readable if the parts have no names and no
    # callouts. That is a picture, not a labelling task.
    if not diagram_texts(visual):
        return "the diagram prints no labels at all, so there is nothing to read"

    # 🔬 `cycle` and `tree` are exempt from the two `form` rules that follow,
    # because in those layouts `form` is not drawn at all — `_FORMS` gives them
    # an empty vocabulary and the renderer derives every shape from the layout
    # ("the layout, not the part, is what gives them their shape"). So a stage
    # of a life cycle comes back as `box` whatever the model writes, and both
    # rules were refusing a figure over a field with no effect on the picture.
    # A live monarch-butterfly cycle died this way twice, on `caterpillar`,
    # `chrysalis` and `adult` — exactly the stages a cycle diagram is made of.
    #
    # Exempt from these two only. Every other check below still applies.
    #
    # 🔬 Asked through `choose_layout`, not `diagram_layout`, because this runs
    # on the way IN — before `normalize_diagram` has settled the layout — and
    # the two answers differ for exactly the figures that need the exemption.
    # An Antarctic ice core arrives as `scene` with every part a `box` and is
    # refused for being all boxes; normalisation would have made it `layers`,
    # where no part is a box at all because the band vocabulary has no such
    # form. One of the four failures in the 36-set sweep of 2026-08-29 died
    # that way (`r_diagram_layers_r4`). `layers` joins the exemption for the
    # same reason `cycle` has it: the band, not the part, is what gives a
    # stratum its shape.
    shaped = choose_layout(visual) not in (CYCLE, TREE, LAYERS)

    # A figure drawn entirely from `box` looks the same whatever it is of,
    # which is the complaint that prompted the whole `scene` rewrite. `box` is
    # the fallback for a part no other form fits, never the default. Refused
    # only when EVERY part is one, so a single genuinely box-shaped part still
    # passes.
    # Environment forms are excluded from the count: a `ground` line is not a
    # part of the OBJECT, and counting it let a figure of nothing but boxes
    # slip through because it happened to stand on something.
    drawn_forms = {
        p.get("form") for p in parts
        if p.get("form") not in _ENVIRONMENT_FORMS
    }
    if shaped and len(parts) >= 3 and drawn_forms and drawn_forms <= {"box"}:
        return (
            "every part of the diagram is drawn as a plain `box`, so the figure "
            "does not look like the thing it is of. Choose the form that "
            "matches each real part — a canister, a wheel, a pipe, a panel. "
            "If the parts are not physical objects at all but STAGES of a "
            "process or branches of a classification, draw it as `cycle` or "
            "`tree` instead: those layouts take no form and a stage is drawn "
            "from its position, not its shape."
        )

    # 🔬 Live 2026-08-27: asked for a solar plant, the model drew three real
    # parts and then a ROW of empty `box`es underneath whose only content was
    # `__1__`, `__2__`, `__3__` — filler to hang the numbers on. A student
    # numbering a blank rectangle is being asked to name a shape that could be
    # anything. A number belongs on a part that is drawn as something, or in a
    # callout pointing at one.
    filler = [
        part
        for part in parts
        if part.get("form") == "box"
        and _text(part.get("name"))
        and not DIAGRAM_GAP_RE.sub("", _text(part.get("name"))).strip()
    ]
    # Two or more, not one: a single rectangular component is a real thing to
    # number, and refusing it costs a whole hosted regeneration. A ROW of them
    # is the filler pattern -- three empty boxes under the drawing holding
    # `__1__`, `__2__`, `__3__` -- which is what was seen live.
    if shaped and len(filler) >= 2:
        names = ", ".join(repr(p.get("id")) for p in filler)
        return (
            f"parts {names} are plain `box`es whose only content is their gap, "
            "so the student is asked to name blank rectangles. Put each number "
            "on the part it names, or in a callout pointing at it — never on a "
            "box added to hold it."
        )

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

    # ...and the other half of that invariant, which the comment above has
    # promised since `b089b4a` and nothing has ever enforced. 🔬 Live
    # 2026-08-29, in 2 of 16 figures that PASSED: one wrote a bare `_______`
    # into all four callouts, so the drawing carried no numbers at all and
    # four questions had nowhere to be answered; the other drew one gap for
    # four questions. Both shipped. A question with no gap is the most
    # complete failure a figure can have — the student is asked about a part
    # the drawing never points at.
    labelling = labelling_numbers(questions)
    ungapped = [n for n in labelling if n not in set(gaps)]
    if ungapped and after_repairs:
        blank_but_unnumbered = [
            lb
            for lb in labels
            if _BARE_BLANK_RE.search(_text(lb.get("text")))
            and not DIAGRAM_GAP_RE.search(_text(lb.get("text")))
        ]
        if blank_but_unnumbered:
            return (
                f"question {ungapped[0]} has no gap on the diagram: "
                f"{len(blank_but_unnumbered)} callout(s) write the blank as a "
                "row of underscores with no number in it, which prints a "
                "leader line the student cannot match to any question. Write "
                "each blank as __N__ with the question's own number in it "
                '("The __3__ carries air to the helmet").'
            )
        return (
            f"question {ungapped[0]} asks about a part of the diagram that "
            f"carries no gap ({len(gaps)} gap(s) drawn for {len(labelling)} "
            "question(s)), so there is nowhere on the figure to write the "
            "answer. Every numbered question needs its own __N__ on the "
            "drawing."
        )

    # Two leader lines into one shape ask the student to give that shape two
    # different names. 🔬 Live 2026-08-29: a termite mound with 8 gaps on 4
    # parts — wall, shaft, chimney and gallery each carrying two. A callout may
    # hold two blanks ("the __25__ behind blades, known as __26__"), which is
    # one line to one part and stays legal here; two SEPARATE callouts on one
    # part is the fault.
    targets = [
        _slug(lb.get("at") or lb.get("target") or lb.get("part"), "")
        for lb in labels
        if DIAGRAM_GAP_RE.search(_text(lb.get("text")))
    ]
    # The figure may not print the name of a part whose own name is the
    # question. `blank_gapped_part_names` deletes it, so reaching the gate with
    # one still on the drawing means that repair did not take.
    named_gap = gapped_part_names(visual)
    if named_gap and after_repairs:
        at, name, gap = named_gap[0]
        return (
            f"the figure prints {name!r} on part {at!r} while gap {gap} asks the "
            "student to name that very part, so they cannot know which word is "
            "wanted — the one on the drawing, or the one in the passage. Leave "
            "a part unnamed when its own name is the answer."
        )

    doubled = next((t for t in targets if targets.count(t) > 1), "")
    if doubled and after_repairs:
        return (
            f"part {doubled!r} carries two numbered callouts, so two leader "
            "lines point at one shape and the student must name it twice. "
            "Give each gap a part of its own, or fold both blanks into a "
            "single callout on that part."
        )

    # An answer that names no thing cannot be found in the passage. 🔬 Live
    # 2026-08-29: a monarch life cycle keyed `first stage`..`fourth stage`
    # against a figure that printed Egg, Caterpillar, Chrysalis and Adult
    # butterfly — the real answers drawn on it, and a key no reader could
    # produce. Matched narrowly, on the whole answer only, so a genuine
    # passage term like "pupal stage" still passes.
    for gap in gaps:
        answer = _text((answer_key or {}).get(gap))
        if _EMPTY_ANSWER_RE.match(norm(answer)):
            return (
                f"the answer to diagram gap {gap} is {answer!r}, which names "
                "nothing the passage says — the student cannot read an ordinal "
                "out of the text. Key each gap to the term the passage itself "
                "uses for that part."
            )

    return None


# A callout whose blank is the SUBJECT is asking the student to NAME that part:
# "The __3__ is the lever you turn to grind the beans". Anchored, because a
# blank later in the clause asks for something else about it — "The impurity
# layer contains __1__ and volcanic ash" gaps a property of a part the figure
# is free to name, and Cambridge prints exactly that.
_SUBJECT_GAP_RE = re.compile(
    r"^\s*(?:the|a|an|this|each|its)?\s*__(\d+)__\s*([A-Za-z'’\-]*)", re.I
)


def gapped_part_names(visual: object) -> list[tuple[str, str, str]]:
    """(part id, printed name, gap) for every part the figure names AND asks for.

    🔬 The commonest defect left on a live figure, 46 times over the saved
    corpus of 2026-08-29. It is not a matter of taste: the model prints a
    SYNONYM of the answer as the part's name, so a box labelled "Crank lever"
    carries a leader reading "The __3__ is the lever you turn to grind the
    beans" and the key says `handle`. A student who reads the figure writes
    "crank lever" or "lever" and is marked wrong. Cambridge never names a part
    it is about to gap — on a labelled diagram the numbered blank IS the
    part's missing name.

    A name carrying a gap of its own is left alone: that name IS the question,
    and blanking it would take the gap with it — the same rule
    `blank_self_answering_labels` keeps.

    🔬 So is a blank that MODIFIES the part rather than naming it. "The __1__
    gate holds back water at the higher level" wants an adjective — `upper` —
    and the part is still a gate, so printing "Lock gate" on it helps the
    student and gives nothing away. The first version of this rule read the
    anchor alone and deleted those names too, leaving a canal lock as five
    blank rectangles. The word after the blank is what separates the two: if it
    appears in the part's own name, the blank describes that part; if it does
    not, the blank IS the part.
    """
    if not is_diagram(visual):
        return []
    named = {
        _slug(p.get("id") or p.get("name"), ""): _text(p.get("name"))
        for p in diagram_parts(visual)
    }
    out: list[tuple[str, str, str]] = []
    for label in diagram_labels(visual):
        found = _SUBJECT_GAP_RE.match(_text(label.get("text")))
        if not found:
            continue
        at = _slug(label.get("at") or label.get("target") or label.get("part"), "")
        name = named.get(at, "")
        if not name or DIAGRAM_GAP_RE.search(name):
            continue
        after = stem_words(found.group(2))
        if after and f" {after} " in f" {stem_words(name)} ":
            continue
        out.append((at, name, found.group(1)))
    return out


def gap_the_named_answers(result: dict) -> list[tuple[str, str]]:
    """Turn an answer the figure PRINTS into the gap that asks for it.

    A labelled diagram's legal shape, the one Cambridge prints: the numbered
    blank IS the part's missing name. A figure that instead writes the name out
    and carries no gap for that question has both faults at once — it answers
    itself, and it leaves the question pointing at nothing — and the two cure
    each other in one move.

    Unambiguous, unlike anything that has to GUESS which question a mark
    belongs to: question 1 is keyed 'surface pump' and exactly one part prints
    'surface pump', so there is nothing to infer. Skipped when the match is not
    unique, or when the part already carries a gap of its own.

    🔬 Live 2026-09-01, `r_diagram_apparatus` — the Victorian diving suit, the
    trapped subject `prompts.py` warns about with a 🚨. Its four answers were
    'surface pump', 'rubber hose', 'helmet' and 'non-return valve': three
    printed as part names with no gaps at all, one drawn properly. The redraw
    spent all three attempts on it and the set was refused holding a figure
    that was one rename away from legal.
    """
    visual = result.get("visual")
    if not is_diagram(visual):
        return []
    answer_key = result.get("answer_key") or {}
    drawn = set(diagram_gaps(visual))
    parts = diagram_parts(visual)
    moved: list[tuple[str, str]] = []
    for number in labelling_numbers(result.get("questions") or []):
        if number in drawn:
            continue
        answer = norm(_text(answer_key.get(number)))
        if not answer:
            continue
        named = [
            part
            for part in parts
            if norm(_text(part.get("name"))) == answer
            and not DIAGRAM_GAP_RE.search(_text(part.get("name")))
        ]
        if len(named) != 1:
            continue
        named[0]["name"] = f"__{number}__"
        drawn.add(number)
        moved.append((_slug(named[0].get("id"), ""), number))
    return moved


def blank_gapped_part_names(result: dict) -> list[tuple[str, str, str]]:
    """Rub out the name of any part whose own identity is the question.

    Repaired rather than refused, and deterministically: there is one right
    answer — the printed name goes, the callout and its gap stay — so a
    regeneration would buy nothing a deletion does not. The student keeps the
    clause, which is what they match against the passage or the recording.
    """
    visual = result.get("visual")
    hits = gapped_part_names(visual)
    if not hits:
        return []
    guilty = {at for at, _, _ in hits}
    for part in diagram_parts(visual):
        if _slug(part.get("id") or part.get("name"), "") in guilty:
            part["name"] = ""
    return hits


def drop_doubled_gap_markers(result: dict) -> list[tuple[str, str]]:
    """Delete a gap printed on a part when a callout already carries it.

    `diagram_error` refuses a figure that prints the same gap twice, because
    one question then has two boxes and the student cannot tell which to fill.
    That rule is judged on the way IN, so the whole set dies before any repair
    in the pipeline gets a turn -- which is why this runs from `_judge_reply`
    rather than beside the other figure repairs.

    🔬 Live 2026-09-06, the first sweep after `openai/gpt-oss-120b` was retired
    and `nvidia/nemotron-3-super-120b-a12b` took over. The replacement numbers
    a figure BOTH ways at once: `helmet` is named `__1__` and a callout reads
    "The __1__ protects the diver's head and face", for all six gaps. Four of
    the seven refusals in a 40-set sweep were this one shape
    (`r_diagram_apparatus`, `r_diagram_crosssec`, twice each), and a corrective
    retry reproduced it -- the model is not being careless, it is drawing the
    figure the way it thinks the exam prints it.

    The callout is the copy worth keeping: it carries the clause that says
    WHICH part is wanted, which a bare `__1__` on a shape does not, and the
    part is then left unnamed -- exactly what `diagram_error` demands anyway of
    a part whose own name is the answer.

    Deterministic, so repaired rather than retried. Only a part whose name is
    NOTHING BUT the gap is touched: a name like "The __3__ valve" would leave
    "The valve" behind, printing the answer's own noun beside the gap keyed to
    it. Two callouts holding one gap are `merge_doubled_callouts`' business,
    not this one's, and a gap printed on two PARTS is left alone because
    nothing here can say which shape the question meant.

    Returns (part id, gap) for the caller to log.
    """
    visual = result.get("visual")
    if not is_diagram(visual):
        return []

    # Where each gap is printed, kept apart by container: the repair is only
    # safe when the surplus copy is the bare one on a part.
    elsewhere: dict[str, int] = {}
    for label in diagram_labels(visual):
        for gap in DIAGRAM_GAP_RE.findall(_text(label.get("text"))):
            elsewhere[gap] = elsewhere.get(gap, 0) + 1
    for link in diagram_links(visual):
        for gap in DIAGRAM_GAP_RE.findall(_text(link.get("label"))):
            elsewhere[gap] = elsewhere.get(gap, 0) + 1

    bare: dict[str, list[dict]] = {}
    for part in diagram_parts(visual):
        name = _text(part.get("name"))
        gaps = DIAGRAM_GAP_RE.findall(name)
        # Nothing but the gap: strip it and the name is empty.
        if len(gaps) == 1 and not DIAGRAM_GAP_RE.sub("", name).strip():
            bare.setdefault(gaps[0], []).append(part)

    dropped: list[tuple[str, str]] = []
    for gap, parts in bare.items():
        # One bare part, and the callouts hold the gap exactly once. Anything
        # else is a different fault with a different cure.
        if len(parts) != 1 or elsewhere.get(gap, 0) != 1:
            continue
        part = parts[0]
        part["name"] = None
        dropped.append((str(part.get("id") or "?"), gap))
    return dropped


def merge_doubled_callouts(result: dict) -> list[tuple[str, list[str]]]:
    """Fold two leader lines on one part into the single callout the rule allows.

    `diagram_error` refuses a part carrying two numbered callouts, because two
    leaders into one shape ask the student to name it twice. What it does NOT
    refuse is one callout holding two blanks — "the __25__ behind blades, known
    as __26__" — which is one line to one part and is what Cambridge prints. So
    the illegal figure and the legal one differ by a join, and the refusal
    message has always said so: "fold both blanks into a single callout".

    🔬 Live 2026-09-02, `r_diagram_machine_r3`, a canal lock. Two callouts sat
    on `gate` — "When the boat enters, the __2__ lowers to seal the lock" and
    "During the final stage, the __8__ is lifted" — while `balance` carried
    __6__ and __7__ in ONE callout, legally, in the same figure. The whole set
    was thrown away over a join the model had already demonstrated it knew.

    Deterministic, so repaired rather than retried: both callouts are already
    about that part, the text of each is kept whole, and the order they are
    printed in is the order they arrived. Nothing is guessed — least of all
    which question belongs to which shape, which is the repair this codebase
    has tested and rejected.

    Returns (part, numbers folded) for the caller to log.
    """
    visual = result.get("visual")
    if not is_diagram(visual):
        return []
    labels = diagram_labels(visual)
    gapped: dict[str, list[dict]] = {}
    for label in labels:
        if not DIAGRAM_GAP_RE.search(_text(label.get("text"))):
            continue
        at = _slug(label.get("at") or label.get("target") or label.get("part"), "")
        gapped.setdefault(at, []).append(label)

    merged: list[tuple[str, list[str]]] = []
    for at, group in gapped.items():
        if len(group) < 2:
            continue
        joined = _join_callouts([_text(lb.get("text")) for lb in group])
        # A join that overruns the cap is not a repair: the set would be
        # refused for the callout's length instead of for its doubling, which
        # is the same set lost and a worse sentence to diagnose it by.
        # `condense_doubled_callouts` writes those as one clause, the way the
        # exam prints a two-blank callout.
        if len(joined.split()) > _MAX_LABEL_WORDS:
            continue
        keeper, rest = group[0], group[1:]
        keeper["text"] = joined
        # By identity, not equality: two callouts that happen to read alike
        # are still two objects, and dropping the wrong one drops its gap.
        visual["labels"] = [
            lb for lb in diagram_labels(visual)
            if not any(lb is dropped for dropped in rest)
        ]
        merged.append(
            (at, DIAGRAM_GAP_RE.findall(_text(keeper.get("text")))))
    return merged


def _join_callouts(texts: list[str]) -> str:
    """Two callouts as one line of the figure.

    Whole sentences are kept whole and simply follow one another — the student
    matches a callout's wording against the passage, so trimming it to fit
    would cost them the match the gap is answered from. Fragments, which is
    what the exam prints more often ("Float dropped into ocean and __23__ by
    satellite"), are joined with a semicolon: a full stop after a phrase that
    was never a sentence reads as a typo on the drawing.
    """
    parts = [t.strip() for t in texts if t.strip()]
    if all(p.endswith((".", "!", "?")) for p in parts):
        return " ".join(parts)
    return "; ".join(p.rstrip(".") for p in parts)


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


# A labelled figure is worth printing only if it asks about several parts.
# Cambridge never prints one with a single blank, and all 5 figure-bearing
# corpus sets carry 3 or 4. One label is a figure drawn for its own sake rather
# than a question block -- and `ad0e767` needs 3+ numbered items anyway, so a
# sparse figure cannot simply have its odd question dropped.
MIN_LABELS = 3


def sparse_diagram_error(labelling_questions: list) -> str | None:
    """Reject a figure that numbers too few of its parts to be worth drawing.

    Takes the QUESTIONS rather than the figure, because this is a judgement
    about the question block: a set that asks about two parts is the fault
    whether or not the drawing itself is fine. Shared by both trainers so the
    reading and listening thresholds cannot drift apart.
    """
    count = len(labelling_questions or [])
    if not count or count >= MIN_LABELS:
        return None
    return (
        f"the diagram carries only {count} numbered part(s); a labelled figure "
        f"is worth printing only if it asks about at least {MIN_LABELS} of "
        "them. Number that many parts on the figure and write one question for "
        "each, or drop the diagram and use another question type."
    )


def inaudible_diagram_error(
    visual: object, answer_key: dict, script: str
) -> str | None:
    """Reject a listening diagram whose answer the recording never says.

    A Listening gap-fill answer is words the student HEARS. Reading has enforced
    that against its passage since `84c426c` (`_non_verbatim_answers`); the
    listening side has never had the rule at all, for any question type.

    Scoped to the drawn diagram on purpose, and narrowly:

    * this is the failure the diagram schema itself invites. `id` is an
      internal tag written as a lowercase slug, and it sits in the payload
      right beside the answer -- a live Part 2 keyed 'grouphead' and
      'steamwand' off the ids of parts the script calls "group head" and
      "steam wand", which a student can never write.
    * a rule scoped to a question type that did not exist yesterday cannot
      refuse a set that worked before it, so it needs no corpus measurement to
      be safe. The GENERAL listening verbatim rule does, and is not built here.

    Matched on padded whole words after `norm`, the same way every other
    figure check in this module matches.
    """
    if not is_diagram(visual) or not script:
        return None
    heard = f" {norm(script)} "
    for gap in diagram_gaps(visual):
        answer = _text((answer_key or {}).get(gap))
        want = norm(answer)
        if not want or f" {want} " in heard:
            continue
        return (
            f"the answer to diagram gap {gap} is {answer!r}, which the script "
            "never says. A Listening answer is words the student HEARS, so key "
            "each numbered part to the wording the speaker actually uses — "
            "never to the part's `id`, which is an internal tag and not "
            "something anyone says aloud."
        )
    return None


# ---------------------------------------------------------------------------
# Picture choice — "Which diagram shows ...? A, B or C"
#
# The exam prints two to four small line drawings and asks which one matches
# what the speaker described. It is the diagram vocabulary again, so it lives
# here: a choice is a diagram body without a kind of its own, and the student
# answers with a letter rather than by writing into a gap.
# ---------------------------------------------------------------------------

PICTURE_KIND = "picture"

_MIN_CHOICES = 2
_MAX_CHOICES = 4
# What the exam actually prints: three pictures, A, B and C. Every Cambridge
# picture-choice item has three, and a two-picture item is a coin toss rather
# than a question.
#
# 🔬 2026-09-01, eight live picture sets: six emitted three choices and every
# one was clean; BOTH of the two that emitted only two had drawn the same
# picture twice, and both were refused. Emitting two is not a second defect
# beside the duplicate — it is the same one. The model collapses "differ in
# one feature" into one drawing and then has only two to show. So the count is
# held on the way IN, where a corrective retry is cheap, rather than left to
# `drop_duplicate_pictures`, which cannot help a set with nothing to drop.
_EXAM_CHOICES = 3


def is_picture(visual: object) -> bool:
    return (
        isinstance(visual, dict)
        and str(visual.get("kind", "")).lower() == PICTURE_KIND
    )


def picture_choices(visual: object) -> list[dict]:
    if not is_picture(visual):
        return []
    raw = visual.get("choices")
    if not isinstance(raw, list):
        return []
    return [c for c in raw if isinstance(c, dict)]


def normalize_picture(visual: object) -> dict | None:
    """Clean a generated picture-choice, or None if it is not one.

    Each choice is normalised through the diagram normaliser, so a picture
    cannot drift away from what the diagram renderer knows how to draw. Letters
    are reassigned A, B, C in order rather than trusted: the model numbers them
    out of order often enough, and the letter is the ANSWER, so a wrong one
    marks a correct student wrong.
    """
    if not is_picture(visual):
        return None
    choices = []
    for i, raw in enumerate(picture_choices(visual)):
        body = normalize_diagram({**raw, "kind": DIAGRAM_KIND}) or {}
        choices.append({
            "letter": chr(ord("A") + i),
            "layout": body.get("layout", APPARATUS),
            "parts": body.get("parts", []),
            "labels": body.get("labels", []),
        })
    return {
        "kind": PICTURE_KIND,
        "title": _text(visual.get("title")),
        "choices": choices,
    }


def picture_error(
    visual: object, questions: list, answer_key: dict, *, exam_count: bool = True
) -> str | None:
    """Why this is not a printable picture-choice question, or None if it is.

    The letter is the answer, so what matters is that every choice is drawable
    and that the keyed letter is one of them. A choice the renderer cannot draw
    is a blank box beside three real ones, which tells the student the answer.

    `exam_count=False` drops the floor from the three the exam prints to the
    two that are still markable. It is for the gate that runs AFTER
    `drop_duplicate_pictures`: that repair deletes a twin, and a three-picture
    set which loses one is left with two. Refusing there would discard a whole
    generation to enforce a count, having already fixed the fault that made the
    set unmarkable.
    """
    if not is_picture(visual):
        return None

    choices = picture_choices(visual)
    floor = _EXAM_CHOICES if exam_count else _MIN_CHOICES
    if not floor <= len(choices) <= _MAX_CHOICES:
        return (
            f"a picture-choice question needs {floor}-{_MAX_CHOICES} "
            f"pictures to choose between, not {len(choices)}. The exam prints "
            f"{_EXAM_CHOICES}: the correct one and two that differ from it in "
            "the single thing the question asks about"
        )

    for i, choice in enumerate(choices):
        letter = chr(ord("A") + i)
        parts = [p for p in (choice.get("parts") or []) if isinstance(p, dict)]
        if not _MIN_PARTS <= len(parts) <= _MAX_PARTS:
            return (
                f"picture {letter} has {len(parts)} parts; each picture needs "
                f"{_MIN_PARTS}-{_MAX_PARTS} to be a drawing at all"
            )

    # A gap belongs to a completion question. Here the student writes a letter,
    # so a `__n__` anywhere means the model has mixed the two tasks together.
    body = {"kind": DIAGRAM_KIND, "parts": [], "labels": []}
    for choice in choices:
        body = {"kind": DIAGRAM_KIND, **choice}
        if diagram_gaps(body):
            return (
                "a picture-choice picture carries a numbered gap; the student "
                "answers with a letter here, so nothing on the pictures is "
                "written into"
            )

    # Two pictures the student cannot tell apart are two correct answers.
    # 🔬 Found live on the first picture-choice the model drew with placement:
    # choices A and B were both [box, box, hose] at the same cells, against a
    # question asking which irrigation system was most water-efficient.
    shapes = [
        tuple(
            sorted(
                (str(p.get("form")), p.get("col"), p.get("row"))
                for p in (c.get("parts") or [])
                if isinstance(p, dict)
            )
        )
        for c in choices
    ]
    # Refused only when it cannot be REPAIRED, and what decides that is how
    # many DISTINCT drawings there are — not how many letters are printed.
    # `drop_duplicate_pictures` cures a repeat by deleting it, which works only
    # while something different survives the deletion: with two distinct
    # drawings among three, the twin goes and the set is markable, so refusing
    # there would discard the script, the questions and the key over something
    # one deletion cures. With every picture the same, deletion leaves one
    # picture, which is no choice at all.
    #
    # 🔬 Live 2026-09-01, and it is the route the count rule did NOT close.
    # Asking the prompt for three pictures stopped the model emitting two; it
    # did not stop it drawing the SAME thing three times. Keyed on the count,
    # this rule passed that set clean on the way in, `drop_duplicate_pictures`
    # deleted one of the three and stopped at its floor of two, and the gate
    # after the figure work then refused the pair the repair had just made —
    # "pictures A and B are the same drawing", a whole generation lost to a
    # fault that was visible before the first repair ran. Keyed on the distinct
    # count it is caught on the way in instead, where it costs one corrective
    # retry.
    if len(set(shapes)) < _MIN_CHOICES:
        if len(choices) > _MIN_CHOICES:
            return (
                f"all {len(choices)} pictures are the same drawing, so every "
                "letter is correct and none can be marked. The pictures must "
                "differ in the thing the question asks about."
            )
        for i, shape in enumerate(shapes):
            twin = shapes.index(shape)
            if twin != i:
                return (
                    f"pictures {chr(ord('A') + twin)} and {chr(ord('A') + i)} "
                    "are the same drawing, so both are correct and neither can "
                    "be marked. The pictures must differ in the thing the "
                    "question asks about."
                )

    # A drawing made of nothing but rectangles is a drawing of nothing. The
    # vocabulary carries a form for a can, a wheel, a hose, a nozzle; `box` is
    # the fallback for a part none of them fits, not the default.
    for i, choice in enumerate(choices):
        forms = {
            p.get("form") for p in (choice.get("parts") or []) if isinstance(p, dict)
        }
        forms = {f for f in forms if f not in _ENVIRONMENT_FORMS}
        if forms and forms <= {"box"}:
            return (
                f"picture {chr(ord('A') + i)} is drawn entirely with `box`, so "
                "it does not look like anything. Choose the form that matches "
                "each real part."
            )

    letters = {chr(ord("A") + i) for i in range(len(choices))}
    keyed = [
        _text(v).upper()
        for q in (questions or [])
        if isinstance(q, dict)
        for v in [(answer_key or {}).get(str(q.get("number")))]
        if _text(v)
    ]
    stray = [k for k in keyed if len(k) == 1 and k.isalpha() and k not in letters]
    if stray:
        return (
            f"a question is keyed {stray[0]!r}, but the pictures printed are "
            f"{', '.join(sorted(letters))}"
        )
    return None


def _picture_shape(choice: dict) -> tuple:
    """What a choice DRAWS, ignoring its letter — two equal shapes are one picture."""
    return tuple(
        sorted(
            (str(p.get("form")), p.get("col"), p.get("row"))
            for p in (choice.get("parts") or [])
            if isinstance(p, dict)
        )
    )


def drop_duplicate_pictures(result: dict) -> list[str]:
    """Delete a picture that repeats another, and re-letter what is left.

    A picture-choice set whose A and B are the same drawing has two correct
    answers and cannot be marked, so `picture_error` refuses it — and refusing
    it discards the script, the questions and the answer key too. Measured over
    three live sweeps, this was the failure in two of them.

    Dropping the twin is safe and needs no model call. The drawings are
    identical, so a student who picked either was seeing the same thing: if the
    answer key named the copy, it is moved to the survivor, which is the same
    picture. `_MIN_CHOICES` is 2, so a three-picture set survives losing one.

    Returns the letters removed, for the caller to log.
    """
    visual = result.get("visual")
    if not is_picture(visual):
        return []
    choices = picture_choices(visual)
    if len(choices) <= _MIN_CHOICES:
        return []
    # Deletion only cures a repeat while something DIFFERENT survives it. Three
    # drawings of the same thing collapse to one, which is no choice at all, so
    # drop nothing and leave the set to `picture_error` — which refuses it for
    # what it is, on the way in, where the retry is corrective.
    #
    # 🔬 Without this the floor guard below stopped the collapse at two and
    # handed the gate a set whose A and B were still the same drawing: a fault
    # this repair had made itself, reported as if the model had drawn it.
    if len({_picture_shape(c) for c in choices}) < _MIN_CHOICES:
        return []

    keep: list[dict] = []
    # Old letter -> the letter that now stands for that drawing.
    moved: dict[str, str] = {}
    seen: dict[tuple, str] = {}
    dropped: list[str] = []
    for i, choice in enumerate(choices):
        old = str(choice.get("letter") or chr(ord("A") + i))
        shape = _picture_shape(choice)
        if shape in seen:
            dropped.append(old)
            moved[old] = seen[shape]
            continue
        new = chr(ord("A") + len(keep))
        seen[shape] = new
        moved[old] = new
        keep.append({**choice, "letter": new})

    if not dropped:
        return []

    visual["choices"] = keep
    answer_key = result.get("answer_key") or {}
    for number, answer in list(answer_key.items()):
        letter = str(answer).strip().upper()
        if letter in moved and letter != moved[letter]:
            answer_key[number] = moved[letter]
    # The question prints the letters it offers, so a stale "A, B or C" would
    # send the student looking for a picture that is no longer there. Matched
    # as a whole enumeration — "A, B or C", "A-C", "A or B" — because matching
    # a pair at a time rewrote "A, B or C" into "A-B or C".
    letters = [c["letter"] for c in keep]
    span = (
        " or ".join(letters)
        if len(letters) < 3
        else ", ".join(letters[:-1]) + f" or {letters[-1]}"
    )
    enumeration = re.compile(r"\bA\b(?:\s*(?:,|–|-|or)\s*[B-Z]\b)+")
    for question in result.get("questions") or []:
        if not isinstance(question, dict):
            continue
        text = str(question.get("question") or "")
        if text:
            question["question"] = enumeration.sub(span, text)
    return dropped


def pictureless_error(questions: list, visual: object) -> str | None:
    """Reject a picture-choice question with no pictures to choose between.

    There is no escape hatch of the kind `dangling_structure_error` gives a
    completion item that inlines its own gap: "Which picture best shows the
    layout of the Formal Gardens?" is not answerable by any student on earth
    without the pictures, however the question is worded.

    🔬 Found live 2026-08-27, the first time Listening was asked for this type:
    it returned TWO picture_choice questions, each offering options A, B and C,
    and `visual` was null. The set passed every validator there was.

    The second rule is a consequence of the schema rather than of the exam: a
    set carries ONE `visual`, so one printed set of pictures, so at most one
    question can be asking about it. Two would both point at the same drawings.
    """
    numbers = [
        str(q.get("number"))
        for q in (questions or [])
        if isinstance(q, dict) and str(q.get("type", "")).strip().lower()
        in {"picture_choice", "picture choice", "picture"}
    ]
    if not numbers:
        return None
    if not is_picture(visual):
        return (
            f"question(s) {', '.join(numbers)} ask which PICTURE is correct, but "
            "`visual` carries no pictures — there is nothing to choose between, "
            "so the question cannot be answered at all. Emit the picture object, "
            "or use a question type that needs no drawing."
        )
    if len(numbers) > 1:
        return (
            f"questions {', '.join(numbers)} are all picture_choice, but a set "
            "prints ONE set of pictures — they would all be asking about the "
            "same drawings. Keep one picture_choice question and make the rest "
            "another type."
        )
    return None
