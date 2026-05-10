from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, EmailStr
from app.models.user import UserRole, UserLLMMode
from .base import PaginatedList

class UserBase(BaseModel):
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=100)
    full_name: str | None = Field(None, max_length=255)

class UserCreate(UserBase):
    password: str = Field(..., min_length=8)
    role: UserRole = UserRole.USER

class UserUpdate(BaseModel):
    email: EmailStr | None = None
    username: str | None = Field(None, min_length=3, max_length=100)
    full_name: str | None = None
    is_active: bool | None = None
    role: UserRole | None = None

class UserLLMModeUpdate(BaseModel):
    preferred_llm_mode: UserLLMMode

class UserResponse(UserBase):
    id: int
    role: UserRole
    is_active: bool
    is_verified: bool
    preferred_llm_mode: str = "local"
    created_at: datetime
    last_login: datetime | None = None
    model_config = ConfigDict(from_attributes=True)

class UserList(PaginatedList[UserResponse]):
    pass