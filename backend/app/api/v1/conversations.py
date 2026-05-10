"""
conversations.py — Endpoints FastAPI pour l'historique des conversations RAG.

Une conversation = une session de chat créée automatiquement à chaque échange.
Elle stocke tous les messages (questions + réponses) pour l'historique.

ENDPOINTS :
  GET    /conversations               → liste paginée + filtres
  POST   /conversations               → créer une conversation (manuel, rarement utilisé)
  GET    /conversations/{id}          → détail + messages
  PATCH  /conversations/{id}          → modifier statut/flags
  DELETE /conversations/{id}          → supprimer une conversation
  DELETE /conversations/bulk/delete-all → vider l'historique complet
  GET    /conversations/{id}/messages → messages d'une conversation
"""
import uuid
from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import desc, func, or_, select, text
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DBSession
from app.models.conversation import Conversation, ConversationChannel, ConversationStatus
from app.models.message import Message
from app.schemas.conversation import (
    ConversationCreate, ConversationDetail, ConversationList,
    ConversationResponse, ConversationUpdate,
)
from app.schemas.message import MessageResponse

router = APIRouter()


@router.get("", response_model=ConversationList)
async def list_conversations(
    db        : DBSession,
    _         : CurrentUser,
    page      : int                      = Query(1, ge=1),
    page_size : int                      = Query(20, ge=1, le=100),
    status    : ConversationStatus|None  = None,
    channel   : ConversationChannel|None = None,
    q         : str|None                 = Query(None, description="Recherche sur le nom du contact ou l'ID de session"),
):
    """Liste les conversations avec filtrage optionnel par statut, canal et texte."""
    query = select(Conversation)

    # Application des filtres (uniquement si fournis)
    if status  : query = query.where(Conversation.status  == status)
    if channel : query = query.where(Conversation.channel == channel)
    if q:
        p = f"%{q}%"
        query = query.where(or_(Conversation.contact_name.ilike(p), Conversation.session_id.ilike(p)))

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    rows  = (await db.execute(
        query.order_by(desc(Conversation.last_message_at))
             .offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()

    return ConversationList(items=rows, total=total, page=page, page_size=page_size, pages=-(-total // page_size))


@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(conv_in: ConversationCreate, db: DBSession, current_user: CurrentUser):
    """Ouvre une nouvelle conversation. Le session_id est généré automatiquement si absent."""
    session_id = conv_in.session_id or str(uuid.uuid4())

    # Vérifier qu'un session_id identique n'existe pas déjà
    if (await db.execute(select(Conversation).where(Conversation.session_id == session_id))).scalar_one_or_none():
        raise HTTPException(400, "Session ID déjà utilisé")

    conv = Conversation(
        session_id=session_id, channel=conv_in.channel,
        phone_number=conv_in.phone_number, contact_name=conv_in.contact_name,
        user_id=current_user.id, status=ConversationStatus.ACTIVE,
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return conv


@router.delete("/bulk/delete-all")
async def delete_all_conversations(db: DBSession, _: CurrentUser):
    """
    Supprime TOUTES les conversations et messages, et remet l'auto-incrément à 1.
    TRUNCATE CASCADE vide aussi la table `messages` liée par FK.
    """
    count = (await db.execute(select(func.count(Conversation.id)))).scalar_one()
    await db.execute(text("TRUNCATE TABLE conversations RESTART IDENTITY CASCADE"))
    await db.commit()
    return {"message": f"{count} conversation(s) supprimée(s)", "deleted_count": count}


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: int, db: DBSession, _: CurrentUser):
    """Retourne une conversation avec tous ses messages (utile dans l'historique)."""
    conv = (await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
                            .options(selectinload(Conversation.messages))
    )).scalar_one_or_none()
    if not conv:
        raise HTTPException(404, "Conversation introuvable")
    return conv


@router.patch("/{conversation_id}", response_model=ConversationResponse)
async def update_conversation(conversation_id: int, conv_in: ConversationUpdate, db: DBSession, _: CurrentUser):
    """Modifie le statut ou les flags d'une conversation (tous les champs optionnels)."""
    conv = await db.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(404, "Conversation introuvable")

    if conv_in.status         is not None : conv.status         = conv_in.status
    if conv_in.contact_name   is not None : conv.contact_name   = conv_in.contact_name
    if conv_in.is_flagged     is not None : conv.is_flagged     = conv_in.is_flagged
    if conv_in.requires_human is not None : conv.requires_human = conv_in.requires_human

    await db.commit()
    await db.refresh(conv)
    return conv


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(conversation_id: int, db: DBSession, _: CurrentUser):
    """Supprime une conversation et tous ses messages (cascade)."""
    conv = await db.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(404, "Conversation introuvable")
    await db.delete(conv)
    await db.commit()


@router.get("/{conversation_id}/messages", response_model=list[MessageResponse])
async def get_messages(conversation_id: int, db: DBSession, _: CurrentUser):
    """Retourne uniquement les messages d'une conversation, triés par date."""
    if not await db.get(Conversation, conversation_id):
        raise HTTPException(404, "Conversation introuvable")
    rows = (await db.execute(
        select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at)
    )).scalars().all()
    return rows
