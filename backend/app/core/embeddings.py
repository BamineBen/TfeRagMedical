"""
Embeddings SentenceTransformers — singleton avec encode() normalisé pour FAISS.
"""
import logging

import numpy as np
import faiss
from sentence_transformers import SentenceTransformer
from app.config import settings

logger = logging.getLogger(__name__)
_model = None


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        name = settings.EMBEDDING_MODEL
        logger.info(f"[Embedder] Chargement de '{name}'...")
        _model = SentenceTransformer(name)
        logger.info(f"[Embedder] Prêt. Dimension = {_model.get_sentence_embedding_dimension()}")
    return _model


def get_dimension() -> int:
    return get_model().get_sentence_embedding_dimension()


class EmbeddingService:
    """Wrapper singleton compatible avec l'ancien code."""

    def __init__(self):
        pass

    def encode(self, texts: list[str], normalize: bool = True) -> np.ndarray:
        model = get_model()
        embeddings = model.encode(texts).astype("float32")
        if normalize:
            faiss.normalize_L2(embeddings)
        return embeddings

    def embed_text(self, text: str) -> list[float]:
        return self.encode([text])[0].tolist()


_service = None


def get_embedding_service() -> EmbeddingService:
    global _service
    if _service is None:
        _service = EmbeddingService()
    return _service
