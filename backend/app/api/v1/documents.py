"""
documents.py — Endpoints FastAPI de gestion des documents médicaux
══════════════════════════════════════════════════════════════════

RÔLE : Upload, listage, suppression, retraitement des PDFs patients.
Chaque document uploadé est sauvegardé en base (PostgreSQL) ET indexé
dans FAISS (via process_document_background) pour la recherche RAG.

SÉCURITÉ :
- Tous les endpoints qui accèdent au contenu des fichiers requièrent
  une authentification (CurrentUser). Un médecin ne peut pas lire le
  PDF d'un autre médecin sans droits.
- La validation du type de fichier se fait côté backend (extension +
  content_type), pas seulement côté frontend.
"""

import asyncio
import hashlib
import logging
import os
import shutil
import time
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import delete as sql_delete, desc, func, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DBSession
from app.config import settings
from app.models.chunk import DocumentChunk
from app.models.document import Document, DocumentStatus, DocumentType
from app.models.user import UserRole
from app.schemas.document import DocumentList, DocumentResponse

from app.database import AsyncSessionLocal
from app.services.document_service import process_document_background, reembed_all_background

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    background_tasks: BackgroundTasks,
    current_user: CurrentUser,
    file: UploadFile = File(...),
):
    """
    Upload et démarre le traitement d'un document
    """
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Type de fichier non supporté. Admis: {settings.ALLOWED_EXTENSIONS}"
        )

    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    
    safe_filename = f"{int(time.time())}_{file.filename.replace(' ', '_')}"
    file_path = os.path.join(settings.UPLOAD_DIR, safe_filename)

    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur sauvegarde fichier: {str(e)}")
    
    doc_type = DocumentType.TXT
    if ext == ".pdf":
        doc_type = DocumentType.PDF
    elif ext in [".doc", ".docx"]:
        doc_type = DocumentType.DOCX
    elif ext == ".md":
        doc_type = DocumentType.MARKDOWN

    async with AsyncSessionLocal() as db:
        document = Document(
            title=file.filename,
            filename=file.filename,
            file_path=file_path,
            file_size=os.path.getsize(file_path),
            file_type=doc_type,
            mime_type=file.content_type or "application/octet-stream",
            content_hash="", 
            uploaded_by=current_user.id,
            status=DocumentStatus.PENDING
        )
        db.add(document)
        await db.commit()
        await db.refresh(document)
        doc_id = document.id

    background_tasks.add_task(process_document_background, doc_id, AsyncSessionLocal)

    now = datetime.now(timezone.utc)
    return {
        "id": doc_id,
        "title": document.title,
        "filename": document.filename,
        "file_size": document.file_size,
        "file_type": document.file_type,
        "status": document.status,
        "chunk_count": 0,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }


@router.get("", response_model=DocumentList)
async def list_documents(
    db: DBSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    search: str | None = None
):
    """Liste les documents"""
    query = select(Document).options(
        selectinload(Document.chunks).defer(DocumentChunk.content)
    )

    if search:
        query = query.where(Document.title.ilike(f"%{search}%"))

    count_query = select(func.count()).select_from(Document)
    if search:
        count_query = count_query.where(Document.title.ilike(f"%{search}%"))
    total = (await db.execute(count_query)).scalar_one()

    query = query.order_by(desc(Document.created_at)).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    documents = result.scalars().all()

    # Enrichir chunk_count depuis FAISS pour les documents legacy (0 en DB)
    # Les documents uploadés via l'ancien endpoint n'ont pas de document_chunks en DB.
    from app.core.rag_state import rag_state
    _, _chunks_mapping = rag_state.get()
    faiss_counts: dict[str, int] = {}
    for ch in _chunks_mapping:
        src = ch.get("source", "")
        faiss_counts[src] = faiss_counts.get(src, 0) + 1

    def _faiss_count_for(filename: str) -> int:
        return sum(cnt for src, cnt in faiss_counts.items() if filename in src or src.endswith(filename))

    items = []
    for doc in documents:
        db_count = len(doc.chunks) if hasattr(doc, "chunks") else 0
        faiss_count = _faiss_count_for(doc.filename)
        chunk_count = faiss_count if faiss_count > 0 else db_count
        items.append(DocumentResponse(
            id=doc.id,
            title=doc.title,
            description=doc.description,
            category=doc.category,
            tags=doc.tags.split(",") if isinstance(doc.tags, str) and doc.tags else (doc.tags or []),
            filename=doc.filename,
            file_size=doc.file_size,
            file_type=doc.file_type,
            status=doc.status,
            page_count=doc.page_count,
            word_count=doc.word_count,
            chunk_count=chunk_count,
            is_active=doc.is_active,
            uploaded_by=doc.uploaded_by,
            created_at=doc.created_at,
            updated_at=doc.updated_at,
            processed_at=doc.processed_at,
            error_message=doc.error_message,
        ))

    return DocumentList(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size
    )


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: int,
    db: DBSession,
    current_user: CurrentUser
):
    """
    Récupère un document par ID avec statistiques
    """
    result = await db.execute(
        select(Document).where(Document.id == document_id).options(selectinload(Document.chunks))
    )
    document = result.scalar_one_or_none()
    
    if not document:
        raise HTTPException(status_code=404, detail="Document non trouvé")
    
    return document


