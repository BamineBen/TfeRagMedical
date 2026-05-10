"""
vector_store.py — Stockage et recherche vectorielle avec FAISS
═══════════════════════════════════════════════════════════════

RÔLE DANS L'ARCHITECTURE
─────────────────────────
Ce module est une COUCHE D'ABSTRACTION sur FAISS (Facebook AI Similarity Search).
Il cache la complexité de FAISS derrière des fonctions simples.

QU'EST-CE QUE FAISS ?
─────────────────────
FAISS est une bibliothèque développée par Meta/Facebook pour la recherche
de vecteurs similaires. C'est le cœur de la recherche sémantique.

Fonctionnement :
1. Chaque chunk de texte est transformé en vecteur de 384 dimensions
   par le modèle d'embedding (paraphrase-multilingual-MiniLM-L12-v2).
2. Ces vecteurs sont stockés dans l'index FAISS.
3. Quand on pose une question, on encode la question en vecteur
   et FAISS trouve les vecteurs les plus proches = les chunks les plus similaires.

SIMILARITÉ COSINUS
──────────────────
On utilise IndexFlatIP (Inner Product = produit scalaire).
Après normalisation L2 des vecteurs, produit scalaire = similarité cosinus.
Valeur entre -1 et 1 :
  - 1.0  = vecteurs identiques (parfaitement similaires)
  - 0.0  = vecteurs orthogonaux (aucun lien)
  - -1.0 = vecteurs opposés

PERSISTANCE SUR DISQUE
──────────────────────
L'index FAISS + le mapping (metadata) sont sauvegardés dans /app/data/ :
- faiss_index.bin    : index FAISS binaire (vecteurs)
- chunks_mapping.json: metadata des chunks (texte, source, date, catégorie, etc.)

Source originale : rag_theorie/rag/backend/vector_store.py (adapté)
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import faiss
import numpy as np

logger = logging.getLogger(__name__)

# ── Chemins de persistance ──────────────────────────────────────────────
import os as _os
_DATA_DIR = Path(_os.environ.get("DATA_DIR", str(Path(__file__).resolve().parents[2] / "data")))
FAISS_INDEX_PATH    = _DATA_DIR / "faiss_index.bin"
CHUNKS_MAPPING_PATH = _DATA_DIR / "chunks_mapping.json"
MEDICAL_DOCS_DIR    = _DATA_DIR / "medical_docs"


# ── Gestion de l'index ──────────────────────────────────────────────────

def create_index(dimension: int) -> faiss.IndexFlatIP:
    """
    Crée un nouvel index FAISS vide.

    IndexFlatIP = "Flat" (pas d'approximation) + "IP" (Inner Product).
    Après normalisation L2, IP = similarité cosinus.
    "Flat" signifie qu'on compare la requête à TOUS les vecteurs → précision maximale.

    Pour des corpus > 100 000 chunks, on pourrait utiliser IndexIVFFlat
    (avec approximation) pour des recherches plus rapides.

    Paramètres :
        dimension : taille des vecteurs d'embedding (384 pour notre modèle)

    Retourne :
        Index FAISS vide prêt à recevoir des vecteurs
    """
    return faiss.IndexFlatIP(dimension)


def add_vectors(index: faiss.IndexFlatIP, embeddings: np.ndarray):
    """
    Ajoute des vecteurs à l'index FAISS.

    IMPORTANT : les vecteurs doivent être normalisés L2 avant l'ajout
    pour que la recherche IP = cosinus.

    Paramètres :
        index      : index FAISS existant
        embeddings : tableau numpy de shape (n_chunks, dimension)
    """
    index.add(embeddings)


def search(index: faiss.IndexFlatIP, query_embedding: np.ndarray, k: int = 5):
    """
    Cherche les k vecteurs les plus proches dans l'index FAISS.

    COMMENT ÇA MARCHE ?
    ─────────────────────
    1. query_embedding est le vecteur de la question encodée (1 vecteur)
    2. FAISS calcule le produit scalaire entre query et TOUS les vecteurs de l'index
    3. Retourne les k vecteurs avec les scores les plus élevés

    Complexité : O(n × d) où n = nb de vecteurs, d = dimension (384)
    Pour n=5000, d=384 : ~2M opérations → très rapide (~1-2ms sur CPU)

    Paramètres :
        index          : index FAISS chargé en mémoire
        query_embedding: vecteur de la question, shape (1, dimension)
        k              : nombre de résultats à retourner

    Retourne :
        (distances, indices) :
        - distances : shape (1, k), scores de similarité
        - indices   : shape (1, k), positions dans l'index (correspondent à chunks_mapping)
    """
    distances, indices = index.search(query_embedding, k=k)
    return distances, indices


def save_index(index: faiss.IndexFlatIP, path: Path = FAISS_INDEX_PATH):
    """
    Sauvegarde l'index FAISS sur disque au format binaire.

    Le fichier .bin est propre à FAISS et ne peut être lu qu'avec FAISS.
    Cette sauvegarde est nécessaire pour que l'index survive au redémarrage.

    Paramètres :
        index : index FAISS à sauvegarder
        path  : chemin de destination (défaut: /app/data/faiss_index.bin)
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(path))
    logger.info(f"[vector_store] Index sauvegardé : {path} ({index.ntotal} vecteurs)")


