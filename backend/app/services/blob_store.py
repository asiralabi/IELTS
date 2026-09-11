"""Durable object storage for generated audio, on Vercel Blob.

Why this exists: a Listening recording costs ~100 seconds of neural synthesis
and was cached on LOCAL DISK — the one kind of storage this app does not have.
A serverless instance gets a fresh `/tmp` and is killed when it goes idle, and
the CI job that keeps the practice pool warm throws its whole runner away at
the end of every run. So the cache was empty again by the time a student
pressed PLAY, and the warmer — which exists precisely to move that wait off
the student — was voicing parts into a directory nobody would ever read.

Serving the bytes back through the API had a second cost: a Vercel function
response is capped at 4.5MB and a Part 3 recording measured 3.25MB, so the
feature was one longer script away from failing outright. A blob is served
from the edge network instead, and the function only ever answers with its
URL.

This is deliberately NOT the `vercel` Python SDK: that pulls in eight
transitive packages (sandbox, queue, websockets, cbor2) to send the two HTTP
requests httpx — already a dependency — sends here. The wire contract below is
read from `@vercel/blob@2.8.0`, not guessed.

Everything is keyed off ONE environment variable, `BLOB_READ_WRITE_TOKEN`,
which Vercel sets on the project when a Blob store is linked. The store id is
the fourth underscore-separated field of that token, and the public hostname is
built from it — so there is no second variable to set, and no way to configure
a token and a bucket that disagree. Unset (a local run, the Docker stack, a
fork) means `enabled` is False, every call here is a no-op, and the disk cache
carries on alone.
"""

from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# `@vercel/blob` sends this and the API rejects a request without it. It is a
# number the service bumps, so it lives next to the base URL rather than being
# spelled into each call.
_API_VERSION = "12"

# A blob is addressed by the sha256 of what is inside it, so its content can
# never change. Cache it for a year rather than the API's one-month default.
_IMMUTABLE_MAX_AGE = 31_536_000

_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def _store_id() -> str:
    """The store id encoded in a read-write token.

    A token reads `vercel_blob_rw_<storeid>_<secret>`; the SDK splits on "_"
    and takes field 3. Hostnames are case-insensitive, and the store id is
    printed capitalised in the dashboard, so this lower-cases it.
    """
    parts = (settings.blob_read_write_token or "").split("_")
    return parts[3].lower() if len(parts) > 4 else ""


def enabled() -> bool:
    """Whether there is a Blob store to read and write."""
    return bool(_store_id())


def public_url(pathname: str) -> str | None:
    """The CDN address a blob at `pathname` would have, without asking.

    The store is public and uploads are made with no random suffix, so the URL
    is a pure function of the pathname — worth knowing, because it means the
    "is it cached?" question is a plain unauthenticated HEAD against the edge
    rather than a round trip through the Blob API.
    """
    store = _store_id()
    if not store:
        return None
    return f"https://{store}.public.blob.vercel-storage.com/{pathname}"


async def head(pathname: str) -> str | None:
    """Return the blob's public URL if it is already stored, else None."""
    url = public_url(pathname)
    if url is None:
        return None
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.head(url)
    except httpx.HTTPError as exc:
        logger.warning("blob head failed for %s: %s", pathname, exc)
        return None
    return url if response.status_code == 200 else None


async def get(pathname: str) -> bytes | None:
    """Download a stored blob, or None if it is not there.

    Only for callers that genuinely need the bytes in this process. Anything
    answering a browser should hand out `public_url` instead and let the edge
    serve it.
    """
    url = public_url(pathname)
    if url is None:
        return None
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(url)
    except httpx.HTTPError as exc:
        logger.warning("blob get failed for %s: %s", pathname, exc)
        return None
    return response.content if response.status_code == 200 else None


async def put(pathname: str, data: bytes, content_type: str) -> str | None:
    """Store `data` at `pathname` and return its public URL.

    Returns None on any failure: a missing recording in the store is a slow
    student, whereas raising here would lose a generated practice set or fail
    a request that could still have served the audio itself.
    """
    store = _store_id()
    if not store:
        return None

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.put(
                settings.blob_api_url.rstrip("/") + "/",
                params={"pathname": pathname},
                content=data,
                headers={
                    "authorization": f"Bearer {settings.blob_read_write_token}",
                    "x-api-version": _API_VERSION,
                    "x-vercel-blob-store-id": store,
                    "x-vercel-blob-access": "public",
                    "x-content-type": content_type,
                    # Without this the pathname gains a random suffix and the
                    # URL stops being derivable from the content digest.
                    "x-add-random-suffix": "0",
                    # Two warmers racing on the same script would otherwise
                    # make the second one an error. The bytes are identical.
                    "x-allow-overwrite": "1",
                    "x-cache-control-max-age": str(_IMMUTABLE_MAX_AGE),
                },
            )
    except httpx.HTTPError as exc:
        logger.warning("blob upload failed for %s: %s", pathname, exc)
        return None

    if response.status_code >= 400:
        logger.warning(
            "blob upload rejected for %s: %s %s",
            pathname,
            response.status_code,
            response.text[:200],
        )
        return None

    try:
        return str(response.json()["url"])
    except (ValueError, KeyError, TypeError):
        # The upload landed; only the reply was unexpected. The address is
        # derivable anyway, so this is not worth failing over.
        logger.warning("blob upload returned no url for %s", pathname)
        return public_url(pathname)
