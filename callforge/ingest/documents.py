"""Per-agent document ingest into isolated Chroma collections."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from callforge.store.db import PlatformStore
from services.rag_service import RagService

logger = logging.getLogger(__name__)


def collection_name_for_agent(agent_id: str) -> str:
    return f"agent_{agent_id.replace('-', '')[:16]}"


def ingest_file_for_agent(
    store: PlatformStore,
    agent_id: str,
    doc_id: str,
    filepath: Path,
    ollama_base_url: str,
) -> int:
    """Index one file into the agent's Chroma collection."""
    from langchain_community.document_loaders import Docx2txtLoader, PyPDFLoader
    from langchain_core.documents import Document
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    from ingest_data import _load_timetable_xlsx, _load_xlsx_as_row_documents

    rag = RagService(
        ollama_base_url=ollama_base_url,
        collection_name=collection_name_for_agent(agent_id),
    )
    filename = filepath.name
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)

    try:
        lower = filename.lower()
        if lower.endswith(".pdf"):
            docs = PyPDFLoader(str(filepath)).load()
            chunks = text_splitter.split_documents(docs)
        elif lower.endswith(".docx"):
            docs = Docx2txtLoader(str(filepath)).load()
            chunks = text_splitter.split_documents(docs)
        elif lower.endswith(".xlsx"):
            chunks = _load_timetable_xlsx(str(filepath), filename)
            if chunks is None:
                chunks = _load_xlsx_as_row_documents(str(filepath), filename)
        elif lower.endswith(".txt") or lower.endswith(".md"):
            text = filepath.read_text(encoding="utf-8", errors="ignore")
            chunks = text_splitter.split_documents(
                [Document(page_content=text, metadata={"source": filename})]
            )
        else:
            raise ValueError(f"Unsupported file type: {filename}")

        if not chunks:
            store.update_document(doc_id, status="failed", error="No extractable text", chunk_count=0)
            return 0

        rag.vector_store.add_documents(chunks)
        store.update_document(doc_id, status="indexed", chunk_count=len(chunks), error="")
        logger.info("Indexed %d chunks for agent %s from %s", len(chunks), agent_id, filename)
        return len(chunks)
    except Exception as exc:
        logger.exception("Ingest failed for %s", filename)
        store.update_document(doc_id, status="failed", error=str(exc)[:500], chunk_count=0)
        raise


def remove_document_file(stored_path: str) -> None:
    path = Path(stored_path)
    if path.exists():
        path.unlink(missing_ok=True)
    parent = path.parent
    if parent.exists() and parent.is_dir() and not any(parent.iterdir()):
        shutil.rmtree(parent, ignore_errors=True)
