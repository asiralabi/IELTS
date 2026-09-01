"""Which exam figures can this engine actually produce, per module?

A figure is only real if THREE things line up: a prompt that asks for it, a
validator that knows what a good one looks like, and a renderer that draws it.
Miss any one and the feature is a rumour -- the reading `plan` renderer existed
for months while no reading prompt ever allowed a plan, so no student ever saw
one.

This reads the prompts, the agents and the frontend and reports the three
columns side by side, so a gap is visible without generating anything.

Usage: PYTHONIOENCODING=utf-8 python tools/figure_coverage.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT.parent / "frontend" / "src" / "components" / "practice"

PROMPTS = (ROOT / "app" / "llm" / "prompts.py").read_text(encoding="utf-8")
AGENTS = "\n".join(
    p.read_text(encoding="utf-8") for p in (ROOT / "app" / "agents").glob("*.py")
)
RENDER = "\n".join(
    p.read_text(encoding="utf-8")
    for p in FRONTEND.glob("*.tsx")
) if FRONTEND.exists() else ""

# The prompts are one file with a section per module. Split on the two system
# prompts so "does READING allow a plan" is answerable separately from
# "does LISTENING allow one".
def section(name: str) -> str:
    start = PROMPTS.index(name)
    tail = PROMPTS[start:]
    nxt = re.search(r"\n[A-Z_]+_SYSTEM = ", tail[10:])
    return tail[: nxt.start() + 10] if nxt else tail


READING = section("READING_TRAINER_SYSTEM = ")
LISTENING = section("LISTENING_TRAINER_SYSTEM = ")

# The target list, as the user specified it on 2026-08-27. `modules` is which
# papers the REAL exam prints this figure in, so an "n/a" is a deliberate
# absence rather than a gap: IELTS Reading never prints a registration form,
# and Listening never prints a pie chart.
#
# (label, question type that asks for it, `kind` marker in the payload spec,
#  renderer marker, modules it is wanted in)
FIGURES = [
    ("Map / Plan",            "map_labelling",            '"plan"',    "PlanBlock",      "rl"),
    # Split from the row above on 2026-08-28. `MapBlock` — features at
    # coordinates with roads between them — had existed for months and NO
    # prompt ever emitted `kind: "map"`, so every outdoor place was drawn as a
    # grid of rooms sharing walls. A live reading set laid an excavated Roman
    # town out as a floor plan. The row above could not see it, because the
    # plan half of "Map / Plan" was reachable and reported "yes".
    ("Open map (outdoor)",    "map_labelling",            '"map"',     "MapBlock",       "rl"),
    ("Diagram",               "diagram_label_completion", '"diagram"', "DiagramBlock",   "rl"),
    ("Cross-section",         "diagram_label_completion", "layers",    "waveTop",        "r"),
    ("Scientific illustration", "diagram_label_completion", "cycle",   "function cycle", "r"),
    ("Historical illustration", "diagram_label_completion", "apparatus", "function apparatus", "r"),
    ("Flow chart / Process",  "flow_chart_completion",    '"flow"',    "FlowBlock",      "rl"),
    ("Table",                 "table_completion",         '"table"',   "ChartTable",     "rl"),
    ("Form",                  "form_completion",          '"table"',   "ChartFormTable", "l"),
    ("Notes",                 "note_completion",          '"notes"',   "NotesBlock",     "rl"),
    ("Summary",               "summary_completion",       '"notes"',   "NotesBlock",     "rl"),
    # The exam prints one lettered box above a matching block. This UI shows
    # one question at a time and renders that block's options as SELECTABLE
    # lettered buttons under each question (`optionEntries` in
    # question-list.tsx), which is the same information plus the answer input.
    # A printed box on top would put the options on screen twice, so it is
    # deliberately not built.
    ("Matching (lettered options)", "matching",             '"options"', "optionEntries",  "l"),
    ("Pictures",              "picture_choice",           '"picture"', "PictureBlock",   "l"),
    ("Graph / Chart",         "chart_completion",         '"bar"',     "BarChart",       "rl"),
    ("Pie chart",             "chart_completion",         '"pie"',     "PieChart",       "r"),
]


def asks(module: str, qtype: str, kind: str) -> bool:
    """Does this module's prompt offer the type AND describe the payload?"""
    return qtype in module and kind in module


def main() -> None:
    print(f"{'figure':<24}{'READING':<22}{'LISTENING':<22}{'renders?'}")
    print("-" * 76)
    gaps = []
    for label, qtype, kind, marker, modules in FIGURES:
        drawn = marker in RENDER

        def cell(module: str, want: bool) -> str:
            if not want:
                return "n/a"
            return "yes" if asks(module, qtype, kind) else "-- NO --"

        print(f"{label:<24}{cell(READING, 'r' in modules):<22}"
              f"{cell(LISTENING, 'l' in modules):<22}"
              f"{'yes' if drawn else '-- NO --'}")
        for name, module, want in (("reading", READING, "r" in modules),
                                   ("listening", LISTENING, "l" in modules)):
            if want and not asks(module, qtype, kind):
                gaps.append(f"{name}: {label}")
        if not drawn:
            gaps.append(f"renderer: {label}")

    print(f"\n{len(gaps)} gaps")
    for g in gaps:
        print(f"  - {g}")


if __name__ == "__main__":
    main()
