agent.py : Endpoints FastAPI de l'agent médical autonome.

Endpoints :
  POST /agent/stream  → Lance une requête agent (SSE streaming)
  POST /agent/confirm → Confirme/rejette une action en attente
  GET  /agent/tools   → Liste des outils disponibles

import json
import logging
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.deps import CurrentUser
from app.core.agent.medical_agent import MedicalAgent
from app.core.agent.types import AgentEventType

logger = logging.getLogger(__name__)
router = APIRouter()

_SSE_HEADERS = {
    "Cache-Control":               "no-cache",
    "X-Accel-Buffering":           "no",
    "Access-Control-Allow-Origin": "*",
}


class AgentChatRequest(BaseModel):
    query:      str                 # Question du médecin
    session_id: str | None = None   # ID de session (pour confirm)
    llm_mode:   str        = "gemini"


class AgentConfirmRequest(BaseModel):
    session_id: str   # ID de session retourné par CONFIRMATION_REQUEST
    approved:   bool  # True = confirmer, False = annuler


@router.post("/stream")
async def agent_stream(request: AgentChatRequest, current_user: CurrentUser):
    """
    Lance une requête agent en streaming SSE.
    
    Le frontend lit les événements JSON ligne par ligne :
    data: {"type": "STEP_START", "step_name": "calendar_read", ...}
    data: {"type": "STEP_COMPLETE", "data": {"events": [...], "free_slots": [...]}}
    data: {"type": "CONFIRMATION_REQUEST", "data": {"message": "Confirmer ?"}}
    data: {"type": "DONE"}
    """
    agent      = MedicalAgent()
    session_id = request.session_id or f"sess_{current_user.id}_{id(request)}"

    async def generate():
        try:
            async for event in agent.run(
                query=request.query,
                session_id=session_id,
                user_id=current_user.id,
                llm_mode=request.llm_mode,
            ):
                yield f"data: {json.dumps(event, default=str)}\n\n"
        except Exception as e:
            logger.error(f"[agent/stream] Erreur : {e}", exc_info=True)
            yield f"data: {json.dumps({'type': AgentEventType.ERROR, 'data': {'message': str(e)}})}\n\n"
        finally:
            yield f"data: {json.dumps({'type': AgentEventType.DONE})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream", headers=_SSE_HEADERS)


@router.post("/confirm")
async def agent_confirm(request: AgentConfirmRequest, current_user: CurrentUser):
    """
    Confirme ou rejette une action en attente (ex: création de RDV).
    Appelé par le frontend quand le médecin clique Confirmer / Annuler.
    """
    agent  = MedicalAgent()
    result = agent.confirm(request.session_id, request.approved)
    return {
        "success": result.success,
        "data":    result.data,
        "message": result.error_message or (result.data.get("message") if result.data else ""),
    }


@router.get("/tools")
async def list_tools(current_user: CurrentUser):
    """Retourne la liste des outils disponibles (pour debug/doc)."""
    agent = MedicalAgent()
    return {
        "tools": [
            {"name": t.name, "description": t.description, "requires_confirmation": t.requires_confirmation}
            for t in agent._tools.values()
        ]
    }