from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from callforge.ingest.documents import ingest_file_for_agent, remove_document_file

router = APIRouter(tags=["documents"])
logger = logging.getLogger(__name__)

ALLOWED_SUFFIXES = {".pdf", ".docx", ".xlsx", ".txt", ".md"}


@router.get("/agents/{agent_id}/documents")
async def list_documents(agent_id: str, request: Request):
    if not request.app.state.store.get_agent(agent_id):
        raise HTTPException(404, "Agent not found")
    return [d.to_dict() for d in request.app.state.store.list_documents(agent_id)]


@router.post("/agents/{agent_id}/documents")
async def upload_document(agent_id: str, request: Request, file: UploadFile = File(...)):
    store = request.app.state.store
    if not store.get_agent(agent_id):
        raise HTTPException(404, "Agent not found")
    if not file.filename:
        raise HTTPException(400, "Missing filename")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(400, f"Unsupported type {suffix}. Allowed: {sorted(ALLOWED_SUFFIXES)}")

    upload_dir: Path = request.app.state.upload_root / agent_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"{uuid.uuid4().hex[:8]}_{Path(file.filename).name}"
    dest = upload_dir / safe_name
    content = await file.read()
    if len(content) > 25 * 1024 * 1024:
        raise HTTPException(400, "File too large (max 25MB)")
    dest.write_bytes(content)

    doc = store.add_document(agent_id, file.filename, str(dest))

    async def _index() -> None:
        try:
            await asyncio.to_thread(
                ingest_file_for_agent,
                store,
                agent_id,
                doc.id,
                dest,
                request.app.state.ollama_base_url,
            )
        except Exception:
            logger.exception("Background ingest failed for %s", file.filename)

    asyncio.create_task(_index())
    return doc.to_dict()


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str, request: Request):
    store = request.app.state.store
    doc = store.delete_document(doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    remove_document_file(doc.stored_path)
    return {"ok": True}
