from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from app.models.user import User, UserRole
from app.schemas.auth import LoginRequest, Token, RefreshTokenRequest, PasswordChangeRequest
from app.schemas.user import UserCreate, UserResponse
from app.core.security import verify_password, get_password_hash, create_access_token, create_refresh_token, verify_token
from app.api.deps import CurrentUser, DBSession
from app.config import settings

router = APIRouter()

@router.post("/login", response_model=Token)
async def login(request: LoginRequest, db: DBSession):
    result = await db.execute(
        select(User).where((User.username == request.username) | (User.email == request.username))
    )
    user = result.scalar_one_or_none()
    if not user or not verify_password(request.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Identifiants incorrects")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Compte désactivé")
    access_token = create_access_token(str(user.id), user.role.value)
    refresh_token = create_refresh_token(str(user.id), user.role.value)
    user.refresh_token = refresh_token
    user.last_login = datetime.now(timezone.utc)
    await db.commit()
    return Token(access_token=access_token, refresh_token=refresh_token,
                 token_type="bearer", expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60)

@router.post("/refresh", response_model=Token)
async def refresh_token(request: RefreshTokenRequest, db: DBSession):
    token_data = verify_token(request.refresh_token, "refresh")
    if not token_data:
        raise HTTPException(status_code=401, detail="Refresh token invalide ou expiré")
    result = await db.execute(select(User).where(User.id == int(token_data.sub)))
    user = result.scalar_one_or_none()
    if not user or user.refresh_token != request.refresh_token:
        raise HTTPException(status_code=401, detail="Refresh token invalide")
    access_token = create_access_token(str(user.id), user.role.value)
    new_rt = create_refresh_token(str(user.id), user.role.value)
    user.refresh_token = new_rt
    await db.commit()
    return Token(access_token=access_token, refresh_token=new_rt,
                 token_type="bearer", expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60)

@router.post("/logout")
async def logout(current_user: CurrentUser, db: DBSession):
    current_user.refresh_token = None
    await db.commit()
    return {"message": "Déconnexion réussie"}

@router.get("/me", response_model=UserResponse)
async def get_me(current_user: CurrentUser):
    return current_user

@router.post("/change-password")
async def change_password(request: PasswordChangeRequest, current_user: CurrentUser, db: DBSession):
    if not verify_password(request.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Mot de passe actuel incorrect")
    current_user.hashed_password = get_password_hash(request.new_password)
    current_user.refresh_token = None
    await db.commit()
    return {"message": "Mot de passe modifié avec succès"}