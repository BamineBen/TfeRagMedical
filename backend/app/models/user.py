from datetime import datetime
from enum import Enum
from typing import List
from sqlalchemy import String, Boolean, DateTime, Text, Enum as SQLEnum, Integer
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy.sql import func
from app.database import Base


class UserRole(str, Enum):
    ADMIN = "admin"
    USER = "user"


class UserLLMMode(str, Enum):
    LOCAL = "local"
    MISTRAL = "mistral"
    GEMINI = "gemini"


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[UserRole] = mapped_column(SQLEnum(UserRole), default=UserRole.USER, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    preferred_llm_mode: Mapped[str] = mapped_column(String(20), default="local", server_default="local", nullable=False)
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    documents: Mapped[List["Document"]] = relationship("Document", back_populates="uploaded_by_user", lazy="selectin")
    conversations: Mapped[List["Conversation"]] = relationship("Conversation", back_populates="user", lazy="selectin")

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN