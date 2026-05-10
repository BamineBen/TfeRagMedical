"""
patients.py — Endpoints FastAPI pour la liste des patients
══════════════════════════════════════════════════════════

RÔLE
─────
Exposer la table `patients` (171 lignes post-migration) au frontend.
Le KnowledgeBase.jsx utilise cet endpoint pour afficher TOUS les dossiers
patients (pas seulement les 6 uploadés via l'UI).

ENDPOINTS
──────────
GET /api/v1/patients              → liste paginée + recherche
GET /api/v1/patients/{id}         → détail d'un patient + ses notes
GET /api/v1/patients/{id}/pdf     → retourne le PDF du patient (tous les 171)
GET /api/v1/patients/{id}/chunks  → sections du dossier groupées par catégorie (BIOLOGIE, TRAITEMENTS…)
"""

import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select

from app.api.deps import CurrentUser, DBSession, OptionalUser, FileUser
from app.config import settings
from app.core.rag_state import rag_state
from app.core import vector_store
from app.models.document import Document
from app.models.note import Note
from app.models.patient import Patient

logger = logging.getLogger(__name__)
router = APIRouter()


def _chunk_counts_by_source() -> dict[str, int]:
    """
    Retourne un dict {source_filename: nb_chunks} depuis l'état FAISS en mémoire.

    NORMALISATION : indexe chaque source sous deux clés — avec ET sans extension —
    pour absorber le mismatch .pdf / .txt (la table patients stocke .pdf,
    mais les fichiers Medilogiciel sont souvent indexés en .txt).

    Exemple :
        "1775359612_P00001_LEBRETON.txt"  →  clé .txt  ET clé sans extension
        "1775359612_P00001_LEBRETON.pdf"  →  clé .pdf  ET clé sans extension
    → Le lookup fonctionne quel que soit le suffixe stocké en DB.
    """
    _, chunks = rag_state.get()
    if not chunks:
        return {}
    counts: dict[str, int] = {}
    for c in chunks:
        src = c.get("source", "")
        if not src:
            continue
        counts[src] = counts.get(src, 0) + 1
        # Clé normalisée sans extension pour le fallback cross-format
        stem = os.path.splitext(src)[0]
        counts[stem] = counts.get(stem, 0) + 1
    return counts


def _lookup_chunk_count(chunk_map: dict[str, int], source_filename: str) -> int:
    """
    Cherche le nb de chunks d'un patient en gérant le mismatch d'extension.

    Ordre de recherche :
      1. Correspondance exacte           (source_filename tel quel)
      2. Sans extension                  (normalisation cross-format)
      3. Suffixe bare (retire timestamp) (ex. 1775xxx_P001_NOM.pdf → P001_NOM.pdf)
    """
    if not source_filename:
        return 0
    # 1. Exact
    if source_filename in chunk_map:
        return chunk_map[source_filename]
    # 2. Sans extension
    stem = os.path.splitext(source_filename)[0]
    if stem in chunk_map:
        return chunk_map[stem]
    # 3. Bare (sans préfixe timestamp)
    if source_filename[0].isdigit() and "_" in source_filename:
        bare = source_filename.split("_", 2)[-1]
        bare_stem = os.path.splitext(bare)[0]
        for key in (bare, bare_stem):
            if key in chunk_map:
                return chunk_map[key]
    return 0


