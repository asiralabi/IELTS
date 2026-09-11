"""Handing a rendered Listening recording back to the browser.

Two routes serve the same thing from different owners — a practice set has a
`GeneratedQuestion` id, a mock exam's listening paper is a snapshot inside the
exam — so the decision of *how* to answer lives here rather than twice.
"""

from fastapi import Response
from fastapi.responses import RedirectResponse

from app.services.tts import Recording

# The recording is immutable for a given practice id, so a browser may keep it
# for a day. `private` because the route behind it is per-user.
_CACHE = "private, max-age=86400"


def serve_recording(recording: Recording) -> Response:
    """A redirect to the edge when the audio is stored there, else the bytes.

    The redirect is the case worth having: a Vercel function response is
    capped at 4.5MB and a Part 3 recording has measured 3.25MB, so streaming
    MP3s through the function was one longer script away from failing. It is
    also a 307 rather than a 302 so the method survives, and the browser drops
    the Authorization header on the cross-origin hop — which is why the blob
    has to be publicly readable, and why its name is a sha256 of the script.

    The byte path is not a fallback nobody takes: it is how the containerised
    deployment and every local run serve audio, where the disk cache is real
    storage and there is no blob store at all.
    """
    if recording.url:
        return RedirectResponse(
            recording.url, status_code=307, headers={"Cache-Control": _CACHE}
        )
    return Response(
        content=recording.audio or b"",
        media_type="audio/mpeg",
        headers={"Cache-Control": _CACHE},
    )
