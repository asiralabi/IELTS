import importlib
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from openai import APIStatusError

from app.config import settings
from app.database import init_db

logger = logging.getLogger(__name__)

ROUTER_MODULES = [
    "app.routers.auth",
    "app.routers.chat",
    "app.routers.questions",
    "app.routers.writing",
    "app.routers.speaking",
    "app.routers.reading",
    "app.routers.listening",
    "app.routers.mock_exam",
    "app.routers.progress",
    "app.routers.knowledge",
    "app.routers.cambridge",
    "app.routers.feedback",
]


def check_jwt_secret() -> None:
    """Refuse to serve real users with the placeholder signing key.

    The placeholder ships in `.env.example` and in git history, so a
    deployment that kept it will accept a token anyone can forge. A debug run
    only warns — a developer who has not written a `.env` yet should still get
    a server rather than a traceback.
    """
    if not settings.jwt_secret_is_default:
        return
    if settings.debug:
        logger.warning(
            "JWT_SECRET is the placeholder from .env.example — tokens signed "
            "with it can be forged by anyone. Set it before this serves real "
            "users."
        )
        return
    raise RuntimeError(
        "JWT_SECRET is still the placeholder from .env.example, so any login "
        "token can be forged. Set JWT_SECRET in backend/.env to a random "
        'value (python -c "import secrets; print(secrets.token_urlsafe(48))") '
        "or set DEBUG=true for a local run."
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    check_jwt_secret()
    settings.ensure_data_dirs()
    init_db()
    try:
        from app.rag.ingest import seed_knowledge_base

        seed_knowledge_base()
    except Exception as exc:
        logger.warning("Knowledge base seeding skipped: %s", exc)

    # Pre-load fastembed model + prime the embedding cache so the first
    # user query doesn't pay the ~120ms cold-load penalty.
    try:
        from app.rag.store import warm_embedder

        warm_embedder()
    except Exception as exc:
        logger.warning("Embedder warm-up skipped: %s", exc)

    from app.services.practice_pool import get_warmer

    # See `practice_pool_enabled`: a thread per process is a container idea, and
    # a platform that runs many instances of the app would start one in each.
    warmer = get_warmer() if settings.practice_pool_enabled else None
    if warmer is not None:
        warmer.start()
    else:
        logger.info("practice pool warmer disabled (practice_pool_enabled=false)")
    try:
        yield
    finally:
        if warmer is not None:
            await warmer.stop()
        # Close the singleton httpx client that Ollama shares across requests.
        try:
            from app.llm.client import shutdown_llm_http_client

            await shutdown_llm_http_client()
        except Exception as exc:
            logger.warning("LLM http client shutdown skipped: %s", exc)


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(APIStatusError)
    async def upstream_llm_error(_request: Request, exc: APIStatusError) -> JSONResponse:
        """Say what actually happened when the hosted model turns us away.

        Every router catches `ValueError` — a reply the validators rejected —
        and nothing catches the provider refusing to answer at all. So a 429
        reached the student as a bare 500 and the page said "Internal Server
        Error", which is both untrue and unactionable: nothing is broken, the
        quota is spent, and the right advice is to wait a moment.

        🔬 Live 2026-09-01: `POST /writing/full-test/submit` raised
        `openai.RateLimitError` straight through `submit_full_test` after three
        figure sweeps had drained the free tier. One handler here rather than a
        clause in each router — the whole app talks to one model, and every
        module can be told no.
        """
        busy = exc.status_code in (429, 503)
        logger.warning("hosted model refused: %s %s", exc.status_code, exc)
        return JSONResponse(
            status_code=503 if busy else 502,
            content={"detail": (
                "The examiner is busy right now — wait a moment and try again."
                if busy else
                "The examiner is unavailable right now. Please try again."
            )},
        )

    settings.ensure_data_dirs()
    app.mount("/assets", StaticFiles(directory=settings.assets_dir), name="assets")

    for module_name in ROUTER_MODULES:
        try:
            module = importlib.import_module(module_name)
            app.include_router(module.router)
        except ImportError as exc:
            logger.warning("Router %s not available: %s", module_name, exc)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "app": settings.app_name}

    return app


app = create_app()
