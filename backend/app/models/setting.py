from datetime import datetime
from typing import Optional
from sqlalchemy import String, DateTime, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.database import Base

class SystemSetting(Base):
    __tablename__ = "system_settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True, index=True)
    value: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    updated_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

DEFAULT_SETTINGS = [
    {"key": "gemini_enabled",  "value": "true", "description": "Activer Gemini"},
    {"key": "mistral_enabled", "value": "true", "description": "Activer Mistral"},
    {"key": "tools_enabled",   "value": "true", "description": "Activer les outils LLM"},
]