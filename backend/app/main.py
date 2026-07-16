import importlib
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

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
]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
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

    warmer = get_warmer()
    warmer.start()
    try:
        yield
    finally:
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
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
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
