from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from app.models.conversation import ConversationChannel, ConversationStatus
from .base import PaginatedList
from .message import MessageResponse


class ConversationCreate(BaseModel):
    channel      : ConversationChannel
    session_id   : str|None = None
    phone_number : str|None = Field(None, max_length=20)
    contact_name : str|None = Field(None, max_length=255)


class ConversationUpdate(BaseModel):
    status         : ConversationStatus|None = None
    contact_name   : str|None                = Field(None, max_length=255)
    is_flagged     : bool|None               = None
    requires_human : bool|None               = None


class ConversationResponse(BaseModel):
    id              : int
    session_id      : str
    channel         : ConversationChannel
    phone_number    : str|None               = None
    contact_name    : str|None               = None
    status          : ConversationStatus
    message_count   : int                    = 0
    is_flagged      : bool                   = False
    requires_human  : bool                   = False
    context_summary : str|None               = None
    created_at      : datetime
    updated_at      : datetime
    last_message_at : datetime|None          = None

    model_config = ConfigDict(from_attributes=True)


class ConversationDetail(ConversationResponse):
    messages: list[MessageResponse] = []


class ConversationList(PaginatedList[ConversationResponse]):
    pass
