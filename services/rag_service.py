
import logging
from typing import Optional

from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings

logger = logging.getLogger(__name__)


class RagService:
    def __init__(
        self,
        ollama_base_url: str = "http://localhost:11434",
        relevance_threshold: float = 0.5,
        collection_name: str = "company_knowledge",
        persist_directory: str = "./chroma_data",
    ):
        # We use a fast, lightweight embedding model like nomic-embed-text
        # (Make sure to run: `ollama run nomic-embed-text` to download it)
        self.collection_name = collection_name
        self.embeddings = OllamaEmbeddings(
            base_url=ollama_base_url,
            model="nomic-embed-text"
        )
        # Initialize local ChromaDB in the ./chroma_data directory.
        # collection_metadata specifies cosine distance so the
        # relevance-score normalization used in retrieve_context() is
        # mathematically valid -- see the IMPORTANT note in the module
        # docstring: this only takes effect for a freshly created
        # collection, not an existing persisted one.
        # Per-agent isolation: pass a unique collection_name (e.g. agent_<id>).
        self.vector_store = Chroma(
            collection_name=collection_name,
            embedding_function=self.embeddings,
            persist_directory=persist_directory,
            collection_metadata={"hnsw:space": "cosine"},
        )
        self.relevance_threshold = relevance_threshold

    def retrieve_context(self, query: str, top_k: int = 1) -> str:
        """
        Searches the database for the most relevant chunk of text,
        keeping only chunks that clear `relevance_threshold`. Returns ""
        when nothing clears the bar. Trims to max ~200 characters to keep
        LLM prompt evaluation ultra-fast on CPU.
        """
        # Fast exit: if collection is empty, bypass embedding computation completely (0ms vs 800ms)
        try:
            if self.vector_store._collection.count() == 0:
                return ""
        except Exception:
            pass

        scored_docs = self.vector_store.similarity_search_with_relevance_scores(query, k=top_k)

        # Defensive check: if scores are wildly outside [0,1], the
        # collection's distance metric doesn't match what the relevance
        # normalization expects (see module docstring) -- every query
        # would otherwise silently return no context forever, with no
        # obvious signal why. Surface it loudly instead of guessing.
        if any(score < -0.5 or score > 1.5 for _, score in scored_docs):
            logger.error(
                "RAG relevance scores out of expected [0,1] range (got %s) -- "
                "the Chroma collection likely wasn't created with cosine distance. "
                "Delete ./chroma_data and re-run ingestion so it's rebuilt with "
                "collection_metadata={'hnsw:space': 'cosine'}. Until then, retrieval "
                "is effectively disabled (every result will fail the threshold check).",
                [round(score, 2) for _, score in scored_docs],
            )

        if logger.isEnabledFor(logging.DEBUG):
            for doc, score in scored_docs:
                logger.debug(
                    "RAG candidate (score=%.3f, %s threshold): %.80s",
                    score,
                    "PASSED" if score >= self.relevance_threshold else "dropped",
                    doc.page_content.replace("\n", " "),
                )

        kept = [doc for doc, score in scored_docs if score >= self.relevance_threshold]
        if not kept:
            return ""

        # Limit to the single best concise excerpt (max ~200 chars) for fast telephony response
        best_text = kept[0].page_content.strip().replace("\n", " ")
        if len(best_text) > 220:
            best_text = best_text[:220].rsplit(" ", 1)[0] + "..."
        return f"- {best_text}"