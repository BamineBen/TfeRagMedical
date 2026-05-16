"""models.py — Structures de données de l'agent médical."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, List, Optional

from app.core.agent.types import InteractionSeverity, Status

@dataclass
class AgentConfig:
    """Configuration de l'agent. """
    language:     str  = "fr"
    timeout:      int  = 120
    privacy_mode: bool = False

@dataclass
class Appointment:
    """Rendez-vous médical. """
    id:          str
    patient_id:  str
    doctor_id:   str
    start_time:  datetime
    end_time:    datetime
    title:       str
    description: str    = ""
    status:      Status = Status.PENDING

@dataclass
class AppointmentResult:
    """Résultat d'une opération RDV. """
    success:        bool
    appointment_id: str
    message:        str
    status:         Status

@dataclass
class AgentResponse:
    """Réponse finale de l'agent (chemin non-streaming)."""
    message: str
    success: bool
    sources: List[str] = field(default_factory=list)
    data:    Any       = None
    status:  Status    = Status.COMPLETED

@dataclass
class Prescription:
    """Ordonnance. Paramètre d'InteractionChecker. """
    patient_id:  str
    medications: List[str] = field(default_factory=list)
    dosages:     List[str] = field(default_factory=list)

@dataclass
class InteractionResult:
    """Résultat d'interactions. """
    has_interaction: bool
    severity:        InteractionSeverity = InteractionSeverity.LOW
    medications:     List[str]           = field(default_factory=list)
    description:     str                 = ""
    recommendations: List[str]           = field(default_factory=list)
    allergies:       List[str]           = field(default_factory=list)
    status:          Status              = Status.COMPLETED

@dataclass
class PatientInfo:
    """Informations patient (depuis RAG). """
    patient_id:      str
    name:            str
    medical_summary: str       = ""
    medications:     List[str] = field(default_factory=list)
    allergies:       List[str] = field(default_factory=list)

@dataclass
class CalendarEvent:
    """Événement Google Calendar. """
    id:            str
    title:         str
    doctor_name:   str
    start:         datetime
    end:           datetime
    description:   str = ""
    patient_name:  str = ""
    calendar_link: str = ""

@dataclass
class TimeSlot:
    """Créneau libre dans le calendrier. """
    start:            datetime
    end:              datetime
    duration_minutes: int = 30

@dataclass
class ToolResult:
    """Résultat d'un outil (Pattern Strategy). """
    success:           bool
    data:              Any
    error_message:     str = ""
    execution_time_ms: int = 0

    @classmethod
    def ok(cls, data: Any, execution_time_ms: int = 0) -> "ToolResult":
        return cls(success=True, data=data, execution_time_ms=execution_time_ms)

    @classmethod
    def fail(cls, message: str, execution_time_ms: int = 0) -> "ToolResult":
        return cls(success=False, data=None, error_message=message, execution_time_ms=execution_time_ms)
