"""Screenshot the figure inside any saved practice-set payload.

The render checks prove the RENDERER against hand-built fixtures. This proves
the whole chain: a payload the model actually produced, drawn the way a student
would see it. It exists because the only honest answer to "does the figure look
like the exam's" is a picture, and every live harness in `tools/` saves its
sets as JSON and then has no way to look at them.

Point it at a directory of saved sets — `tools/_diag_cross_live/`,
`tools/_diag_redraw_live/` — and it writes one PNG per figure.

Run with the backend on :8000 and a production frontend build on :3100.

Usage:
  PYTHONIOENCODING=utf-8 python tools/render_figure_payloads.py <dir> [--tag t]
  PYTHONIOENCODING=utf-8 python tools/render_figure_payloads.py a.json b.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))

from browser_diagram_render_check import (  # noqa: E402
    BASE,
    OUT,
    auth_state,
    build_fixture,
    serve,
)

# Every figure family the practice page can draw, so one tool covers a redrawn
# diagram, a flow chart and a notes block without being told which it is.
FIGURE = "figure[aria-label]"


def payloads(paths: list[Path]) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for path in paths:
        if path.is_dir():
            out.extend(payloads(sorted(path.glob("*.json"))))
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # a harness mid-write, or a log beside them
            print(f"  !! {path.name}: {exc}")
            continue
        visual = data.get("visual")
        if isinstance(visual, dict) and visual.get("kind"):
            out.append((path.stem, visual))
        else:
            print(f"  -- {path.name}: no figure")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--tag", default="payload")
    ap.add_argument("--theme", default="light", choices=("light", "dark"))
    args = ap.parse_args()

    found = payloads([Path(p) for p in args.paths])
    if not found:
        print("no figures found")
        return 1
    print(f"{len(found)} figure(s) to draw")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for name, visual in found:
            # One figure per page load. The practice page draws the four parts
            # of a full test at once, and putting several figures on one page
            # makes the screenshots impossible to attribute back to a payload.
            fixture = build_fixture((visual,))
            ctx = browser.new_context(
                viewport={"width": 1440, "height": 1100},
                color_scheme=args.theme,
            )
            page = ctx.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.route("**/listening/full-test", lambda route: serve(route, fixture))
            page.goto(f"{BASE}/login", wait_until="domcontentloaded")
            page.evaluate(
                "([k, v]) => window.localStorage.setItem(k, v)",
                ["ai-ielts-auth", json.dumps(auth_state())],
            )
            page.goto(f"{BASE}/listening/test", wait_until="domcontentloaded")
            page.get_by_role("button", name="Generate full test").click()
            try:
                page.wait_for_selector(FIGURE, timeout=60000)
            except Exception:
                print(f"  !! {name}: no figure rendered")
                ctx.close()
                continue
            page.wait_for_timeout(500)
            fig = page.locator(FIGURE).first
            fig.scroll_into_view_if_needed()
            shot = OUT / f"{args.tag}_{name}_{args.theme}.png"
            fig.screenshot(path=str(shot))
            label = fig.get_attribute("aria-label") or ""
            print(f"  [shot] {shot.name}  {label[:60]}")
            if errors:
                print(f"    !! page errors: {errors[:2]}")
            ctx.close()
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
