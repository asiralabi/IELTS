"""Live browser check: login demo user, visit pages, verify rendering."""

import json
import re
import sys
import time
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

OUT = Path("tools/browser_shots")
OUT.mkdir(parents=True, exist_ok=True)

BASE = "http://127.0.0.1:3000"
API = "http://127.0.0.1:8000"
EMAIL = "demo@example.com"
PASSWORD = "demo1234"


def shot(page, name: str) -> None:
    path = OUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    print(f"  [shot] {path.name}")


def dump(page, name: str) -> None:
    Path(OUT / f"{name}.html").write_text(page.content(), encoding="utf-8")


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


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        logs: list[str] = []
        page.on("console", lambda m: logs.append(f"[{m.type}] {m.text}"))
        page.on("pageerror", lambda e: logs.append(f"[pageerror] {e}"))

        print("[1] fetching auth tokens from backend ...")
        auth_blob = get_auth_state()
        print(f"    got access_token starting {auth_blob['state']['accessToken'][:12]}...")

        # Land on origin to establish localStorage scope
        page.goto(f"{BASE}/login", wait_until="domcontentloaded")
        page.evaluate(
            "([k, v]) => window.localStorage.setItem(k, v)",
            ["ai-ielts-auth", json.dumps(auth_blob)],
        )
        stored = page.evaluate("() => window.localStorage.getItem('ai-ielts-auth')")
        print(f"    localStorage confirmed: {stored[:40]}...")

        for slug, name in [
            ("dashboard", "10_dashboard"),
            ("writing", "11_writing"),
            ("speaking", "12_speaking"),
            ("study-plan", "13_study_plan_empty"),
        ]:
            print(f"[2] visiting /{slug} ...")
            page.goto(f"{BASE}/{slug}", wait_until="domcontentloaded")
            # Wait for RSC hydration by polling for real body text
            for _ in range(30):
                text = page.locator("body").inner_text().strip()
                if text:
                    break
                page.wait_for_timeout(500)
            page.wait_for_timeout(1500)
            shot(page, name)
            dump(page, name)
            text = page.locator("body").inner_text()[:200].replace("\n", " | ")
            html_len = len(page.content())
            print(f"    url={page.url}  html_len={html_len}  body_head='{text}'")

        print("[3] clicking 'Build my study plan' ...")
        try:
            btn = page.get_by_role("button", name=re.compile("Build my study plan", re.I))
            btn.click(timeout=15000)
        except Exception as e:
            print(f"    ! button click failed: {e}")
            print("    fallback: enumerate buttons")
            for b in page.locator("button").all():
                try:
                    print(f"      button text: {b.inner_text()!r}")
                except Exception:
                    pass
        else:
            print("    clicked — waiting up to 3 min for study plan JSON ...")
            end = time.time() + 180
            while time.time() < end:
                body = page.locator("body").inner_text()
                if "study_plan" in body or "cambridge-" in body or "priorities" in body:
                    break
                page.wait_for_timeout(1500)
            shot(page, "14_study_plan_loaded")
            body_text = page.locator("body").inner_text()
            Path(OUT / "study_plan_body.txt").write_text(body_text, encoding="utf-8")
            cites = sorted(set(re.findall(r"cambridge-\d+(?:-test\d+)?", body_text)))
            print(f"    grounded citations: {cites or '(none)'}")

        print("\n[4] captured browser logs:")
        for line in logs[-20:]:
            print(f"    {line}")

        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
