"""
tools/interaction_check.py : Vérification des interactions médicamenteuses.

Appelle directement checkDrugInteractions() — pas de PatientInfo fictif.
"""
import time
import logging

from app.core.agent.tools.base import AgentTool
from app.core.agent.models import ToolResult
from app.core.agent.interaction_checker import InteractionChecker

logger = logging.getLogger(__name__)

class InteractionCheckTool(AgentTool):
    """Vérifie les interactions médicamenteuses entre une liste de médicaments."""

    name                  = "interaction_check"
    description           = "Vérifie les interactions entre médicaments"
    requires_confirmation = False

    def validate_params(self, params: dict) -> bool:
        return "medications" in params and isinstance(params["medications"], list)

    def execute(self, params: dict) -> ToolResult:
        """
        Paramètres : {"medications": ["warfarine", "aspirine"]}
        Retourne   : résultat avec severity, description, recommendations.
        """
        t0          = time.time()
        medications = params["medications"]
        checker     = InteractionChecker()
        result      = checker.checkDrugInteractions(medications)

        return ToolResult.ok(
            data={
                "has_interaction":  result.has_interaction,
                "severity":         result.severity.value if result.severity else None,
                "medications":      medications,
                "description":      result.description,
                "recommendations":  result.recommendations,
            },
            execution_time_ms=int((time.time() - t0) * 1000),
        )
