"""Live browser check for the three dead ends the pilot testers reported.

A tester who goes into the app cannot get out of it. The sidebar logo points
at /dashboard, so nothing in the shell links to `/`, and the feedback box
lives only on the landing page -- so "I can't go to the homepage" and "after
one feedback I can't find it again" are the same missing link reported twice.

Three things are checked, on desktop and on a phone viewport:

  1. the price box is gone from the landing page, nav link included
  2. the app shell offers Home and Feedback, and both arrive somewhere real
  3. a signed-in visitor to `/` is offered the dashboard, not "Login"

  IELTS_BASE=http://127.0.0.1:3100 IELTS_API=http://127.0.0.1:8000 \
    python tools/browser_nav_check.py
"""

import os
import sys
import uuid
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

OUT = Path("tools/browser_shots")
OUT.mkdir(parents=True, exist_ok=True)

BASE = os.environ.get("IELTS_BASE", "http://127.0.0.1:3100").rstrip("/")
API = os.environ.get("IELTS_API", "http://127.0.0.1:8000").rstrip("/")


def shot(page, name: str) -> None:
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
    print(f"  [shot] {name}.png")


def make_account() -> dict:
    """Register a throwaway user and return the persisted-auth blob for it."""
    email = f"navcheck-{uuid.uuid4().hex[:8]}@gmail.com"
    httpx.post(
        f"{API}/auth/register",
        json={"email": email, "password": "password123", "full_name": "Nav Tester"},
        timeout=30,
    ).raise_for_status()
    tokens = httpx.post(
        f"{API}/auth/login",
        data={"username": email, "password": "password123"},
        timeout=30,
    )
    tokens.raise_for_status()
    tokens = tokens.json()
    me = httpx.get(
        f"{API}/auth/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        timeout=30,
    )
    me.raise_for_status()
    return {
        "email": email,
        "blob": {
            "state": {
                "accessToken": tokens["access_token"],
                "refreshToken": tokens["refresh_token"],
                "user": me.json(),
            },
            "version": 0,
        },
    }


def seed_auth(ctx, blob: dict) -> None:
    """Plant the persisted session before any script runs on the page."""
    import json

    ctx.add_init_script(
        "window.localStorage.setItem('ai-ielts-auth', "
        + json.dumps(json.dumps(blob))
        + ");"
    )


def main() -> int:
    failures: list[str] = []
    account = make_account()
    print(f"[account] {account['email']}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # --- 1. the landing page, signed out -------------------------------
        print("[1] landing page has no price box")
        ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(BASE, wait_until="domcontentloaded")
        page.wait_for_timeout(1800)

        body = page.locator("body").inner_text()
        if "#pricing" in page.content():
            failures.append("landing page still links to #pricing")
        if page.locator("#pricing").count():
            failures.append("landing page still renders a #pricing section")
        for word in ("/month", "per month", "Most Popular"):
            if word in body:
                failures.append(f"price-box text still on the landing page: {word!r}")
        if page.get_by_role("link", name="Pricing").count():
            failures.append("navbar still offers a Pricing link")
        shot(page, "40_landing_no_pricing")

        # The sections that must survive the removal.
        for section in ("#home", "#features", "#modules", "#feedback", "#about"):
            if not page.locator(section).count():
                failures.append(f"{section} disappeared with the price box")
        ctx.close()

        # --- 2. the app shell, signed in -----------------------------------
        print("[2] app shell offers Home and Feedback")
        ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
        seed_auth(ctx, account["blob"])
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{BASE}/dashboard", wait_until="domcontentloaded")
        page.wait_for_timeout(2500)

        sidebar = page.locator("aside").first
        for label in ("Home", "Feedback"):
            if not sidebar.get_by_role("link", name=label).count():
                failures.append(f"desktop sidebar has no {label} link")
        shot(page, "41_app_sidebar")

        # Clicking Feedback must land on the form, not merely on `/`.
        page.get_by_role("link", name="Feedback").first.click()
        page.wait_for_timeout(2500)
        if "#feedback" not in page.url:
            failures.append(f"Feedback link did not reach the box; url={page.url}")
        if not page.locator("#feedback-message").count():
            failures.append("Feedback link arrived somewhere without the form")
        shot(page, "42_feedback_from_app")

        # --- 3. a signed-in visitor to `/` is offered the way back ----------
        print("[3] signed-in landing navbar points back into the app")
        # Scoped to the header on purpose: the hero and footer keep their
        # "Start Free" CTAs for everyone -- that is marketing copy, not
        # navigation. It is the nav chrome that must not send a signed-in
        # tester back to the register form.
        header = page.locator("header").first
        if not header.get_by_role("link", name="Go to Dashboard").count():
            failures.append("signed-in navbar does not offer the dashboard")
        if header.get_by_role("link", name="Start Free").count():
            failures.append("signed-in navbar still offers Start Free")
        if header.get_by_role("link", name="Login").count():
            failures.append("signed-in navbar still offers Login")

        page.get_by_role("link", name="Go to Dashboard").first.click()
        page.wait_for_timeout(2500)
        if "/dashboard" not in page.url:
            failures.append(f"dashboard button went nowhere; url={page.url}")

        # Home, from the app, reaches the landing page.
        page.get_by_role("link", name="Home").first.click()
        page.wait_for_timeout(2000)
        if page.url.rstrip("/") != BASE:
            failures.append(f"Home link did not reach the landing page; url={page.url}")
        ctx.close()

        # --- 4. the same two, on a phone ------------------------------------
        print("[4] mobile drawer offers both")
        ctx = browser.new_context(viewport={"width": 390, "height": 844})
        seed_auth(ctx, account["blob"])
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{BASE}/dashboard", wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        page.get_by_role("button", name="Open menu").click()
        page.wait_for_timeout(900)
        drawer = page.locator("#mobile-drawer")
        for label in ("Home", "Feedback"):
            if not drawer.get_by_role("link", name=label).count():
                failures.append(f"mobile drawer has no {label} link")
        shot(page, "43_mobile_drawer")
        ctx.close()

        browser.close()

    real = [e for e in errors if "hydrat" not in e.lower() or True]
    if real:
        failures.append(f"{len(real)} console/page error(s): {real[:3]}")

    print()
    if failures:
        print(f"FAIL ({len(failures)})")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("PASS - no dead ends left")
    return 0


if __name__ == "__main__":
    sys.exit(main())
