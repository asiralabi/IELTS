import logging
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.auth import get_current_user
from app.config import settings
from app.models import User
from app.rag.ingest import ingest_pdf, seed_knowledge_base
from app.rag.store import get_vector_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.post("/ingest")
async def ingest(
    file: UploadFile = File(...), user: User = Depends(get_current_user)
) -> dict:
    filename = file.filename or ""
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    settings.ensure_data_dirs()
    dest = Path(settings.upload_dir) / f"{uuid4().hex}_{Path(filename).name}"
    dest.write_bytes(await file.read())
    try:
        chunks = ingest_pdf(str(dest), source_name=Path(filename).stem)
    except Exception as exc:
        logger.exception("PDF ingestion failed")
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="PDF ingestion failed") from exc
    return {"chunks_indexed": chunks}


@router.post("/reindex")
async def reindex(user: User = Depends(get_current_user)) -> dict:
    settings.ensure_data_dirs()
    try:
        get_vector_store().clear()
        total = seed_knowledge_base()
        for pdf in sorted(Path(settings.upload_dir).glob("*.pdf")):
            total += ingest_pdf(str(pdf))
    except Exception as exc:
        logger.exception("Reindex failed")
        raise HTTPException(status_code=500, detail="Reindex failed") from exc
    return {"chunks_indexed": total}


@router.get("/status")
async def status(user: User = Depends(get_current_user)) -> dict:
    try:
        return {"documents": get_vector_store().count()}
    except Exception as exc:
        logger.exception("Vector store unavailable")
        raise HTTPException(status_code=500, detail="Vector store unavailable") from exc
