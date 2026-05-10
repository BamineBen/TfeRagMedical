"""
notes.py — Endpoints FastAPI pour les Notes Atomiques
══════════════════════════════════════════════════════

RÔLE : Création et mise à jour de notes médicales courtes directement
indexées dans FAISS (ajout incrémental O(1), sans rebuild complet).

FLUX D'UNE NOTE :
  1. POST /notes       → crée en DB (table `notes`) + encode 1 chunk FAISS
  2. PUT  /notes/{id}  → soft-delete ancien chunk (active=False) + nouveau chunk
  3. GET  /notes/patients → liste des patients pour l'autocomplete frontend

PRINCIPE :
  Contrairement aux PDFs (uploadés + découpés en N chunks), une note
  produit exactement 1 chunk. Cela permet l'indexation instantanée
  sans recharger tout l'index (hot-update).
"""
import re
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CurrentUser
from app.core import vector_store
from app.core.rag_state import rag_state
from app.database import AsyncSessionLocal
from app.models.note import Note
from app.utils.naming import patient_label_lower as _label_from_source

router = APIRouter()
logger = logging.getLogger(__name__)

VALID_CATEGORIES = {
    "CONSULTATIONS", "BIOLOGIE", "TRAITEMENTS", "IMAGERIE",
    "ECG", "CONSTANTES", "VACCINATIONS", "HOSPITALISATIONS",
    "EXAMENS", "ALLERGIES", "ANTECEDENTS", "AUTRE",
}

CATEGORY_LABELS = sorted(VALID_CATEGORIES)


class NoteCreate(BaseModel):
    patient_name: str
    category: str = "CONSULTATIONS"
    date: str | None = None   # "2026-03-05" — défaut = aujourd'hui
    text: str


def _find_patient_source(patient_name: str, chunks_mapping: list) -> str | None:
    """Trouve la source FAISS d'un patient par correspondance de nom."""
    name_lower = patient_name.lower().strip()
    known: dict[str, str] = {}
    for c in chunks_mapping:
        src = c["source"]
        lbl = _label_from_source(src)
        if lbl and lbl not in known:
            known[lbl] = src

    if name_lower in known:
        return known[name_lower]

    parts = name_lower.split()
    if len(parts) >= 2:
        for label, src in known.items():
            if all(p in label for p in parts):
                return src
    return None


def _make_source(patient_name: str) -> str:
    parts = patient_name.strip().split()
    if len(parts) >= 2:
        return f"NOTE_{parts[-1].upper()}_{parts[0].capitalize()}.txt"
    return f"NOTE_{patient_name.replace(' ', '_').upper()}.txt"


def _make_note_id() -> str:
    return f"note_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S%f')[:22]}"


def _note_to_dict(note: Note) -> dict:
    body = re.sub(r'^[A-Z]+\n\[\d{4}-\d{2}-\d{2}\]\n', '', note.text, flags=re.MULTILINE)
    return {
        "note_id": note.note_id,
        "source": note.source,
        "patient": _label_from_source(note.source).title(),
        "category": note.category,
        "date": note.note_date,
        "indexed_at": note.created_at.isoformat() if note.created_at else "",
        "updated_at": note.updated_at.isoformat() if note.updated_at else "",
        "text": body.strip(),
        "preview": body.strip()[:200],
    }


