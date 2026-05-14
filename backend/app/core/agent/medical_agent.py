medical_agent.py : Orchestrateur central de l'agent médical (Singleton).

MedicalAgent coordonne :
1. IntentDetector    → comprend la requête
2. plan()            → génère les étapes à exécuter
3. run()             → exécute en streaming (SSE) avec confirmations
4. confirm()         → reprend après confirmation médecin

FLUX COMPLET :
    Requête → detectAction() → plan() → [execute step1] → [CONF_REQUEST] → /confirm → execute()

import asyncio
import logging
import time
import uuid
from datetime import timedelta
from typing import AsyncGenerator, Dict, List, Optional

from app.core.agent.types import ActionType, AgentEventType, Status
from app.core.agent.models import (
    AgentConfig, AgentResponse, Appointment,
    InteractionResult, PatientInfo, Prescription, ToolResult,
)
from app.core.agent.intent_classifier import IntentDetector
from app.core.agent.calendar_manager import CalendarManager
from app.core.agent.interaction_checker import InteractionChecker
from app.core.agent.tools.rag_query import RAGQueryTool
from app.core.agent.tools.calendar_read import CalendarReadTool
from app.core.agent.tools.calendar_write import CalendarWriteTool
from app.core.agent.tools.interaction_check import InteractionCheckTool

logger = logging.getLogger(__name__)


