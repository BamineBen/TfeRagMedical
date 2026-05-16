"""
calendar_service.py : Accès Google Calendar via OAuth2.

GoogleCredentials : gère le flux OAuth2 (URL consentement, échange code, refresh).
CalendarService   : appels REST directs à l'API Google Calendar (httpx).
UserTokenStore    : chargé automatiquement si user_id fourni.
"""
import os
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from urllib.parse import urlencode

import httpx

from app.core.agent.models import CalendarEvent

logger = logging.getLogger(__name__)

_GOOGLE_AUTH_URL  = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_CALENDAR_BASE    = "https://www.googleapis.com/calendar/v3"
_SCOPES           = "https://www.googleapis.com/auth/calendar"

#  GoogleCredentials 
@dataclass
class GoogleCredentials:
    """Credentials OAuth2 Google d'un médecin. """
    client_id:     str
    client_secret: str
    redirect_uri:  str
    refresh_token: str = ""
    access_token:  str = ""
    expires_at:    Optional[datetime] = None

    def get_authorization_url(self, state: str = "") -> str:
        """URL de consentement Google (étape 1 OAuth2)."""
        params = {
            "client_id":     self.client_id,
            "redirect_uri":  self.redirect_uri,
            "response_type": "code",
            "scope":         _SCOPES,
            "access_type":   "offline",
            "prompt":        "consent",
        }
        if state:
            params["state"] = state
        return f"{_GOOGLE_AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, code: str) -> None:
        """Échange le code d'autorisation contre access_token + refresh_token."""
        with httpx.Client(timeout=15) as client:
            resp = client.post(_GOOGLE_TOKEN_URL, data={
                "code":          code,
                "client_id":     self.client_id,
                "client_secret": self.client_secret,
                "redirect_uri":  self.redirect_uri,
                "grant_type":    "authorization_code",
            })
            resp.raise_for_status()
            data = resp.json()
        self.access_token  = data["access_token"]
        self.refresh_token = data.get("refresh_token", self.refresh_token)
        self.expires_at    = datetime.now(timezone.utc) + timedelta(seconds=data.get("expires_in", 3600))
        logger.info("[GoogleCredentials] Tokens échangés")

    def refresh(self) -> None:
        """Rafraîchit l'access_token via le refresh_token."""
        if not self.refresh_token:
            raise ValueError("Aucun refresh_token — connexion Google requise")
        with httpx.Client(timeout=15) as client:
            resp = client.post(_GOOGLE_TOKEN_URL, data={
                "refresh_token": self.refresh_token,
                "client_id":     self.client_id,
                "client_secret": self.client_secret,
                "grant_type":    "refresh_token",
            })
            resp.raise_for_status()
            data = resp.json()
        self.access_token = data["access_token"]
        self.expires_at   = datetime.now(timezone.utc) + timedelta(seconds=data.get("expires_in", 3600))
        logger.info("[GoogleCredentials] Token rafraîchi")

    def is_expired(self) -> bool:
        if not self.expires_at:
            return True
        return datetime.now(timezone.utc) >= (self.expires_at - timedelta(seconds=60))

    def get_access_token(self) -> str:
        """Retourne un token valide, rafraîchit si nécessaire."""
        if self.is_expired():
            self.refresh()
        return self.access_token

