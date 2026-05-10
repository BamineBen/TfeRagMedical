"""
users.py — Endpoints FastAPI pour la gestion des utilisateurs.

ACCÈS :
  /users/me*      → tout utilisateur connecté (son propre profil)
  /users          → admin uniquement (liste, création, modification, suppression)

HELPER _get_or_404 :
  Éviter de répéter le pattern "db.get → si None → raise 404" dans chaque endpoint.
  Exemple d'utilisation : user = await _get_or_404(db, User, user_id)
"""
from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import desc, func, or_, select

from app.api.deps import CurrentAdminUser, CurrentUser, DBSession
from app.core.llm_client import get_available_modes
from app.core.security import get_password_hash
from app.models.user import User, UserRole
from app.schemas.user import UserCreate, UserList, UserLLMModeUpdate, UserResponse, UserUpdate

router = APIRouter()


#  Helper DRY 

async def _get_or_404(db, model, pk: int):
    """
    Récupère un objet par sa clé primaire ou lève une erreur 404.

    Sans ce helper, chaque endpoint répète :
        obj = await db.get(Model, pk)
        if not obj:
            raise HTTPException(404, "Non trouvé")

    Avec ce helper : obj = await _get_or_404(db, Model, pk)
    """
    obj = await db.get(model, pk)
    if not obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{model.__name__} introuvable",
        )
    return obj


#  Profil de l'utilisateur connecté 

@router.get("/me", response_model=UserResponse)
async def get_me(current_user: CurrentUser):
    """Retourne le profil de l'utilisateur connecté."""
    return current_user


@router.get("/me/llm-modes")
async def get_my_llm_modes(current_user: CurrentUser):
    """
    Liste les 3 modes LLM disponibles + le mode préféré de l'utilisateur.
    Utilisé par le toggle LLM dans la navbar.
    """
    return {"current": current_user.preferred_llm_mode, "modes": get_available_modes()}


@router.put("/me/llm-mode", response_model=UserResponse)
async def update_my_llm_mode(payload: UserLLMModeUpdate, db: DBSession, current_user: CurrentUser):
    """
    Met à jour le mode LLM préféré (local | mistral | gemini).
    La préférence est sauvegardée en DB et persist entre les sessions.
    """
    user = await _get_or_404(db, User, current_user.id)
    user.preferred_llm_mode = payload.preferred_llm_mode.value
    await db.commit()
    await db.refresh(user)
    return user


#  Admin : CRUD utilisateurs 

@router.get("", response_model=UserList)
async def list_users(
    db         : DBSession,
    _          : CurrentAdminUser,                    # _ = variable ignorée (on vérifie juste l'accès)
    page       : int      = Query(1, ge=1),
    page_size  : int      = Query(20, ge=1, le=100),
    search     : str|None = None,
):
    """Liste tous les utilisateurs (paginée + recherche par username/email/nom)."""
    q = select(User)
    if search:
        p = f"%{search}%"
        q = q.where(or_(User.username.ilike(p), User.email.ilike(p), User.full_name.ilike(p)))

    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    users = (await db.execute(q.order_by(desc(User.created_at)).offset((page - 1) * page_size).limit(page_size))).scalars().all()

    return UserList(items=users, total=total, page=page, page_size=page_size, pages=-(-total // page_size))


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(user_in: UserCreate, db: DBSession, _: CurrentAdminUser):
    """Crée un nouvel utilisateur (admin uniquement)."""
    # Vérifier les doublons email et username en une seule requête
    existing = (await db.execute(
        select(User).where(or_(User.email == user_in.email, User.username == user_in.username))
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Email ou nom d'utilisateur déjà utilisé")

    user = User(
        email=user_in.email, username=user_in.username, full_name=user_in.full_name,
        hashed_password=get_password_hash(user_in.password),
        role=user_in.role, is_active=True, is_verified=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(user_id: int, db: DBSession, _: CurrentAdminUser):
    """Récupère un utilisateur par son ID."""
    return await _get_or_404(db, User, user_id)


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(user_id: int, user_in: UserUpdate, db: DBSession, _: CurrentAdminUser):
    """Modifie un utilisateur. Vérifie l'unicité du nouveau username/email si changés."""
    user = await _get_or_404(db, User, user_id)

    # Vérifier unicité du nouveau username (seulement si changé)
    if user_in.username and user_in.username != user.username:
        if (await db.execute(select(User).where(User.username == user_in.username))).scalar_one_or_none():
            raise HTTPException(400, "Nom d'utilisateur déjà pris")
        user.username = user_in.username

    # Vérifier unicité du nouvel email (seulement si changé)
    if user_in.email and user_in.email != user.email:
        if (await db.execute(select(User).where(User.email == user_in.email))).scalar_one_or_none():
            raise HTTPException(400, "Email déjà utilisé")
        user.email = user_in.email

    # Appliquer les autres changements (uniquement si la valeur est fournie)
    if user_in.full_name is not None : user.full_name = user_in.full_name
    if user_in.role      is not None : user.role      = user_in.role
    if user_in.is_active is not None : user.is_active = user_in.is_active

    await db.commit()
    await db.refresh(user)
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: int, db: DBSession, current_user: CurrentAdminUser):
    """Supprime un utilisateur. Un admin ne peut pas supprimer son propre compte."""
    if user_id == current_user.id:
        raise HTTPException(400, "Impossible de supprimer son propre compte")

    user = await _get_or_404(db, User, user_id)
    await db.delete(user)
    await db.commit()
