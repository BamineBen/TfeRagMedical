from datetime import datetime
from enum import Enum
from typing import Optional, TYPE_CHECKING
from sqlalchemy import Boolean, DateTime, Enum as SQLEnum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base

if TYPE_CHECKING:
    from .conversation import Conversation


class MessageRole(str, Enum):
    USER      = "user"
    ASSISTANT = "assistant"
    SYSTEM    = "system"


class MessageStatus(str, Enum):
    PENDING   = "pending"
    SENT      = "sent"
    DELIVERED = "delivered"
    READ      = "read"
    FAILED    = "failed"


class Message(Base):
    __tablename__ = "messages"

    id : Mapped[int] = mapped_column(Integer, primary_key=True)

    content : Mapped[str]         = mapped_column(Text, nullable=False)
    role    : Mapped[MessageRole] = mapped_column(SQLEnum(MessageRole), nullable=False, index=True)
    status  : Mapped[MessageStatus] = mapped_column(SQLEnum(MessageStatus), default=MessageStatus.PENDING, nullable=False)

    sources_json      : Mapped[str|None]   = mapped_column(Text)
    tools_used_json   : Mapped[str|None]   = mapped_column(Text)
    confidence_score  : Mapped[float|None] = mapped_column(Float)

    processing_time_ms  : Mapped[int|None] = mapped_column(Integer)
    token_count_input   : Mapped[int|None] = mapped_column(Integer)
    token_count_output  : Mapped[int|None] = mapped_column(Integer)

    feedback_rating  : Mapped[int|None] = mapped_column(Integer)
    feedback_comment : Mapped[str|None] = mapped_column(Text)

    is_error      : Mapped[bool]     = mapped_column(Boolean, default=False, nullable=False)
    error_message : Mapped[str|None] = mapped_column(Text)

    created_at   : Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    delivered_at : Mapped[datetime|None] = mapped_column(DateTime(timezone=True))

    conversation_id : Mapped[int] = mapped_column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)

    conversation : Mapped["Conversation"] = relationship("Conversation", back_populates="messages")

    @property
    def preview(self) -> str:
        return self.content[:50] + "…" if len(self.content) > 50 else self.content

    def __repr__(self) -> str:
        return f"<Message {self.role.value} conv={self.conversation_id}>"
