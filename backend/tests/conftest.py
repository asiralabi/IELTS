"""Shared test fixtures.

IMPORTANT ordering note: ``app.config.settings`` and ``app.database.engine``
are module-level singletons.  pytest imports this conftest before any test
module imports ``app.*``, so we mutate ``settings`` here at module import
time — BEFORE ``app.database`` builds its engine — pointing everything at a
throwaway temp directory.  All tests are fully offline: the LLM client and
the Qdrant/fastembed vector store are replaced with in-process mocks.
"""

import tempfile
from pathlib import Path
from typing import Any

import pytest

# --- 1. Redirect all storage to a temp dir BEFORE app.database is imported ---

_TMP = Path(tempfile.mkdtemp(prefix="ielts_tests_"))

from app.config import settings  # noqa: E402

settings.database_url = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
settings.data_dir = str(_TMP / "data")
settings.upload_dir = str(_TMP / "data" / "uploads")
settings.qdrant_path = str(_TMP / "data" / "qdrant")
settings.qdrant_url = ""
settings.jwt_secret = "test-secret-key-for-the-ielts-test-suite-only"

from app.database import init_db  # noqa: E402  (engine now bound to temp sqlite)
from app.llm.client import LLMClient, set_llm_client  # noqa: E402
from app.rag.store import set_vector_store  # noqa: E402

# --- 2. Offline mocks -------------------------------------------------------

CANNED_CHAT_REPLY = (
    "Under Lexical Resource at Band 7, you need flexibility and precision. "
    "Can you rewrite your sentence using a concession clause?"
)

WRITING_RESULT = {
    "band_score": 6.5,
    "task_response_score": 6.5,
    "coherence_cohesion_score": 6.0,
    "lexical_resource_score": 6.5,
    "grammatical_range_accuracy_score": 6.5,
    "strengths": ["clear position", "logical paragraphing"],
    "weaknesses": ["limited range of complex structures"],
    "errors": [
        {
            "excerpt": "peoples are",
            "issue": "subject-verb agreement",
            "correction": "people are",
        }
    ],
    "improved_sentences": [
        {"original": "It is good.", "improved": "It is undeniably beneficial."}
    ],
    "feedback": "A solid Band 6.5 attempt; work on grammatical range.",
    "estimated_final_band": 6.5,
}

SPEAKING_RESULT = {
    "band_score": 6.0,
    "fluency_coherence": 6.0,
    "lexical_resource": 6.0,
    "grammatical_range_accuracy": 6.0,
    "pronunciation": None,
    "strengths": ["willing to extend answers"],
    "weaknesses": ["frequent fillers"],
    "feedback": "Reduce hesitation by practising 60-second monologues.",
}

QUESTION_PAYLOAD = {
    "section": "reading",
    "question_type": "True/False/Not Given",
    "difficulty": "Band 6",
    "question": "The statement paraphrases the passage.",
    "passage": "A short academic passage about renewable energy.",
    "audio_script": None,
    "answers": ["TRUE"],
    "explanation": "Stated in paragraph B.",
}

READING_PRACTICE = {
    "title": "The History of Tea",
    "passage": "Tea was first cultivated in China. " * 30,
    "questions": [
        {
            "number": 1,
            "type": "True/False/Not Given",
            "question": "Tea originated in China.",
            "options": None,
        },
        {
            "number": 2,
            "type": "True/False/Not Given",
            "question": "Tea was first exported to Portugal.",
            "options": None,
        },
    ],
    "answer_key": {"1": "TRUE", "2": "NOT GIVEN"},
}

LISTENING_PRACTICE = {
    "title": "Booking a City Tour",
    "audio_script": "AGENT: Good morning, City Tours. STUDENT: Hello, I would like to book. " * 15,
    "questions": [
        {
            "number": 1,
            "type": "form completion",
            "question": "Tour starts at ... (ONE WORD AND/OR A NUMBER)",
            "options": None,
        },
        {
            "number": 2,
            "type": "form completion",
            "question": "Surname: ... (ONE WORD)",
            "options": None,
        },
    ],
    "answer_key": {"1": "6:00", "2": "BRAITHWAITE"},
}

CHECK_RESULT = {
    "score": 1,
    "total": 2,
    "band_estimate": 5.5,
    "results": [
        {
            "number": 1,
            "correct": True,
            "student_answer": "TRUE",
            "correct_answer": "TRUE",
            "explanation": "Stated in the first sentence.",
        },
        {
            "number": 2,
            "correct": False,
            "student_answer": "FALSE",
            "correct_answer": "NOT GIVEN",
            "explanation": "The passage never mentions Portugal.",
        },
    ],
}

FEEDBACK_PLAN = {
    "summary": "Currently around Band 6; grammar is the main bottleneck.",
    "priorities": ["grammatical range", "TFNG paraphrase recognition"],
    "study_plan": [
        {"day": 1, "focus": "grammar", "tasks": ["Review complex sentences"]}
    ],
    "resources": ["Cambridge IELTS 18"],
}

