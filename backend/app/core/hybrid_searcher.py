"""
hybrid_searcher.py — Moteur de recherche hybride (Vectoriel + BM25 + RRF).

RÔLE
─────
Combine deux stratégies de recherche complémentaires :
  1. Vectorielle (FAISS / pgvector) : sémantique — trouve les idées similaires
  2. Mots-clés  (SQL ILIKE)         : exacte    — trouve les termes précis (dosages, noms)

Fusion via Reciprocal Rank Fusion (RRF) :
  RRF(document) = Σ  1 / (k + rang_i(document))
  → pondère les documents bien classés dans les DEUX méthodes

CLASSES EXPORTÉES
──────────────────
  RetrievedChunk : chunk récupéré avec ses métadonnées
  RAGResponse    : réponse complète du moteur RAG
  HybridSearcher : moteur de recherche — méthodes publiques :
    search()              → recherche hybride (standard)
    search_cross_patient() → recherche par pathologie multi-patient
    search_keyword_only()  → recherche SQL uniquement (mode Flash < 200ms)
"""

import logging
from typing import List, Optional, Dict, Tuple
from dataclasses import dataclass
from collections import defaultdict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import joinedload

from app.config import settings
from app.models.chunk import DocumentChunk
from app.models.document import Document, DocumentStatus
from app.core.nlp.entity_extractor import EntityExtractor, STOP_WORDS_FR, _EN_FUNCTION_WORDS
from app.core.embeddings import get_embedding_service

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dataclasses partagées
# ---------------------------------------------------------------------------

@dataclass
class RetrievedChunk:
    """Chunk récupéré avec metadata enrichie"""
    chunk_id: int
    document_id: int
    document_title: str
    patient_name: str
    content: str
    section_title: str
    similarity_score: float
    page_number: int | None = None
    consultation_date: str | None = None
    confidence_score: float = 0.0
    metadata: Dict | None = None


@dataclass
class RAGResponse:
    """Réponse du moteur RAG"""
    answer: str
    sources: List[RetrievedChunk]
    confidence_score: float
    processing_time_ms: int
    token_count_input: int
    token_count_output: int
    tools_used: List[Dict] = None
    was_filtered: bool = False
    citation_map: List[Dict] = None  # Extraits numérotés [N] pour le frontend


# ---------------------------------------------------------------------------
# HybridSearcher
# ---------------------------------------------------------------------------

