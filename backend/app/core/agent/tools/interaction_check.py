tools/interaction_check.py : Vérification des interactions médicamenteuses.

import time
import logging
from app.core.agent.tools.base import AgentTool
from app.core.agent.models import PatientInfo, Prescription, ToolResult
from app.core.agent.interaction_checker import InteractionChecker

logger = logging.getLogger(__name__)


class InteractionCheckTool(AgentTool):
    name        = "interaction_check"
    description = "Vérifie les interactions entre médicaments et les allergies patient"
    requires_confirmation = False

    def validate_params(self, params: dict) -> bool:
        return "medications" in params and isinstance(params["medications"], list)

    def execute(self, params: dict) -> ToolResult:

        Paramètres : {"medications": ["warfarine","aspirine"], "patient_allergies": [...]}

        start   = time.time()
        checker = InteractionChecker()

        medications = params["medications"]
        allergies   = params.get("patient_allergies", [])
        patient_name = params.get("patient_name", "Patient")

        patient_info = PatientInfo(patient_id="", name=patient_name, allergies=allergies)
        prescription = Prescription(patient_id="", medications=medications)

        result = checker.validatePrescription(patient_info, prescription)

        elapsed = int((time.time() - start) * 1000)
        return ToolResult.ok(
            data={
                "has_interaction":  result.has_interaction,
                "severity":         result.severity.value if result.has_interaction else None,
                "medications":      result.medications,
                "description":      result.description,
                "recommendations":  result.recommendations,
                "allergies_found":  result.allergies,
            },
            elapsed_ms=elapsed,
        )