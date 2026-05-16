"""
tools/calendar_read.py : Lecture du planning médecin.

Retourne RDV existants + créneaux libres pour un médecin et une période.
"""
import time
import logging
from datetime import datetime, timedelta

from app.core.agent.tools.base import AgentTool
from app.core.agent.models import ToolResult
from app.core.agent.calendar_service import CalendarService

logger = logging.getLogger(__name__)

class CalendarReadTool(AgentTool):
    """Lit le planning et calcule les créneaux libres — lecture seule."""

    name                  = "calendar_read"
    description           = "Consulte les rendez-vous et créneaux libres d'un médecin"
    requires_confirmation = False

    def validate_params(self, params: dict) -> bool:
        return "doctor_name" in params and "start" in params

    def execute(self, params: dict) -> ToolResult:
        """
        Paramètres : {"doctor_name": str, "start": str|datetime,
                      "end": str|datetime, "duration_minutes": int}
        """
        t0     = time.time()
        svc    = CalendarService(user_id=params.get("user_id"))
        doctor = params["doctor_name"]

        start_dt = CalendarService._parse_dt(params["start"])
        end_dt   = (
            CalendarService._parse_dt(params["end"])
            if params.get("end")
            else start_dt + timedelta(hours=9)
        )
        duration = params.get("duration_minutes", 30)

        try:
            events = svc.get_events(doctor, start_dt, end_dt)

            # Créneaux libres calculés ici (logique appartenant à CalendarManager,
            # reproduite pour le tool qui ne passe pas par CalendarManager)
            from app.core.agent.calendar_manager import CalendarManager
            mgr        = CalendarManager(user_id=params.get("user_id"))
            free_slots = mgr.findAvailableSlots(doctor, start_dt, duration)

            return ToolResult.ok(
                data={
                    "doctor":     doctor,
                    "date":       start_dt.strftime("%d/%m/%Y"),
                    "events": [
                        {
                            "id":           e.id,
                            "title":        e.title,
                            "start":        e.start.isoformat(),
                            "end":          e.end.isoformat(),
                            "patient_name": e.patient_name,
                        }
                        for e in events
                    ],
                    "free_slots": [
                        {
                            "start":            s.start.isoformat(),
                            "end":              s.end.isoformat(),
                            "duration_minutes": s.duration_minutes,
                        }
                        for s in free_slots
                    ],
                },
                execution_time_ms=int((time.time() - t0) * 1000),
            )
        except Exception as exc:
            logger.error("[CalendarReadTool] %s", exc)
            return ToolResult.fail(str(exc), int((time.time() - t0) * 1000))
