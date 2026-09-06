# syntax=docker/dockerfile:1

# Oratio — AI IELTS Instructor & Examiner — backend (FastAPI).
#
# The image carries CODE ONLY. Everything the app reads or writes at runtime —
# the SQLite DB, the Qdrant store, the extracted figure assets, the TTS cache —
# lives on a mounted volume, because it is student data and a grounding corpus,
# not build output. docs/deploy.md says what that volume has to contain.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# libgomp1: OpenMP. onnxruntime (under fastembed) and ctranslate2 (under
# faster-whisper) both ship manylinux wheels that link against it without
# vendoring it, so an image without it imports fine and dies on first use.
# curl is here for the HEALTHCHECK and nothing else.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Non-root, and HOME is load-bearing: fastembed caches the embedding model and
# faster-whisper caches Whisper large-v3 (~3GB) underneath it. Unless that path
# is a volume, every container start re-downloads them.
RUN useradd --create-home --uid 1000 app \
 && mkdir -p /app/data /home/app/.cache \
 && chown -R app:app /app /home/app
USER app
ENV HOME=/home/app \
    HF_HOME=/home/app/.cache/huggingface \
    FASTEMBED_CACHE_PATH=/home/app/.cache/fastembed

EXPOSE 8000

# start-period is long on purpose: startup seeds the knowledge base and warms
# the embedder before the first request is served.
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
  CMD curl -fsS http://localhost:8000/health || exit 1

# One worker, deliberately. The warm practice pool runs a background thread per
# process, and a second copy would generate against the same SQLite file.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
