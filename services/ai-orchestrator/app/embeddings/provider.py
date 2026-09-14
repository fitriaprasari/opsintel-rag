"""
Embedding provider — wraps sentence-transformers with a mock fallback.

EMBEDDING_MODEL=mock  → returns zero vectors instantly; no download needed.
                         Perfect for local dev, unit tests, and CI.

EMBEDDING_MODEL=BAAI/bge-small-en-v1.5  → ~130 MB, good for dev with real embeddings.
EMBEDDING_MODEL=BAAI/bge-large-en-v1.5  → ~1.3 GB, production quality.

The model is loaded LAZILY — on first embed() call, not at import time.
This means `uvicorn app.main:app` starts in seconds even without the model downloaded.
"""
from __future__ import annotations

import logging
from functools import lru_cache

import numpy as np

from app.config import get_settings

logger = logging.getLogger(__name__)

_MOCK_DIMENSION = 1024  # matches bge-large output dimension for schema compatibility


class MockEmbeddingProvider:
    """
    Zero-vector embedding provider used when EMBEDDING_MODEL=mock.
    Returns correctly shaped float32 arrays filled with zeros.
    Useful for: local dev startup, unit tests, CI pipelines.
    """

    @property
    def dimension(self) -> int:
        return _MOCK_DIMENSION

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, _MOCK_DIMENSION), dtype=np.float32)
        return np.zeros((len(texts), _MOCK_DIMENSION), dtype=np.float32)

    def embed_single(self, text: str) -> np.ndarray:
        return np.zeros(_MOCK_DIMENSION, dtype=np.float32)


class RealEmbeddingProvider:
    """
    sentence-transformers embedding provider.
    Model is downloaded and loaded lazily on first use.
    """

    def __init__(self, model_name: str, device: str, batch_size: int) -> None:
        self._model_name = model_name
        self._device = device
        self._batch_size = batch_size
        self._model = None  # lazy — not loaded until first call
        self._dimension: int | None = None

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        logger.info("Loading embedding model '%s' on %s (first use)…", self._model_name, self._device)
        from sentence_transformers import SentenceTransformer  # noqa: PLC0415
        self._model = SentenceTransformer(self._model_name, device=self._device)
        self._dimension = self._model.get_sentence_embedding_dimension()
        logger.info("Embedding model loaded. Dimension: %d", self._dimension)

    @property
    def dimension(self) -> int:
        self._ensure_loaded()
        return self._dimension  # type: ignore[return-value]

    def embed(self, texts: list[str]) -> np.ndarray:
        self._ensure_loaded()
        if not texts:
            return np.empty((0, self._dimension), dtype=np.float32)
        embeddings = self._model.encode(  # type: ignore[union-attr]
            texts,
            batch_size=self._batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return embeddings.astype(np.float32)

    def embed_single(self, text: str) -> np.ndarray:
        return self.embed([text])[0]


# Union type used by the rest of the codebase
EmbeddingProvider = MockEmbeddingProvider | RealEmbeddingProvider


@lru_cache(maxsize=1)
def get_embedding_provider() -> MockEmbeddingProvider | RealEmbeddingProvider:
    """
    Return the configured embedding provider (cached singleton).

    EMBEDDING_MODEL=mock        → MockEmbeddingProvider (instant, no download)
    EMBEDDING_MODEL=<hf-model>  → RealEmbeddingProvider (lazy model load)
    """
    s = get_settings()
    if s.embedding_model.lower() == "mock":
        logger.info("Using MockEmbeddingProvider (EMBEDDING_MODEL=mock)")
        return MockEmbeddingProvider()
    return RealEmbeddingProvider(
        model_name=s.embedding_model,
        device=s.embedding_device,
        batch_size=s.embedding_batch_size,
    )
