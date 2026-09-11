"""A recording rendered once stays rendered — on a platform with no disk.

The Listening audio was cached to local disk and nowhere else. Neither machine
that runs this app keeps one: a Vercel instance gets a fresh /tmp and is killed
when it goes idle, and the CI job that warms the practice pool deletes its
whole runner when the job ends. So the pre-rendering happened, the cache was
written, and the first student to press PLAY after a cold start still waited
out ~100 seconds of neural synthesis.

The second half of the same problem: a Vercel function response is capped at
4.5MB and a Part 3 recording measured 3.25MB, so serving the MP3 through the
API was one longer script away from failing outright.

These tests pin both halves — the recording survives the process that made it,
and the bytes stop travelling through the function once it does.
"""

import asyncio

import pytest

from app.config import settings
from app.models import GeneratedQuestion
from app.services import blob_store, tts

SCRIPT = "AGENT: Good morning, City Tours. STUDENT: Hello, I would like to book."
STORE_TOKEN = "vercel_blob_rw_AvNADMKgWjdKRy6Q_deadbeefdeadbeef"
EDGE = "https://avnadmkgwjdkry6q.public.blob.vercel-storage.com"


class _Store:
    """A Blob store that remembers, standing in for the real one."""

    def __init__(self, prefilled: bool = False, upload_fails: bool = False) -> None:
        self.blobs: dict[str, bytes] = {}
        self.heads: list[str] = []
        self.puts: list[tuple[str, str]] = []
        self.prefilled = prefilled
        self.upload_fails = upload_fails

    def enabled(self) -> bool:
        return True

    async def head(self, pathname: str) -> str | None:
        self.heads.append(pathname)
        if self.prefilled or pathname in self.blobs:
            return f"{EDGE}/{pathname}"
        return None

    async def get(self, pathname: str) -> bytes | None:
        return self.blobs.get(pathname)

    async def put(self, pathname: str, data: bytes, content_type: str) -> str | None:
        self.puts.append((pathname, content_type))
        if self.upload_fails:
            return None
        self.blobs[pathname] = data
        return f"{EDGE}/{pathname}"


@pytest.fixture
def voice(monkeypatch):
    """Count the synthesis calls — the whole point is to make them rare."""
    calls: list[str] = []

    async def _synthesize(script, specs):
        calls.append(script)
        return b"ID3-pretend-mp3"

    monkeypatch.setattr(tts, "_synthesize", _synthesize)
    return calls


@pytest.fixture
def store(monkeypatch):
    def _install(**kw):
        s = _Store(**kw)
        for name in ("enabled", "head", "get", "put"):
            monkeypatch.setattr(blob_store, name, getattr(s, name))
        return s

    return _install


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "tts_cache_dir", str(tmp_path / "tts"))
    return tmp_path / "tts"


# --- the durable tier -------------------------------------------------------


def test_a_stored_recording_is_never_voiced_again(voice, store, cache_dir):
    """The case that was costing 100 seconds: a cold instance, a warm store."""
    s = store(prefilled=True)
    recording = asyncio.run(tts.ensure_recording(SCRIPT))

    assert voice == [], "asked the voice service for audio that already exists"
    assert recording.url and recording.url.startswith(EDGE)
    assert recording.audio is None, "the bytes should never enter the process"


def test_a_freshly_voiced_recording_is_uploaded(voice, store, cache_dir):
    s = store()
    recording = asyncio.run(tts.ensure_recording(SCRIPT))

    assert len(voice) == 1
    assert len(s.puts) == 1
    pathname, content_type = s.puts[0]
    assert pathname.startswith("listening/") and pathname.endswith(".mp3")
    assert content_type == "audio/mpeg"
    assert recording.url == f"{EDGE}/{pathname}"


def test_the_second_instance_reads_what_the_first_one_wrote(voice, store, cache_dir):
    """Two processes, one store — which is the pool warmer and the app."""
    s = store()
    asyncio.run(tts.ensure_recording(SCRIPT))
    assert len(voice) == 1

    # A different instance: same store, empty disk.
    cache_dir.rename(cache_dir.parent / "gone")
    recording = asyncio.run(tts.ensure_recording(SCRIPT))

    assert len(voice) == 1, "voiced the same script twice across instances"
    assert recording.url


