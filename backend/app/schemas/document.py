from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from app.models.document import DocumentStatus, DocumentType
from .base import PaginatedList


class DocumentCreate(BaseModel):
    title       : str      = Field(..., min_length=1, max_length=500)
    description : str|None = None
    category    : str|None = Field(None, max_length=100)
    tags        : list[str]|None = None


class DocumentUpdate(BaseModel):
    title       : str|None      = Field(None, min_length=1, max_length=500)
    description : str|None      = None
    category    : str|None      = Field(None, max_length=100)
    tags        : list[str]|None = None
    is_active   : bool|None     = None


class DocumentResponse(BaseModel):
    id            : int
    title         : str
    filename      : str
    file_size     : int
    file_type     : DocumentType
    status        : DocumentStatus
    description   : str|None          = None
    category      : str|None          = None
    tags          : list[str]|None    = None
    page_count    : int|None          = None
    word_count    : int|None          = None
    chunk_count   : int               = 0
    is_active     : bool              = True
    uploaded_by   : int|None          = None
    error_message : str|None          = None
    created_at    : datetime
    updated_at    : datetime
    processed_at  : datetime|None     = None

    model_config = ConfigDict(from_attributes=True)


class DocumentList(PaginatedList[DocumentResponse]):
    pass


class DocumentChunkResponse(BaseModel):
    id               : int
    document_id      : int
    content          : str
    chunk_index      : int
    page_number      : int|None   = None
    token_count      : int
    similarity_score : float|None = None

    model_config = ConfigDict(from_attributes=True)
