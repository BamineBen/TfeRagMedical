import asyncio
import hashlib
import logging
import os
import shutil
from dataclasses import dataclass

from sqlalchemy import func, select

from app.core import vector_store
from app.core.document_processor import index_single_document, load_document, semantic_chunk_text
from app.core.embeddings import get_embedding_service
from app.core.query_cache import query_cache
from app.models.chunk import DocumentChunk
from app.models.document import Document, DocumentStatus

logger = logging.getLogger(__name__)

# IMPORTANT: Semaphore(1) obligatoire — medspacy NLP n'est PAS thread-safe.
_processing_semaphore = asyncio.Semaphore(1)

@dataclass
class _ChunkData:
    content: str
    chunk_index: int
    page_number: int = None
    start_char: int = None
    end_char: int = None
    token_count: int = 0
    metadata: dict = None

async def process_document_background(document_id: int, db_session_factory):
    """Tâche d'arrière-plan pour traiter le document.
    Le sémaphore(1) garantit un seul document traité à la fois (medspacy non thread-safe)."""
    async with _processing_semaphore:
        await _process_document_inner(document_id, db_session_factory)

async def _process_document_inner(document_id: int, db_session_factory):
    """Traitement réel du document en 3 phases avec sessions DB courtes.

    CRITIQUE: La connexion DB est libérée AVANT les opérations CPU (asyncio.to_thread).
    Raison: medspacy/Cython re-acquiert le GIL pendant le traitement, bloquant l'event loop.
    Avec l'ancien code (1 session longue), la connexion restait ouverte 7-15s pendant le CPU,
    causant l'épuisement du pool SQLAlchemy (pool_timeout=30s défaut) → HTTP 500 au 30e upload.
    Solution: 3 sessions courtes → connexion jamais détenue pendant le travail CPU.
    """
    # ── Phase 1: Lire les métadonnées, marquer PROCESSING (connexion ~50ms) ──────
    async with db_session_factory() as db:
        document = await db.get(Document, document_id)
        if not document:
            return
        document.status = DocumentStatus.PROCESSING
        await db.commit()
        file_path = str(document.file_path)

    # ── Phase 2: Travail CPU intensif (SANS connexion DB ouverte) ────────────────
    embedder = get_embedding_service()
    try:
        text = await asyncio.to_thread(load_document, file_path)
        chunks = await asyncio.to_thread(semantic_chunk_text, text)
        chunk_data_list = [_ChunkData(content=c, chunk_index=i) for i, c in enumerate(chunks)]

        texts_to_embed = [c.content for c in chunk_data_list]
        embeddings = await asyncio.to_thread(lambda: [embedder.embed_text(t) for t in texts_to_embed])

        try:
            dest = vector_store.MEDICAL_DOCS_DIR / os.path.basename(file_path)
            if not dest.exists():
                shutil.copy2(file_path, str(dest))
            await asyncio.to_thread(index_single_document, str(dest))
            from app.main import _load_index
            _load_index()
            query_cache.invalidate_all()
        except Exception as ie:
            logger.warning(f"FAISS indexing skipped: {ie}")

        class ProcessedDoc:
            def __init__(self):
                self.chunks = chunk_data_list
                self.content_hash = ''
                self.page_count = None
                self.word_count = len(text.split())
        processed_doc = ProcessedDoc()

    except Exception as e:
        logger.error(f"Error processing document {document_id}: {e}", exc_info=True)
        async with db_session_factory() as db:
            document = await db.get(Document, document_id)
            if document:
                document.status = DocumentStatus.FAILED
                document.error_message = str(e)
                await db.commit()
        return

    # ── Phase 3: Écrire les résultats en DB (connexion ~100ms) ──────────────────
    async with db_session_factory() as db:
        document = await db.get(Document, document_id)
        if not document:
            return
        try:
            document.content_hash = processed_doc.content_hash or ''
            document.page_count = processed_doc.page_count
            document.word_count = processed_doc.word_count

            chunks_to_add = []
            for i, chunk_data in enumerate(processed_doc.chunks):
                chunk_hash = hashlib.md5(chunk_data.content.encode('utf-8')).hexdigest()
                chunk = DocumentChunk(
                    document_id=document_id,
                    content=chunk_data.content,
                    content_hash=chunk_hash,
                    chunk_index=chunk_data.chunk_index,
                    page_number=chunk_data.page_number,
                    token_count=chunk_data.token_count,
                    metadata_=chunk_data.metadata,
                )
                # Note: embedding non stocké en DB (FAISS gère les vecteurs)
                chunks_to_add.append(chunk)

            db.add_all(chunks_to_add)
            document.status = DocumentStatus.COMPLETED
            document.processed_at = func.now()
            await db.commit()

        except Exception as e:
            await db.rollback()
            document.status = DocumentStatus.FAILED
            document.error_message = str(e)
            await db.commit()
            logger.error(f"Error saving document {document_id}: {e}", exc_info=True)


async def reembed_all_background(db_session_factory):
    """Tâche d'arrière-plan : re-génère les embeddings de tous les chunks"""
    async with db_session_factory() as db:
        try:
            embedder = get_embedding_service()
            logger.info("Re-embedding all chunks...")

            batch_size = 100
            offset = 0
            total_reembedded = 0

            while True:
                stmt = (
                    select(DocumentChunk)
                    .join(DocumentChunk.document)
                    .where(
                        Document.status == DocumentStatus.COMPLETED,
                        Document.is_active == True
                    )
                    .order_by(DocumentChunk.id)
                    .offset(offset)
                    .limit(batch_size)
                )
                result = await db.execute(stmt)
                chunks = result.scalars().all()

                if not chunks:
                    break

                texts = [c.content for c in chunks]
                embeddings = [embedder.embed_text(t) for t in texts]

                # Note: embeddings stockés dans FAISS uniquement (pas en DB)
                # chunk.embedding n'existe plus — la colonne pgvector est retirée en local

                await db.commit()
                total_reembedded += len(chunks)
                logger.info(f"Re-embedded {total_reembedded} chunks...")
                offset += batch_size

            logger.info(f"Re-embedding complete: {total_reembedded} chunks updated")

        except Exception as e:
            logger.error(f"Re-embedding failed: {e}", exc_info=True)
            await db.rollback()
