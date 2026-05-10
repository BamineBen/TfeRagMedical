from datetime import datetime
from enum import Enum
from typing import Optional, List, TYPE_CHECKING
from sqlalchemy import String, DateTime, Text, Enum as SQLEnum, Integer, ForeignKey, Boolean
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy.sql import func
from app.database import Base
if TYPE_CHECKING:
    from app.models.user import User
    from app.models.message import Message

class ConversationChannel(str, Enum):
    SMS = "sms"; WHATSAPP = "whatsapp"; WEB = "web"; API = "api"

class ConversationStatus(str, Enum):
    ACTIVE = "active"; CLOSED = "closed"; ARCHIVED = "archived"

class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    channel: Mapped[ConversationChannel] = mapped_column(SQLEnum(ConversationChannel), nullable=False, index=True)
    phone_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[ConversationStatus] = mapped_column(SQLEnum(ConversationStatus), default=ConversationStatus.ACTIVE, nullable=False)
    context_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_flagged: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    requires_human: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    user: Mapped[Optional["User"]] = relationship("User", back_populates="conversations")
    messages: Mapped[List["Message"]] = relationship("Message", back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at", lazy="selectin")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)