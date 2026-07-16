"""API-level integration smoke: log in as demo, hit every endpoint the
frontend consumes, and verify the responses match the shapes the frontend
now expects (after the recent type tightening)."""

import json
import sys
from typing import Any

import httpx

API = "http://127.0.0.1:8000"
EMAIL = "demo@example.com"
PASSWORD = "demo1234"


def ok(msg: str) -> None:
    print(f"  [OK]   {msg}")


def bad(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def has_keys(obj: Any, keys: list[str]) -> tuple[bool, list[str]]:
    if not isinstance(obj, dict):
        return False, keys
    missing = [k for k in keys if k not in obj]
    return not missing, missing


def main() -> int:
    print("=" * 62)
    print(" API smoke test — demo@example.com")
    print("=" * 62)

    # --- login ---
    print("\n[auth]")
    r = httpx.post(f"{API}/auth/login",
                   data={"username": EMAIL, "password": PASSWORD}, timeout=15)
    if r.status_code != 200:
        bad(f"/auth/login -> {r.status_code}"); return 1
    tokens = r.json()
    ok("POST /auth/login")
    hdrs = {"Authorization": f"Bearer {tokens['access_token']}"}

    r = httpx.get(f"{API}/auth/me", headers=hdrs, timeout=15)
    if r.status_code != 200:
        bad(f"/auth/me -> {r.status_code}: {r.text[:200]}"); return 1
    user = r.json()
    okp, miss = has_keys(user, ["id", "email", "full_name", "target_band"])
    (ok if okp else bad)(f"GET /auth/me  user_id={user.get('id')}  missing={miss}")

    # --- writing history ---
    print("\n[writing]")
    r = httpx.get(f"{API}/writing/history", headers=hdrs, timeout=15)
    if r.status_code == 200 and isinstance(r.json(), list):
        rows = r.json()
        ok(f"GET /writing/history -> {len(rows)} rows")
        if rows:
            first = rows[0]
            okp, miss = has_keys(first, ["id", "task_type", "band_score", "word_count", "created_at"])
            (ok if okp else bad)(f"  shape ok, missing={miss}")
    else:
        bad(f"/writing/history -> {r.status_code}")

    # --- speaking history ---
    print("\n[speaking]")
    r = httpx.get(f"{API}/speaking/history", headers=hdrs, timeout=15)
    if r.status_code == 200:
        rows = r.json()
        ok(f"GET /speaking/history -> {len(rows)} rows")
        if rows:
            first = rows[0]
            okp, miss = has_keys(first, ["id", "part", "band_score", "created_at"])
            (ok if okp else bad)(f"  shape ok, missing={miss}")
    else:
        bad(f"/speaking/history -> {r.status_code}")

    # --- progress ---
    print("\n[progress]")
    r = httpx.get(f"{API}/progress", headers=hdrs, timeout=30)
    if r.status_code == 200:
        p = r.json()
        okp, miss = has_keys(p, ["counts", "skills", "target_band", "timeline"])
        (ok if okp else bad)(f"GET /progress  missing={miss}")
        if okp:
            skills = p["skills"]
            for k in ["writing", "speaking", "reading", "listening", "mock_exam"]:
                latest = skills.get(k, {}).get("latest_band")
                ok(f"  skill {k:9} latest_band={latest}")
            ok(f"  timeline entries: {len(p['timeline'])}")
    else:
        bad(f"/progress -> {r.status_code}")

    # --- study plan (RAG-grounded) ---
    print("\n[study plan]")
    r = httpx.get(f"{API}/progress/study-plan", headers=hdrs, timeout=600)
    if r.status_code == 200:
        plan = r.json()
        okp, miss = has_keys(plan, ["summary", "priorities", "study_plan"])
        (ok if okp else bad)(f"GET /progress/study-plan  missing={miss}")
        if okp:
            days = plan["study_plan"]
            ok(f"  {len(days)} day(s), first focus: {days[0].get('focus') if days else 'n/a'}")
            import re
            blob = json.dumps(plan)
            cites = sorted(set(re.findall(r"cambridge-\d+(?:-test\d+)?", blob)))
            (ok if cites else bad)(f"  grounded citations: {cites or '(none)'}")
            # matches the tightened frontend StudyPlan type?
            if isinstance(days, list) and days and \
               all(isinstance(d.get("day"), int) and isinstance(d.get("focus"), str)
                   and isinstance(d.get("tasks"), list) for d in days):
                ok("  shape matches StudyPlan type (day:int, focus:str, tasks:string[])")
            else:
                bad("  shape does not match StudyPlan type")
    else:
        bad(f"/progress/study-plan -> {r.status_code}: {r.text[:200]}")

    # --- weaknesses ---
    print("\n[weaknesses]")
    r = httpx.get(f"{API}/progress/weaknesses", headers=hdrs, timeout=600)
    if r.status_code == 200:
        w = r.json()
        criterion_keys = ["grammar", "vocabulary", "coherence", "pronunciation",
                          "fluency", "task_response", "reading_comprehension",
                          "listening_accuracy"]
        okp, miss = has_keys(w, criterion_keys + ["details"])
        (ok if okp else bad)(f"GET /progress/weaknesses  missing={miss}")
        if okp:
            trues = [k for k in criterion_keys if w.get(k) is True]
            ok(f"  weaknesses flagged: {trues or '(none)'}")
            details_okp, dmiss = has_keys(w.get("details", {}), criterion_keys)
            (ok if details_okp else bad)(f"  details.* keys missing={dmiss}")
    else:
        bad(f"/progress/weaknesses -> {r.status_code}: {r.text[:200]}")

    # --- mock exam get by id ---
    print("\n[mock exam]")
    r = httpx.get(f"{API}/mock-exam/1", headers=hdrs, timeout=15)
    if r.status_code == 200:
        mx = r.json()
        okp, miss = has_keys(mx, ["id", "status", "exam", "results", "overall_band"])
        (ok if okp else bad)(f"GET /mock-exam/1  status={mx.get('status')} band={mx.get('overall_band')}  missing={miss}")
    else:
        bad(f"/mock-exam/1 -> {r.status_code}")

    print("\n" + "=" * 62)
    print(" Smoke test complete.")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
