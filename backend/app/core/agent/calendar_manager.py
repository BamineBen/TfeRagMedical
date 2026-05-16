"""
calendar_manager.py : Couche métier des rendez-vous.

CalendarManager :
  - getDoctorSchedule()  → liste des RDV d'un médecin
  - createAppointment()  → vérifie conflits puis crée
  - updateAppointment()  → modifie un RDV existant
  - deleteAppointment()  → supprime un RDV
  - checkConflicts()     → True si créneau occupé
  - findAvailableSlots() → créneaux libres
"""
import logging
from datetime import datetime
from typing import List, Optional

from app.core.agent.calendar_service import CalendarService
from app.core.agent.models import (
    Appointment, AppointmentResult, CalendarEvent, TimeSlot,
)
from app.core.agent.types import Status

logger = logging.getLogger(__name__)

class CalendarManager:
    """
    Couche métier au-dessus de CalendarService.
    Gère la logique de validation (conflits) avant toute écriture.
    """

    def __init__(self, user_id: Optional[int] = None):
        self._service = CalendarService(user_id=user_id)

    #  Lecture 

    def getDoctorSchedule(self, doctor_id: str, date: datetime) -> List[CalendarEvent]:
        """Retourne les RDV d'un médecin sur la journée (8h–18h)."""
        start = date.replace(hour=8,  minute=0, second=0, microsecond=0)
        end   = date.replace(hour=18, minute=0, second=0, microsecond=0)
        return self._service.get_events(doctor_id, start, end)

    def findAvailableSlots(
        self, doctor_id: str, start: datetime, duration: int = 30
    ) -> List[TimeSlot]:
        """Retourne les créneaux libres du médecin sur la journée."""
        end_of_day = start.replace(hour=18, minute=0, second=0, microsecond=0)
        events     = sorted(
            self._service.get_events(doctor_id, start, end_of_day),
            key=lambda e: e.start,
        )
        slots, cursor = [], start
        for ev in events:
            if (ev.start - cursor).total_seconds() >= duration * 60:
                slots.append(TimeSlot(start=cursor, end=ev.start, duration_minutes=duration))
            cursor = max(cursor, ev.end)
        if (end_of_day - cursor).total_seconds() >= duration * 60:
            slots.append(TimeSlot(start=cursor, end=end_of_day, duration_minutes=duration))
        return slots

    def checkConflicts(self, appointment: Appointment) -> bool:
        """Retourne True si le créneau est déjà occupé."""
        events = self._service.get_events(
            appointment.doctor_id, appointment.start_time, appointment.end_time
        )
        return any(
            not (ev.end <= appointment.start_time or ev.start >= appointment.end_time)
            for ev in events
        )

    #  Écriture 

    def createAppointment(self, appointment: Appointment) -> AppointmentResult:
        """Crée un RDV après vérification des conflits."""
        if self.checkConflicts(appointment):
            return AppointmentResult(
                success=False,
                appointment_id="",
                message=(
                    f"Conflit : {appointment.doctor_id} n'est pas disponible "
                    f"à {appointment.start_time.strftime('%H:%M')}"
                ),
                status=Status.FAILED,
            )
        event = self._service.create_event({
            "title":        appointment.title,
            "doctor_name":  appointment.doctor_id,
            "patient_name": appointment.patient_id,
            "start":        appointment.start_time,
            "end":          appointment.end_time,
            "description":  appointment.description,
        })
        logger.info("[CalendarManager] RDV créé : %s", event.id)
        return AppointmentResult(
            success=True,
            appointment_id=event.id,
            message=f"RDV créé : {appointment.title} le {appointment.start_time.strftime('%d/%m à %H:%M')}",
            status=Status.COMPLETED,
        )

    def updateAppointment(
        self, appointment_id: str, appointment: Appointment
    ) -> AppointmentResult:
        """Modifie un RDV existant."""
        event = self._service.update_event(appointment_id, {
            "title":        appointment.title,
            "doctor_name":  appointment.doctor_id,
            "patient_name": appointment.patient_id,
            "start":        appointment.start_time,
            "end":          appointment.end_time,
            "description":  appointment.description,
        })
        logger.info("[CalendarManager] RDV modifié : %s", appointment_id)
        return AppointmentResult(
            success=True,
            appointment_id=event.id,
            message=f"RDV modifié : {event.title}",
            status=Status.COMPLETED,
        )

    def deleteAppointment(self, appointment_id: str) -> AppointmentResult:
        """Supprime un RDV par son ID."""
        ok = self._service.delete_event(appointment_id)
        if ok:
            logger.info("[CalendarManager] RDV supprimé : %s", appointment_id)
            return AppointmentResult(
                success=True, appointment_id=appointment_id,
                message="RDV supprimé.", status=Status.COMPLETED,
            )
        return AppointmentResult(
            success=False, appointment_id=appointment_id,
            message="RDV introuvable.", status=Status.FAILED,
        )
