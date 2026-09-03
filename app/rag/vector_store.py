"""
Qdrant vector store adapter.
Implements hybrid retrieval: dense (cosine) + sparse (BM25) + metadata filter.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

import numpy as np
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels
from qdrant_client.http.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    SparseVector,
    SparseVectorParams,
    VectorParams,
    VectorsConfig,
)

from app.config import get_settings

logger = logging.getLogger(__name__)

DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"


class QdrantVectorStore:
    """
    Qdrant adapter implementing the VectorStore interface.
    Supports:
    - Dense cosine retrieval (sentence-transformers embeddings)
    - Sparse BM25 retrieval
    - Metadata filtering
    """

    def __init__(self, client: AsyncQdrantClient, collection: str, dimension: int) -> None:
        self._client = client
        self._collection = collection
        self._dimension = dimension

    # ── Collection management ─────────────────────────────────────────────

    async def ensure_collection(self) -> None:
        """Create collection if it does not already exist."""
        collections = await self._client.get_collections()
        names = [c.name for c in collections.collections]
        if self._collection in names:
            logger.info("Qdrant collection '%s' already exists.", self._collection)
            return

        await self._client.create_collection(
            collection_name=self._collection,
            vectors_config={
                DENSE_VECTOR_NAME: VectorParams(
                    size=self._dimension,
                    distance=Distance.COSINE,
                )
            },
            sparse_vectors_config={
                SPARSE_VECTOR_NAME: SparseVectorParams()
            },
        )
        # Create payload indexes for metadata filtering
        for field in [
            "service_name", "environment", "document_type",
            "source_type", "team", "application", "cluster",
            "namespace", "region", "severity",
        ]:
            await self._client.create_payload_index(
                collection_name=self._collection,
                field_name=field,
                field_schema=qmodels.PayloadSchemaType.KEYWORD,
            )
        logger.info("Qdrant collection '%s' created.", self._collection)

    # ── Upsert ────────────────────────────────────────────────────────────

    async def upsert_chunks(
        self,
        chunks: list[dict[str, Any]],
        dense_vectors: np.ndarray,
        sparse_vectors: list[dict[str, list]],
    ) -> int:
        """
        Upsert document chunks as Qdrant points.

        Args:
            chunks: List of dicts with 'text' and 'metadata' keys.
            dense_vectors: float32 ndarray of shape (N, dim).
            sparse_vectors: List of dicts with 'indices' and 'values' lists.

        Returns:
            Number of points upserted.
        """
        points: list[PointStruct] = []
        for i, chunk in enumerate(chunks):
            point_id = str(uuid.uuid4())
            payload = {**chunk.get("metadata", {}), "content": chunk["text"]}
            points.append(
                PointStruct(
                    id=point_id,
                    vector={
                        DENSE_VECTOR_NAME: dense_vectors[i].tolist(),
                        SPARSE_VECTOR_NAME: SparseVector(
                            indices=sparse_vectors[i]["indices"],
                            values=sparse_vectors[i]["values"],
                        ),
                    },
                    payload=payload,
                )
            )

        await self._client.upsert(
            collection_name=self._collection,
            points=points,
            wait=True,
        )
        return len(points)

    # ── Dense retrieval ───────────────────────────────────────────────────

    async def dense_search(
        self,
        query_vector: np.ndarray,
        top_k: int,
        metadata_filter: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """Dense cosine similarity search with optional metadata filter."""
        qdrant_filter = _build_filter(metadata_filter) if metadata_filter else None
        results = await self._client.search(
            collection_name=self._collection,
            query_vector=(DENSE_VECTOR_NAME, query_vector.tolist()),
            limit=top_k,
            query_filter=qdrant_filter,
            with_payload=True,
        )
        return [
            {
                "id": str(r.id),
                "score": r.score,
                "payload": r.payload or {},
            }
            for r in results
        ]

    # ── Sparse retrieval ──────────────────────────────────────────────────

    async def sparse_search(
        self,
        sparse_vector: dict[str, list],
        top_k: int,
        metadata_filter: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """BM25-style sparse retrieval."""
        qdrant_filter = _build_filter(metadata_filter) if metadata_filter else None
        results = await self._client.search(
            collection_name=self._collection,
            query_vector=qmodels.NamedSparseVector(
                name=SPARSE_VECTOR_NAME,
                vector=SparseVector(
                    indices=sparse_vector["indices"],
                    values=sparse_vector["values"],
                ),
            ),
            limit=top_k,
            query_filter=qdrant_filter,
            with_payload=True,
        )
        return [
            {
                "id": str(r.id),
                "score": r.score,
                "payload": r.payload or {},
            }
            for r in results
        ]


# ── Filter builder ────────────────────────────────────────────────────────────

def _build_filter(metadata_filter: dict[str, str]) -> Filter:
    """Convert a flat k/v metadata dict into a Qdrant Filter (AND of MatchValue)."""
    conditions = [
        FieldCondition(key=k, match=MatchValue(value=v))
        for k, v in metadata_filter.items()
        if v
    ]
    return Filter(must=conditions) if conditions else None


# ── Client factory ────────────────────────────────────────────────────────────

def make_qdrant_client() -> AsyncQdrantClient:
    s = get_settings()
    kwargs: dict[str, Any] = {"host": s.qdrant_host, "port": s.qdrant_port}
    if s.qdrant_api_key:
        kwargs["api_key"] = s.qdrant_api_key
    return AsyncQdrantClient(**kwargs)