WEAKNESS_PROFILE = {
    "grammar": True,
    "vocabulary": False,
    "coherence": False,
    "pronunciation": False,
    "fluency": False,
    "task_response": False,
    "reading_comprehension": False,
    "listening_accuracy": False,
    "details": {
        "grammar": "agreement errors recur across essays",
        "vocabulary": "adequate range shown",
        "coherence": "clear progression in essays",
        "pronunciation": "insufficient data",
        "fluency": "insufficient data",
        "task_response": "positions fully developed",
        "reading_comprehension": "insufficient data",
        "listening_accuracy": "insufficient data",
    },
}


class MockLLMClient(LLMClient):
    """Offline stand-in: dispatches on distinctive system-prompt substrings."""

    async def complete(
        self,
        system: str,
        messages: list[dict],
        json_mode: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        return CANNED_CHAT_REPLY

    async def complete_json(
        self, system: str, messages: list[dict], **kw: Any
    ) -> dict:
        if "Writing examiner" in system:
            return dict(WRITING_RESULT)
        if "Speaking examiner" in system:
            return dict(SPEAKING_RESULT)
        if "question writer" in system:
            payload = dict(QUESTION_PAYLOAD)
            user_msg = messages[-1]["content"] if messages else ""
            for section in ("reading", "listening", "writing", "speaking"):
                if f"IELTS {section} question" in user_msg:
                    payload["section"] = section
            # Post-generation validators in question_generator.py require
            # specific shapes for certain (section, question_type) pairs.
            # The mock returns whichever shape the validator will accept.
            lower = user_msg.lower()
            if "part 2" in lower or "cue card" in lower:
                payload["question"] = {
                    "topic": "Describe a place you visited that made a strong impression on you.",
                    "bullets": [
                        "where it was",
                        "when you went there",
                        "what you did there",
                    ],
                    "closing": "and explain why it made such a strong impression on you.",
                }
            elif "part 1" in lower and ("across" in lower or "topics" in lower):
                payload["question"] = [
                    {
                        "topic": "Home",
                        "questions": [
                            "Where do you live?",
                            "Do you like your home?",
                            "What is your favourite room?",
                            "Would you like to move?",
                        ],
                    },
                    {
                        "topic": "Studies",
                        "questions": [
                            "What are you studying?",
                            "Do you enjoy it?",
                            "What is your favourite subject?",
                            "What do you plan to do next?",
                        ],
                    },
                    {
                        "topic": "Hobbies",
                        "questions": [
                            "What do you do in your free time?",
                            "How often do you do it?",
                            "When did you start?",
                            "Would you recommend it to others?",
                        ],
                    },
                ]
            if payload["section"] == "writing" and (
                "task 1" in lower or "task1" in lower
            ):
                payload["visual"] = {
                    "kind": "chart",
                    "chart_type": "bar",
                    "title": "Test chart",
                    "x_label": "Year",
                    "y_label": "Value",
                    "series": [
                        {"name": "A", "data": [["2020", 10], ["2021", 20]]}
                    ],
                }
            if payload["section"] == "writing" and (
                "task 2" in lower or "task2" in lower
            ):
                payload["task2_type"] = "opinion"
            return payload
        if "Reading test writer" in system:
            return dict(READING_PRACTICE)
        if "Listening test writer" in system:
            return dict(LISTENING_PRACTICE)
        if "marking assistant" in system:
            return dict(CHECK_RESULT)
        if "study coach" in system:
            return dict(FEEDBACK_PLAN)
        if "diagnostic analyst" in system:
            return dict(WEAKNESS_PROFILE)
        raise AssertionError(f"MockLLMClient: unrecognised system prompt: {system[:80]!r}")


class MockVectorStore:
    """Offline stand-in for app.rag.store.VectorStore (no qdrant, no fastembed)."""

    def search(
        self, query: str, top_k: int | None = None, source: str | None = None
    ) -> list[dict]:
        return [{"text": "band descriptor snippet", "source": "seed", "score": 0.9}]

    def index_chunks(self, chunks: list[dict]) -> int:
        return len(chunks)

    def count(self) -> int:
        return 1

    def clear(self) -> None:
        pass

    def ensure_collection(self) -> None:
        pass


# --- 3. Install mocks and create schema before the app boots ----------------

set_llm_client(MockLLMClient())
set_vector_store(MockVectorStore())
init_db()


# --- 4. Fixtures -------------------------------------------------------------


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    # Context manager so lifespan runs (init_db + guarded seed against the mock store).
    with TestClient(app) as c:
        yield c


def _register_and_login(client, email: str, password: str = "password123") -> dict:
    resp = client.post(
        "/auth/register",
        json={"email": email, "password": password, "full_name": "Test User", "target_band": 7.0},
    )
    assert resp.status_code in (200, 201), resp.text
    resp = client.post("/auth/login", data={"username": email, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture(scope="session")
def auth_headers(client) -> dict:
    """Headers for the default shared test user."""
    return _register_and_login(client, "tester@example.com")


@pytest.fixture()
def make_user(client):
    """Factory: register+login a fresh user, return its auth headers."""

    counter = {"n": 0}

    def _make(prefix: str = "user") -> dict:
        counter["n"] += 1
        import uuid

        email = f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"
        return _register_and_login(client, email)

    return _make
