"""
patient_summary.py — PatientSummaryTool
Section 5 : Outil de résumé complet du dossier patient

Génère un résumé structuré du dossier d'un patient via RAGQueryTool.
Paramètres attendus : { "patient_name": str, "llm_mode": str (optionnel) }
"""
import logging
import time

from app.core.agent.models import ToolResult
from app.core.agent.tools.base import AgentTool

logger = logging.getLogger(__name__)

class PatientSummaryTool(AgentTool):
    """Génère un résumé du dossier médical d'un patient via RAGQueryTool."""

    def __init__(self):
        super().__init__(
            name="patient_summary",
            description="Génère un résumé complet du dossier d'un patient",
            requires_confirmation=False,
        )
        self._rag_tool = None

    @property
    def rag_tool(self):
        if self._rag_tool is None:
            from app.core.agent.tools.rag_query import RAGQueryTool
            self._rag_tool = RAGQueryTool()
        return self._rag_tool

    def validate_params(self, params: dict) -> bool:
        return isinstance(params, dict) and "patient_name" in params

    def execute(self, params: dict) -> ToolResult:
        if not self.validate_params(params):
            return ToolResult.fail("Paramètre 'patient_name' requis")

        patient_name: str = params["patient_name"]
        llm_mode: str = params.get("llm_mode", "cloud")
        t0 = time.time()

        result = self.rag_tool.execute({
            "patient_name": patient_name,
            "query": (
                f"résumé complet antécédents traitements "
                f"consultations biologie constantes {patient_name}"
            ),
            "llm_mode": llm_mode,
        })

        elapsed = int((time.time() - t0) * 1000)

        if not result.success:
            return ToolResult.fail(result.error_message, elapsed)

        return ToolResult.ok(
            data={
                "answer":          result.data.get("answer", ""),
                "patient":         patient_name,
                "sources":         result.data.get("sources", 0),
                "sources_preview": result.data.get("sources_preview", []),
                "llm_used":        result.data.get("llm_used", ""),
                "patient_found":   result.data.get("patient_found", True),
            },
            execution_time_ms=elapsed,
        )
