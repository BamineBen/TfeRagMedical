from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from app.models.message import MessageRole, MessageStatus


class MessageCreate(BaseModel):
    conversation_id : int
    content         : str = Field(default="")
    role            : MessageRole


class MessageResponse(BaseModel):
    id                  : int
    conversation_id     : int
    content             : str
    role                : MessageRole
    status              : MessageStatus
    confidence_score    : float|None  = None
    processing_time_ms  : int|None    = None
    token_count_input   : int|None    = None
    token_count_output  : int|None    = None
    is_error            : bool        = False
    error_message       : str|None    = None
    created_at          : datetime

    model_config = ConfigDict(from_attributes=True)


class ChatRequest(BaseModel):
    message         : str           = Field(..., min_length=1, max_length=10_000)
    patient_id      : int|None      = None
    conversation_id : int|None      = None
    session_id      : str|None      = None
    channel         : str           = "web"
    use_rag         : bool          = True
    llm_mode        : str|None      = None
    model_mode      : str|None      = None
    phone_number    : str|None      = None


class SourceDocument(BaseModel):
    document_title   : str
    chunk_content    : str
    similarity_score : float
    document_id      : int          = 0
    page_number      : int|None     = None


class ChatResponse(BaseModel):
    message_id          : int
    conversation_id     : int
    session_id          : str
    response            : str
    sources             : list[SourceDocument] = []
    confidence_score    : float|None           = None
    processing_time_ms  : int
    token_count_input   : int
    token_count_output  : int
