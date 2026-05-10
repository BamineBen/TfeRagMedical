"""
rag_engine.py — Orchestrateur principal du pipeline RAG
════════════════════════════════════════════════════════

RÔLE DANS L'ARCHITECTURE
─────────────────────────
Ce module est le CHEF D'ORCHESTRE du pipeline RAG.
Il coordonne les 3 étapes principales :
  1. RETRIEVE  → retriever.py      (trouver les chunks pertinents)
  2. BUILD     → context_builder.py (construire le contexte textuel + citations)
  3. GENERATE  → prompts.py         (assembler le prompt pour le LLM)

Il expose une seule fonction publique : build_rag_prompt().

PRINCIPE SRP (Single Responsibility Principle)
───────────────────────────────────────────────
Chaque étape du pipeline est dans son propre module :
- retriever.py    → UNIQUEMENT la recherche (FAISS, BM25, reranking)
- context_builder.py → UNIQUEMENT la construction du contexte
- prompts.py      → UNIQUEMENT la génération des prompts LLM
- rag_engine.py   → UNIQUEMENT l'orchestration des 3 étapes ci-dessus

Si tu dois modifier la logique de recherche → touche retriever.py
Si tu dois modifier les prompts LLM → touche prompts.py
Ce module ne change QUE si l'orchestration globale change.

COMMENT ÇA MARCHE ? (pour les débutants)
─────────────────────────────────────────
1. Le médecin pose une question : "Quels sont les traitements de Sophie LECOMTE ?"
2. build_rag_prompt() est appelé avec cette question.
3. retrieve_chunks() cherche les 15 extraits les plus pertinents dans FAISS.
4. build_context() les formate avec des numéros [1], [2], [3]... (citations).
5. generate_system_prompt() assemble le prompt final pour le LLM.
6. Le LLM (qwen2.5 / Mistral / Gemini) génère la réponse structurée.
"""
import logging

from app.config import settings
from app.utils.naming import patient_label as _patient_label

from app.core.rag.prompts import (
    classify_query,
    generate_system_prompt,
    get_greeting_response,
    get_offtopic_response,
    is_cohort_query,
    is_soap_query,
    is_english
)
from app.core.rag.retriever import retrieve_chunks
from app.core.rag.context_builder import build_context, _build_cohort_table_local

logger = logging.getLogger(__name__)

# Valeurs par défaut chargées depuis .env (via app/config.py → Settings)
TOP_K = settings.TOP_K_RESULTS          # Nombre de chunks à récupérer (ex: 15)
MIN_SCORE = settings.SIMILARITY_THRESHOLD  # Score minimum de pertinence (ex: 0.15)
MAX_CONTEXT_CHARS = settings.MAX_CONTEXT_CHARS  # Taille max du contexte envoyé au LLM


