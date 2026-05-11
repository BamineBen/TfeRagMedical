calendar_service.py : Accès Google Calendar 

Mode réel   : tokens OAuth2 valides → appels API Google Calendar

Architecture : CalendarManager utilise CalendarService.
"""
import os
import uuid
import logging
from datetime import datetime, timedelta
from typing import List, Optional

from app.core.agent.models import CalendarEvent, TimeSlot

logger = logging.getLogger(__name__)


class CalendarService:
    """


    # API publique 

    def get_events(self, doctor_name: str, start: datetime, end: datetime) -> List[CalendarEvent]:
        """Retourne les RDV d'un médecin entre start et end."""
        if self._is_real_mode():
            return self._get_events_google(doctor_name, start, end)
        return [
            ev for ev in self._demo_store.values()
            if ev.doctor_name.lower() == doctor_name.lower()
            and start <= ev.start < end
        ]

    def create_event(self, event_data: dict) -> CalendarEvent:
        """Crée un nouveau RDV."""
        if self._is_real_mode():
            return self._create_event_google(event_data)
        return self._create_event_demo(event_data)

    def delete_event(self, event_id: str) -> bool:
        """Supprime un RDV. Retourne True si trouvé et supprimé."""
        if self._is_real_mode():
            return self._delete_event_google(event_id)
        if event_id in self._demo_store:
            del self._demo_store[event_id]
            return True
        return False

    def find_free_slots(self, doctor_name: str, start: datetime, duration_minutes: int = 30) -> List[TimeSlot]:
        """
        Trouve les créneaux libres d'un médecin.
        Algorithme : parcourt les RDV triés et comble les trous.
        """
        end_of_day = start.replace(hour=18, minute=0, second=0, microsecond=0)
        events = self.get_events(doctor_name, start, end_of_day)
        events.sort(key=lambda e: e.start)

        slots = []
        cursor = start

        for ev in events:
            gap_seconds = (ev.start - cursor).total_seconds()
            if gap_seconds >= duration_minutes * 60:
                slots.append(TimeSlot(start=cursor, end=ev.start, duration_minutes=duration_minutes))
            cursor = ev.end

        # Dernier créneau jusqu'à 18h exemple de donnée.
        if (end_of_day - cursor).total_seconds() >= duration_minutes * 60:
            slots.append(TimeSlot(start=cursor, end=end_of_day, duration_minutes=duration_minutes))

        return slots

    def check_conflicts(self, doctor_name: str, start: datetime, end: datetime) -> bool:
        """Retourne True si le créneau est déjà occupé."""
        events = self.get_events(doctor_name, start, end)
        return any(not (ev.end <= start or ev.start >= end) for ev in events)

    #  Google Calendar

    def _is_real_mode(self) -> bool:
        """True si les tokens Google OAuth2 sont valides."""
        client_id = os.getenv("GOOGLE_CLIENT_ID", "")
        if not client_id:
            return False
        # TODO : vérifier les tokens depuis la DB ou les fichiers
        return False  # Pour l'instant toujours mode démo

    def _get_events_google(self, doctor_name, start, end) -> List[CalendarEvent]:
        """Appel API Google Calendar (à implémenter avec les vrais tokens)."""
        raise NotImplementedError("Google Calendar pas encore configuré")

    def _create_event_google(self, event_data) -> CalendarEvent:
        raise NotImplementedError("Google Calendar pas encore configuré")

    def _delete_event_google(self, event_id) -> bool:
        raise NotImplementedError("Google Calendar pas encore configuré")