@router.get("")
async def list_patients(
    db: DBSession,
    current_user: CurrentUser,
    search: Optional[str] = Query(None, description="Recherche par nom ou prénom"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """
    Liste tous les patients avec leur nombre de chunks FAISS.

    Retourne les 171 patients de la table `patients`, enrichis avec :
    - chunk_count  : nombre de chunks dans l'index FAISS
    - doc_id       : id dans `documents` (si uploadé via UI), sinon null
    - note_count   : nombre de notes atomiques liées
    """
    #  Compter les chunks par source (lecture mémoire — rapide) 
    chunk_map = _chunk_counts_by_source()

    #  Requête DB 
    q = select(Patient)
    if search and search.strip():
        s = f"%{search.strip()}%"
        q = q.where(
            or_(
                Patient.nom.ilike(s),
                Patient.prenom.ilike(s),
                Patient.source_filename.ilike(s),
            )
        )
    q = q.order_by(Patient.nom, Patient.prenom)

    # Nombre total pour la pagination
    count_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar_one()

    # Page courante
    q = q.offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(q)).scalars().all()

    #  Enrichir avec doc_id 
    # Pour chaque patient, vérifier s'il a un Document en DB (uploadé via UI)
    patient_ids = [p.id for p in rows]
    doc_rows = (
        await db.execute(
            select(Document.id, Document.patient_id, Document.status, Document.filename)
            .where(Document.patient_id.in_(patient_ids))
        )
    ).all()
    doc_by_patient: dict[int, dict] = {
        r.patient_id: {"doc_id": r.id, "status": r.status, "filename": r.filename}
        for r in doc_rows
    }

    #  Compter les notes par patient 
    note_rows = (
        await db.execute(
            select(Note.patient_id, func.count(Note.id).label("cnt"))
            .where(Note.patient_id.in_(patient_ids), Note.active == True)
            .group_by(Note.patient_id)
        )
    ).all()
    notes_by_patient: dict[int, int] = {r.patient_id: r.cnt for r in note_rows}

    #  Sérialiser 
    items = []
    for p in rows:
        src = p.source_filename
        chunks = _lookup_chunk_count(chunk_map, src)

        doc_info = doc_by_patient.get(p.id)
        items.append({
            "id": p.id,
            "patient_code": p.patient_code,
            "nom": p.nom,
            "prenom": p.prenom,
            "full_name": f"{p.prenom} {p.nom}",
            "source_filename": src,
            "chunk_count": chunks,
            "in_faiss": chunks > 0,
            "doc_id": doc_info["doc_id"] if doc_info else None,
            "doc_status": doc_info["status"] if doc_info else None,
            "note_count": notes_by_patient.get(p.id, 0),
            "created_at": p.created_at.isoformat() if p.created_at else None,
        })

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }


@router.get("/{patient_id}/pdf")
async def view_patient_pdf(
    patient_id: int,
    db: DBSession,
    current_user: FileUser,              # accepte header ET ?token= dans l'URL
):
    """
    Retourne le PDF d'un patient pour affichage inline dans le navigateur.

    STRATÉGIE DE RECHERCHE (priorité : PDF généré Medilogiciel > upload UI)
    ─────────────────────────────────────────────────────────────────────────
    PRIORITÉ 1 — PDF généré (medical_docs/) : format uniforme pour tous les patients.
       Cherche par nom de base (stem) dans medical_docs/, avec ou sans préfixe timestamp.
    PRIORITÉ 2 — Document uploadé via UI (fallback) : si aucun PDF généré trouvé.

    Pourquoi cette priorité ?
      Certains patients ont un PDF brut uploadé manuellement (2 pages, ancien format).
      On veut que tous affichent le même modèle Medilogiciel généré par scripts (PY).

    SÉCURITÉ : endpoint protégé — JWT requis.
    Réponse 404 JSON si aucun fichier trouvé (le frontend bascule sur le visionneur texte).
    """
    #  Récupérer le patient 
    result = await db.execute(select(Patient).where(Patient.id == patient_id))
    patient = result.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient introuvable")

    source = patient.source_filename or ""
    medical_docs_dir = str(vector_store.MEDICAL_DOCS_DIR)
    upload_dir       = settings.UPLOAD_DIR

    def _serve(path: str, name: str = source) -> FileResponse:
        """Raccourci : retourne le fichier avec les bons en-têtes inline."""
        return FileResponse(
            path=path,
            media_type="application/pdf",
            filename=name,
            headers={"Content-Disposition": f"inline; filename={name}"},
        )

    #  PRIORITÉ 1 : PDF généré dans medical_docs/ 
    # Cherche le PDF par stem (sans extension ni préfixe timestamp)
    stem = os.path.splitext(source)[0]                        # "1775xxx_P00012_LECOMTE_Sophie"
    bare = stem.split("_", 1)[1] if stem[0:1].isdigit() and "_" in stem else stem
    # bare = "P00012_LECOMTE_Sophie"

    for candidate_stem in (stem, bare):
        pdf_path = os.path.join(medical_docs_dir, candidate_stem + ".pdf")
        if os.path.isfile(pdf_path):
            return _serve(pdf_path, candidate_stem + ".pdf")

    # Scan exhaustif dans medical_docs/ par nom de base (gère accents, majuscules)
    if os.path.isdir(medical_docs_dir):
        bare_lower = bare.lower()
        for fname in sorted(os.listdir(medical_docs_dir)):
            if not fname.endswith(".pdf"):
                continue
            if os.path.splitext(fname)[0].lower() == bare_lower:
                return _serve(os.path.join(medical_docs_dir, fname), fname)

    # ── PRIORITÉ 2 : Document uploadé via UI (fallback) ─────────────
    doc_result = await db.execute(
        select(Document).where(Document.patient_id == patient_id)
    )
    doc = doc_result.scalar_one_or_none()
    if doc and doc.file_path:
        if os.path.exists(doc.file_path):
            return _serve(doc.file_path)
        relocated = os.path.join(upload_dir, os.path.basename(doc.file_path))
        if os.path.exists(relocated):
            return _serve(relocated)

    #  Passe 3 : chemins exacts + variante .txt dans medical_docs/ et UPLOAD_DIR ───
    # Les fichiers Medilogiciel sont souvent stockés en .txt même si la DB dit .pdf
    source_txt = os.path.splitext(source)[0] + ".txt"
    for candidate in (
        os.path.join(medical_docs_dir, source),
        os.path.join(upload_dir, source),
        os.path.join(medical_docs_dir, source_txt),
        os.path.join(upload_dir, source_txt),
    ):
        if os.path.exists(candidate):
            return _serve(candidate)

    #  Passe 4 : source avec préfixe timestamp (ex. 1700000000_nom.pdf) ──
    # Certains fichiers Medilogiciel sont copiés avec un timestamp préfixe
    # lors de l'upload. On reconstruit le nom nu ET on cherche l'inverse.
    bare = source
    if source and source[0].isdigit() and "_" in source:
        bare = source.split("_", 1)[1]           # "1234_P001_NOM.pdf" → "P001_NOM.pdf"

    for candidate in (
        os.path.join(medical_docs_dir, bare),
        os.path.join(upload_dir, bare),
    ):
        if candidate != os.path.join(medical_docs_dir, source) and os.path.exists(candidate):
            return _serve(candidate, bare)

    #  Passe 5 : scan fuzzy dans les deux répertoires 
    # Cherche tout fichier PDF dont le nom contient la base du source_filename.
    # Tolère : préfixe timestamp, suffixe de version, casse différente.
    base_lower = os.path.splitext(bare)[0].lower()   # "p00013_nom_prenom"

    for search_dir in (medical_docs_dir, upload_dir):
        if not os.path.isdir(search_dir):
            continue
        for fname in sorted(os.listdir(search_dir)):   # sorted → résultat déterministe
            if not fname.lower().endswith(".pdf"):
                continue
            fname_lower = os.path.splitext(fname)[0].lower()
            # Correspondance si ≥ 60 % des mots clés de base_lower sont dans fname_lower
            key_words = [w for w in base_lower.replace("_", " ").split() if len(w) > 2]
            if key_words and sum(w in fname_lower for w in key_words) >= max(1, len(key_words) * 0.6):
                full = os.path.join(search_dir, fname)
                if os.path.isfile(full):
                    logger.info(f"[pdf] fuzzy match: {source!r} → {fname}")
                    return _serve(full, fname)

    logger.warning(f"[pdf] introuvable pour patient_id={patient_id} source={source!r}")
    raise HTTPException(
        status_code=404,
        detail={
            "code": "PDF_NOT_FOUND",
            "message": f"PDF introuvable pour {patient.prenom} {patient.nom}",
            "hint": "Le visionneur de sections reste disponible.",
        },
    )


