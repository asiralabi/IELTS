"""Live browser verification of the three full-test routes added alongside
the existing Listening one: /writing/test, /speaking/test and /reading/test.

Writing and Speaking generate against the hosted provider and come back in
seconds. Reading is three passages from the local checkpoint and can take the
better part of an hour cold, so it runs last and every section reports
independently — a slow Reading must not cost us the Writing result.

The Reading section is the only browser-level check of `_numbering.renumber`:
it asserts the answer inputs run 1..N unbroken ACROSS passages, which is what
a per-passage numbering bug would break.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
from playwright.sync_api import Page, sync_playwright

OUT = Path("tools/browser_shots")
OUT.mkdir(parents=True, exist_ok=True)

BASE = "http://127.0.0.1:3100"
API = "http://127.0.0.1:8000"
EMAIL = "demo@example.com"
PASSWORD = "demo1234"

FAST_GEN_MS = 180_000  # hosted provider
SLOW_GEN_MS = 3_600_000  # three passages on local CPU
MARK_MS = 600_000

ESSAY = (
    "The chart shows a clear upward movement across the whole period, and the "
    "difference between the two groups widens steadily rather than all at once. "
    "In my view this reflects a change in priorities rather than a change in "
    "resources, because the same pattern appears in countries with very "
    "different levels of income. Supporters of the opposite position argue that "
    "cost is the decisive factor, but that explanation does not account for the "
    "countries which spent less and still recorded the sharper increase. A more "
    "convincing reading is that public attitudes shifted first and spending "
    "followed. Governments respond to what voters already believe, so the "
    "spending figures are better understood as a consequence than as a cause. "
) * 4

TRANSCRIPT = (
    "I live in a fairly quiet neighbourhood about twenty minutes from the centre "
    "of the city, and what I like most about it is that everything I need is "
    "within walking distance. There is a small market at the end of my street "
    "where I buy vegetables, and a park just behind it where I usually run in "
    "the early morning before work. I have lived there for about six years now, "
    "and although the rent has gone up I would find it hard to move somewhere "
    "less green. "
) * 2


def shot(page: Page, name: str) -> None:
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
    print(f"    [shot] {name}.png", flush=True)


def wait_for_hydrate(page: Page, min_chars: int = 120, tries: int = 40) -> str:
    for _ in range(tries):
        text = page.locator("body").inner_text().strip()
        if len(text) >= min_chars:
            return text
        page.wait_for_timeout(500)
    return page.locator("body").inner_text().strip()


def get_auth_state() -> dict:
    r = httpx.post(
        f"{API}/auth/login",
        data={"username": EMAIL, "password": PASSWORD},
        timeout=15,
    )
    r.raise_for_status()
    tokens = r.json()
    me = httpx.get(
        f"{API}/auth/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        timeout=15,
    )
    me.raise_for_status()
    return {
        "state": {
            "accessToken": tokens["access_token"],
            "refreshToken": tokens["refresh_token"],
            "user": me.json(),
        },
        "version": 0,
    }


def generate(page: Page, route: str, timeout_ms: int) -> None:
    page.goto(f"{BASE}{route}", wait_until="domcontentloaded")
    wait_for_hydrate(page)
    page.get_by_role("button", name="Generate full test").click()
    page.get_by_role("button", name="Submit test", exact=False).wait_for(
        state="visible", timeout=timeout_ms
    )
    page.wait_for_timeout(1200)


def band_text(page: Page) -> str:
    """The banded-result screen, once marking has replaced the answer sheet."""
    page.get_by_role("button", name="Start over", exact=False).wait_for(
        state="visible", timeout=MARK_MS
    )
    page.wait_for_timeout(800)
    return page.locator("body").inner_text()


def check_writing(page: Page, failures: list[str]) -> None:
    print("\n[writing] /writing/test ...", flush=True)
    generate(page, "/writing/test", FAST_GEN_MS)
    shot(page, "nt_writing_10_answering")

    body = page.locator("body").inner_text()
    for expected in ("Task 1", "Task 2"):
        if expected not in body:
            failures.append(f"writing: {expected!r} missing from the answer sheet")

    for label in ("Task 1", "Task 2"):
        page.get_by_role("button", name=label, exact=False).first.click()
        page.wait_for_timeout(300)
        page.locator("textarea").first.fill(ESSAY)
        page.wait_for_timeout(300)

    page.get_by_role("button", name="Submit test", exact=False).click()
    text = band_text(page)
    shot(page, "nt_writing_20_result")
    if "Band" not in text:
        failures.append("writing: no band on the result screen")
    else:
        print("    banded OK", flush=True)


def check_speaking(page: Page, failures: list[str]) -> None:
    print("\n[speaking] /speaking/test ...", flush=True)
    generate(page, "/speaking/test", FAST_GEN_MS)
    shot(page, "nt_speaking_10_answering")

    body = page.locator("body").inner_text()
    for expected in ("Part 1", "Part 2", "Part 3"):
        if expected not in body:
            failures.append(f"speaking: {expected!r} missing from the interview")

    for label in ("Part 1", "Part 2", "Part 3"):
        page.get_by_role("button", name=label, exact=False).first.click()
        page.wait_for_timeout(300)
        page.locator("textarea").first.fill(TRANSCRIPT)
        page.wait_for_timeout(300)

    page.get_by_role("button", name="Submit test", exact=False).click()
    text = band_text(page)
    shot(page, "nt_speaking_20_result")
    if "Band" not in text:
        failures.append("speaking: no band on the result screen")
    else:
        print("    banded OK", flush=True)


def check_reading(page: Page, failures: list[str]) -> None:
    print("\n[reading] /reading/test (slow — 3 local passages) ...", flush=True)
    generate(page, "/reading/test", SLOW_GEN_MS)
    shot(page, "nt_reading_10_answering")

    inputs = page.locator("input[aria-label^='Answer to question']")
    count = inputs.count()
    print(f"    answer inputs: {count}", flush=True)
    if count == 0:
        failures.append("reading: the answer sheet rendered no inputs")
        return

    numbers = sorted(
        int(inputs.nth(i).get_attribute("aria-label").rsplit(" ", 1)[1])
        for i in range(count)
    )
    if numbers != list(range(1, count + 1)):
        failures.append(
            f"reading: questions are not numbered 1..{count} across passages "
            f"— got {numbers[:12]}..."
        )
    else:
        print(f"    numbering runs 1..{count} unbroken across passages", flush=True)

    for i in range(count):
        inputs.nth(i).fill("test")

    page.get_by_role("button", name="Submit test", exact=False).click()
    text = band_text(page)
    shot(page, "nt_reading_20_result")
    if "Band" not in text:
        failures.append("reading: no band on the result screen")
    else:
        print("    banded OK", flush=True)


def main() -> int:
    only = sys.argv[1:] or ["writing", "speaking", "reading"]
    checks = {
        "writing": check_writing,
        "speaking": check_speaking,
        "reading": check_reading,
    }

    failures: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        logs: list[str] = []
        page.on("console", lambda m: logs.append(f"[{m.type}] {m.text}"))
        page.on("pageerror", lambda e: logs.append(f"[pageerror] {e}"))

        print("[auth] seeding demo session ...", flush=True)
        page.goto(f"{BASE}/login", wait_until="domcontentloaded")
        page.evaluate(
            "([k, v]) => window.localStorage.setItem(k, v)",
            ["ai-ielts-auth", json.dumps(get_auth_state())],
        )

        for name in only:
            try:
                checks[name](page, failures)
            except Exception as exc:
                failures.append(f"{name}: raised {type(exc).__name__}: {exc}")
                shot(page, f"nt_{name}_99_error")

        errors = [line for line in logs if "pageerror" in line or "[error]" in line]
        print(f"\n[console] {len(errors)} error(s)", flush=True)
        for line in errors[:10]:
            print(f"    {line}", flush=True)
        browser.close()

    print("\n" + "=" * 60, flush=True)
    if failures:
        for f in failures:
            print(f"  [FAIL] {f}", flush=True)
        return 1
    print("  ALL CHECKS PASSED", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
