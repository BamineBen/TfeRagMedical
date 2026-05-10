"""
Cache en mémoire pour les requêtes RAG.
Évite de recalculer embedding + FAISS + LLM pour des questions déjà posées.

Stratégie :
  - Clé     : SHA256(question.strip().lower() + "|" + (source_filter or ""))
  - TTL     : 30 minutes par défaut (configurable)
  - Max     : 200 entrées (LRU — on supprime la plus ancienne si dépassé)
  - Reset   : cache.invalidate_all() appelé après ajout/suppression de documents

Source : rag_theorie/rag/backend/query_cache.py (identique)
"""
import hashlib
import time
import logging
from collections import OrderedDict

logger = logging.getLogger(__name__)

_DEFAULT_TTL_SECONDS = 30 * 60   # 30 minutes
_DEFAULT_MAX_SIZE    = 200


class QueryCache:
    """Cache LRU thread-safe (GIL) pour les réponses RAG."""

    def __init__(self, ttl: int = _DEFAULT_TTL_SECONDS, max_size: int = _DEFAULT_MAX_SIZE):
        self._store: OrderedDict = OrderedDict()
        self._ttl = ttl
        self._max_size = max_size
        self._hits = 0
        self._misses = 0

    # ── Clé ──────────────────────────────────────────────────────────

    @staticmethod
    def make_key(question: str, source_filter) -> str:
        raw = question.strip().lower() + "|" + (source_filter or "")
        return hashlib.sha256(raw.encode()).hexdigest()[:20]

    # ── Accès ─────────────────────────────────────────────────────────

    def get(self, key: str):
        """Retourne la valeur cachée ou None si absente / expirée."""
        if key not in self._store:
            self._misses += 1
            return None

        value, ts = self._store[key]
        if time.time() - ts > self._ttl:
            del self._store[key]
            self._misses += 1
            logger.debug(f"[cache] EXPIRED key={key[:8]}")
            return None

        self._store.move_to_end(key)
        self._hits += 1
        logger.debug(f"[cache] HIT key={key[:8]} (hits={self._hits})")
        return value

    def set(self, key: str, value) -> None:
        """Stocke une valeur dans le cache."""
        if key in self._store:
            self._store.move_to_end(key)
        self._store[key] = (value, time.time())

        while len(self._store) > self._max_size:
            evicted_key, _ = self._store.popitem(last=False)
            logger.debug(f"[cache] EVICT key={evicted_key[:8]}")

    def invalidate_all(self) -> None:
        """Vide le cache (appeler après ajout/suppression de document)."""
        n = len(self._store)
        self._store.clear()
        logger.info(f"[cache] INVALIDATED ({n} entrées supprimées)")

    @property
    def stats(self) -> dict:
        return {
            "size": len(self._store),
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / max(1, self._hits + self._misses) * 100, 1),
        }


# ── Instance globale ──────────────────────────────────────────────────
query_cache = QueryCache()