async def _index_in_faiss(note_id: str, source: str, category: str, note_date: str, text: str) -> None:
    """
    Encode et ajoute une note dans l'index FAISS de façon incrémentale.

    THREAD SAFETY
    ─────────────
    Cette fonction utilise rag_state.write_lock pour garantir qu'un seul
    médecin peut créer/modifier une note à la fois.

    POURQUOI LE LOCK ICI ?
    ──────────────────────
    Sans lock, deux notes créées simultanément :
      Médecin A : load_mapping(3462) → append → save(3463)
      Médecin B : load_mapping(3462) → append → save(3463)  ← écrase A !
    Résultat : 3463 chunks au lieu de 3464. La note de A est perdue.

    Avec le lock : A puis B s'exécutent séquentiellement → 3464 chunks.
    """
    from app.core.embeddings import get_embedding_service
    from app.core.document_processor import extract_date_score
    from app.core.query_cache import query_cache
    from app.core.bm25_engine import bm25_engine

    chunk_text = f"{category}\n[{note_date}]\n{text}"
    date_score = extract_date_score(chunk_text) or extract_date_score(note_date)

    # Encoder le vecteur EN DEHORS du lock (opération CPU lente ~100ms)
    # → les autres médecins peuvent lire l'état pendant ce temps
    emb = get_embedding_service()
    new_embedding = emb.encode([chunk_text])

    # Toute la séquence read-modify-write est atomique grâce au lock
    async with rag_state.write_lock:
        # Charger l'index FAISS (depuis disque ou mémoire)
        try:
            idx = vector_store.load_index()
        except FileNotFoundError:
            from app.core.embeddings import get_dimension
            idx = vector_store.create_index(get_dimension())

        vector_store.add_vectors(idx, new_embedding)
        vector_store.save_index(idx)

        # Charger, modifier et sauvegarder le mapping JSON
        try:
            existing = vector_store.load_chunks_mapping()
        except Exception:
            existing = []

        new_entry = {
            "text": chunk_text,
            "source": source,
            "date_score": date_score,
            "page_number": 1,
            "category": category,
            "parent_text": chunk_text,
            "indexed_at": datetime.now(timezone.utc).isoformat(),
            "note_id": note_id,
            "active": True,
        }
        new_mapping = existing + [new_entry]
        vector_store.CHUNKS_MAPPING_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(vector_store.CHUNKS_MAPPING_PATH, "w", encoding="utf-8") as f:
            json.dump(new_mapping, f, ensure_ascii=False, indent=2)

        # Mettre à jour le singleton en mémoire (set() car on est déjà dans le lock)
        rag_state.set(idx, new_mapping)
        bm25_engine.build(new_mapping)

    query_cache.invalidate_all()


async def _soft_delete_faiss(note_id: str) -> None:
    """
    Marque le chunk FAISS de cette note comme inactif (soft delete).
    Protégé par write_lock pour éviter les race conditions.
    """
    from app.core.query_cache import query_cache
    from app.core.bm25_engine import bm25_engine

    async with rag_state.write_lock:
        try:
            mapping = vector_store.load_chunks_mapping()
        except Exception:
            return

        changed = False
        for entry in mapping:
            if entry.get("note_id") == note_id and entry.get("active", True):
                entry["active"] = False
                changed = True

        if changed:
            vector_store.CHUNKS_MAPPING_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(vector_store.CHUNKS_MAPPING_PATH, "w", encoding="utf-8") as f:
                json.dump(mapping, f, ensure_ascii=False, indent=2)
            idx, _ = rag_state.get()
            rag_state.set(idx, mapping)
            bm25_engine.build(mapping)

    if changed:
        query_cache.invalidate_all()


#  Endpoints 

@router.post("", status_code=201)
async def create_note(note: NoteCreate, current_user: CurrentUser):
    """Crée une note, la sauvegarde en DB et l'indexe dans FAISS."""
    text = note.text.strip()
    if len(text) < 10:
        raise HTTPException(400, "Note trop courte (minimum 10 caractères)")

    patient_name = note.patient_name.strip()
    if not patient_name:
        raise HTTPException(400, "Le nom du patient est requis")

    category = note.category.upper() if note.category.upper() in VALID_CATEGORIES else "CONSULTATIONS"
    note_date = note.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Trouver ou créer la source FAISS patient
    try:
        from app.core import vector_store
        existing = vector_store.load_chunks_mapping()
    except Exception:
        existing = []
    source = _find_patient_source(patient_name, existing) or _make_source(patient_name)

    note_id = _make_note_id()

    # Sauvegarder en base de données
    async with AsyncSessionLocal() as db:
        db_note = Note(
            note_id=note_id,
            patient_name=patient_name,
            source=source,
            category=category,
            note_date=note_date,
            text=text,
            active=True,
        )
        db.add(db_note)
        await db.commit()

    # Indexation FAISS incrémentale
    await _index_in_faiss(note_id, source, category, note_date, text)
    logger.info(f"[notes] Note créée: {note_id}, source={source}, category={category}")

    return {
        "message": f"Note sauvegardée pour « {_label_from_source(source).title()} »",
        "note_id": note_id,
        "source": source,
        "category": category,
    }


