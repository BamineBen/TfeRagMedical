"""types.py : Énumérations de l'agent médical."""
from enum import Enum

class ActionType(str, Enum):
    """Actions possibles détectées par IntentDetector."""
    CREATE_APPOINTMENT  = "CREATE_APPOINTMENT"
    MODIFY_APPOINTMENT  = "MODIFY_APPOINTMENT"
    DELETE_APPOINTMENT  = "DELETE_APPOINTMENT"
    CONSULT_PLANNING    = "CONSULT_PLANNING"
    QUERY_PATIENT       = "QUERY_PATIENT"
    CHECK_INTERACTIONS  = "CHECK_INTERACTIONS"
    MIXED               = "MIXED"

class Status(str, Enum):
    """État d'une opération agent."""
    PENDING               = "PENDING"
    RUNNING               = "RUNNING"
    COMPLETED             = "COMPLETED"
    FAILED                = "FAILED"
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"

class InteractionSeverity(str, Enum):
    """Gravité d'une interaction médicamenteuse."""
    LOW      = "LOW"
    MEDIUM   = "MEDIUM"
    HIGH     = "HIGH"
    CRITICAL = "CRITICAL"

class AgentEventType(str, Enum):
    """Types d'événements SSE envoyés au frontend."""
    STEP_START           = "STEP_START"
    STEP_COMPLETE        = "STEP_COMPLETE"
    CONFIRMATION_REQUEST = "CONFIRMATION_REQUEST"
    ANSWER               = "ANSWER"
    ERROR                = "ERROR"
    DONE                 = "DONE"
