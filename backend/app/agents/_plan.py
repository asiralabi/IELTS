"""The grid floor plan, shared by every module that draws one.

Listening labels rooms on it, Reading numbers parts of a diagram with it, and
Writing Task 1 shows two of them side by side for a "before and after" map
task. The grid states only which room owns which cell; walls, doors and room
shapes are derived by the renderer, which is what keeps a generated plan from
coming out overlapping or off-page.
"""

from collections import Counter


def _num(value: object, default: float) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return default


def _clampi(value: float, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(round(value))))


_PLAN_MAX_COLS = 12
_PLAN_MAX_ROWS = 10
_PLAN_SIDES = ("top", "bottom", "left", "right")


# The renderer draws exactly one connective value as a walkway, matching the
# literal "corridor". An outdoor Writing map naturally calls the same thing a
# path or a road, so the wording the model reaches for is folded to that one
# token here and the frontend contract stays as it was. Every one of these is
# connective tissue; none is a place a question would ask a student to find.
_WALKWAY = {"corridor", "hallway", "hall way", "path", "pathway", "footpath",
            "walkway", "road", "street", "lane", "driveway"}


def _plan_cell(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) == 1 and text.isalpha():
        return text.upper()
    if text.lower() in _WALKWAY:
        return "corridor"
    return text


def named_areas(visual: object) -> list[str]:
    """The places a plan actually prints, walkways and bare letters excluded.

    Reads each cell through `_plan_cell`, so this gives the same answer on a
    raw plan as on a cleaned one. Comparing raw grids without it counted a
    "path" cell as a place, which let two unrelated maps look like the same
    site because both happened to have paths.
    """
    if not isinstance(visual, dict):
        return []
    seen: list[str] = []
    for row in visual.get("grid") or []:
        if not isinstance(row, list):
            continue
        for cell in row:
            text = _plan_cell(cell)
            if not text or text == "corridor" or (len(text) == 1 and text.isalpha()):
                continue
            if text not in seen:
                seen.append(text)
    return seen


def comparison_error(plans: object) -> str | None:
    """Why this pair of plans is not a Writing Task 1 map, or None if it is.

    Task 1 gives the student one place at two times and asks what changed, so
    the pair has to be legible AS a pair: same footprint, some fixed points to
    orient by, and some actual change to write about. A pair with nothing in
    common is two unrelated maps; a pair with nothing different is a task with
    no content. Neither is a thing 150 words can be written about.
    """
    if not isinstance(plans, list) or len(plans) != 2:
        return "a Task 1 map must be exactly two plans, the same place at two times"

    shapes = []
    for plan in plans:
        if not isinstance(plan, dict) or plan.get("kind") != "plan":
            return "both figures in a Task 1 map must be plan objects"
        grid = plan.get("grid")
        if not isinstance(grid, list) or not grid or not isinstance(grid[0], list):
            return "a Task 1 map plan needs a non-empty grid"
        shapes.append((len(grid), len(grid[0])))
        # A lettered room is the Listening convention and means the opposite
        # thing there. Here it leaves the student describing "area B".
        for row in grid:
            for cell in row if isinstance(row, list) else []:
                text = str(cell or "").strip()
                if len(text) == 1 and text.isalpha():
                    return (
                        f"the plan {plan.get('title')!r} labels an area {text!r} "
                        "instead of naming it; a Task 1 map is described, not "
                        "answered, so every area must carry its real name"
                    )

    if shapes[0] != shapes[1]:
        return (
            f"the two plans are different sizes ({shapes[0]} and {shapes[1]}); "
            "the same place at two times must keep the same footprint"
        )

    before, after = (set(named_areas(p)) for p in plans)
    if not before & after:
        return (
            "the two plans share no area at all, so nothing fixes them as the "
            "same place — keep at least two areas unchanged in both"
        )
    if not (before ^ after):
        return (
            "the two plans show exactly the same areas, so there is no change "
            "to describe — a Task 1 map must differ in 3-5 real ways"
        )
    return None