def test_a_different_direction_is_a_different_recording(voice, store, cache_dir):
    """Accent/gender/WPM change the sound, so they must change the key."""
    store()
    asyncio.run(tts.ensure_recording(SCRIPT, [{"label": "AGENT", "accent": "British"}]))
    asyncio.run(tts.ensure_recording(SCRIPT, [{"label": "AGENT", "accent": "American"}]))
    assert len(voice) == 2


# --- degrading without a store ---------------------------------------------


def test_without_a_blob_store_the_bytes_come_back(voice, cache_dir):
    """The container deployment: a real disk, no object storage, still works."""
    recording = asyncio.run(tts.ensure_recording(SCRIPT))
    assert recording.audio == b"ID3-pretend-mp3"
    assert recording.url is None


def test_without_a_blob_store_the_disk_still_answers(voice, cache_dir):
    asyncio.run(tts.ensure_recording(SCRIPT))
    asyncio.run(tts.ensure_recording(SCRIPT))
    assert len(voice) == 1


def test_a_failed_upload_still_serves_the_student(voice, store, cache_dir):
    """A store that is down is a slower recording, not a silent player."""
    store(upload_fails=True)
    recording = asyncio.run(tts.ensure_recording(SCRIPT))
    assert recording.audio == b"ID3-pretend-mp3"


def test_a_disk_it_cannot_write_to_does_not_stop_playback(voice, monkeypatch, tmp_path):
    """On Vercel everything outside /tmp is read-only, and TTS_CACHE_DIR is one
    env var away from pointing at it. Losing the cache must not lose the audio."""
    blocked = tmp_path / "file-not-a-dir"
    blocked.write_bytes(b"")
    monkeypatch.setattr(settings, "tts_cache_dir", str(blocked / "tts"))

    recording = asyncio.run(tts.ensure_recording(SCRIPT))
    assert recording.audio == b"ID3-pretend-mp3"


def test_an_empty_script_is_refused(voice, cache_dir):
    with pytest.raises(RuntimeError):
        asyncio.run(tts.ensure_recording("   "))
    assert voice == []


# --- the store id comes out of the token ------------------------------------


def test_the_store_is_addressed_from_the_token_alone(monkeypatch):
    """One env var configures this. A token and a bucket that disagree is a
    class of misconfiguration that should not be expressible."""
    monkeypatch.setattr(settings, "blob_read_write_token", STORE_TOKEN)
    assert blob_store.enabled()
    assert blob_store.public_url("listening/x.mp3") == f"{EDGE}/listening/x.mp3"


def test_no_token_means_no_store(monkeypatch):
    monkeypatch.setattr(settings, "blob_read_write_token", "")
    assert not blob_store.enabled()
    assert blob_store.public_url("listening/x.mp3") is None


def test_a_malformed_token_is_not_half_a_store(monkeypatch):
    """Better off with no blob tier than with a URL built from nonsense."""
    monkeypatch.setattr(settings, "blob_read_write_token", "vercel_blob_rw_oops")
    assert not blob_store.enabled()


# --- what the browser is handed ---------------------------------------------


def _listening_set(client, auth_headers) -> int:
    """A stored listening set with a script, without generating one."""
    from app.database import SessionLocal

    with SessionLocal() as db:
        me = client.get("/auth/me", headers=auth_headers).json()
        question = GeneratedQuestion(
            user_id=me["id"],
            section="listening",
            question_type="mixed",
            difficulty="Band 6",
            payload={"audio_script": SCRIPT},
        )
        db.add(question)
        db.commit()
        db.refresh(question)
        return question.id


def test_the_audio_route_sends_the_browser_to_the_edge(
    client, auth_headers, voice, store, cache_dir
):
    """The 4.5MB cap: once the recording is stored, no MP3 crosses the function."""
    store(prefilled=True)
    practice_id = _listening_set(client, auth_headers)

    resp = client.get(
        f"/listening/audio/{practice_id}", headers=auth_headers, follow_redirects=False
    )
    assert resp.status_code == 307
    assert resp.headers["location"].startswith(EDGE)
    assert not resp.content


def test_the_audio_route_still_serves_bytes_without_a_store(
    client, auth_headers, voice, cache_dir
):
    practice_id = _listening_set(client, auth_headers)

    resp = client.get(f"/listening/audio/{practice_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/mpeg"
    assert resp.content == b"ID3-pretend-mp3"
