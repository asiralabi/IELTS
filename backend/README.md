# AI IELTS Instructor & Examiner — Backend

A FastAPI backend that acts as a personal IELTS instructor and examiner. It combines RAG (official band descriptors, exam-format notes and strategy guides in an embedded vector store) with a set of specialised LLM agents: an instructor chat coach, exam-authentic question generators, strict Writing/Speaking examiners, Reading/Listening trainers with clerical answer checking, a weakness analyst, a study-plan coach, and a full mock-exam orchestrator.

## Architecture

| Layer | Technology |
|---|---|
| API | FastAPI + Uvicorn |
| Database | SQLite (default) or PostgreSQL via SQLAlchemy 2.0 — set `DATABASE_URL` |
| Auth | JWT access + refresh tokens (PyJWT), bcrypt password hashing |
| Vector store | Qdrant (embedded on-disk by default, or remote via `QDRANT_URL`) |
| Embeddings | FastEmbed (`BAAI/bge-small-en-v1.5`, local, no API needed) |
| LLM | Provider-agnostic: **Ollama `qwen3:4b` (default, fully local)**, Anthropic, or OpenAI-compatible |
| Agents | Instructor, question generator, writing/speaking examiners, reading/listening trainers, answer checker, feedback coach, weakness analyst, mock-exam orchestrator (`app/agents/`) |
| Knowledge base | Seed markdown (band descriptors, strategies) auto-ingested on first startup; Cambridge PDFs ingestible at runtime |

## Setup

Requires Python 3.11+.

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env         # Windows  (Linux/macOS: cp .env.example .env)
```

For the default local LLM, install [Ollama](https://ollama.com) and pull the model:

```bash
ollama pull qwen3:4b
```

## Run

```bash
uvicorn app.main:app --reload
```

Interactive API docs: http://127.0.0.1:8000/docs — health check at `/health`.

On first startup the app creates the SQLite database and seeds the vector store from `app/rag/seed/*.md` (band descriptors, exam format, strategies). The first seeding downloads the FastEmbed embedding model (~100 MB) once.

## API overview

All endpoints except `/auth/*` and `/health` require `Authorization: Bearer <access_token>`.

| Endpoint | Method | Purpose |
|---|---|---|
| `/auth/register`, `/auth/login`, `/auth/refresh`, `/auth/me` | POST/GET | Account + JWT token pair |
| `/chat` | POST | Talk to the RAG-grounded instructor (creates/continues a session) |
| `/chat/sessions`, `/chat/sessions/{id}` | GET | List sessions / read a session's messages |
| `/questions/generate` | POST | Generate an exam-authentic question for any section |
| `/writing/submit`, `/writing/history` | POST/GET | Essay marked on the four official criteria with band scores, errors, rewrites |
| `/speaking/submit`, `/speaking/history` | POST/GET | Speaking answer (transcript or audio) marked on the official criteria |
| `/reading/practice`, `/reading/check` | POST | Full reading practice set (answer key hidden) + clerical marking with explanations |
| `/listening/practice`, `/listening/check` | POST | Same for listening (script-based; bring your own TTS/reader) |
| `/mock-exam/generate`, `/mock-exam/{id}/submit`, `/mock-exam/{id}` | POST/GET | Full four-skill mock exam, scored with an overall band |
| `/progress`, `/progress/weaknesses`, `/progress/study-plan` | GET | Band trends & counts, evidence-based weakness profile, 7-day study plan |
| `/knowledge/ingest`, `/knowledge/reindex`, `/knowledge/status` | POST/GET | Manage the RAG knowledge base |

## Ingesting Cambridge practice books (PDF)

Upload any IELTS PDF (e.g. Cambridge IELTS 15–19) to ground the agents in real material:

```bash
curl -X POST http://127.0.0.1:8000/knowledge/ingest \
  -H "Authorization: Bearer <token>" \
  -F "file=@Cambridge-IELTS-18.pdf"
```

Text is extracted (PyMuPDF), cleaned (headers/footers/page numbers stripped), chunked with overlap, embedded and indexed. `/knowledge/reindex` rebuilds the whole store from seeds + previously uploaded PDFs; `/knowledge/status` reports the document count.

## Switching LLM provider

Edit `.env`:

```env
LLM_PROVIDER=anthropic          # ollama | anthropic | openai
ANTHROPIC_API_KEY=sk-ant-...
# or
LLM_PROVIDER=openai             # also works with any OpenAI-compatible endpoint
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
```

No code changes needed — `app/llm/client.py` selects the client at first use.

## Tests

```bash
pytest
```

The suite is fully offline: the LLM client and vector store are replaced with mocks (see `tests/conftest.py`), and a throwaway SQLite database is used. No Ollama, no network, no embedding model download.

## Notes

- **Local inference speed**: on CPU-only machines `qwen3:4b` generates a few tokens per second, so examiner calls (essay marking, mock-exam scoring) can take several minutes. Requests time out after `LLM_TIMEOUT` seconds (default 600); raise it in `.env` if needed, or switch to a hosted provider for interactive latency.
- **Malformed LLM output**: every structured call validates that the returned JSON contains the expected schema keys and retries once with a corrective message; if the model still fails, the API responds `502` rather than storing a bad result.
- **Speaking audio uploads** require `pip install faster-whisper` for local transcription. Without it, send the `transcript` form field instead of an audio file.
- **Roadmap alignment**: examiners are provider-agnostic and injected via `set_llm_client()`, so fine-tuned dedicated scoring models can replace the generic LLM examiners later without touching routers or agents.
