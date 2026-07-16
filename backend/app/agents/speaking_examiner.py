from fastapi import HTTPException

from app.agents.writing_examiner import clamp_band, require_numeric_bands
from app.config import settings
from app.llm.client import get_llm_client
from app.llm.prompts import SPEAKING_EXAMINER_SYSTEM
from app.rag.retriever import retrieve_context

CRITERION_KEYS = (
    "fluency_coherence",
    "lexical_resource",
    "grammatical_range_accuracy",
)
SCORED_FIELDS = ("band_score",) + tuple(f"{k}_score" for k in CRITERION_KEYS)
# pronunciation is legitimately null for transcript-only submissions; validated separately
BAND_FIELDS = SCORED_FIELDS + ("pronunciation_score",)


async def evaluate(part: str, question: str, transcript: str) -> dict:
    context = retrieve_context(f"IELTS speaking {part} band descriptors")
    system = SPEAKING_EXAMINER_SYSTEM.format(
        context=context or "No reference material retrieved."
    )
    user_msg = (
        f"Speaking part: {part}\n"
        f"Examiner question:\n{question}\n\n"
        f"Candidate transcript (no audio features available):\n{transcript}"
    )
    result = await get_llm_client().complete_json(
        system,
        [{"role": "user", "content": user_msg}],
        required_keys=SCORED_FIELDS + ("feedback",),
        validate=require_numeric_bands(SCORED_FIELDS),
    )
    for field in BAND_FIELDS:
        if field in result and result[field] is not None:
            result[field] = clamp_band(result[field])
    for key in (*CRITERION_KEYS, "pronunciation"):
        result[key] = result.pop(f"{key}_score", None)
    return result


_whisper_model = None


def _get_whisper():
    """Lazily load and cache the Whisper model (Large-v3 per the system design).

    Loading the model is expensive, so it is created once and reused across
    requests rather than re-instantiated on every transcription.
    """
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel

        _whisper_model = WhisperModel(
            settings.whisper_model,
            device=settings.whisper_device,
            compute_type=settings.whisper_compute_type,
        )
    return _whisper_model


def transcribe(audio_path: str) -> str:
    try:
        model = _get_whisper()
    except ImportError:
        raise HTTPException(
            status_code=400,
            detail="install faster-whisper or provide a transcript",
        )
    segments, _info = model.transcribe(audio_path)
    return " ".join(seg.text.strip() for seg in segments).strip()
