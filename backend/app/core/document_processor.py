"""
document_processor.py — Pipeline complet d'ingestion de documents médicaux.

RÔLE
─────
Transforme un fichier PDF ou TXT en chunks vectorisés prêts pour FAISS.

PIPELINE (ordre d'exécution)
──────────────────────────────
  1. load_document()        → extrait le texte brut (PDF via PyPDF2 ou TXT direct)
                              avec marqueurs de page ===PAGE:N=== pour les PDF
  2. semantic_chunk_rich()  → découpe intelligente en chunks sémantiques :
                              - Respecte les sections médicales détectées
                              - Produit un chunk "enfant" court (pour l'embedding)
                              - Et un "parent" complet (pour le contexte LLM)
  3. _detect_section_category() → catégorise chaque chunk (BIOLOGIE, TRAITEMENTS,
                                  CONSULTATIONS, DIAGNOSTIC, etc.)
  4. extract_date_score()   → score temporel [0.0 - 1.0] pour favoriser les infos récentes
  5. index_single_document() → encode + ajoute au FAISS + sauvegarde sur disque

FONCTIONS PUBLIQUES
────────────────────
  index_single_document(path)  → indexe un fichier, retourne le nombre de chunks
  index_all_documents()        → indexe tous les fichiers de medical_docs/
  extract_date_score(text)     → score temporel d'un texte
"""
import re
import logging
from pathlib import Path

from PyPDF2 import PdfReader

from app.config import settings
from app.core import vector_store
from app.core.embeddings import get_embedding_service, get_dimension

_PAGE_MARKER_RE = re.compile(r'===PAGE:(\d+)===\s*')

logger = logging.getLogger(__name__)

CHUNK_SIZE = settings.CHUNK_SIZE
OVERLAP = settings.CHUNK_OVERLAP
MAX_SECTION_CHARS = 1200

# ── Extraction de dates pour temporal reranking ──
_DATE_RE = re.compile(
    r'(?:'
    r'(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{4})'
    r'|(\d{4})[/\-\.](\d{1,2})[/\-\.](\d{1,2})'
    r'|(\d{1,2})\s+(?:jan|fév|mar|avr|mai|juin|juil|aoû|sep|oct|nov|déc)[a-zé]*\.?\s+(\d{4})'
    r'|(\d{4})'
    r')'
)


def extract_date_score(text: str) -> float:  # noqa: D103
    best = 0
    for m in _DATE_RE.finditer(text):
        for g in m.groups():
            if g and len(g) == 4:
                try:
                    y = int(g)
                    if 2005 <= y <= 2030:
                        best = max(best, y)
                except ValueError:
                    pass
    return (best - 2005) / 25 if best else 0.0


# ── Ingestion ──
def load_document(path: str) -> str:
    """Charge le texte du document avec marqueurs de page (===PAGE:N===) pour les PDF."""
    ext = Path(path).suffix.lower()
    if ext == ".txt":
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    elif ext == ".pdf":
        reader = PdfReader(path)
        parts = []
        for i, page in enumerate(reader.pages):
            text = (page.extract_text() or "").strip()
            if text:
                parts.append(f"===PAGE:{i + 1}===\n{text}")
        return "\n".join(parts)
    raise ValueError(f"Format non supporté : {ext}")


def _extract_page(chunk: str) -> int:
    """Retourne le premier numéro de page trouvé dans un chunk (1 par défaut)."""
    m = _PAGE_MARKER_RE.search(chunk)
    return int(m.group(1)) if m else 1


def _strip_page_markers(chunk: str) -> str:
    """Supprime les marqueurs ===PAGE:N=== du texte du chunk."""
    return _PAGE_MARKER_RE.sub('', chunk).strip()


# ── Chunking sémantique ──
# Reconnaît les en-têtes de sections médicales (SOAP, FR, EN) pour couper aux bonnes limites.
# Règle : ligne courte (≤ 120 chars) commençant par un des patterns connus.
_SECTION_RE = re.compile(
    r'^(?:'
    # SOAP : "S —", "## O — Objectif", "A — ANALYSE", "P — PLAN"
    r'(?:#{1,3}\s*)?[SOAPsoap]\s*[—–\-]{1,3}\s*\S'
    r'|'
    # En-têtes numérotés ou avec tirets : "1. Antécédents", "─── BIOLOGIE"
    r'(?:[0-9]+[.)]\s+)?(?:#{1,3}\s*)?[─═\-]{0,3}\s*'
    r'(?:IDENTIT[ÉE]|ANT[ÉE]C[ÉE]DENTS?|CONSULTATIONS?|TRAITEMENTS?|'
    r'BIOLOGIE|IMAGERIE|HOSPITALISATIONS?|VACCINATIONS?|SYNTH[ÈE]SE|'
    r'ORDONNANCE|PRESCRIPTION|ALLERGIES?|[ÉE]TAT CIVIL|COORDONN[ÉE]ES?|'
    r'CONSTANTES?\s*VITALES?|EXAMENS?\s*(?:COMPL[ÉE]MENTAIRES?|CLINIQUES?)?|'
    r'DIAGNOSTICS?|COMPTE.RENDU|BILAN|PROBL[ÈE]MES?|'
    r'MODE\s*DE\s*VIE|MOTIF\s*(?:PRINCIPAL\s*)?(?:DE\s*)?CONSULTATION|'
    r'REVUE\s*DES\s*SYST[ÈE]MES?|HISTORIQUE\s*DE\s*LA|'
    r'PLAN\s*TH[ÉE]RAPEUTIQUE|ACTIONS?\s*IMMÉDIATES?|'
    r'SUIVI\s*(?:PR[ÉE]VU|[ÀA]\s*LONG\s*TERME)|'
    r'CONTINUITÉ\s*DES\s*SOINS|EXAMENS?\s*ATTENDUS?|'
    r'THÉRAPEUTIQUE\s*D.ATTENTE'
    r')'
    r').{0,100}$',
    re.IGNORECASE | re.UNICODE
)


