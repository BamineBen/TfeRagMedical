"""
tools/calendar_write.py : Écriture dans le calendrier.

requires_confirmation = True : tout changement nécessite la validation du médecin.
L'agent envoie CONFIRMATION_REQUEST et attend POST /agent/confirm.
"""
import time
import logging
from datetime import datetime

from app.core.agent.tools.base import AgentTool
from app.core.agent.models import ToolResult
from app.core.agent.calendar_service import CalendarService

logger = logging.getLogger(__name__)

class CalendarWriteTool(AgentTool):
    """Crée, modifie ou supprime un RDV — nécessite confirmation."""

    name                  = "calendar_write"
    description           = "Crée, modifie ou supprime un rendez-vous dans le calendrier"
    requires_confirmation = True

    def validate_params(self, params: dict) -> bool:
        return "action" in params and params["action"] in ("create", "update", "delete")

    def execute(self, params: dict) -> ToolResult:
        """
        Paramètres : {"action": "create"|"update"|"delete",
                      "event": {...}, "event_id": str}
        """
        t0     = time.time()
        action = params["action"]
        svc    = CalendarService(user_id=params.get("user_id"))

        try:
            if action == "create":
                event_data = params.get("event", {})
                event = svc.create_event(event_data)
                return ToolResult.ok(
                    data={
                        "created":       True,
                        "event_id":      event.id,
                        "title":         event.title,
                        "start":         event.start.isoformat() if event.start else "",
                        "end":           event.end.isoformat()   if event.end   else "",
                        "doctor_name":   event.doctor_name,
                        "patient_name":  event.patient_name,
                        "calendar_link": event.calendar_link,
                    },
                    execution_time_ms=int((time.time() - t0) * 1000),
                )

            elif action == "update":
                event_id   = params.get("event_id", "")
                event_data = params.get("event", {})
                event = svc.update_event(event_id, event_data)
                return ToolResult.ok(
                    data={
                        "updated":      True,
                        "event_id":     event.id,
                        "title":        event.title,
                        "calendar_link": event.calendar_link,
                    },
                    execution_time_ms=int((time.time() - t0) * 1000),
                )

            elif action == "delete":
                event_id = params.get("event_id", "")
                deleted  = svc.delete_event(event_id)
                return ToolResult.ok(
                    data={"deleted": deleted, "event_id": event_id},
                    execution_time_ms=int((time.time() - t0) * 1000),
                )

            return ToolResult.fail(f"Action inconnue : {action}")

        except Exception as exc:
            logger.error("[CalendarWriteTool] %s", exc)
            return ToolResult.fail(str(exc), int((time.time() - t0) * 1000))