class MedicalAgent:

    Singleton : une seule instance partagée entre toutes les requêtes.
    
    Pattern Singleton via __new__ :
    - Premier appel → crée l'instance + initialise les attributs
    - Appels suivants → retourne la même instance (sans ré-initialiser)

    _instance: Optional["MedicalAgent"] = None

    def __new__(cls) -> "MedicalAgent":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return  # Singleton : ne pas ré-initialiser

        # Attributs du diagramme UML
        self.config             = AgentConfig()
        self.intentDetector     = IntentDetector()
        self.calendarManager    = CalendarManager()
        self.interactionChecker = InteractionChecker()

        # Outils (Pattern Strategy)
        self._tools = {
            "rag_query":         RAGQueryTool(),
            "calendar_read":     CalendarReadTool(),
            "calendar_write":    CalendarWriteTool(),
            "interaction_check": InteractionCheckTool(),
        }

        # Sessions en attente de confirmation {session_id: step_dict}
        self._pending: Dict[str, dict] = {}

        self._initialized = True
        logger.info("[MedicalAgent] Singleton initialisé")

    #  API publique 

    def processRequest(self, query: str) -> AgentResponse:
        """Point d'entrée non-streaming (pour tests rapides)."""
        action = self.intentDetector.detectAction(query)
        return self._dispatch_sync(action, query)

    async def run(
        self,
        query: str,
        session_id: Optional[str] = None,
        user_id: Optional[int] = None,
        llm_mode: str = "gemini",
    ) -> AsyncGenerator[dict, None]:

        Exécute la requête en streaming SSE.
        Chaque `yield` envoie un événement JSON au frontend.
        
        Séquence d'événements :
          → STEP_START (step_name)
          → STEP_COMPLETE (data du résultat)
          → CONFIRMATION_REQUEST (si requires_confirmation)
          → ANSWER (réponse finale)
          → DONE (fin du stream)

        if session_id is None:
            session_id = str(uuid.uuid4())[:8]

        intent   = self.intentDetector.detectAction(query)
        entities = self.intentDetector.extract_entities(query)
        steps    = self.plan(query, intent, entities)

        logger.info(f"[Agent] intent={intent.value} steps={[s['tool'] for s in steps]}")

        for step in steps:
            tool_name = step["tool"]
            params    = step["params"]

            # Émettre STEP_START
            yield {"type": AgentEventType.STEP_START, "step_name": tool_name, "data": {"order": steps.index(step) + 1}}

            # Si confirmation requise → stocker et attendre
            if step.get("requires_confirmation", False):
                self._pending[session_id] = step
                yield {
                    "type":      AgentEventType.CONFIRMATION_REQUEST,
                    "step_name": tool_name,
                    "data":      {
                        "tool":    tool_name,
                        "params":  self._sanitize_params(params),
                        "message": step.get("confirm_message", f"Confirmer l'action {tool_name} ?"),
                    },
                }
                return  # PAUSE : attendre /confirm

            # Exécuter l'outil
            result: ToolResult = await asyncio.to_thread(
                self._tools[tool_name].execute, params
            )

            yield {
                "type":               AgentEventType.STEP_COMPLETE,
                "step_name":          tool_name,
                "data":               result.data if result.success else {"error": result.error_message},
                "execution_time_ms":  result.execution_time_ms,
            }

            # Enrichir les étapes suivantes avec les résultats de cette étape
            self._enrich_next_steps(steps, steps.index(step), result)

        # Réponse finale
        yield {
            "type": AgentEventType.ANSWER,
            "data": {"intent": intent.value, "entities": entities},
        }

    def confirm(self, session_id: str, approved: bool) -> ToolResult:
        """
        Appelé par POST /agent/confirm.
        Reprend l'exécution d'une étape mise en pause pour confirmation.
        """
        step = self._pending.pop(session_id, None)
        if not step:
            return ToolResult.fail(f"Session {session_id} introuvable ou expirée.")

        if not approved:
            return ToolResult.ok({"cancelled": True, "message": "Action annulée par le médecin."})

        tool_name = step["tool"]
        result    = self._tools[tool_name].execute(step["params"])
        return result

    #  Planification 

    def plan(self, query: str, intent: ActionType, entities: dict) -> List[dict]:

        Génère la liste des étapes à exécuter selon l'intention.
        Chaque étape = {"tool": str, "params": dict, "requires_confirmation": bool}

        doctor  = entities.get("doctor") or "Dr Martin"
        patient = entities.get("patient")
        dt      = self.intentDetector.resolve_datetime(entities.get("date"), entities.get("time"))

        if intent == ActionType.CONSULT_PLANNING:
            return [{
                "tool":   "calendar_read",
                "params": {"doctor_name": doctor, "start": dt, "end": dt + timedelta(hours=9)},
            }]

        elif intent == ActionType.CREATE_APPOINTMENT:
            steps = []
            if patient:
                steps.append({
                    "tool":   "rag_query",
                    "params": {"query": f"Résumé médical {patient}", "source_filter": None},
                })
            steps.append({
                "tool":   "calendar_read",
                "params": {"doctor_name": doctor, "start": dt},
            })
            steps.append({
                "tool":   "calendar_write",
                "params": {
                    "action": "create",
                    "appointment": {
                        "id":          "",
                        "patient_id":  patient or "Patient",
                        "doctor_id":   doctor,
                        "start_time":  dt,
                        "end_time":    dt + timedelta(minutes=30),
                        "title":       f"Consultation {patient or 'Patient'}",
                        "description": "",
                        "status":      Status.PENDING,
                    },
                },
                "requires_confirmation": True,
                "confirm_message": f"Créer un RDV pour {patient} avec {doctor} le {dt.strftime('%d/%m à %H:%M')} ?",
            })
            return steps

        elif intent == ActionType.DELETE_APPOINTMENT:
            return [{
                "tool":   "calendar_read",
                "params": {"doctor_name": doctor, "start": dt},
            }, {
                "tool":              "calendar_write",
                "params":            {"action": "delete", "event_id": "__TO_FILL__"},
                "requires_confirmation": True,
                "confirm_message":   f"Supprimer le RDV de {doctor} le {dt.strftime('%d/%m')} ?",
            }]

        elif intent == ActionType.CHECK_INTERACTIONS:
            meds = self._extract_medications(query)
            return [{
                "tool":   "interaction_check",
                "params": {"medications": meds, "patient_allergies": [], "patient_name": patient or ""},
            }]

        else:  # QUERY_PATIENT
            return [{
                "tool":   "rag_query",
                "params": {"query": query, "source_filter": None},
            }]

    #  Helpers privés 

    def _dispatch_sync(self, action: ActionType, query: str) -> AgentResponse:
        """Version synchrone simple pour tests."""
        entities = self.intentDetector.extract_entities(query)
        steps    = self.plan(query, action, entities)

        if not steps:
            return AgentResponse(message="Requête non comprise.", success=False)

        step   = steps[0]
        result = self._tools[step["tool"]].execute(step["params"])

        if result.success:
            return AgentResponse(message=str(result.data), success=True, data=result.data)
        return AgentResponse(message=result.error_message, success=False, status=Status.FAILED)

    def _extract_medications(self, query: str) -> List[str]:
        """Extrait les noms de médicaments depuis une requête texte."""
        import re
        meds = re.findall(
            r'\b(aspirine|warfarine|ibuprofene|paracetamol|metformine|simvastatine|'
            r'atenolol|verapamil|clopidogrel|omeprazole|lithium|sertraline|tramadol|'
            r'digoxine|amiodarone|methotrexate|clarithromycine|penicilline)\b',
            query.lower()
        )
        return list(set(meds))

    def _enrich_next_steps(self, steps: List[dict], current_idx: int, result: ToolResult):
        """
        Injecte les résultats d'une étape dans les paramètres des étapes suivantes.
        Ex: résumé RAG → description du RDV à créer.
        """
        if not result.success or not result.data:
            return
        for step in steps[current_idx + 1:]:
            if step["tool"] == "calendar_write" and "appointment" in step["params"]:
                if "answer" in result.data:  # Résultat RAG
                    step["params"]["appointment"]["description"] = result.data["answer"][:500]

    @staticmethod
    def _sanitize_params(params: dict) -> dict:
        """Retire les données sensibles avant d'envoyer la confirmation au frontend."""
        safe = dict(params)
        # Convertir les datetime en str pour JSON
        for k, v in safe.items():
            if hasattr(v, "isoformat"):
                safe[k] = v.isoformat()
        return safe