def normalize_plan(visual: object) -> dict | None:
    """Clean a generated floor plan so it always renders legibly.

    The grid says only which room owns which cell, so walls, doors and room
    shapes are derived downstream and cannot come out overlapping or off-page.
    What the model still gets wrong is bookkeeping: ragged rows, casing, and
    above all writing one room in two unconnected places, which leaves the
    question with two rooms to point at instead of one.

    Returns the cleaned plan, or None if there is nothing drawable left. Takes
    the visual rather than the set that holds it, because Writing Task 1 draws
    the same figure with no questions wrapped around it.
    """
    if not isinstance(visual, dict) or visual.get("kind") != "plan":
        return None

    rows = [row for row in (visual.get("grid") or []) if isinstance(row, list)]
    if not rows:
        return None

    width = min(_PLAN_MAX_COLS, max((len(row) for row in rows), default=0))
    grid = [
        [_plan_cell(row[c] if c < len(row) else "") for c in range(width)]
        for row in rows[:_PLAN_MAX_ROWS]
    ]
    if not width or not any(cell for row in grid for cell in row):
        return None

    _split_repeated_rooms(grid)
    visual["grid"] = grid
    entrance = _plan_entrance(visual.get("entrance"), grid)
    if entrance:
        visual["entrance"] = entrance
    else:
        visual.pop("entrance", None)
    return visual


def _split_repeated_rooms(grid: list[list[str]]) -> None:
    """Leave one region per room name.

    A letter written in two unconnected places gives the question two rooms to
    point at, so the smaller copy is folded into whatever surrounds it.
    Corridors are exempt — several separate walkways are a legitimate plan.
    """
    rows, cols = len(grid), len(grid[0])
    seen = [[False] * cols for _ in range(rows)]
    groups: dict[str, list[list[tuple[int, int]]]] = {}
    for r in range(rows):
        for c in range(cols):
            value = grid[r][c]
            if seen[r][c] or not value or value == "corridor":
                continue
            cells: list[tuple[int, int]] = []
            stack = [(r, c)]
            seen[r][c] = True
            while stack:
                cr, cc = stack.pop()
                cells.append((cr, cc))
                for nr, nc in ((cr - 1, cc), (cr + 1, cc), (cr, cc - 1), (cr, cc + 1)):
                    if not (0 <= nr < rows and 0 <= nc < cols):
                        continue
                    if seen[nr][nc] or grid[nr][nc] != value:
                        continue
                    seen[nr][nc] = True
                    stack.append((nr, nc))
            groups.setdefault(value, []).append(cells)

    for value, regions in groups.items():
        if len(regions) < 2:
            continue
        regions.sort(key=len, reverse=True)
        for cells in regions[1:]:
            replacement = _surrounding_room(grid, cells, value)
            for r, c in cells:
                grid[r][c] = replacement


def _surrounding_room(
    grid: list[list[str]], cells: list[tuple[int, int]], exclude: str
) -> str:
    """The room the given cells are most enclosed by, so absorbing them keeps
    the plan solid rather than punching a hole in it."""
    rows, cols = len(grid), len(grid[0])
    inside = set(cells)
    counts: Counter[str] = Counter()
    for r, c in cells:
        for nr, nc in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
            if not (0 <= nr < rows and 0 <= nc < cols) or (nr, nc) in inside:
                continue
            neighbour = grid[nr][nc]
            if neighbour and neighbour != exclude:
                counts[neighbour] += 1
    if not counts:
        return "corridor"
    return max(sorted(counts), key=lambda name: counts[name])


def _plan_edge(grid: list[list[str]], side: str, index: int) -> str:
    if side == "top":
        return grid[0][index]
    if side == "bottom":
        return grid[-1][index]
    if side == "left":
        return grid[index][0]
    return grid[index][-1]


def _plan_entrance(entrance: object, grid: list[list[str]]) -> dict | None:
    """Put the way in against the walkway.

    An entrance opening straight into a room reads as a mistake on a floor
    plan — the corridor is what the recording walks the student down — so the
    stated position is nudged to the nearest corridor before anything else.
    """
    rows, cols = len(grid), len(grid[0])
    data = entrance if isinstance(entrance, dict) else {}
    side = str(data.get("side") or "").strip().lower()
    if side not in _PLAN_SIDES:
        side = "bottom"

    def along(name: str) -> int:
        return cols if name in ("top", "bottom") else rows

    want = _clampi(_num(data.get("index"), along(side) / 2), 0, along(side) - 1)

    def nearest(name: str, wanted: str | None) -> int | None:
        order = sorted(range(along(name)), key=lambda i: (abs(i - want), i))
        for i in order:
            cell = _plan_edge(grid, name, i)
            if cell and (wanted is None or cell == wanted):
                return i
        return None

    for name in (side, *(s for s in _PLAN_SIDES if s != side)):
        index = nearest(name, "corridor")
        if index is not None:
            side = name
            break
    else:
        index = nearest(side, None)
        if index is None:
            return None

    label = str(data.get("label") or "").strip() or "Main entrance"
    return {"side": side, "index": index, "label": label}