@router.put("/{note_id}", status_code=200)
async def update_note(note_id: str, note: NoteCreate, current_user: CurrentUser):
    """Met à jour une note existante (DB + FAISS)."""
    text = note.text.strip()
    if len(text) < 10:
        raise HTTPException(400, "Note trop courte (minimum 10 caractères)")

    patient_name = note.patient_name.strip()
    category = note.category.upper() if note.category.upper() in VALID_CATEGORIES else "CONSULTATIONS"
    note_date = note.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Note).where(Note.note_id == note_id, Note.active == True))
        db_note = result.scalar_one_or_none()
        if not db_note:
            raise HTTPException(404, "Note non trouvée")

        try:
            from app.core import vector_store
            mapping = vector_store.load_chunks_mapping()
        except Exception:
            mapping = []
        source = _find_patient_source(patient_name, mapping) or db_note.source or _make_source(patient_name)

        db_note.patient_name = patient_name
        db_note.category = category
        db_note.note_date = note_date
        db_note.text = text
        db_note.source = source
        await db.commit()

    # Re-indexer dans FAISS (désactive l'ancien chunk, ajoute le nouveau)
    await _soft_delete_faiss(note_id)
    await _index_in_faiss(note_id, source, category, note_date, text)
    logger.info(f"[notes] Note mise à jour: {note_id}")

    return {
        "message": f"Note mise à jour pour « {_label_from_source(source).title()} »",
        "note_id": note_id,
        "source": source,
        "category": category,
    }


@router.get("", status_code=200)
async def list_notes(current_user: CurrentUser):
    """Liste toutes les notes actives, triées par date de création décroissante."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Note).where(Note.active == True).order_by(Note.created_at.desc())
        )
        notes = result.scalars().all()

    return {"notes": [_note_to_dict(n) for n in notes]}


@router.get("/patients", status_code=200)
async def list_known_patients(current_user: CurrentUser):
    """Retourne la liste des patients ayant des notes actives en DB.
    Utilise patient_name (tel que saisi) plutôt que la source pour éviter
    les problèmes d'ordre prénom/nom dans les noms de fichiers."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Note.patient_name).where(Note.active == True).distinct()
        )
        names = [row[0] for row in result.all()]

    patients = sorted(set(n.strip().title() for n in names if n.strip()))
    return {"patients": patients}


@router.get("/categories", status_code=200)
async def list_categories(current_user: CurrentUser):
    """Retourne les catégories disponibles."""
    return {"categories": CATEGORY_LABELS}


@router.get("/{note_id}", status_code=200)
async def get_note(note_id: str, current_user: CurrentUser):
    """Récupère une note par son ID."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Note).where(Note.note_id == note_id, Note.active == True))
        db_note = result.scalar_one_or_none()

    if not db_note:
        raise HTTPException(404, "Note non trouvée")

    return _note_to_dict(db_note)


@router.delete("/{note_id}", status_code=200)
async def delete_note(note_id: str, current_user: CurrentUser):
    """Supprime une note (soft-delete DB + FAISS)."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Note).where(Note.note_id == note_id))
        db_note = result.scalar_one_or_none()
        if not db_note:
            raise HTTPException(404, "Note non trouvée")
        db_note.active = False
        await db.commit()

    await _soft_delete_faiss(note_id)
    logger.info(f"[notes] Note supprimée: {note_id}")
    return {"message": "Note supprimée"}
