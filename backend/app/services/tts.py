"""Multi-speaker neural text-to-speech for the Listening audio.

The Listening trainer emits a single speaker-labelled ``audio_script`` (e.g.
``AGENT: ...`` / ``STUDENT: ...`` / ``LECTURER: ...``) plus an optional
``speakers`` array of per-speaker *Audio Performance Instructions* (gender,
accent, persona, words-per-minute, inter-turn pause) as described in the
system design.  This module turns that script into a realistic, multi-voice
recording using edge-tts neural voices: each distinct speaker gets a voice
matching its accent/gender, is spoken at its target WPM, and turns are
stitched into one MP3 with the requested pauses between them.  Synthesis is
lazy and cached to disk keyed by the script *and* the performance spec, so a
part is only ever voiced once per direction.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

from app.config import settings

# en-GB neural voices, split by perceived gender so a two-speaker Part 1
# sounds like a natural male/female pair. Used for the heuristic fallback when
# the generator did not supply explicit performance instructions.
_FEMALE_VOICES = ["en-GB-SoniaNeural", "en-GB-LibbyNeural", "en-GB-BellaNeural"]
_MALE_VOICES = ["en-GB-RyanNeural", "en-GB-ThomasNeural", "en-GB-EthanNeural"]
_DEFAULT_VOICE = "en-GB-SoniaNeural"

# Neural voice pools keyed by (accent, gender). The Audio Performance
# Instructions pick an accent + gender per speaker; we cycle through the pool
# so two same-accent/same-gender speakers still sound distinct.
_ACCENT_VOICES: dict[tuple[str, str], list[str]] = {
    ("british", "F"): ["en-GB-SoniaNeural", "en-GB-LibbyNeural", "en-GB-BellaNeural"],
    ("british", "M"): ["en-GB-RyanNeural", "en-GB-ThomasNeural", "en-GB-EthanNeural"],
    ("american", "F"): ["en-US-AriaNeural", "en-US-JennyNeural", "en-US-MichelleNeural"],
    ("american", "M"): ["en-US-GuyNeural", "en-US-EricNeural", "en-US-RogerNeural"],
    ("australian", "F"): ["en-AU-NatashaNeural", "en-AU-FreyaNeural"],
    ("australian", "M"): ["en-AU-WilliamNeural", "en-AU-DarrenNeural"],
    ("canadian", "F"): ["en-CA-ClaraNeural"],
    ("canadian", "M"): ["en-CA-LiamNeural"],
}
# edge-tts default neural voices speak natural prose at roughly this rate; a
# speaker's requested WPM is converted to a percentage offset around it.
_BASELINE_WPM = 150

# Labels that unambiguously mark a spoken turn even though they are ordinary
# words — used to tell a real speaker label from an inline "word:" fragment.
_KNOWN_ROLES = {
    "speaker", "agent", "student", "tutor", "lecturer", "professor", "woman",
    "man", "male", "female", "receptionist", "guide", "presenter", "narrator",
    "interviewer", "host", "customer", "clerk", "officer", "manager",
    "assistant", "librarian", "instructor", "operator", "caller", "advisor",
    "supervisor", "examiner", "teacher", "moderator",
}
_FEMALE_HINTS = {"woman", "female", "receptionist", "she", "her"}
_MALE_HINTS = {"man", "male", "he", "his"}

_TURN_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 .'\-]{0,23}?)\s*:\s+(.+)$")
# Names spelled out letter-by-letter ("B-R-A-I-T-H") read as words unless we
# space the letters so the voice pronounces each one.
_SPELLED_RE = re.compile(r"\b([A-Za-z](?:-[A-Za-z]){2,})\b")

_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


def _is_speaker_label(label: str) -> bool:
    label = label.strip()
    if not label or any(ch.isdigit() for ch in label):
        return False
    low = label.lower()
    if low in _KNOWN_ROLES:
        return True
    if re.fullmatch(r"speaker\s*[a-z0-9]", low):
        return True
    words = label.split()
    if len(words) <= 3 and len(label) <= 20 and all(w[:1].isupper() for w in words):
        return True
    return False


def _gender_for(label: str, order: int) -> str:
    low = label.lower()
    if any(h in low for h in _FEMALE_HINTS):
        return "F"
    if any(h in low for h in _MALE_HINTS):
        return "M"
    # Alternate so the first speaker is female, the second male, etc.
    return "F" if order % 2 == 0 else "M"


def _assign_voices(speakers: list[str]) -> dict[str, str]:
    voices: dict[str, str] = {}
    f_i = m_i = 0
    for order, name in enumerate(speakers):
        if _gender_for(name, order) == "F":
            voices[name] = _FEMALE_VOICES[f_i % len(_FEMALE_VOICES)]
            f_i += 1
        else:
            voices[name] = _MALE_VOICES[m_i % len(_MALE_VOICES)]
            m_i += 1
    return voices


def _norm_gender(value: object) -> str | None:
    low = str(value or "").strip().lower()
    if low in {"f", "female", "woman", "w"} or "female" in low:
        return "F"
    if low in {"m", "male", "man"} or "male" in low:
        return "M"
    return None


def _norm_accent(value: object) -> str:
    low = str(value or "").strip().lower()
    # Order matters: check the specific accents before the loose "us" token,
    # since "australian" contains the substring "us".
    if any(k in low for k in ("austral", "aussie", "en-au")):
        return "australian"
    if any(k in low for k in ("canad", "en-ca")):
        return "canadian"
    if any(k in low for k in ("brit", "england", "en-gb", "welsh", "scott", "irish")):
        return "british"
    if any(k in low for k in ("america", "en-us", "yank", "united states", "u.s")):
        return "american"
    return "british"  # IELTS recordings default to British English


def _num(value: object, default: float) -> float:
    try:
        f = float(str(value))
        return f if f == f else default
    except (TypeError, ValueError):
        return default


def _base_rate_pct() -> int:
    m = re.match(r"\s*([+-]?\d+)\s*%", settings.tts_voice_rate or "")
    return int(m.group(1)) if m else 0


def _rate_str(wpm: float) -> str:
    """Map a target words-per-minute to an edge-tts ``rate`` string.

    150 WPM is treated as the voice's natural pace (0% offset). The global
    ``tts_voice_rate`` (e.g. -6% for exam realism) is added on top, and the
    result is clamped so a stray WPM never renders speech unintelligible.
    """
    pct = _base_rate_pct() + round((wpm / _BASELINE_WPM - 1) * 100)
    pct = max(-40, min(25, pct))
    return f"{pct:+d}%"


def _pause_suffix(pause_ms: float) -> str:
    """Approximate an inter-turn pause with terminal punctuation.

    edge-tts has no SSML break support, but neural voices lengthen their
    natural pause after sentence-final punctuation / ellipses, so we append a
    proportional cue to the end of a turn instead of splicing raw silence
    (which would require an audio codec dependency).
    """
    if pause_ms >= 450:
        return " . . ."
    if pause_ms >= 200:
        return " ."
    return ""


def _specs_by_label(speakers: object) -> dict[str, dict]:
    """Index a ``speakers`` performance array by upper-cased label."""
    out: dict[str, dict] = {}
    if not isinstance(speakers, list):
        return out
    for spec in speakers:
        if not isinstance(spec, dict):
            continue
        label = str(spec.get("label") or spec.get("name") or "").strip()
        if label:
            out[label.upper()] = spec
    return out


def _plan_performance(
    ordered_speakers: list[str], specs: dict[str, dict]
) -> dict[str, dict]:
    """Resolve a voice + rate + pause for every distinct speaker in a script.

    Speakers with an explicit performance spec use it (accent/gender pick the
    voice pool, WPM sets the rate, pause_ms sets the trailing pause). Speakers
    with no spec fall back to the gender heuristic and a default British voice.
    """
    counters: dict[tuple[str, str], int] = defaultdict(int)
    plan: dict[str, dict] = {}
    for order, label in enumerate(ordered_speakers):
        spec = specs.get(label.upper(), {})
        gender = _norm_gender(spec.get("gender")) or _gender_for(label, order)
        accent = _norm_accent(spec.get("accent")) if spec else "british"
        pool = _ACCENT_VOICES.get((accent, gender)) or _ACCENT_VOICES[("british", gender)]
        idx = counters[(accent, gender)]
        counters[(accent, gender)] += 1
        plan[label] = {
            "voice": pool[idx % len(pool)],
            "rate": _rate_str(_num(spec.get("wpm"), _BASELINE_WPM)),
            "pause": _pause_suffix(_num(spec.get("pause_ms"), 0)),
        }
    return plan


def _clean(text: str) -> str:
    text = _SPELLED_RE.sub(lambda m: m.group(1).replace("-", " "), text)
    return re.sub(r"\s+", " ", text).strip()


def parse_turns(script: str) -> list[tuple[str, str]]:
    """Split a labelled script into ``(speaker, text)`` turns.

    Continuation lines (no leading label) are appended to the current turn.
    A script with no detectable labels becomes a single unnamed turn.
    """
    turns: list[tuple[str, list[str]]] = []
    for raw in script.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line:
            continue
        m = _TURN_RE.match(line)
        if m and _is_speaker_label(m.group(1)):
            turns.append((m.group(1).strip(), [m.group(2).strip()]))
        elif turns:
            turns[-1][1].append(line)
        else:
            turns.append(("", [line]))

    out: list[tuple[str, str]] = []
    for speaker, parts in turns:
        text = _clean(" ".join(parts))
        if text:
            out.append((speaker, text))
    return out


def _spec_fingerprint(specs: dict[str, dict]) -> str:
    """A stable string of the performance directions for cache keying.

    Different Audio Performance Instructions must yield a different recording,
    so the accent/gender/WPM/pause of every speaker feeds the cache digest.
    """
    if not specs:
        return ""
    trimmed = {
        label: {
            "gender": _norm_gender(s.get("gender")),
            "accent": _norm_accent(s.get("accent")) if s else "british",
            "wpm": _num(s.get("wpm"), _BASELINE_WPM),
            "pause": _num(s.get("pause_ms"), 0),
        }
        for label, s in specs.items()
    }
    return json.dumps(trimmed, sort_keys=True)


def _cache_path(script: str, specs: dict[str, dict]) -> Path:
    digest = hashlib.sha256(
        f"{settings.tts_voice_rate}|{_spec_fingerprint(specs)}|{script}".encode("utf-8")
    ).hexdigest()
    return Path(settings.tts_cache_dir) / f"{digest}.mp3"


async def _synthesize(script: str, specs: dict[str, dict]) -> bytes:
    import edge_tts  # imported lazily so a missing dep never blocks app startup

    turns = parse_turns(script)
    ordered = list(dict.fromkeys(s for s, _ in turns if s))
    plan = _plan_performance(ordered, specs)
    default = {"voice": _DEFAULT_VOICE, "rate": settings.tts_voice_rate, "pause": ""}

    audio = bytearray()
    for speaker, text in turns:
        perf = plan.get(speaker, default)
        comm = edge_tts.Communicate(
            text + perf["pause"], perf["voice"], rate=perf["rate"]
        )
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                audio.extend(chunk["data"])
    if not audio:
        raise RuntimeError("TTS produced no audio")
    return bytes(audio)


async def synthesize_script(script: str, speakers: object = None) -> bytes:
    """Return MP3 bytes for a labelled script, synthesizing + caching on first use.

    ``speakers`` is the optional Audio Performance Instructions array from the
    generator; when absent, voices fall back to the gender heuristic.
    """
    if not settings.tts_enabled:
        raise RuntimeError("TTS is disabled")
    script = (script or "").strip()
    if not script:
        raise RuntimeError("Empty script")

    specs = _specs_by_label(speakers)
    path = _cache_path(script, specs)
    if path.exists():
        return path.read_bytes()

    async with _locks[path.name]:
        if path.exists():  # another request may have finished while we waited
            return path.read_bytes()
        audio = await _synthesize(script, specs)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".mp3.part")
        tmp.write_bytes(audio)
        tmp.replace(path)
        return audio