@router.get("/{patient_id}/document")
async def view_patient_document(
    patient_id: int,
    db: DBSession,
    current_user: CurrentUser,
):
    """
    Retourne le contenu texte du dossier Medilogiciel d'un patient.
    Cherche le fichier .txt (ou .pdf) dans medical_docs en normalisant l'extension.
    """
    result = await db.execute(select(Patient).where(Patient.id == patient_id))
    patient = result.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient introuvable")

    source = patient.source_filename or ""
    stem   = os.path.splitext(source)[0]   # "P00010_MARTINEZ_Emma"
    docs   = str(vector_store.MEDICAL_DOCS_DIR)

    # Cherche dans cet ordre : .txt exact, .pdf exact, .txt bare (sans timestamp), scan
    candidates = [
        os.path.join(docs, stem + ".txt"),
        os.path.join(docs, stem + ".pdf"),
        os.path.join(docs, source),
    ]
    # Variante sans préfixe timestamp
    if stem and stem[0].isdigit() and "_" in stem:
        bare_stem = stem.split("_", 2)[-1]
        candidates += [
            os.path.join(docs, bare_stem + ".txt"),
            os.path.join(docs, bare_stem + ".pdf"),
        ]

    for path in candidates:
        if os.path.isfile(path):
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except Exception as e:
                raise HTTPException(500, f"Erreur lecture fichier : {e}")
            return {
                "patient_id": patient_id,
                "full_name": f"{patient.prenom} {patient.nom}",
                "filename": os.path.basename(path),
                "content": content,
            }

    # Scan exhaustif par nom
    if os.path.isdir(docs):
        base_lower = stem.lower()
        for fname in sorted(os.listdir(docs)):
            if os.path.splitext(fname)[0].lower() == base_lower:
                path = os.path.join(docs, fname)
                with open(path, encoding="utf-8", errors="replace") as f:
                    content = f.read()
                return {
                    "patient_id": patient_id,
                    "full_name": f"{patient.prenom} {patient.nom}",
                    "filename": fname,
                    "content": content,
                }

    raise HTTPException(
        status_code=404,
        detail={"code": "DOC_NOT_FOUND", "message": f"Document introuvable pour {patient.prenom} {patient.nom}"},
    )


