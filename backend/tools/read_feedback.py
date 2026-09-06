"""Read the pilot feedback inbox as something a human can actually skim.

The route returns JSON on one line, which is the right thing for a program and
the wrong thing for the person who has to read twenty notes over breakfast.

    FEEDBACK_ADMIN_TOKEN=... python tools/read_feedback.py
    FEEDBACK_ADMIN_TOKEN=... python tools/read_feedback.py --limit 500
    FEEDBACK_ADMIN_TOKEN=... python tools/read_feedback.py --json > inbox.json
    FEEDBACK_ADMIN_TOKEN=... python tools/read_feedback.py --csv  > inbox.csv

Defaults to the deployment. Point it elsewhere with IELTS_API:

    IELTS_API=http://127.0.0.1:8000 python tools/read_feedback.py
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import sys
import textwrap
from datetime import datetime, timezone

import httpx

API = os.environ.get("IELTS_API", "https://oratio-api.vercel.app").rstrip("/")
TOKEN = os.environ.get("FEEDBACK_ADMIN_TOKEN", "")

FIELDS = ["id", "created_at", "email", "rating", "page", "user_id", "user_agent", "message"]


def device(user_agent: str | None) -> str:
    """Condense a user-agent into the part that changes how you'd debug.

    The raw string is 120 characters of version numbers nobody reads. What
    matters in a bug report is "which browser, which kind of device" — a
    layout complaint from mobile Safari is a different hunt than the same
    words from desktop Chrome.
    """
    if not user_agent:
        return "-"
    ua = user_agent
    if "Edg/" in ua:
        browser = "Edge"
    elif "OPR/" in ua or "Opera" in ua:
        browser = "Opera"
    elif "Chrome/" in ua or "CriOS" in ua:
        browser = "Chrome"
    elif "Firefox/" in ua or "FxiOS" in ua:
        browser = "Firefox"
    elif "Safari/" in ua:
        browser = "Safari"
    else:
        browser = "?"

    if "iPhone" in ua or "iPod" in ua:
        plat = "iPhone"
    elif "iPad" in ua:
        plat = "iPad"
    elif "Android" in ua:
        plat = "Android tablet" if "Mobile" not in ua else "Android"
    elif "Windows" in ua:
        plat = "Windows"
    elif "Mac OS X" in ua or "Macintosh" in ua:
        plat = "Mac"
    elif "Linux" in ua:
        plat = "Linux"
    else:
        plat = "?"
    return f"{browser} / {plat}"


def when(iso: str | None) -> str:
    """Absolute time plus how long ago, because both answer different questions."""
    if not iso:
        return "-"
    try:
        ts = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - ts
    secs = int(delta.total_seconds())
    if secs < 3600:
        ago = f"{max(secs // 60, 0)}m ago"
    elif secs < 86400:
        ago = f"{secs // 3600}h ago"
    else:
        ago = f"{secs // 86400}d ago"
    return f"{ts.strftime('%Y-%m-%d %H:%M')} UTC  ({ago})"


def stars(rating: int | None) -> str:
    if rating is None:
        return "not rated"
    return "*" * rating + "." * (5 - rating) + f"  {rating}/5"


def fetch(limit: int) -> list[dict]:
    if not TOKEN:
        sys.exit(
            "! FEEDBACK_ADMIN_TOKEN is not set.\n"
            "  It is the only thing guarding every tester's email address, so the\n"
            "  route refuses to answer without it. Set it and try again:\n"
            "      FEEDBACK_ADMIN_TOKEN=... python tools/read_feedback.py"
        )
    try:
        resp = httpx.get(
            f"{API}/feedback",
            headers={"X-Admin-Token": TOKEN},
            params={"limit": limit},
            timeout=30,
        )
    except httpx.HTTPError as exc:
        sys.exit(f"! Could not reach {API}: {exc}")

    if resp.status_code == 403:
        detail = ""
        try:
            detail = resp.json().get("detail", "")
        except ValueError:
            pass
        sys.exit(
            f"! Refused (403): {detail or 'wrong or missing admin token'}\n"
            f"  The token here must match FEEDBACK_ADMIN_TOKEN on {API}."
        )
    resp.raise_for_status()
    return resp.json()


def render(rows: list[dict]) -> None:
    width = min(shutil.get_terminal_size((100, 24)).columns, 100)
    rule = "=" * width

    print(rule)
    rated = [r["rating"] for r in rows if r.get("rating") is not None]
    average = f"{sum(rated) / len(rated):.1f}/5 from {len(rated)}" if rated else "none yet"
    print(f" Oratio - pilot feedback   |   {len(rows)} note(s)   |   avg rating: {average}")
    print(f" {API}")
    print(rule)

    if not rows:
        print("\n  Nothing yet. The box is on the landing page at #feedback.\n")
        return

    for row in rows:
        print()
        who = row.get("email") or "-"
        if row.get("user_id") is not None:
            who += f"   [signed in, user {row['user_id']}]"
        print(f"  #{row['id']}  {who}")
        print(f"      {when(row.get('created_at'))}")
        print(f"      {stars(row.get('rating'))}      {device(row.get('user_agent'))}"
              f"      page: {row.get('page') or '-'}")
        print()
        body = re.sub(r"\s*\n\s*", "\n", (row.get("message") or "").strip())
        for para in body.split("\n"):
            if not para:
                print()
                continue
            for line in textwrap.wrap(para, width=width - 8) or [""]:
                print(f"      {line}")
        print(f"  {'-' * (width - 2)}")
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=100, help="how many notes to pull (max 500)")
    ap.add_argument("--json", action="store_true", help="print raw JSON instead of a table")
    ap.add_argument("--csv", action="store_true", help="print CSV, for a spreadsheet")
    args = ap.parse_args()

    rows = fetch(args.limit)

    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    if args.csv:
        writer = csv.DictWriter(sys.stdout, fieldnames=FIELDS, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        return 0

    render(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
