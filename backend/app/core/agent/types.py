ActionType  : ce que le médecin veut faire
Status      : état d'une opération
InteractionSeverity : gravité d'une interaction médicamenteuse
AgentEventType : type d'événement SSE envoyé au frontend
""Classes de types utilisées dans l'agent (IntentClassifier, InteractionChecker, etc.) et pour la communication avec le frontend (/send)."""
from enum import Enum


class ActionType(str, Enum):
    """Actions possibles détectées par IntentDetector."""
    CREATE_APPOINTMENT  = "CREATE_APPOINTMENT"   # "Créer un RDV pour..."
    MODIFY_APPOINTMENT  = "MODIFY_APPOINTMENT"   # "Modifier le RDV de..."
    DELETE_APPOINTMENT  = "DELETE_APPOINTMENT"   # "Annuler le RDV de..."
    CONSULT_PLANNING    = "CONSULT_PLANNING"     # "Planning Dr Martin..."
    QUERY_PATIENT       = "QUERY_PATIENT"        # "Dossier de DUPONT..."
    CHECK_INTERACTIONS  = "CHECK_INTERACTIONS"   # "Interactions warfarine..."
    MIXED               = "MIXED"                # Intention ambiguë


class Status(str, Enum):
    """État d'une opération agent."""
    PENDING               = "PENDING"
    RUNNING               = "RUNNING"
    COMPLETED             = "COMPLETED"
    FAILED                = "FAILED"
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"  # Attend OK du médecin


class InteractionSeverity(str, Enum):
    """Gravité d'une interaction médicamenteuse."""
    LOW      = "LOW"       # Mineure, surveillance simple
    MEDIUM   = "MEDIUM"    # Modérée, ajuster les doses
    HIGH     = "HIGH"      # Majeure, éviter l'association
    CRITICAL = "CRITICAL"  # Contre-indication absolue


class AgentEventType(str, Enum):
    """Types d'événements SSE envoyés au frontend."""
    STEP_START           = "STEP_START"           # Un outil commence
    STEP_COMPLETE        = "STEP_COMPLETE"         # Un outil a terminé
    CONFIRMATION_REQUEST = "CONFIRMATION_REQUEST"  # Attente confirmation
    ANSWER               = "ANSWER"                # Réponse finale
    ERROR                = "ERROR"                 # Erreur
    DONE                 = "DONE"                  # Stream terminé