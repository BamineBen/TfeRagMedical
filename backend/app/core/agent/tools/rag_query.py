"""
rag_query.py — RAGQueryTool
Section 5 : Outil de requête RAG patient

Interroge la base documentaire médicale et génère un résumé patient.

STRATÉGIE DE RECHERCHE :
  - Patient connu  → Recherche DIRECTE par nom de fichier (fiable à 100%)
                     On évite FAISS qui peut retourner d'autres patients
                     (même pathologie, même médecin → faux positifs)
  - Requête libre  → FAISS sémantique (recherche dans tous les dossiers)

GÉNÉRATION DU RÉSUMÉ :
  - Mode cloud : Mistral API (~2-3s)
  - Mode local  : Ollama sur le serveur (~5-8s, données 100% privées)
                  Si Ollama indisponible → bascule automatiquement sur Mistral

Paramètres attendus :
  { "patient_name": str, "query": str, "llm_mode": "cloud"|"local" }
"""
import logging
import os
import time
from typing import List, Optional

import httpx

from app.core.agent.models import ToolResult
from app.core.agent.tools.base import AgentTool

logger = logging.getLogger(__name__)

# ── Prompt système Mistral/Ollama ─────────────────────────────────────
_SUMMARY_PROMPT = (
    "Tu es un assistant médical. À partir du dossier fourni, "
    "rédige un résumé médical concis en français (150-200 mots) structuré ainsi :\n"
    "- Antécédents notables\n"
    "- Traitements en cours\n"
    "- Dernière consultation / motif\n"
    "Sois précis et factuel. Ne mentionne QUE le patient indiqué."
)


# ══════════════════════════════════════════════════════════════════════
# Fonctions de recherche de chunks
# ══════════════════════════════════════════════════════════════════════

def _normalize(text: str) -> str:
    """
    Supprime les accents pour la comparaison de noms.
    'Frédéric' → 'frederic', 'Élodie' → 'elodie'

    Nécessaire car les noms de fichiers serveur peuvent avoir des accents
    alors que le nom extrait de la requête est souvent sans accent.
    """
    import unicodedata
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()


def _find_patient_chunks(all_chunks: List[dict], patient_name: str,
                         k: int = 15) -> List[dict]:
    """
    Recherche DIRECTE d'un patient dans tous les chunks par nom de fichier.

    POURQUOI PAS FAISS ?
    FAISS retourne les chunks sémantiquement proches de la requête.
    Problème : deux patients avec la même pathologie ou le même médecin
    auront des chunks similaires → FAISS peut retourner le mauvais patient.

    La recherche par nom de fichier est 100% fiable pour un patient connu :
    "Martine DURAND" → cherche "martine" ET "durand" dans le nom de fichier
    → trouve uniquement P00049_DURAND_Martine.txt.

    NORMALISATION DES ACCENTS :
    "Frédéric" → "frederic" pour matcher "P00007_AUBERT_Frédéric.txt"
    (les noms de fichiers gardent les accents mais les requêtes les perdent)

    Paramètres :
      all_chunks   : liste complète des chunks du rag_state
      patient_name : "Martine DURAND", "Frédéric Aubert", etc.
      k            : nombre max de chunks à retourner

    Retourne :
      Liste des chunks du bon patient, ou [] si introuvable
    """
    # Mots du nom normalisés (sans accents, min 3 chars)
    parts = [_normalize(p) for p in patient_name.split() if len(p) > 2]
    if not parts:
        return []

    # Passe 1 : STRICT — TOUS les mots dans le nom de fichier source
    # Comparaison sans accents des deux côtés
    # Ex : "frederic" ET "aubert" dans "p00007_aubert_frederic.txt" ✓
    strict = [
        c for c in all_chunks
        if all(p in _normalize(c.get("source", "")) for p in parts)
    ]
    if strict:
        logger.info("[RAGQueryTool] Match strict '%s' → %d chunks", patient_name, len(strict))
        return strict[:k]

    # Passe 2 : PARTIEL — seulement pour les noms à UN seul mot significatif
    # Ex : "LEBRETON" (1 mot) → cherche "lebreton" dans les sources
    # Évite les faux positifs : "Dupont Jean" → NE cherche PAS juste "dupont"
    # car cela trouverait "DUPONT Thomas" (mauvais patient)
    if len(parts) == 1:
        longest = parts[0]
        if len(longest) >= 5:
            partial = [
                c for c in all_chunks
                if longest in _normalize(c.get("source", ""))
            ]
            if partial:
                logger.info("[RAGQueryTool] Match partiel '%s' → %d chunks", longest, len(partial))
                return partial[:k]

    logger.info("[RAGQueryTool] Patient '%s' introuvable dans les sources", patient_name)
    return []


