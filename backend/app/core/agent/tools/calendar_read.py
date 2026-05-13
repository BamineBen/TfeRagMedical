tools/calendar_read.py : Lecture du calendrier médecin.

Retourne les RDV existants et les créneaux libres pour un médecin/date donnés.
Aucune confirmation requise (lecture seule).

import time
import logging
from datetime import timedelta
from app.core.agent.tools.base import AgentTool
from app.core.agent.models import ToolResult
from app.core.agent.calendar_service import CalendarService

logger = logging.getLogger(__name__)


class CalendarReadTool(AgentTool):
    name        = "calendar_read"
    description = "Consulte les rendez-vous et créneaux libres d'un médecin"
    requires_confirmation = False

    def validate_params(self, params: dict) -> bool:
        return "doctor_name" in params and "start" in params

    def execute(self, params: dict) -> ToolResult:
        Paramètres : {"doctor_name": str, "start": datetime, "duration_minutes": int}
        Retourne : {"events": [...], "free_slots": [...], "doctor": str}
        
        start = time.time()
        svc          = CalendarService()
        doctor       = params["doctor_name"]
        start_dt     = params["start"]
        duration     = params.get("duration_minutes", 30)
        end_dt       = params.get("end", start_dt + timedelta(hours=9))

        try:
            events     = svc.get_events(doctor, start_dt, end_dt)
            free_slots = svc.find_free_slots(doctor, start_dt, duration)

            elapsed = int((time.time() - start) * 1000)
            return ToolResult.ok(
                data={
                    "doctor":     doctor,
                    "date":       start_dt.strftime("%d/%m/%Y"),
                    "events":     [
                        {"id": e.id, "title": e.title,
                         "start": e.start.isoformat(), "end": e.end.isoformat()}
                        for e in events
                    ],
                    "free_slots": [
                        {"start": s.start.isoformat(), "end": s.end.isoformat(),
                         "duration_minutes": s.duration_minutes}
                        for s in free_slots
                    ],
                },
                elapsed_ms=elapsed,
            )
        except Exception as e:
            logger.error(f"[CalendarReadTool] {e}")
            return ToolResult.fail(str(e))