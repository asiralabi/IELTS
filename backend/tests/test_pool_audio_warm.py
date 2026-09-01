"""The warm pool renders the recording, not just the script.

🔬 Measured 2026-09-02 against the running app: a listening set popped from the
pool in 0.3s and the student then waited **102 seconds** on a dead player while
~1900 words were spoken on demand. The audio is cached on disk keyed by
script+voices, so the same request came back in 0.2s the second time — every
student was simply paying for the first one. Pre-generating the script and not
the sound left the wait exactly where this pool exists to remove it from.
"""

import asyncio

import pytest

from app.services import practice_pool as pool


class _Recorder:
    def __init__(self, blow_up: bool = False) -> None:
        self.scripts: list[str] = []
        self.blow_up = blow_up

    async def synthesize_script(self, script, speakers=None):
        self.scripts.append(script)
        if self.blow_up:
            raise RuntimeError("the voice service is down")
        return b"mp3"


@pytest.fixture
def tts(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr("app.services.tts.synthesize_script", rec.synthesize_script)
    return rec


def test_a_listening_set_is_voiced_before_it_is_stored(tts):
    bucket = pool.Bucket("listening", None, target_size=1)
    payload = {"audio_script": "Emma: Hello there.", "speakers": [{"label": "Emma"}]}
    asyncio.run(pool._warm_audio(bucket, payload))
    assert tts.scripts == ["Emma: Hello there."]


def test_every_part_of_a_full_test_is_voiced(tts):
    """`/listening/audio/{id}?part=N` asks for them one at a time."""
    bucket = pool.Bucket("listening", pool.FULL_TEST, target_size=1)
    payload = {"parts": [{"audio_script": f"Speaker: Part {n}."} for n in (1, 2, 3, 4)]}
    asyncio.run(pool._warm_audio(bucket, payload))
    assert len(tts.scripts) == 4


def test_reading_is_not_sent_to_the_voice_service(tts):
    bucket = pool.Bucket("reading", None, target_size=1)
    asyncio.run(pool._warm_audio(bucket, {"passage": "Rubber was discovered..."}))
    assert tts.scripts == []


def test_a_scriptless_set_asks_for_nothing(tts):
    bucket = pool.Bucket("listening", None, target_size=1)
    asyncio.run(pool._warm_audio(bucket, {"audio_script": "   "}))
    assert tts.scripts == []


def test_a_voice_failure_does_not_cost_the_generated_set(monkeypatch):
    """The set is still usable — the student just pays the synthesis the old
    way. Losing the whole generation would waste the hosted call as well."""
    rec = _Recorder(blow_up=True)
    monkeypatch.setattr("app.services.tts.synthesize_script", rec.synthesize_script)
    bucket = pool.Bucket("listening", None, target_size=1)
    asyncio.run(pool._warm_audio(bucket, {"audio_script": "Emma: Hello."}))  # must not raise
    assert rec.scripts == ["Emma: Hello."]