def load_index(path: Path = FAISS_INDEX_PATH) -> faiss.IndexFlatIP:
    """
    Charge un index FAISS depuis le disque.

    Appelé au démarrage de l'application (main.py → lifespan()).
    L'index est gardé en mémoire RAM pendant toute la durée de vie du process.
    → Recherches très rapides car pas d'accès disque à chaque requête.

    Paramètres :
        path : chemin de l'index binaire (défaut: /app/data/faiss_index.bin)

    Retourne :
        Index FAISS chargé et prêt pour la recherche

    Raises :
        FileNotFoundError : si le fichier n'existe pas
    """
    if not path.exists():
        raise FileNotFoundError(f"Index non trouvé : {path}")
    index = faiss.read_index(str(path))
    logger.info(f"[vector_store] Index chargé : {path} ({index.ntotal} vecteurs)")
    return index


# ── Gestion du mapping (métadonnées des chunks) ─────────────────────────

def save_chunks_mapping(
    chunks: list,
    doc_names: list,
    date_scores: list = None,
    page_numbers: list = None,
    categories: list = None,
    parent_texts: list = None,
    path: Path = CHUNKS_MAPPING_PATH,
):
    """
    Sauvegarde les métadonnées des chunks dans un fichier JSON.

    POURQUOI UN FICHIER SÉPARÉ ?
    ────────────────────────────
    FAISS stocke seulement les vecteurs (nombres flottants).
    Il ne stocke pas le texte original, le nom du fichier source, etc.
    → On maintient un fichier JSON parallèle :
      - FAISS index[i]   ↔   chunks_mapping[i]
      - Le i-ème vecteur FAISS correspond au i-ème dict dans le mapping JSON

    STRUCTURE D'UN CHUNK DANS LE MAPPING
    ──────────────────────────────────────
    {
        "text"       : "Glycémie à 7.2 mmol/L le 15/03/2024",  # texte court (embedding)
        "parent_text": "BIOLOGIE — résultats complets...",       # texte long (LLM context)
        "source"     : "1234_P00001_DUPONT_Marie.pdf",           # fichier source
        "date_score" : 0.82,                                      # récence (0-1)
        "page_number": 3,                                         # page dans le PDF
        "category"   : "BIOLOGIE",                               # section médicale
        "indexed_at" : "2026-03-15T10:30:00+00:00"              # date d'indexation
    }

    Paramètres :
        chunks       : liste de textes courts (enfants, pour l'embedding)
        doc_names    : liste des noms de fichiers sources
        date_scores  : scores de récence (0.0 par défaut)
        page_numbers : numéros de pages (1 par défaut)
        categories   : catégories médicales ('AUTRE' par défaut)
        parent_texts : textes longs pour le LLM (= chunks si non fournis)
        path         : chemin de sauvegarde JSON
    """
    # Valeurs par défaut si les listes optionnelles ne sont pas fournies
    if date_scores is None:
        date_scores = [0.0] * len(chunks)
    if page_numbers is None:
        page_numbers = [1] * len(chunks)
    if categories is None:
        categories = ['AUTRE'] * len(chunks)
    if parent_texts is None:
        parent_texts = list(chunks)  # fallback: parent = enfant

    indexed_at = datetime.now(timezone.utc).isoformat()

    mapping = [
        {
            "text":        chunk,
            "source":      doc,
            "date_score":  ds,
            "page_number": pg,
            "category":    cat,
            "parent_text": pt,
            "indexed_at":  indexed_at,
        }
        for chunk, doc, ds, pg, cat, pt
        in zip(chunks, doc_names, date_scores, page_numbers, categories, parent_texts)
    ]

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)

    logger.info(f"[vector_store] Mapping sauvegardé : {len(mapping)} chunks")


def load_chunks_mapping(path: Path = CHUNKS_MAPPING_PATH) -> list:
    """
    Charge les métadonnées des chunks depuis le fichier JSON.

    Appelé au démarrage de l'application (main.py) et après chaque indexation.
    Comme l'index FAISS, le mapping est gardé en mémoire RAM.

    Retourne une liste vide si le fichier n'existe pas encore
    (ex: première utilisation avant tout document indexé).

    Paramètres :
        path : chemin du fichier JSON (défaut: /app/data/chunks_mapping.json)

    Retourne :
        Liste de dicts, 1 dict par chunk (voir structure ci-dessus)
    """
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
