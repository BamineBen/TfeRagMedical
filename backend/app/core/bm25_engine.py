"""
Moteur de recherche BM25 pour la recherche hybride (BM25 + FAISS).
BM25 = recherche textuelle classique (excellente pour termes exacts :
dosages, codes médicaux, noms de médicaments).

Utilisé en complément de FAISS pour la recherche multipatient.
Fusion via Reciprocal Rank Fusion (RRF).

Source : rag_theorie/rag/backend/bm25_engine.py (identique)
"""
import re
import logging
from rank_bm25 import BM25Okapi

logger = logging.getLogger(__name__)

# ── Tokenizer français simple ─────────────────────────────────────────

_STOP_WORDS = {
    "le", "la", "les", "de", "du", "des", "un", "une", "et", "est", "en",
    "au", "aux", "par", "sur", "dans", "avec", "pour", "que", "qui", "ou",
    "se", "ce", "il", "elle", "ils", "elles", "je", "tu", "nous", "vous",
    "son", "sa", "ses", "mon", "ma", "mes", "ton", "ta", "tes", "leur",
    "pas", "ne", "plus", "très", "été", "être", "avoir", "faire", "tout",
    "mais", "donc", "car", "si", "comme",
}


def _tokenize(text: str) -> list:
    """Tokenise un texte français : minuscules, sans accents, sans stop-words."""
    text = text.lower()
    text = (text
        .replace("é", "e").replace("è", "e").replace("ê", "e").replace("ë", "e")
        .replace("à", "a").replace("â", "a").replace("ä", "a")
        .replace("ô", "o").replace("ö", "o").replace("î", "i").replace("ï", "i")
        .replace("ù", "u").replace("û", "u").replace("ü", "u")
        .replace("ç", "c").replace("œ", "oe").replace("æ", "ae")
    )
    tokens = re.findall(r'[a-z0-9]+', text)
    return [t for t in tokens if len(t) > 2 and t not in _STOP_WORDS]


# ── Index BM25 ────────────────────────────────────────────────────────

class BM25Engine:
    """Index BM25 sur les chunks médicaux avec recherche par mots-clés."""

    def __init__(self):
        self._index = None
        self._corpus: list = []

    def build(self, chunks_mapping: list) -> None:
        """Construit l'index BM25 depuis le mapping de chunks."""
        self._corpus = chunks_mapping
        tokenized = [_tokenize(c["text"]) for c in chunks_mapping]
        self._index = BM25Okapi(tokenized)
        logger.info(f"[bm25] Index construit : {len(chunks_mapping)} documents")

    def search(self, query: str, top_k: int = 200) -> list:
        """
        Retourne les top_k chunks par score BM25.
        Format : [{"text":..., "score":..., "source":..., "bm25_rank":N}]
        """
        if self._index is None or not self._corpus:
            return []

        tokens = _tokenize(query)
        if not tokens:
            return []

        scores = self._index.get_scores(tokens)

        ranked = sorted(
            enumerate(scores),
            key=lambda x: x[1],
            reverse=True,
        )[:top_k]

        results = []
        for rank, (idx, score) in enumerate(ranked):
            if score > 0:
                chunk = self._corpus[idx]
                results.append({
                    "text": chunk["text"],
                    "score": float(score),
                    "source": chunk["source"],
                    "bm25_rank": rank,
                })
        return results

    def is_ready(self) -> bool:
        return self._index is not None


def reciprocal_rank_fusion(
    faiss_hits: list,
    bm25_hits: list,
    k: int = 60,
    faiss_weight: float = 0.6,
    bm25_weight: float = 0.4,
) -> list:
    """
    Fusionne les résultats FAISS et BM25 via Reciprocal Rank Fusion (RRF).

    RRF(d) = Σ  weight_i / (k + rank_i(d))

    Args:
        faiss_hits   : résultats FAISS triés par score décroissant
        bm25_hits    : résultats BM25 triés par score décroissant
        k            : constante de lissage RRF (défaut 60, standard industrie)
        faiss_weight : poids du score FAISS (0.6 = légèrement favorisé)
        bm25_weight  : poids du score BM25

    Returns:
        Liste fusionnée triée par score RRF décroissant
    """
    scores: dict = {}

    def _chunk_key(hit: dict) -> str:
        return hit["source"] + "||" + hit["text"][:50]

    for rank, hit in enumerate(faiss_hits):
        key = _chunk_key(hit)
        if key not in scores:
            scores[key] = {"hit": hit, "rrf": 0.0}
        scores[key]["rrf"] += faiss_weight / (k + rank + 1)

    for rank, hit in enumerate(bm25_hits):
        key = _chunk_key(hit)
        if key not in scores:
            scores[key] = {"hit": hit, "rrf": 0.0}
        scores[key]["rrf"] += bm25_weight / (k + rank + 1)

    fused = sorted(scores.values(), key=lambda x: x["rrf"], reverse=True)
    result = []
    for item in fused:
        h = dict(item["hit"])
        h["rrf_score"] = round(item["rrf"], 6)
        result.append(h)
    return result


# ── Singleton global ──────────────────────────────────────────────────
bm25_engine = BM25Engine()
