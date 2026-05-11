calendar_manager.py : Couche métier rdv.

CalendarManager est une couche au-dessus de CalendarService :
- CalendarService : accès brut au calendrier (Google)
- CalendarManager : logique métier (vérifier conflits avant de créer, etc.)

CalendarManager A un CalendarService.

import logging
from datetime import datetime, timedelta
from typing import List, Optional

from app.core.agent.calendar_service import CalendarService
from app.core.agent.models import Appointment, AppointmentResult, CalendarEvent, TimeSlot
from app.core.agent.types import Status

logger = logging.getLogger(__name__)


class CalendarManager:
    """
    Gère les rendez-vous médicaux avec validation métier.
    possède un CalendarService (pas d'héritage).
    """

    def __init__(self):
        self.calendar_service = CalendarService()

    def createAppointment(self, appointment: Appointment) -> AppointmentResult:
        """
        Crée un RDV après vérification des conflits.
        Retourne AppointmentResult avec success=False si conflit détecté.
        """
        if self.checkConflicts(appointment):
            return AppointmentResult(
                success=False,
                appointment_id="",
                message=f"Conflit : {appointment.doctor_id} n'est pas disponible à {appointment.start_time.strftime('%H:%M')}",
                status=Status.FAILED,
            )

        event_data = {
            "title":       appointment.title,
            "doctor_name": appointment.doctor_id,
            "start":       appointment.start_time,
            "end":         appointment.end_time,
            "description": appointment.description,
        }

        event = self.calendar_service.create_event(event_data)
        logger.info(f"[CalendarManager] RDV créé : {event.id}")

        return AppointmentResult(
            success=True,
            appointment_id=event.id,
            message=f"RDV créé : {appointment.title} le {appointment.start_time.strftime('%d/%m à %H:%M')}",
            status=Status.COMPLETED,
        )

    def checkConflicts(self, appointment: Appointment) -> bool:
        """Retourne True si le créneau est déjà occupé."""
        return self.calendar_service.check_conflicts(
            appointment.doctor_id,
            appointment.start_time,
            appointment.end_time,
        )

    def findAvailableSlots(self, doctor_name: str, start: datetime, duration: int = 30) -> List[TimeSlot]:
        """Retourne les créneaux libres du médecin."""
        return self.calendar_service.find_free_slots(doctor_name, start, duration)

    def getDoctorEvents(self, doctor_name: str, start: datetime, end: Optional[datetime] = None) -> List[CalendarEvent]:
        """Retourne tous les RDV d'un médecin sur la période."""
        if end is None:
            end = start.replace(hour=18, minute=0)
        return self.calendar_service.get_events(doctor_name, start, end)

    def deleteAppointment(self, event_id: str) -> AppointmentResult:
        """Supprime un RDV par son ID."""
        ok = self.calendar_service.delete_event(event_id)
        if ok:
            return AppointmentResult(success=True, appointment_id=event_id, message="RDV supprimé.", status=Status.COMPLETED)
        return AppointmentResult(success=False, appointment_id=event_id, message="RDV introuvable.", status=Status.FAILED)