def _faiss_search(index, chunks: List[dict], query: str, k: int = 10) -> List[dict]:
    """
    Recherche FAISS sémantique (requêtes sans patient précis).

    Utilisée uniquement quand patient_name est vide (requête générale).
    Ex : "Qui a du diabète ?" → cherche dans tous les dossiers.

    Paramètres :
      index  : index FAISS en mémoire
      chunks : liste des chunks alignée avec l'index
      query  : question posée
      k      : nombre de résultats demandés
    """
    from app.core.embeddings import get_embedding_service
    from app.core.vector_store import search as faiss_search

    emb = get_embedding_service().encode([query])
    distances, indices = faiss_search(index, emb, k=k)

    hits = []
    for dist, idx in zip(distances[0].tolist(), indices[0].tolist()):
        if idx < 0 or idx >= len(chunks):
            continue
        chunk = dict(chunks[idx])
        chunk["score"] = float(dist)
        hits.append(chunk)
    return hits


# ══════════════════════════════════════════════════════════════════════
# Fonctions de résumé LLM
# ══════════════════════════════════════════════════════════════════════

def _call_mistral(context: str, patient_name: str) -> Optional[str]:
    """
    Génère un résumé via l'API Mistral (cloud).

    ⚠ Les données patient quittent le serveur. Utiliser uniquement
    pour des données fictives ou avec consentement explicite du patient.

    Retourne None si Mistral est indisponible.
    """
    api_key  = os.getenv("MISTRAL_API_KEY", "")
    base_url = os.getenv("MISTRAL_BASE_URL", "https://api.mistral.ai/v1").rstrip("/")
    model    = os.getenv("MISTRAL_MODEL_NAME", "mistral-small-latest")

    if not api_key:
        return None

    user_msg = (
        f"Patient : {patient_name}\n\n"
        f"Extrait du dossier :\n{context}\n\n"
        "Rédige le résumé médical."
    )
    try:
        with httpx.Client(timeout=12.0) as client:
            resp = client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model":       model,
                    "messages":    [
                        {"role": "system", "content": _SUMMARY_PROMPT},
                        {"role": "user",   "content": user_msg},
                    ],
                    "max_tokens":  280,
                    "temperature": 0.1,
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        logger.warning("[RAGQueryTool] Mistral indisponible : %s", exc)
        return None


def _call_ollama(context: str, patient_name: str) -> Optional[str]:
    """
    Génère un résumé via Ollama (VPS ou local).
    Utilise l'API native Ollama /api/chat (pas l'OpenAI-compat /v1).
    Retourne None si Ollama est indisponible.
    """
    base_url = os.getenv("VLLM_BASE_URL", "http://ollama:11434").rstrip("/")
    # L'API native Ollama est sur /api/chat, pas /v1/api/chat
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]
    model    = os.getenv("VLLM_MODEL_NAME", "qwen2.5:1.5b-instruct")

    user_msg = (
        f"Patient : {patient_name}\n\n"
        f"Extrait du dossier :\n{context}\n\n"
        "Rédige le résumé médical."
    )
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                f"{base_url}/api/chat",
                json={
                    "model":    model,
                    "stream":   False,
                    "messages": [
                        {"role": "system", "content": _SUMMARY_PROMPT},
                        {"role": "user",   "content": user_msg},
                    ],
                    "options": {"temperature": 0.1, "num_predict": 280},
                },
            )
            resp.raise_for_status()
            return resp.json()["message"]["content"].strip()
    except Exception as exc:
        logger.warning("[RAGQueryTool] Ollama indisponible : %s", exc)
        return None


