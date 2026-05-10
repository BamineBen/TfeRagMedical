"""
chunk.py — Fragment vectorisé d'un document médical.

ARCHITECTURE VECTORIELLE :
  Les embeddings sont dans FAISS (/app/data/faiss_index.bin).
  Cette table PostgreSQL stocke uniquement texte + métadonnées.
  La colonne embedding pgvector est retirée pour compatibilité Windows local.
  En production Linux (Docker pgvector/pgvector:pg16), elle peut être réajoutée.
"""
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base

if TYPE_CHECKING:
    from app.models.document import Document


class DocumentChunk(Base):
    """
    Fragment de document. Les vecteurs sont dans FAISS, pas dans cette table.
    """
    __tablename__ = "document_chunks"

    id           : Mapped[int]       = mapped_column(Integer, primary_key=True, index=True)
    document_id  : Mapped[int]       = mapped_column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    content      : Mapped[str]       = mapped_column(Text,       nullable=False)
    content_hash : Mapped[str]       = mapped_column(String(64), nullable=False, index=True)
    chunk_index  : Mapped[int]       = mapped_column(Integer,    nullable=False)
    page_number  : Mapped[int|None]  = mapped_column(Integer,    nullable=True)
    token_count  : Mapped[int]       = mapped_column(Integer,    nullable=False, default=0)
    metadata_    : Mapped[dict|None] = mapped_column(JSONB,      nullable=True)
    created_at   : Mapped[datetime]  = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    document: Mapped["Document"] = relationship("Document", back_populates="chunks")