def build_rag_prompt(
    query: str,
    index,
    chunks_mapping: list,
    k: int = TOP_K,
    min_score: float = MIN_SCORE,
    max_context_chars: int = MAX_CONTEXT_CHARS,
    source_filter=None,  # str | list[str] | None
    local_mode: bool = False,
) -> tuple:
    """
    Construit le prompt RAG complet pour une question médicale.

    C'est LA fonction centrale du système RAG. Elle orchestre les 3 étapes :
    Retrieve → Build context → Generate prompt.

    Paramètres :
        query           : question posée par le médecin
        index           : index FAISS en mémoire (vecteurs des chunks)
        chunks_mapping  : liste de tous les chunks (texte + métadonnées)
        k               : nombre de chunks à récupérer (défaut: TOP_K depuis .env)
        min_score       : score minimum de similarité (défaut: SIMILARITY_THRESHOLD)
        max_context_chars : limite de caractères pour le contexte LLM
        source_filter   : filtre par patient :
                          - str  : 1 seul fichier
                          - list : plusieurs fichiers (même patient, plusieurs PDFs)
                          - None : tous les patients (mode cohorte)
        local_mode      : True = LLM local (qwen2.5), False = API (Groq/Mistral/Gemini)

    Retourne un tuple (prompt, hits, citation_map) :
        - prompt       : texte complet à envoyer au LLM
        - hits         : liste des chunks trouvés (pour affichage frontend)
        - citation_map : liste des sources numériques [1], [2]... (pour le panneau citations)
    """
    # ── Étape 0 : Classification de la requête ─────────────────────────
    # Détermine si c'est une synthèse SOAP ou une recherche cohorte.
    use_soap = is_soap_query(query)
    is_cohort = is_cohort_query(query, source_filter)

    # ── Étape 1 : RETRIEVE — Recherche des chunks pertinents ───────────
    # retriever.py fait : FAISS + BM25 + RRF + reranking → retourne les k meilleurs chunks.
    hits = retrieve_chunks(
        query=query,
        index=index,
        chunks_mapping=chunks_mapping,
        k=k,
        min_score=min_score,
        source_filter=source_filter,
        use_soap=use_soap,
        is_cohort=is_cohort,
        local_mode=local_mode
    )

    # ── Étape 2 : BUILD CONTEXT — Construction du contexte numéroté ────
    # context_builder.py formate les chunks avec des labels [1], [2]...
    # pour que le LLM puisse citer ses sources dans sa réponse.
    context_block, citation_map, known_labels = build_context(
        hits=hits,
        max_context_chars=max_context_chars,
        is_cohort=is_cohort,
        local_mode=local_mode
    )

    # ── Calcul des métadonnées pour le prompt ──────────────────────────
    n_ext = len(citation_map)           # Nombre d'extraits dans le contexte
    n_pts = len(set(h["source"] for h in hits))  # Nombre de patients concernés

    # Détermine le label du patient affiché dans le prompt
    # (utilise le premier fichier si c'est une liste de sources)
    _first_src = (source_filter[0] if isinstance(source_filter, list) else source_filter)
    patient_label = _patient_label(_first_src) if _first_src else "ce patient"

    # Détecte si des notes atomiques sont présentes dans les résultats
    # (les notes ont priorité sur les PDFs en cas de contradiction)
    has_notes = any(
        h.get("note_id") or
        h["source"].upper().startswith("NOTE_") or
        ("NOTE_" in h["source"].upper() and h["source"].endswith(".txt"))
        for h in hits
    )

    # Détecte si le patient est basé UNIQUEMENT sur des notes (pas de PDF)
    _src_set = (
        set(source_filter) if isinstance(source_filter, list)
        else ({source_filter} if source_filter else set())
    )
    is_note_patient = any(
        s.upper().startswith("NOTE_") or (s.endswith(".txt") and "NOTE_" in s.upper())
        for s in _src_set
    )

    # ── Étape 3 : GENERATE PROMPT — Assemblage du prompt LLM ───────────
    # prompts.py choisit le bon template selon le type de requête :
    # question simple, synthèse SOAP, notes atomiques, ou cohorte.
    prompt = generate_system_prompt(
        query=query,
        context_block=context_block,
        n_ext=n_ext,
        n_pts=n_pts,
        patient_label=patient_label,
        has_notes=has_notes,
        is_note_patient=is_note_patient,
        use_soap=use_soap,
        is_cohort=is_cohort,
        local_mode=local_mode,
        known_labels=known_labels
    )

    return prompt, hits, citation_map


def get_all_patient_chunks(
    source_filter: str,
    chunks_mapping: list,
    max_chars: int = 40000,
) -> str:
    """
    Récupère tous les chunks d'un patient et les retourne concaténés.

    Différent de build_rag_prompt() :
    - build_rag_prompt() sélectionne les chunks PERTINENTS pour une question.
    - get_all_patient_chunks() retourne TOUS les chunks sans filtrage.

    Utilisé pour :
    - /api/summary    → résumé global complet du dossier
    - /api/alerts     → détection d'alertes médicales sur tout le dossier

    Paramètres :
        source_filter : nom du fichier patient (ex: '1775866601_P00012_LECOMTE_Sophie.pdf')
        chunks_mapping: liste complète des chunks indexés
        max_chars     : limite de caractères pour éviter les prompts trop longs

    Retourne :
        Texte complet du dossier (tous les chunks concaténés), tronqué à max_chars
    """
    patient_chunks = [
        c["text"]
        for c in chunks_mapping
        if c["source"] == source_filter and c.get("active", True)
    ]
    return "\n\n".join(patient_chunks)[:max_chars]


# Réexposition pour rétrocompatibilité (évite de casser les imports existants)
# Si d'autres modules faisaient "from rag_engine import _is_english", ça continue de marcher.
_is_english = is_english
