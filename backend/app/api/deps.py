from typing import Optional, Annotated
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db, AsyncSessionLocal
from app.models.user import User, UserRole
from app.core.security import verify_token

security = HTTPBearer(auto_error=False)

async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)]
) -> User:
    if not credentials:
        raise HTTPException(status_code=401, detail="Non authentifié", headers={"WWW-Authenticate": "Bearer"})
    token_data = verify_token(credentials.credentials, "access")
    if not token_data:
        raise HTTPException(status_code=401, detail="Token invalide ou expiré", headers={"WWW-Authenticate": "Bearer"})
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.id == int(token_data.sub)))
        user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Compte désactivé")
    return user

async def get_current_admin_user(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Accès réservé aux administrateurs")
    return current_user

async def get_optional_user(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)]) -> User | None:
    if not credentials:
        return None
    token_data = verify_token(credentials.credentials, "access")
    if not token_data:
        return None
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.id == int(token_data.sub)))
        return result.scalar_one_or_none()

async def get_user_for_file(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    token: Optional[str] = None,
) -> User:
    raw_token = credentials.credentials if credentials else token
    if not raw_token:
        raise HTTPException(status_code=401, detail="Non authentifié")
    token_data = verify_token(raw_token, "access")
    if not token_data:
        raise HTTPException(status_code=401, detail="Token invalide")
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.id == int(token_data.sub)))
        user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Accès refusé")
    return user

CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentAdminUser = Annotated[User, Depends(get_current_admin_user)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]
DBSession = Annotated[AsyncSession, Depends(get_db)]
FileUser = Annotated[User, Depends(get_user_for_file)]