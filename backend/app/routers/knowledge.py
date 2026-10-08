import logging
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.auth import get_current_user
from app.config import settings
from app.security import MAX_UPLOAD_BYTES, read_upload_capped, require_admin
from app.models import User
from app.rag.ingest import ingest_pdf, seed_knowledge_base
from app.rag.store import get_vector_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


# Both write routes change the knowledge base that grounds EVERY student's
# marking, so they are for the team only. Before this, any registered user
# could inject text into everyone's marking, or wipe the index outright.
@router.post("/ingest", dependencies=[Depends(require_admin)])
async def ingest(
    file: UploadFile = File(...), user: User = Depends(get_current_user)
) -> dict:
    filename = file.filename or ""
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    settings.ensure_data_dirs()
    data = await read_upload_capped(file, MAX_UPLOAD_BYTES)
    if not data.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="That file is not a PDF")
    # Only the uuid and a sanitised stem reach the filesystem.
    safe_stem = "".join(c for c in Path(filename).stem if c.isalnum() or c in "-_ ")[:80] or "upload"
    dest = Path(settings.upload_dir) / f"{uuid4().hex}_{safe_stem}.pdf"
    dest.write_bytes(data)
    try:
        chunks = ingest_pdf(str(dest), source_name=safe_stem)
    except Exception as exc:
        logger.exception("PDF ingestion failed")
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="PDF ingestion failed") from exc
    return {"chunks_indexed": chunks}


@router.post("/reindex", dependencies=[Depends(require_admin)])
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
