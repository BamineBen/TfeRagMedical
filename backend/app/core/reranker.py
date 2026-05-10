"""
Module de re-ranking basé sur un cross-encoder.
Après la recherche FAISS (bi-encoder, rapide mais approximatif),
ce module re-trie les candidats avec un cross-encoder (précis sur les paires query/chunk).

Modèle : cross-encoder/mmarco-mMiniLMv2-L12-H384-v1
  → Multilingue (français), léger (~200MB), 64ms/chunk en CPU.

Source : rag_theorie/rag/backend/reranker.py
"""
import logging
from sentence_transformers.cross_encoder import CrossEncoder

logger = logging.getLogger(__name__)

# ── Singleton cross-encoder ───────────────────────────────────────────
_model = None
_MODEL_NAME = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"


def get_model() -> CrossEncoder:
    """Charge le cross-encoder une seule fois (lazy singleton)."""
    global _model
    if _model is None:
        logger.info(f"[reranker] Chargement du cross-encoder : {_MODEL_NAME}")
        _model = CrossEncoder(_MODEL_NAME, max_length=512)
        logger.info("[reranker] Cross-encoder prêt.")
    return _model


def rerank(query: str, hits: list, top_k: int) -> list:
    """
    Re-trie les hits par pertinence réelle (cross-encoder).

    Args:
        query   : la question de l'utilisateur
        hits    : liste de dicts {"text": ..., "score": ..., "source": ...}
        top_k   : nombre de résultats à retourner après re-ranking

    Returns:
        Liste des hits re-triés, de meilleur à moins bon, tronquée à top_k.
    """
    if not hits:
        return hits

    model = get_model()
    pairs = [(query, hit["text"]) for hit in hits]
    ce_scores = model.predict(pairs, show_progress_bar=False)

    for hit, score in zip(hits, ce_scores):
        hit["ce_score"] = float(score)

    return sorted(hits, key=lambda h: h["ce_score"], reverse=True)[:top_k]
