"""Live browser check for the landing-page feedback box.

Two passes, because the box behaves differently for the two people who will
use it during the pilot:

  anonymous  -- a tester following a shared link who never registered. Types
                their own address; the row must carry it and no user_id.
  signed in  -- the field is filled from the account and locked, and the row
                must be attributed to that user even if the form said otherwise.

Run against local dev servers, or against a deployment:
  IELTS_BASE=http://localhost:8080 IELTS_API=http://localhost:8080/api \
    FEEDBACK_ADMIN_TOKEN=... python tools/browser_feedback_check.py
"""

import json
import os
import sys
import uuid
from pathlib import Path

import httpx
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

OUT = Path("tools/browser_shots")
OUT.mkdir(parents=True, exist_ok=True)

BASE = os.environ.get("IELTS_BASE", "http://127.0.0.1:3000").rstrip("/")
API = os.environ.get("IELTS_API", "http://127.0.0.1:8000").rstrip("/")
ADMIN_TOKEN = os.environ.get("FEEDBACK_ADMIN_TOKEN", "")

ANON_EMAIL = "anon.tester@gmail.com"
ANON_NOTE = "Anonymous pass: the listening audio stopped halfway through Part 2."
USER_NOTE = "Signed-in pass: the writing timer keeps running after I submit."


def shot(page, name: str) -> None:
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
    print(f"  [shot] {name}.png")


def make_account() -> dict:
    """Register a throwaway user and return the persisted-auth blob for it."""
    email = f"pilot-{uuid.uuid4().hex[:8]}@gmail.com"
    httpx.post(
        f"{API}/auth/register",
        json={"email": email, "password": "password123", "full_name": "Pilot Tester"},
        timeout=20,
    ).raise_for_status()
    tokens = httpx.post(
        f"{API}/auth/login",
        data={"username": email, "password": "password123"},
        timeout=20,
    )
    tokens.raise_for_status()
    tokens = tokens.json()
    me = httpx.get(
        f"{API}/auth/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        timeout=20,
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


def await_thank_you(page, label: str, failures: list[str]) -> None:
    """Wait for the acknowledgement, not for a fixed number of seconds.

    A cold serverless function takes seconds to answer its first request, and a
    sleep short enough to keep the check quick is short enough to fail against
    a deployment that has been idle. Waiting on the outcome is both faster when
    warm and honest when cold.
    """
    try:
        page.get_by_text("Got it", exact=False).wait_for(state="visible", timeout=90_000)
    except PlaywrightTimeout:
        body = " | ".join(page.locator("#feedback").inner_text().split("\n"))
        failures.append(f"no thank-you after {label} send; section said: {body[:220]!r}")


def fill_and_send(page, *, email: str | None, message: str, stars: int | None) -> None:
    page.get_by_role("link", name="Feedback").first.click()
    page.wait_for_timeout(900)
    if email is not None:
        page.fill("#feedback-email", email)
    page.fill("#feedback-message", message)
    if stars is not None:
        page.get_by_role("radio", name=f"{stars} out of 5").click()
    page.wait_for_timeout(300)


def main() -> int:
    failures: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on(
            "console",
            lambda m: errors.append(f"[console.{m.type}] {m.text}")
            if m.type == "error"
            else None,
        )

        # --- pass 1: a visitor who is not signed in ------------------------
        print("[1] anonymous visitor")
        page.goto(BASE, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)

        fill_and_send(page, email=ANON_EMAIL, message=ANON_NOTE, stars=4)
        shot(page, "20_feedback_anonymous_filled")

        readonly = page.get_attribute("#feedback-email", "readonly")
        if readonly is not None:
            failures.append("anonymous email field is read-only; it must be typable")

        page.get_by_role("button", name="Send Feedback").click()
        await_thank_you(page, "anonymous", failures)
        shot(page, "21_feedback_anonymous_sent")

        # --- pass 2: a signed-in tester ------------------------------------
        print("[2] signed-in tester")
        account = make_account()
        page.evaluate(
            "([k, v]) => window.localStorage.setItem(k, v)",
            ["ai-ielts-auth", json.dumps(account["blob"])],
        )
        page.goto(BASE, wait_until="domcontentloaded")
        page.wait_for_timeout(1800)

        # No email typed: the box should already hold the account's address.
        fill_and_send(page, email=None, message=USER_NOTE, stars=5)
        prefilled = page.input_value("#feedback-email")
        if prefilled != account["email"]:
            failures.append(
                f"email not prefilled from session: got {prefilled!r}, "
                f"want {account['email']!r}"
            )
        if page.get_attribute("#feedback-email", "readonly") is None:
            failures.append("signed-in email field should be read-only")
        shot(page, "22_feedback_signed_in_prefilled")

        page.get_by_role("button", name="Send Feedback").click()
        await_thank_you(page, "signed-in", failures)
        shot(page, "23_feedback_signed_in_sent")

        if errors:
            failures.append(f"browser errors: {errors[:4]}")

        browser.close()

    # --- what actually landed in the table ---------------------------------
    print("[3] reading the inbox back")
    if not ADMIN_TOKEN:
        print("    ! FEEDBACK_ADMIN_TOKEN unset — skipping the read-back check")
    else:
        rows = httpx.get(
            f"{API}/feedback", headers={"X-Admin-Token": ADMIN_TOKEN}, timeout=20
        )
        rows.raise_for_status()
        rows = rows.json()
        by_message = {r["message"]: r for r in rows}

        anon = by_message.get(ANON_NOTE)
        if anon is None:
            failures.append("anonymous note never reached the inbox")
        else:
            print(f"    anon  -> {anon['email']} rating={anon['rating']} user_id={anon['user_id']}")
            if anon["email"] != ANON_EMAIL:
                failures.append(f"anonymous email stored as {anon['email']!r}")
            if anon["user_id"] is not None:
                failures.append("anonymous note was attributed to a user")
            if anon["rating"] != 4:
                failures.append(f"anonymous rating stored as {anon['rating']}")
            if anon["page"] != "/":
                failures.append(f"anonymous page stored as {anon['page']!r}")

        signed = by_message.get(USER_NOTE)
        if signed is None:
            failures.append("signed-in note never reached the inbox")
        else:
            print(
                f"    user  -> {signed['email']} rating={signed['rating']} "
                f"user_id={signed['user_id']}"
            )
            if signed["user_id"] is None:
                failures.append("signed-in note was not attributed to the account")
            if signed["rating"] != 5:
                failures.append(f"signed-in rating stored as {signed['rating']}")

    if failures:
        print("\nFAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nOK: both passes stored, attributed and acknowledged correctly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
