"""
dashboard.py — Endpoints pour le tableau de bord (admin uniquement).

Fournit les statistiques globales de la plateforme :
  - Nombre de documents, utilisateurs, conversations, messages, chunks
  - Activité récente (dernières conversations)
  - Santé des services (DB, LLM, système)
  - Métriques d'activité par jour sur N jours
"""
import psutil
from datetime import date, timedelta
from fastapi import APIRouter, Query
from sqlalchemy import cast, Date as SaDate, desc, func, select, text

from app.api.deps import CurrentAdminUser, DBSession
from app.config import settings
from app.core.gpu_manager import get_gpu_manager
from app.models.conversation import Conversation, ConversationStatus
from app.models.document import Document, DocumentStatus
from app.models.message import Message
from app.models.user import User

router = APIRouter()


@router.get("/stats")
async def get_stats(db: DBSession, _: CurrentAdminUser):
    """
    Statistiques globales de la plateforme.
    Les chunks sont lus depuis rag_state (source de vérité) plutôt que la DB.
    """
    from app.core.rag_state import rag_state
    _, chunks = rag_state.get()

    # Toutes les requêtes en parallèle (SQLAlchemy async)
    total_docs    = (await db.execute(select(func.count(Document.id)))).scalar_one()
    done_docs     = (await db.execute(select(func.count(Document.id)).where(Document.status == DocumentStatus.COMPLETED))).scalar_one()
    total_users   = (await db.execute(select(func.count(User.id)))).scalar_one()
    total_convs   = (await db.execute(select(func.count(Conversation.id)))).scalar_one()
    active_convs  = (await db.execute(select(func.count(Conversation.id)).where(Conversation.status == ConversationStatus.ACTIVE))).scalar_one()
    total_msgs    = (await db.execute(select(func.count(Message.id)))).scalar_one()

    return {
        "documents"    : {"total": total_docs, "processed": done_docs, "pending": total_docs - done_docs},
        "users"        : {"total": total_users},
        "conversations": {"total": total_convs, "active": active_convs},
        "messages"     : {"total": total_msgs},
        "chunks"       : {"total": len(chunks)},
    }


@router.get("/recent-activity")
async def get_recent_activity(db: DBSession, _: CurrentAdminUser):
    """Retourne les 5 dernières conversations actives (pour la timeline du dashboard)."""
    rows = (await db.execute(
        select(Conversation).order_by(desc(Conversation.last_message_at)).limit(5)
    )).scalars().all()

    return [
        {"type": "conversation", "id": c.id, "session_id": c.session_id,
         "time": c.last_message_at, "channel": c.channel, "status": c.status}
        for c in rows
    ]


@router.get("/health")
async def get_health(db: DBSession, _: CurrentAdminUser):
    """
    Vérifie l'état de tous les services critiques.
    Retourne "ok" ou "error" pour chaque service + métriques système.
    """
    results: dict = {}

    # LLM local (Ollama)
    try:
        from app.core.llm_client import get_llm_client
        ok = await get_llm_client().check_health()
        results["ollama"] = {"status": "ok" if ok else "error", "model": settings.VLLM_MODEL_NAME}
    except Exception as e:
        results["ollama"] = {"status": "error", "error": str(e)}

    # Base de données
    try:
        await db.execute(text("SELECT 1"))
        results["database"] = {"status": "ok"}
    except Exception as e:
        results["database"] = {"status": "error", "error": str(e)}

    # GPU Vast.ai (optionnel)
    results["gpu"] = await get_gpu_manager().get_status_info()

    # Ressources système
    mem = psutil.virtual_memory()
    results["system"] = {
        "cpu_percent"  : psutil.cpu_percent(interval=0.1),
        "ram_used_gb"  : round(mem.used  / 1024**3, 2),
        "ram_total_gb" : round(mem.total / 1024**3, 2),
        "ram_percent"  : mem.percent,
    }

    # Statut global : "ok" si la DB répond, "degraded" sinon
    results["overall"] = "ok" if results["database"]["status"] == "ok" else "degraded"
    return results


@router.post("/gpu/start")
async def gpu_start(_: CurrentAdminUser):
    """Démarre l'instance GPU Vast.ai manuellement."""
    gpu = get_gpu_manager()
    if not gpu.is_configured:
        return {"ok": False, "error": "Vast.ai non configuré"}
    await gpu.touch()
    return {"ok": True, "status": gpu.status.value}


@router.post("/gpu/stop")
async def gpu_stop(_: CurrentAdminUser):
    """Arrête l'instance GPU Vast.ai manuellement."""
    gpu = get_gpu_manager()
    if not gpu.is_configured:
        return {"ok": False, "error": "Vast.ai non configuré"}
    await gpu.shutdown()
    return {"ok": True, "status": gpu.status.value}


@router.get("/metrics")
async def get_metrics(db: DBSession, _: CurrentAdminUser, days: int = Query(7, ge=1, le=30)):
    """
    Métriques d'activité : messages et conversations par jour sur les N derniers jours.
    Les jours sans activité sont inclus avec count=0.
    """
    today      = date.today()
    start_date = today - timedelta(days=days - 1)

    def _fill_days(counts_by_date: dict, key: str = "count") -> list[dict]:
        """Génère une liste de N jours consécutifs, en remplissant les jours vides avec 0."""
        return [
            {"date": str(start_date + timedelta(days=i)),
             key: counts_by_date.get(str(start_date + timedelta(days=i)), 0)}
            for i in range(days)
        ]

    # Messages par jour
    msg_rows = (await db.execute(
        select(cast(Message.created_at, SaDate).label("day"), func.count(Message.id).label("cnt"))
        .where(Message.created_at >= start_date)
        .group_by(cast(Message.created_at, SaDate))
    )).all()
    msgs_per_day = {str(r.day): r.cnt for r in msg_rows}

    # Conversations par jour
    conv_rows = (await db.execute(
        select(cast(Conversation.created_at, SaDate).label("day"), func.count(Conversation.id).label("cnt"))
        .where(Conversation.created_at >= start_date)
        .group_by(cast(Conversation.created_at, SaDate))
    )).all()
    convs_per_day = {str(r.day): r.cnt for r in conv_rows}

    msgs_list  = _fill_days(msgs_per_day)
    total_msgs = sum(d["count"] for d in msgs_list)

    return {
        "messages_per_day"     : msgs_list,
        "conversations_per_day": _fill_days(convs_per_day),
        "total_messages"       : total_msgs,
        "avg_messages_per_day" : round(total_msgs / days, 1),
        "days"                 : days,
    }