# ── Catégories de sections médicales ─────────────────────────────────
_CATEGORY_PATTERNS = [
    (re.compile(r'BIOLOGIE|ANALYSE|GLYC[EÉ]MIE|CR[EÉ]ATININE|NFS|BILAN', re.I), 'BIOLOGIE'),
    (re.compile(r'IDENTIT[EÉ]|[EÉ]TAT CIVIL|COORDONN', re.I), 'IDENTITE'),
    (re.compile(r'ANT[EÉ]C[EÉ]DENT', re.I), 'ANTECEDENTS'),
    (re.compile(r'ALLERGI', re.I), 'ALLERGIES'),
    (re.compile(r'TRAITEMENT|M[EÉ]DICAMENT|ORDONNANCE|PRESCRIPTION', re.I), 'TRAITEMENTS'),
    (re.compile(r'IMAGERIE|SCANNER|IRM|RADIO|[EÉ]CHO|SPIROM', re.I), 'IMAGERIE'),
    (re.compile(r'ECG|[EÉ]LECTROCARDIOGRAMME', re.I), 'ECG'),
    (re.compile(r'CONSTANTE|VITALE', re.I), 'CONSTANTES'),
    (re.compile(r'VACCIN', re.I), 'VACCINATIONS'),
    (re.compile(r'HOSPITALISATION', re.I), 'HOSPITALISATIONS'),
    (re.compile(r'CONSULTATION|COMPTE.RENDU', re.I), 'CONSULTATIONS'),
    (re.compile(r'SYNTH[EÈ]SE|R[EÉ]SUM[EÉ]', re.I), 'SYNTHESE'),
    (re.compile(r'EXAMEN', re.I), 'EXAMENS'),
    (re.compile(r'MODE DE VIE|MOTIF', re.I), 'MOTIF'),
    (re.compile(r'PLAN TH[EÉ]RAPEUTIQUE|SUIVI', re.I), 'PLAN'),
    (re.compile(r'DIAGNOSTIC', re.I), 'DIAGNOSTIC'),
]
_SOAP_LETTER_RE = re.compile(r'^[SOAPsoap]\s*[—–\-]')
_SOAP_LETTER_MAP = {'S': 'SUBJECTIF', 'O': 'OBJECTIF', 'A': 'ASSESSMENT', 'P': 'PLAN'}


def _detect_section_category(title: str) -> str:
    """Retourne la catégorie normalisée (BIOLOGIE, TRAITEMENTS, etc.) d'une section."""
    if not title:
        return 'AUTRE'
    if _SOAP_LETTER_RE.match(title.strip()):
        letter = title.strip()[0].upper()
        return _SOAP_LETTER_MAP.get(letter, 'AUTRE')
    for pattern, category in _CATEGORY_PATTERNS:
        if pattern.search(title):
            return category
    return 'AUTRE'


