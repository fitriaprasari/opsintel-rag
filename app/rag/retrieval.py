"""
Hybrid retrieval pipeline.

Architecture:
  query
    ↓
  query classification + metadata extraction
    ↓
  dense retrieval  +  sparse (BM25) retrieval   (parallel)
    ↓
  Reciprocal Rank Fusion
    ↓
  optional cross-encoder reranking
    ↓
  context selection (top-K, access control, min score filter)
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.config import get_settings
from app.embeddings.provider import EmbeddingProvider
from app.models.domain import RetrievedDocument
from app.rag.bm25 import BM25Encoder
from app.rag.vector_store import QdrantVectorStore
from app.security.auth import Principal, check_document_access

logger = logging.getLogger(__name__)

# Optional cross-encoder reranker
try:
    from sentence_transformers import CrossEncoder as _CrossEncoder

    _HAVE_CROSS_ENCODER = True
except ImportError:
    _HAVE_CROSS_ENCODER = False


class RetrievalPipeline:
    """
    Orchestrates hybrid dense + sparse retrieval with fusion and optional reranking.
    """

    def __init__(
        self,
        vector_store: QdrantVectorStore,
        embedding_provider: EmbeddingProvider,
        bm25_encoder: BM25Encoder,
    ) -> None:
        self._vs = vector_store
        self._embedder = embedding_provider
        self._bm25 = bm25_encoder
        self._reranker = None
        _s = get_settings()
        if _s.reranker_enabled and _HAVE_CROSS_ENCODER:
            logger.info("Loading reranker: %s", _s.reranker_model)
            self._reranker = _CrossEncoder(_s.reranker_model)

    async def retrieve(
        self,
        query: str,
        metadata_filter: dict[str, str] | None = None,
        principal: Principal | None = None,
    ) -> list[RetrievedDocument]:
        """
        Execute hybrid retrieval and return ranked RetrievedDocument list.

        Args:
            query: Natural language query.
            metadata_filter: Optional dict of Qdrant payload field filters.
            principal: Caller principal for document access control.

        Returns:
            List of RetrievedDocument sorted by relevance (best first).
        """
        # 1. Embed query (dense)
        query_vector = self._embedder.embed_single(query)

        # 2. Encode query (sparse)
        sparse_query = self._bm25.encode_query(query)
        _s = get_settings()

        # 3. Run dense and sparse retrieval in parallel
        dense_task = asyncio.create_task(
            self._vs.dense_search(
                query_vector=query_vector,
                top_k=_s.retrieval_dense_top_k,
                metadata_filter=metadata_filter,
            )
        )

        if sparse_query["indices"]:
            sparse_task = asyncio.create_task(
                self._vs.sparse_search(
                    sparse_vector=sparse_query,
                    top_k=_s.retrieval_sparse_top_k,
                    metadata_filter=metadata_filter,
                )
            )
            dense_results, sparse_results = await asyncio.gather(dense_task, sparse_task)
        else:
            dense_results = await dense_task
            sparse_results = []

        # 4. Reciprocal Rank Fusion
        fused = _reciprocal_rank_fusion(
            dense_results,
            sparse_results,
            top_k=_s.retrieval_fusion_top_k,
        )

        # 5. Access control filter
        if principal:
            fused = [
                r for r in fused
                if check_document_access(
                    r["payload"].get("access_policy", {}), principal
                )
            ]

        # 6. Min score filter
        fused = [r for r in fused if r["rrf_score"] >= _s.retrieval_min_score]

        if not fused:
            return []

        # 7. Optional reranking
        if self._reranker and len(fused) > 1:
            fused = _rerank(query, fused, self._reranker, top_k=_s.reranker_top_k)

        # 8. Convert to domain model
        return [_to_retrieved_document(r) for r in fused]


# ── Reciprocal Rank Fusion ─────────────────────────────────────────────────────

def _reciprocal_rank_fusion(
    dense: list[dict[str, Any]],
    sparse: list[dict[str, Any]],
    k: int = 60,
    top_k: int = 10,
) -> list[dict[str, Any]]:
    """
    Merge dense and sparse result lists using Reciprocal Rank Fusion.
    RRF score = sum(1 / (k + rank)) across all result lists.
    """
    scores: dict[str, float] = {}
    payloads: dict[str, dict] = {}

    for rank, item in enumerate(dense, start=1):
        doc_id = item["id"]
        scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
        payloads[doc_id] = item["payload"]

    for rank, item in enumerate(sparse, start=1):
        doc_id = item["id"]
        scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
        payloads.setdefault(doc_id, item["payload"])

    merged = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
    return [
        {"id": doc_id, "rrf_score": score, "payload": payloads[doc_id]}
        for doc_id, score in merged
    ]


# ── Reranking ─────────────────────────────────────────────────────────────────

def _rerank(
    query: str,
    results: list[dict[str, Any]],
    reranker: Any,
    top_k: int,
) -> list[dict[str, Any]]:
    """Apply cross-encoder reranking to a list of fused results."""
    texts = [r["payload"].get("content", "") for r in results]
    pairs = [(query, t) for t in texts]
    scores = reranker.predict(pairs)
    ranked = sorted(
        zip(scores, results),
        key=lambda x: x[0],
        reverse=True,
    )[:top_k]
    for score, result in ranked:
        result["rerank_score"] = float(score)
    return [r for _, r in ranked]


# ── Conversion ────────────────────────────────────────────────────────────────

def _to_retrieved_document(result: dict[str, Any]) -> RetrievedDocument:
    payload = result["payload"]
    return RetrievedDocument(
        document_id=result["id"],
        title=payload.get("title", "Untitled"),
        source_type=payload.get("source_type", "unknown"),
        chunk_text=payload.get("content", ""),
        score=result.get("rerank_score", result["rrf_score"]),
        metadata={
            k: v
            for k, v in payload.items()
            if k not in ("content", "access_policy")
        },
    )