class HybridSearcher:
    """Moteur de recherche hybride (Vectoriel + Mots-clés + RRF)"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.extractor = EntityExtractor()
        self.embedding_service = get_embedding_service()

    def _strip_accents(self, text: str) -> str:
        return self.extractor._strip_accents(text)
        
    def _apply_firstname_filter(self, chunks: List, patient_name: str) -> List:
        """Désambiguïsation par prénom (Python, accent-insensible).
        Résout GARNIER Sophie ≠ GARNIER Benoît. Retourne liste vide si aucun match."""
        parts = patient_name.split()
        upper_parts = self.extractor.get_name_title_filters(patient_name)
        mixed_parts = [p for p in parts if p not in upper_parts]

        if not mixed_parts:
            return chunks

        firstname_stripped = self._strip_accents(mixed_parts[0])
        filtered = [
            c for c in chunks
            if firstname_stripped in self._strip_accents(c.document_title)
        ]
        return filtered

    async def search(self, db: AsyncSession, query: str, top_k: int = 5,
                     conversation_history: List[Dict] = None) -> List[RetrievedChunk]:
        """Recherche hybride (Vectoriel + Mots-clés + RRF)"""
        patient_name, terms = self.extractor.extract_entities(query, conversation_history)
        logger.info(f"Hybrid Search - Patient: {patient_name}, Terms: {terms}, top_k: {top_k}")

        # Note : la recherche vectorielle SQL (pgvector) est désactivée en local Windows.
        # Les vecteurs sont gérés par FAISS dans le retriever (app/core/rag/retriever.py).
        # Ici on fait uniquement la recherche par mots-clés (SQL ILIKE) + RRF.
        vector_chunks: list = []
        logger.info("Vector search: skipped (FAISS mode, no pgvector)")

        keyword_chunks = []
        if terms:
            stmt_kw = (
                select(DocumentChunk)
                .join(DocumentChunk.document)
                .options(joinedload(DocumentChunk.document))
                .where(Document.status == DocumentStatus.COMPLETED, Document.is_active == True)
            )
            conditions = [DocumentChunk.content.ilike(f"%{term}%") for term in terms]
            stmt_kw = stmt_kw.where(or_(*conditions)).limit(top_k * 2)
            if patient_name:
                filter_parts = self.extractor.get_name_title_filters(patient_name)
                stmt_kw = stmt_kw.where(and_(*[Document.title.ilike(f"%{p}%") for p in filter_parts]))

            result_kw = await db.execute(stmt_kw)
            keyword_chunks = [{"chunk": row[0], "score": 0.8} for row in result_kw]

            if not keyword_chunks and patient_name:
                logger.info(f"Keyword filter returned 0 → fallback patient-only for '{patient_name}'")
                filter_parts = self.extractor.get_name_title_filters(patient_name)
                stmt_fb = (
                    select(DocumentChunk)
                    .join(DocumentChunk.document)
                    .options(joinedload(DocumentChunk.document))
                    .where(
                        Document.status == DocumentStatus.COMPLETED,
                        Document.is_active == True,
                        *[Document.title.ilike(f"%{p}%") for p in filter_parts]
                    )
                    .order_by(DocumentChunk.chunk_index).limit(top_k)
                )
                result_fb = await db.execute(stmt_fb)
                keyword_chunks = [{"chunk": row[0], "score": 0.85} for row in result_fb]
                logger.info(f"Fallback fetch: {len(keyword_chunks)} chunks")

        elif patient_name:
            filter_parts = self.extractor.get_name_title_filters(patient_name)
            stmt_p = (
                select(DocumentChunk)
                .join(DocumentChunk.document)
                .options(joinedload(DocumentChunk.document))
                .where(
                    Document.status == DocumentStatus.COMPLETED,
                    Document.is_active == True,
                    *[Document.title.ilike(f"%{p}%") for p in filter_parts]
                )
                .order_by(DocumentChunk.chunk_index).limit(top_k)
            )
            result_p = await db.execute(stmt_p)
            keyword_chunks = [{"chunk": row[0], "score": 0.9} for row in result_p]

        logger.info(f"Keyword search: {len(keyword_chunks)} chunks found")

        fused_results = self._apply_rrf(vector_chunks, keyword_chunks, k=60)
        if patient_name:
            fused_results = self._apply_firstname_filter(fused_results, patient_name)

        return fused_results[:top_k]

    async def search_cross_patient(self, db: AsyncSession, pathology_terms: List[str],
                                   top_k: int = 20) -> List[RetrievedChunk]:
        """Recherche cross-patient par pathologie — max 2 chunks par patient."""
        conditions = [DocumentChunk.content.ilike(f"%{term}%") for term in pathology_terms]
        stmt = (
            select(DocumentChunk)
            .join(DocumentChunk.document)
            .options(joinedload(DocumentChunk.document))
            .where(
                Document.status == DocumentStatus.COMPLETED,
                Document.is_active == True,
                or_(*conditions)
            )
            .order_by(DocumentChunk.document_id, DocumentChunk.chunk_index)
            .limit(top_k * 6)
        )

        result = await db.execute(stmt)
        all_chunks = []
        for row in result:
            chunk = row[0]
            meta = chunk.metadata_ if hasattr(chunk, 'metadata_') and chunk.metadata_ else {}
            all_chunks.append(RetrievedChunk(
                chunk_id=chunk.id, document_id=chunk.document_id,
                document_title=chunk.document.title,
                patient_name=self.extractor.extract_patient_name_from_title(chunk.document.title),
                content=chunk.content, section_title=meta.get("section", "GENERAL"),
                similarity_score=0.85, page_number=chunk.page_number,
                consultation_date=meta.get("date"), confidence_score=85.0, metadata=meta
            ))

        MAX_PER_PATIENT = 2
        doc_counts: Dict[int, int] = {}
        retrieved = []
        for chunk in all_chunks:
            count = doc_counts.get(chunk.document_id, 0)
            if count < MAX_PER_PATIENT:
                retrieved.append(chunk)
                doc_counts[chunk.document_id] = count + 1
            if len(retrieved) >= top_k:
                break

        logger.info(f"Cross-patient: {len(retrieved)} chunks from "
                    f"{len(set(c.patient_name for c in retrieved))} patients")
        return retrieved

    async def search_keyword_only(self, db: AsyncSession, query: str,
                                  patient_name: str | None = None,
                                  top_k: int = 15, query_type: str = "specific",
                                  override_terms: List[str] = None) -> List[RetrievedChunk]:
        """Recherche SQL par mots-clés uniquement — zéro embedding. Mode Flash (<200ms)."""
        terms = override_terms if override_terms else self.extractor.extract_entities(query)[1]

        stmt = (
            select(DocumentChunk)
            .join(DocumentChunk.document)
            .options(joinedload(DocumentChunk.document))
            .where(Document.status == DocumentStatus.COMPLETED, Document.is_active == True)
            .order_by(DocumentChunk.chunk_index)
        )

        if patient_name:
            filter_parts = self.extractor.get_name_title_filters(patient_name)
            stmt = stmt.where(and_(*[Document.title.ilike(f"%{p}%") for p in filter_parts]))

        # Filtrer les termes trop courts (< 3 chars) pour éviter les faux positifs
        content_terms = [t for t in terms if len(t) >= 3]
        if patient_name:
            patient_words = {w.lower() for w in patient_name.split()}
            content_terms = [t for t in content_terms if t.lower() not in patient_words]

        apply_filter = bool(content_terms) and (not patient_name or query_type == "specific")
        if apply_filter:
            stmt = stmt.where(or_(*[DocumentChunk.content.ilike(f"%{t}%") for t in content_terms[:6]]))

        stmt = stmt.limit(top_k)
        result = await db.execute(stmt)
        retrieved = []
        for row in result:
            chunk = row[0]
            meta = chunk.metadata_ if hasattr(chunk, 'metadata_') and chunk.metadata_ else {}
            retrieved.append(RetrievedChunk(
                chunk_id=chunk.id, document_id=chunk.document_id,
                document_title=chunk.document.title,
                patient_name=self.extractor.extract_patient_name_from_title(chunk.document.title),
                content=chunk.content, section_title=meta.get("section", "GENERAL"),
                similarity_score=0.85, page_number=chunk.page_number,
                consultation_date=meta.get("date"), confidence_score=85.0, metadata=meta
            ))

        logger.info(f"Keyword-only: {len(retrieved)} chunks (patient={patient_name}, type={query_type})")
        return retrieved

    def _apply_rrf(self, vector_results, keyword_results, k=60):
        """Reciprocal Rank Fusion des résultats vectoriels + mots-clés."""
        scores = defaultdict(float)
        chunk_map = {}
        similarity_map = {}

        for rank, item in enumerate(vector_results):
            chunk = item["chunk"]
            chunk_map[chunk.id] = chunk
            scores[chunk.id] += 1 / (k + rank + 1)
            similarity_map[chunk.id] = item["score"]

        for rank, item in enumerate(keyword_results):
            chunk = item["chunk"]
            chunk_map[chunk.id] = chunk
            scores[chunk.id] += 1 / (k + rank + 1)
            if chunk.id not in similarity_map:
                similarity_map[chunk.id] = item["score"]

        retrieved = []
        for cid in sorted(scores.keys(), key=lambda x: scores[x], reverse=True):
            chunk = chunk_map[cid]
            meta = chunk.metadata_ if hasattr(chunk, 'metadata_') and chunk.metadata_ else {}
            sim = similarity_map.get(cid, 0.5)
            retrieved.append(RetrievedChunk(
                chunk_id=chunk.id, document_id=chunk.document_id,
                document_title=chunk.document.title,
                patient_name=self.extractor.extract_patient_name_from_title(chunk.document.title),
                content=chunk.content, section_title=meta.get("section", "GENERAL"),
                similarity_score=scores[cid], page_number=chunk.page_number,
                consultation_date=meta.get("date"),
                confidence_score=min(sim * 100, 100), metadata=meta
            ))

        return retrieved
