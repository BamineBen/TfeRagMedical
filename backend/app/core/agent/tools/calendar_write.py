tools/calendar_write.py : Écriture dans le calendrier.

IMPORTANT : requires_confirmation = True
Tout changement dans le calendrier nécessite la validation du médecin.
L'agent envoie un événement CONFIRMATION_REQUEST et attend le (/confirm).

import time
import logging
from app.core.agent.tools.base import AgentTool
from app.core.agent.models import Appointment, AppointmentResult, ToolResult
from app.core.agent.calendar_manager import CalendarManager
from app.core.agent.types import Status

logger = logging.getLogger(__name__)


class CalendarWriteTool(AgentTool):
    name        = "calendar_write"
    description = "Crée, modifie ou supprime un rendez-vous dans le calendrier"
    requires_confirmation = True  # Toujours confirmer avant d'écrire

    def validate_params(self, params: dict) -> bool:
        return "action" in params and params["action"] in ("create", "update", "delete")

    def execute(self, params: dict) -> ToolResult:

        Paramètres : {"action": "create"|"update"|"delete", "event": {...}}

        start  = time.time()
        action = params["action"]
        mgr    = CalendarManager()

        try:
            if action == "create":
                appt = Appointment(**params["appointment"])
                result: AppointmentResult = mgr.createAppointment(appt)

            elif action == "delete":
                result = mgr.deleteAppointment(params["event_id"])

            else:
                return ToolResult.fail(f"Action non supportée : {action}")

            elapsed = int((time.time() - start) * 1000)
            if result.success:
                return ToolResult.ok(
                    data={"action": action, "appointment_id": result.appointment_id, "message": result.message},
                    elapsed_ms=elapsed,
                )
            return ToolResult.fail(result.message)

        except Exception as e:
            logger.error(f"[CalendarWriteTool] {e}")
            return ToolResult.fail(str(e))