def _clean(text: str) -> str:
    text = re.sub(r'^[=\-─━]{3,}$', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _split_large(text: str, max_chars=MAX_SECTION_CHARS) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    chunks, current = [], ""
    for para in re.split(r'\n{2,}', text):
        para = para.strip()
        if not para:
            continue
        if len(current) + len(para) + 2 <= max_chars:
            current = (current + "\n\n" + para).strip()
        else:
            if current:
                chunks.append(current)
            current = para if len(para) <= max_chars else para[:max_chars]
    if current:
        chunks.append(current)
    return chunks or [text[:max_chars]]


def semantic_chunk_text(text: str) -> list[str]:
    text = _clean(text)
    lines = text.split('\n')
    sections, title, body = [], "", []

    for line in lines:
        if _SECTION_RE.match(line.strip()):
            if body:
                sections.append((title, body))
            title, body = line.strip(), []
        else:
            body.append(line)
    if body:
        sections.append((title, body))

    if len(sections) <= 1:
        # Fallback naïf
        step = CHUNK_SIZE - OVERLAP
        chunks = []
        i = 0
        while i < len(text):
            c = text[i:i + CHUNK_SIZE].strip()
            if c:
                chunks.append(c)
            i += step
        return chunks

    result = []
    for title, body_lines in sections:
        body = '\n'.join(body_lines).strip()
        if not body:
            continue
        sec = f"{title}\n{body}".strip() if title else body
        result.extend(_split_large(sec))
    return [c for c in result if c.strip()]


def semantic_chunk_rich(text: str) -> list[dict]:
    """
    Variante de semantic_chunk_text() pour le parent-child chunking.

    Retourne list[dict] avec :
      - text        : chunk enfant (peut contenir ===PAGE:N===) → pour l'embedding
      - parent_text : section complète nettoyée → pour le contexte LLM
      - category    : catégorie normalisée (BIOLOGIE, TRAITEMENTS, etc.)

    Les appelants doivent extraire la page avec _extract_page(d["text"])
    et nettoyer avec _strip_page_markers(d["text"]).
    """
    cleaned = _clean(text)
    lines = cleaned.split('\n')
    sections, title, body = [], "", []

    for line in lines:
        if _SECTION_RE.match(line.strip()):
            if body:
                sections.append((title, body))
            title, body = line.strip(), []
        else:
            body.append(line)
    if body:
        sections.append((title, body))

    if len(sections) <= 1:
        step = CHUNK_SIZE - OVERLAP
        result = []
        i = 0
        while i < len(cleaned):
            c = cleaned[i:i + CHUNK_SIZE].strip()
            if c:
                result.append({"text": c, "parent_text": _strip_page_markers(c), "category": "AUTRE"})
            i += step
        return result

    result = []
    for title, body_lines in sections:
        body = '\n'.join(body_lines).strip()
        if not body:
            continue
        sec = f"{title}\n{body}".strip() if title else body
        category = _detect_section_category(title)
        parent_clean = _strip_page_markers(sec)
        for child in _split_large(sec):
            if child.strip():
                result.append({
                    "text": child,
                    "parent_text": parent_clean,
                    "category": category,
                })
    return result


# ── Indexation ──
def index_all_documents():
    """Indexe tous les documents de data/medical_docs/."""
    docs_dir = vector_store.MEDICAL_DOCS_DIR
    files = list(docs_dir.glob("*.pdf")) + list(docs_dir.glob("*.txt"))
    if not files:
        logger.warning(f"Aucun document dans {docs_dir}")
        return

    logger.info(f"Indexation de {len(files)} documents...")
    all_chunks, all_names, all_pages, all_categories, all_parents = [], [], [], [], []

    for fp in files:
        text = load_document(str(fp))
        rich = semantic_chunk_rich(text)
        pages = [_extract_page(r["text"]) for r in rich]
        chunks = [_strip_page_markers(r["text"]) for r in rich]
        all_chunks.extend(chunks)
        all_names.extend([fp.name] * len(chunks))
        all_pages.extend(pages)
        all_categories.extend([r["category"] for r in rich])
        all_parents.extend([r["parent_text"] for r in rich])

    date_scores = [extract_date_score(c) for c in all_chunks]
    emb = get_embedding_service()
    embeddings = emb.encode(all_chunks)

    idx = vector_store.create_index(embeddings.shape[1])
    vector_store.add_vectors(idx, embeddings)
    vector_store.save_index(idx)
    vector_store.save_chunks_mapping(
        all_chunks, all_names, date_scores,
        page_numbers=all_pages, categories=all_categories, parent_texts=all_parents,
    )
    logger.info(f" Indexation terminée : {len(all_chunks)} chunks, {len(files)} docs")


def index_single_document(file_path: str) -> int:
    """Ajoute un document à l'index existant."""
    path = Path(file_path)
    text = load_document(str(path))

    try:
        idx = vector_store.load_index()
        existing = vector_store.load_chunks_mapping()
    except FileNotFoundError:
        idx = vector_store.create_index(get_dimension())
        existing = []

    rich = semantic_chunk_rich(text)
    page_numbers = [_extract_page(r["text"]) for r in rich]
    chunks = [_strip_page_markers(r["text"]) for r in rich]
    categories = [r["category"] for r in rich]
    parent_texts = [r["parent_text"] for r in rich]
    date_scores = [extract_date_score(c) for c in chunks]

    # Supprimer ancien si déjà indexé
    new_mapping = [m for m in existing if m["source"] != path.name]
    all_chunks = [m["text"] for m in new_mapping] + chunks
    all_names = [m["source"] for m in new_mapping] + [path.name] * len(chunks)
    all_ds = [m.get("date_score", 0.0) for m in new_mapping] + date_scores
    all_pages = [m.get("page_number", 1) for m in new_mapping] + page_numbers
    all_cats = [m.get("category", "AUTRE") for m in new_mapping] + categories
    all_parents = [m.get("parent_text", m["text"]) for m in new_mapping] + parent_texts

    emb = get_embedding_service()
    embeddings = emb.encode(all_chunks)
    idx = vector_store.create_index(embeddings.shape[1])
    vector_store.add_vectors(idx, embeddings)
    vector_store.save_index(idx)
    vector_store.save_chunks_mapping(
        all_chunks, all_names, all_ds,
        page_numbers=all_pages, categories=all_cats, parent_texts=all_parents,
    )
    return len(chunks)