@router.get("/{patient_id}/chunks")
async def get_patient_chunks(
    patient_id: int,
    db: DBSession,
    current_user: CurrentUser,
):
    """
    Retourne tous les chunks FAISS d'un patient avec leur catégorie et texte.

    Utilisé par le frontend pour afficher le contenu du dossier
    section par section (BIOLOGIE, CONSULTATIONS, TRAITEMENTS…)
    sans avoir à télécharger le PDF.
    """
    result = await db.execute(select(Patient).where(Patient.id == patient_id))
    patient = result.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient introuvable")

    source = patient.source_filename or ""
    _, chunks_mapping = rag_state.get()

    if not chunks_mapping:
        return {"patient_id": patient_id, "source": source, "chunks": []}

    # Chercher les chunks dont la source correspond à ce patient.
    # On normalise les extensions (.pdf ↔ .txt) et les préfixes timestamp
    # pour absorber le mismatch entre la table patients et FAISS.
    source_stem  = os.path.splitext(source)[0]          # sans extension
    bare_source  = source.split("_", 2)[-1] if source.count("_") >= 2 and source[0].isdigit() else source
    bare_stem    = os.path.splitext(bare_source)[0]

    patient_chunks = []
    for c in chunks_mapping:
        c_source = c.get("source", "")
        if not c_source:
            continue
        c_stem = os.path.splitext(c_source)[0]
        c_bare = c_source.split("_", 2)[-1] if c_source.count("_") >= 2 and c_source[0].isdigit() else c_source
        c_bare_stem = os.path.splitext(c_bare)[0]

        match = (
            c_source   == source       or   # exact
            c_stem     == source_stem  or   # sans extension (pdf↔txt)
            c_bare     == bare_source  or   # sans timestamp
            c_bare_stem== bare_stem         # sans timestamp ni extension
        )
        if match:
            patient_chunks.append({
                "text": c.get("parent_text") or c.get("text", ""),
                "category": c.get("category", "AUTRE"),
                "page_number": c.get("page_number"),
                "date_score": c.get("date_score"),
                "indexed_at": c.get("indexed_at"),
            })

    # Regrouper par catégorie avec déduplication sur parent_text
    # Plusieurs chunks-enfants partagent le même parent_text → on ne garde qu'une fois chaque bloc
    sections: dict[str, list] = {}
    seen_per_cat: dict[str, set] = {}
    for ch in patient_chunks:
        cat = ch["category"] or "AUTRE"
        text = ch["text"]
        key = text[:120]   # empreinte : les 120 premiers caractères suffisent à distinguer les blocs
        if key not in seen_per_cat.setdefault(cat, set()):
            seen_per_cat[cat].add(key)
            sections.setdefault(cat, []).append(text)

    return {
        "patient_id": patient_id,
        "full_name": f"{patient.prenom} {patient.nom}",
        "source": source,
        "total_chunks": len(patient_chunks),
        "sections": sections,   # {"BIOLOGIE": ["...","..."], "TRAITEMENTS": ["..."]}
        "chunks": patient_chunks,  # liste brute pour usage avancé
    }


@router.get("/{patient_id}")
async def get_patient(
    patient_id: int,
    db: DBSession,
    current_user: CurrentUser,
):
    """Détail d'un patient + ses notes."""
    chunk_map = _chunk_counts_by_source()

    result = await db.execute(select(Patient).where(Patient.id == patient_id))
    p = result.scalar_one_or_none()
    if not p:
        from fastapi import HTTPException
        raise HTTPException(404, f"Patient {patient_id} introuvable")

    src = p.source_filename
    chunks = _lookup_chunk_count(chunk_map, src)

    # Notes du patient
    note_rows = (
        await db.execute(
            select(Note)
            .where(Note.patient_id == patient_id, Note.active == True)
            .order_by(Note.created_at.desc())
        )
    ).scalars().all()

    return {
        "id": p.id,
        "patient_code": p.patient_code,
        "nom": p.nom,
        "prenom": p.prenom,
        "full_name": f"{p.prenom} {p.nom}",
        "source_filename": p.source_filename,
        "chunk_count": chunks,
        "in_faiss": chunks > 0,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "notes": [
            {
                "note_id": n.note_id,
                "category": n.category,
                "note_date": n.note_date,
                "text": n.text[:300],
                "created_at": n.created_at.isoformat(),
            }
            for n in note_rows
        ],
    }
