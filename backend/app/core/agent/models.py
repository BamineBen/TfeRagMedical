"""
models.py — Structures de données de l'agent médical.

Utilise @dataclass pour définir des objets simples avec des attributs typés.
Chaque classe correspond à une classe du diagramme de classes UML Section 5.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, List, Optional

from app.core.agent.types import InteractionSeverity, Status


@dataclass
class AgentConfig:
    """Configuration globale de l'agent. Lié à MedicalAgent.config (UML)."""
    language:     str  = "fr"    # Langue des réponses
    timeout:      int  = 120     # Timeout max en secondes
    privacy_mode: bool = False   # Si True, ne pas logger les données patient


@dataclass
class Appointment:
    """Un rendez-vous médical. Correspond à CalendarEvent dans le calendrier."""
    id:          str
    patient_id:  str      # Nom du patient (ex: "DUPONT Jean")
    doctor_id:   str      # Nom du médecin (ex: "Dr Martin")
    start_time:  datetime
    end_time:    datetime
    title:       str      # "Consultation DUPONT Jean"
    description: str = ""
    status: Status = Status.PENDING


@dataclass
class AppointmentResult:
    """Résultat d'une opération sur un RDV (création, modification, suppression)."""
    success:        bool
    appointment_id: str
    message:        str    # Message lisible ("RDV créé le 01/05 à 14h")
    status:         Status


@dataclass
class AgentResponse:
    """Réponse finale de l'agent (endpoint non-streaming /send)."""
    message: str
    success: bool
    sources: List[str] = field(default_factory=list)
    data:    Any       = None
    status:  Status    = Status.COMPLETED


@dataclass
class Prescription:
    """Ordonnance à vérifier. Paramètre d'entrée de InteractionChecker."""
    patient_id:  str
    medications: List[str] = field(default_factory=list)  # ["warfarine","aspirine"]
    dosages:     List[str] = field(default_factory=list)  # ["5mg","100mg"]


@dataclass
class InteractionResult:
    """Résultat d'une vérification d'interactions médicamenteuses."""
    has_interaction: bool
    severity:        InteractionSeverity = InteractionSeverity.LOW
    medications:     List[str]           = field(default_factory=list)
    description:     str                 = ""
    recommendations: List[str]           = field(default_factory=list)
    allergies:       List[str]           = field(default_factory=list)
    status:          Status              = Status.COMPLETED


@dataclass
class PatientInfo:
    """Informations patient extraites du RAG."""
    patient_id:      str
    name:            str
    medical_summary: str       = ""
    medications:     List[str] = field(default_factory=list)
    allergies:       List[str] = field(default_factory=list)


@dataclass
class CalendarEvent:
    """Un événement dans le calendrier Google (ou démo)."""
    id:          str
    title:       str
    doctor_name: str
    start:       datetime
    end:         datetime
    description: str = ""


@dataclass
class TimeSlot:
    """Un créneau libre dans le calendrier."""
    start:            datetime
    end:              datetime
    duration_minutes: int = 30


@dataclass
class ToolResult:
    """Résultat d'exécution d'un outil (Pattern Strategy)."""
    success:       bool
    data:          Any
    error_message: str = ""
    execution_time_ms: int = 0

    @classmethod
    def ok(cls, data: Any, elapsed_ms: int = 0) -> "ToolResult":
        return cls(success=True, data=data, execution_time_ms=elapsed_ms)

    @classmethod
    def fail(cls, message: str) -> "ToolResult":
        return cls(success=False, data=None, error_message=message)