tools/rag_query.py : Outil de recherche dans les dossiers patients (RAG).

Utilise le moteur RAG existant (FAISS + BM25) pour chercher des informations
dans les dossiers médicaux indexés.

import time
import logging
from app.core.agent.tools.base import AgentTool
from app.core.agent.models import ToolResult
from app.core.rag_state import rag_state
from app.core import rag_engine

logger = logging.getLogger(__name__)


class RAGQueryTool(AgentTool):
    name        = "rag_query"
    description = "Recherche des informations médicales dans les dossiers patients"
    requires_confirmation = False

    def validate_params(self, params: dict) -> bool:
        return "query" in params

    def execute(self, params: dict) -> ToolResult:
        Interroge le moteur RAG avec la question du médecin.
        Paramètres attendus : {"query": str, "source_filter": str|None}
        
        start = time.time()
        query         = params.get("query", "")
        source_filter = params.get("source_filter")

        index, chunks = rag_state.get()

        if index is None or not chunks:
            return ToolResult.fail("Aucun document indexé dans la base RAG.")

        try:
            prompt, hits, citation_map = rag_engine.build_rag_prompt(
                query=query,
                index=index,
                chunks_mapping=chunks,
                source_filter=source_filter,
                local_mode=False,
            )
            elapsed = int((time.time() - start) * 1000)
            logger.info(f"[RAGQueryTool] {len(hits)} hits en {elapsed}ms")

            return ToolResult.ok(
                data={
                    "answer":       prompt[:2000],  # Limiter la taille
                    "sources":      [h["source"] for h in hits[:5]],
                    "chunk_count":  len(hits),
                    "citation_map": citation_map[:5],
                },
                elapsed_ms=elapsed,
            )
        except Exception as e:
            logger.error(f"[RAGQueryTool] Erreur : {e}")
            return ToolResult.fail(str(e))