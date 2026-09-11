"""Prove the Blob store this app is configured for actually works.

The Qdrant lesson applied to a second managed service: an embedded store and a
hosted one are not the same thing, and anything only ever exercised against the
forgiving one is untested. The suite mocks `blob_store` — it has to, or the
tests would write into production — so nothing else checks that the wire
contract is right until a student presses PLAY.

It also checks the two response headers the redirect design leans on and that
no unit test can see:

  * `Access-Control-Allow-Origin`, because the browser follows our 307 from the
    API's origin to the blob's and reads the body afterwards.
  * `Accept-Ranges`, because an <audio> element seeks with range requests.

Run against the deployed store by handing it the file Vercel wrote:

    python tools/blob_store_check.py --env-file .env.local

Only BLOB_READ_WRITE_TOKEN is read out of that file. It also holds the
production DATABASE_URL, and loading THAT into a local process is how a
developer ends up writing to the real database by accident.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TOKEN_VAR = "BLOB_READ_WRITE_TOKEN"
PROBE = "probe/blob-store-check.txt"


def load_token(env_file: str | None) -> None:
    if not env_file:
        return
    path = Path(env_file)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[1] / env_file
    if not path.exists():
        sys.exit(f"no such env file: {path}")
    for line in path.read_text(encoding="utf-8").splitlines():
        name, _, value = line.partition("=")
        if name.strip() == TOKEN_VAR:
            os.environ[TOKEN_VAR] = value.strip().strip('"').strip("'")
            return
    sys.exit(f"{path} does not set {TOKEN_VAR}")


async def main(env_file: str | None) -> int:
    load_token(env_file)

    from app.services import blob_store

    if not blob_store.enabled():
        print(f"FAIL  no blob store configured ({TOKEN_VAR} is unset or malformed)")
        print("      the app will fall back to the disk cache, which on Vercel")
        print("      means every cold start re-voices the recording.")
        return 1

    url = blob_store.public_url(PROBE)
    print(f"store  {url.split('//')[1].split('.')[0]}")

    body = b"blob-store-check"
    written = await blob_store.put(PROBE, body, "text/plain")
    if not written:
        print("FAIL  upload rejected — see the warning logged above")
        return 1
    print(f"put    {written}")

    found = await blob_store.head(PROBE)
    print(f"head   {'found' if found else 'MISSING'}")
    if not found:
        print("FAIL  the blob uploaded but is not readable at its derived URL.")
        print("      That breaks the cache lookup: every play would re-voice.")
        return 1

    back = await blob_store.get(PROBE)
    print(f"get    {len(back or b'')} bytes")
    if back != body:
        print("FAIL  read back something other than what was written")
        return 1

    import httpx

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, headers={"Origin": "https://oratio-ielts.vercel.app"})
    cors = resp.headers.get("access-control-allow-origin")
    ranges = resp.headers.get("accept-ranges")
    cache = resp.headers.get("cache-control")
    print(f"cors   {cors}")
    print(f"range  {ranges}")
    print(f"cache  {cache}")
    if cors not in ("*", "https://oratio-ielts.vercel.app"):
        print("FAIL  the browser cannot read a redirect it is not allowed to follow.")
        return 1
    if ranges != "bytes":
        print("WARN  no range support — the player cannot seek within a recording.")

    print("\nOK  a recording rendered once will outlive the process that made it.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-file",
        help="read BLOB_READ_WRITE_TOKEN from this file (e.g. .env.local)",
    )
    raise SystemExit(asyncio.run(main(parser.parse_args().env_file)))