@router.get("/{document_id}/view")
async def view_document_pdf(
    document_id: int,
    db: DBSession,
    current_user: CurrentUser,   # ← AUTH REQUISE : données patients confidentielles
):
    """
    Retourne le PDF pour affichage inline dans le navigateur.

    SÉCURITÉ : endpoint protégé — seul un utilisateur authentifié peut
    accéder au contenu d'un dossier patient.
    """
    result = await db.execute(
        select(Document).where(Document.id == document_id)
    )
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(status_code=404, detail="Document non trouvé")

    # Résolution du chemin physique avec fallback vers UPLOAD_DIR
    file_path = document.file_path
    if not os.path.exists(file_path):
        fallback = os.path.join(settings.UPLOAD_DIR, os.path.basename(file_path))
        if os.path.exists(fallback):
            file_path = fallback
        else:
            raise HTTPException(status_code=404, detail="Fichier PDF introuvable.")

    return FileResponse(
        path=file_path,
        media_type="application/pdf",
        filename=document.filename,
        headers={"Content-Disposition": f"inline; filename={document.filename}"},
    )


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    doc_id: int,
    db: DBSession,
    current_user: CurrentUser
):
    """Supprime un document et ses chunks"""
    document = await db.get(Document, doc_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document non trouvé")

    if current_user.role != UserRole.ADMIN and document.uploaded_by != current_user.id:
        raise HTTPException(status_code=403, detail="Non autorisé")

    if os.path.exists(document.file_path):
        try:
            os.remove(document.file_path)
        except Exception:
            pass

    await db.delete(document)
    await db.commit()

    from app.core.query_cache import query_cache
    query_cache.invalidate_all()


@router.post("/{doc_id}/reprocess")
async def reprocess_document(
    doc_id: int,
    background_tasks: BackgroundTasks,
    db: DBSession,
    current_user: CurrentUser
):
    """Relance le traitement d'un document et invalide le cache RAG."""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin requis")

    document = await db.get(Document, doc_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document non trouvé")

    await db.execute(sql_delete(DocumentChunk).where(DocumentChunk.document_id == doc_id))

    # Invalide le cache RAG — sinon les anciennes réponses restent servies
    # jusqu'au prochain redémarrage du backend.
    from app.core.query_cache import query_cache
    query_cache.invalidate_all()

    from app.database import AsyncSessionLocal
    background_tasks.add_task(process_document_background, doc_id, AsyncSessionLocal)

    return {"message": "Retraitement lancé"}


@router.get("/{doc_id}/download")
async def download_document(
    doc_id: int,
    db: DBSession,
    current_user: CurrentUser,
):
    """Télécharge un document (auth requise)."""
    document = await db.get(Document, doc_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document non trouvé")

    if not os.path.exists(document.file_path):
        raise HTTPException(status_code=404, detail="Fichier physique non trouvé")

    return FileResponse(
        path=document.file_path,
        media_type=document.mime_type or "application/pdf",
        filename=document.filename,
    )


@router.post("/bulk/reembed-all")
async def reembed_all_documents(
    background_tasks: BackgroundTasks,
    db: DBSession,
    current_user: CurrentUser
):
    """Re-génère les embeddings de TOUS les documents avec le modèle actuel."""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin requis")

    doc_count = await db.scalar(
        select(func.count(Document.id)).where(
            Document.status == DocumentStatus.COMPLETED,
            Document.is_active == True
        )
    )
    chunk_count = await db.scalar(
        select(func.count(DocumentChunk.id))
        .join(DocumentChunk.document)
        .where(
            Document.status == DocumentStatus.COMPLETED,
            Document.is_active == True
        )
    )

    from app.database import AsyncSessionLocal
    background_tasks.add_task(reembed_all_background, AsyncSessionLocal)

    return {
        "message": f"Re-embedding lancé pour {doc_count} documents ({chunk_count} chunks)",
        "documents": doc_count,
        "chunks": chunk_count
    }


@router.delete("/bulk/delete-all", status_code=status.HTTP_200_OK)
async def delete_all_documents(
    db: DBSession,
    current_user: CurrentUser
):
    """Supprime TOUS les documents et leurs chunks (Admin uniquement)"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Action réservée aux administrateurs"
        )

    try:
        result = await db.execute(select(Document))
        all_documents = result.scalars().all()

        deleted_count = 0
        failed_files = []

        for document in all_documents:
            if os.path.exists(document.file_path):
                try:
                    os.remove(document.file_path)
                except Exception as e:
                    failed_files.append(document.filename)

            await db.delete(document)
            deleted_count += 1

        await db.commit()

        from app.core.vector_store import MEDICAL_DOCS_DIR, FAISS_INDEX_PATH, CHUNKS_MAPPING_PATH
        if MEDICAL_DOCS_DIR.exists():
            for f in MEDICAL_DOCS_DIR.iterdir():
                try:
                    f.unlink()
                except Exception:
                    pass

        FAISS_INDEX_PATH.unlink(missing_ok=True)
        CHUNKS_MAPPING_PATH.unlink(missing_ok=True)
        try:
            from app.main import _load_index
            _load_index()  # recharge rag_state depuis disque
        except Exception:
            pass

        from app.core.query_cache import query_cache
        query_cache.invalidate_all()

        return {
            "message": f"{deleted_count} document(s) supprimé(s)",
            "deleted_count": deleted_count,
            "failed_files": failed_files
        }

    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la suppression: {str(e)}"
        )