def _generate_summary(context: str, patient_name: str,
                       llm_mode: str = "cloud") -> tuple:
    """
    Génère un résumé médical avec la stratégie en cascade :

      Mode "local"  → Ollama (privé) → si échec → Mistral (cloud)
      Mode "cloud"  → Mistral directement (~2-3s)
      Dernier recours → chunks bruts (illisible mais au moins quelque chose)

    Retourne :
      (résumé: str, llm_utilisé: str)
    """
    if llm_mode == "local":
        summary = _call_ollama(context, patient_name)
        if summary:
            return summary, "ollama-local"
        logger.warning("[RAGQueryTool] Ollama indisponible → bascule Mistral")
        summary = _call_mistral(context, patient_name)
        if summary:
            return summary, "mistral-fallback"
    else:
        summary = _call_mistral(context, patient_name)
        if summary:
            return summary, "mistral-small-latest"

    # Dernier recours : afficher les chunks bruts
    fallback_text = f"Informations pour {patient_name or 'ce patient'} :\n\n{context}"
    return fallback_text, "fallback (chunks bruts)"


# ══════════════════════════════════════════════════════════════════════
# Outil principal
# ══════════════════════════════════════════════════════════════════════

class RAGQueryTool(AgentTool):
    """
    Outil de consultation du dossier médical patient.

    Hérite de AgentTool (pattern Strategy).
    Correspond à RAGQueryTool du diagramme UML Section 5.

    Flux d'exécution :
      1. Charger l'index RAG depuis rag_state
      2. Chercher les chunks du patient (direct ou FAISS)
      3. Construire le contexte textuel
      4. Générer le résumé via LLM (Mistral ou Ollama)
      5. Retourner ToolResult avec le résumé et les sources
    """

    def __init__(self):
        super().__init__(
            name="rag_query",
            description="Interroge le dossier médical d'un patient et génère un résumé",
            requires_confirmation=False,
        )

    def validate_params(self, params: dict) -> bool:
        """Vérifie que les paramètres minimum sont présents."""
        return (
            isinstance(params, dict)
            and "patient_name" in params
            and "query" in params
        )

    def execute(self, params: dict) -> ToolResult:
        """
        Exécute la recherche RAG et génère le résumé médical.

        Paramètres (dans params) :
          patient_name : nom du patient (peut être vide pour requête libre)
          query        : question posée (utilisée pour FAISS si pas de patient)
          llm_mode     : "cloud" (Mistral) ou "local" (Ollama)

        Retourne :
          ToolResult avec :
            answer          : résumé médical généré par le LLM
            patient         : nom du patient
            sources         : nombre de chunks trouvés
            sources_preview : liste des fichiers sources
            patient_found   : False si patient introuvable
        """
        if not self.validate_params(params):
            return ToolResult.fail("Paramètres invalides : 'patient_name' et 'query' requis")

        patient_name: str = params["patient_name"]
        query:        str = params["query"]
        llm_mode:     str = params.get("llm_mode", "cloud")
        t0 = time.time()

        try:
            # ── Étape 1 : charger l'index RAG ────────────────────────
            from app.core.rag_state import rag_state
            index, chunks = rag_state.get()

            if index is None or not chunks:
                return ToolResult.fail(
                    "Index RAG non disponible — vérifiez que des documents sont indexés",
                    int((time.time() - t0) * 1000),
                )

            # ── Étape 2 : récupérer les chunks du patient ─────────────
            if patient_name:
                # Recherche directe par nom de fichier (plus fiable que FAISS)
                hits = _find_patient_chunks(chunks, patient_name, k=15)
            else:
                # Requête libre → recherche sémantique FAISS
                hits = _faiss_search(index, chunks, query, k=10)

            # ── Étape 3 : patient introuvable → message d'aide ────────
            if not hits:
                similar = self._find_similar_patients(chunks, patient_name)
                suggestion = ""
                if similar:
                    suggestion = (
                        "\n\nPatients aux noms similaires dans la base :\n"
                        + "\n".join(f"  • {s}" for s in similar[:4])
                    )
                return ToolResult.ok(
                    data={
                        "answer":   f"Patient « {patient_name} » non trouvé.{suggestion}",
                        "patient":  patient_name,
                        "query":    query,
                        "sources":  0,
                        "patient_found": False,
                        "sources_preview": [],
                    },
                    execution_time_ms=int((time.time() - t0) * 1000),
                )

            # ── Étape 4 : construire le contexte textuel ──────────────
            # On prend les 5 premiers chunks (les plus pertinents)
            # parent_text : texte complet de la section (meilleur pour le contexte)
            # text        : extrait court (fallback si parent_text absent)
            context = "\n\n".join(
                c.get("parent_text", c.get("text", ""))[:400]
                for c in hits[:5]
            )

            # ── Étape 5 : générer le résumé via LLM ──────────────────
            answer, llm_used = _generate_summary(context, patient_name or "ce patient", llm_mode)

            elapsed = int((time.time() - t0) * 1000)
            logger.info(
                "[RAGQueryTool] '%s' — %d chunks — %s — %dms",
                patient_name, len(hits), llm_used, elapsed,
            )

            return ToolResult.ok(
                data={
                    "answer":   answer,
                    "patient":  patient_name,
                    "query":    query,
                    "sources":  len(hits),
                    "llm_used": llm_used,
                    "patient_found": True,
                    "sources_preview": [
                        {
                            "source":   c.get("source", ""),
                            "score":    round(c.get("score", 0.0), 3),
                            "category": c.get("category", ""),
                        }
                        for c in hits[:5]
                    ],
                },
                execution_time_ms=elapsed,
            )

        except Exception as exc:
            logger.error("[RAGQueryTool] Erreur inattendue : %s", exc)
            return ToolResult.fail(str(exc), int((time.time() - t0) * 1000))

    @staticmethod
    def _find_similar_patients(chunks: List[dict], patient_name: str) -> List[str]:
        """
        Cherche des patients aux noms similaires dans la base.

        Utile pour guider le médecin quand un patient n'est pas trouvé.
        Ex : "Sophie Martin" introuvable → suggère "Sophie MARTINEZ"

        Paramètres :
          chunks       : liste complète des chunks
          patient_name : nom cherché

        Retourne :
          Liste de noms formatés ("DURAND Martine", "MARTIN Jean Claude")
        """
        if not patient_name:
            return []

        parts = [p.lower() for p in patient_name.split() if len(p) > 2]
        seen_sources: set = set()
        similar: List[str] = []

        for chunk in chunks:
            src = chunk.get("source", "")
            src_lower = src.lower()

            # Ne traiter chaque fichier source qu'une seule fois
            if src in seen_sources:
                continue

            # Vérifier si un mot du nom apparaît dans le nom de fichier (sans accents)
            if any(p in _normalize(src) for p in parts):
                seen_sources.add(src)
                # Extraire le nom depuis "P00049_DURAND_Martine.txt" → "DURAND Martine"
                name_part = src.replace(".txt", "").replace(".pdf", "")
                # Supprimer le préfixe numérique (P00049_ ou timestamp_P00049_)
                import re
                name_part = re.sub(r"^\d+_P\d+_|^P\d+_", "", name_part)
                similar.append(name_part.replace("_", " "))

        return similar[:5]