#  CalendarService 
class CalendarService:
    """
    Accès Google Calendar v3 via REST (httpx).
    Charge les tokens depuis UserTokenStore si user_id fourni.
    """

    def __init__(
        self,
        credentials: Optional[GoogleCredentials] = None,
        user_id: Optional[int] = None,
    ):
        self._credentials = credentials
        self.user_id      = user_id
        self.calendar_id  = "primary"

    @property
    def credentials(self) -> GoogleCredentials:
        """Charge les credentials depuis le store si non fournis."""
        if self._credentials is None and self.user_id:
            from app.core.agent.user_token_store import UserTokenStore
            self._credentials = UserTokenStore().load_tokens(self.user_id)
        if self._credentials is None:
            raise ValueError(
                "Aucun token Google disponible. "
                "Connectez Google Calendar via /agent/google/auth"
            )
        return self._credentials

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.credentials.get_access_token()}"}

    #  Lecture 

    def get_events(self, doctor_name: str, start: datetime, end: datetime) -> List[CalendarEvent]:
        """Retourne les RDV entre start et end depuis Google Calendar."""
        params = {
            "timeMin":      start.replace(tzinfo=timezone.utc).isoformat(),
            "timeMax":      end.replace(tzinfo=timezone.utc).isoformat(),
            "singleEvents": "true",
            "orderBy":      "startTime",
        }
        with httpx.Client(timeout=15) as client:
            resp = client.get(
                f"{_CALENDAR_BASE}/calendars/{self.calendar_id}/events",
                headers=self._headers(), params=params,
            )
            resp.raise_for_status()
            items = resp.json().get("items", [])

        events = []
        for item in items:
            start_str = item["start"].get("dateTime", item["start"].get("date", ""))
            end_str   = item["end"].get("dateTime",   item["end"].get("date", ""))
            events.append(CalendarEvent(
                id=item["id"],
                title=item.get("summary", ""),
                start=self._parse_dt(start_str),
                end=self._parse_dt(end_str),
                doctor_name=doctor_name,
                patient_name=item.get("description", ""),
                description=item.get("description", ""),
                calendar_link=item.get("htmlLink", ""),
            ))
        return events

    #  Écriture 

    def create_event(self, event_data: dict) -> CalendarEvent:
        """Crée un RDV dans Google Calendar."""
        start_dt = self._parse_dt(event_data.get("start"))
        end_dt   = self._parse_dt(event_data.get("end"))
        body = {
            "summary":     event_data.get("title", "Consultation"),
            "description": event_data.get("description", ""),
            "start": {"dateTime": start_dt.isoformat() + "Z", "timeZone": "UTC"},
            "end":   {"dateTime": end_dt.isoformat()   + "Z", "timeZone": "UTC"},
        }
        with httpx.Client(timeout=15) as client:
            resp = client.post(
                f"{_CALENDAR_BASE}/calendars/{self.calendar_id}/events",
                headers=self._headers(), json=body,
            )
            resp.raise_for_status()
            item = resp.json()
        logger.info("[CalendarService] RDV créé : %s", item["id"])
        return CalendarEvent(
            id=item["id"],
            title=item.get("summary", ""),
            start=start_dt, end=end_dt,
            doctor_name=event_data.get("doctor_name", ""),
            patient_name=event_data.get("patient_name", ""),
            description=item.get("description", ""),
            calendar_link=item.get("htmlLink", ""),
        )

    def update_event(self, event_id: str, event_data: dict) -> CalendarEvent:
        """Modifie un RDV existant."""
        patch = {}
        if "title" in event_data:
            patch["summary"] = event_data["title"]
        if "start" in event_data:
            patch["start"] = {"dateTime": self._parse_dt(event_data["start"]).isoformat() + "Z"}
        if "end" in event_data:
            patch["end"]   = {"dateTime": self._parse_dt(event_data["end"]).isoformat()   + "Z"}
        if "description" in event_data:
            patch["description"] = event_data["description"]

        with httpx.Client(timeout=15) as client:
            resp = client.patch(
                f"{_CALENDAR_BASE}/calendars/{self.calendar_id}/events/{event_id}",
                headers=self._headers(), json=patch,
            )
            resp.raise_for_status()
            item = resp.json()
        start_str = item["start"].get("dateTime", "")
        end_str   = item["end"].get("dateTime",   "")
        logger.info("[CalendarService] RDV modifié : %s", event_id)
        return CalendarEvent(
            id=item["id"],
            title=item.get("summary", ""),
            start=self._parse_dt(start_str),
            end=self._parse_dt(end_str),
            doctor_name=event_data.get("doctor_name", ""),
            patient_name=event_data.get("patient_name", ""),
            description=item.get("description", ""),
            calendar_link=item.get("htmlLink", ""),
        )

    def delete_event(self, event_id: str) -> bool:
        """Supprime un RDV. Retourne True si succès."""
        with httpx.Client(timeout=15) as client:
            resp = client.delete(
                f"{_CALENDAR_BASE}/calendars/{self.calendar_id}/events/{event_id}",
                headers=self._headers(),
            )
        ok = resp.status_code in (200, 204)
        if ok:
            logger.info("[CalendarService] RDV supprimé : %s", event_id)
        return ok

    @staticmethod
    def _parse_dt(value) -> datetime:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str) and value:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
        return datetime.utcnow()
