"""
Ingestion pipeline — orchestrates the full document → Qdrant flow.

Steps:
1. Parse raw content to plain text
2. Normalise whitespace
3. Compute content hash (dedup)
4. Semantic chunk
5. Enrich chunk metadata
6. Embed (dense)
7. Encode sparse (BM25)
8. Upsert to Qdrant
9. Register document in PostgreSQL
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.embeddings.provider import EmbeddingProvider
from app.models.domain import DocumentType, IngestRequest
from app.models.orm import RagDocumentORM
from app.rag.bm25 import BM25Encoder
from app.rag.chunker import Chunk, chunk_text
from app.rag.parser import compute_content_hash, parse_text
from app.rag.vector_store import QdrantVectorStore

logger = logging.getLogger(__name__)


class IngestionPipeline:
    def __init__(
        self,
        vector_store: QdrantVectorStore,
        embedding_provider: EmbeddingProvider,
        bm25_encoder: BM25Encoder,
    ) -> None:
        self._vs = vector_store
        self._embedder = embedding_provider
        self._bm25 = bm25_encoder

    async def ingest(
        self,
        request: IngestRequest,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """
        Full ingestion pipeline for one document.
        Returns a summary dict with document_id, chunk_count, latency_ms.
        """
        t0 = time.monotonic()

        # 1. Parse
        content_type = _guess_content_type(request.source_url)
        plain_text = parse_text(request.content, content_type)

        # 2. Dedup check
        content_hash = compute_content_hash(plain_text)
        existing = await db.get(RagDocumentORM, None)  # handled below via query
        # Check by content_hash
        from sqlalchemy import select
        result = await db.execute(
            select(RagDocumentORM).where(RagDocumentORM.content_hash == content_hash)
        )
        existing_doc = result.scalars().first()
        if existing_doc:
            logger.info("Document already indexed (hash=%s), skipping.", content_hash[:12])
            return {"document_id": existing_doc.id, "chunk_count": existing_doc.chunk_count, "skipped": True}

        # 3. Chunk
        _s = get_settings()
        base_metadata = _build_base_metadata(request)
        chunks: list[Chunk] = chunk_text(
            plain_text,
            max_chunk_chars=_s.retrieval_fusion_top_k * 120,  # ~1200
            overlap_chars=150,
            metadata=base_metadata,
        )
        if not chunks:
            raise ValueError("Document produced zero chunks after parsing.")

        chunk_texts = [c.text for c in chunks]

        # 4. Fit BM25 on this document's chunks (document-local vocabulary)
        self._bm25.fit(chunk_texts)

        # 5. Embed dense
        dense_vectors = self._embedder.embed(chunk_texts)

        # 6. Encode sparse
        sparse_vectors = [self._bm25.encode_document(t) for t in chunk_texts]

        # 7. Prepare payload dicts
        chunk_dicts = [
            {"text": c.text, "metadata": {**c.metadata, "title": request.title}}
            for c in chunks
        ]

        # 8. Upsert to Qdrant
        upserted = await self._vs.upsert_chunks(chunk_dicts, dense_vectors, sparse_vectors)

        # 9. Register in PostgreSQL
        doc_orm = RagDocumentORM(
            title=request.title,
            source_url=request.source_url,
            source_type=request.source_type.value,
            document_type=request.document_type.value,
            service_name=request.service_name,
            environment=request.environment,
            team=request.team,
            application=request.application,
            version=request.version,
            chunk_count=upserted,
            indexed_at=datetime.now(timezone.utc),
            content_hash=content_hash,
            metadata_=request.metadata,
        )
        db.add(doc_orm)
        await db.flush()
        await db.refresh(doc_orm)

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        logger.info(
            "Ingested '%s' → %d chunks in %dms (doc_id=%s)",
            request.title, upserted, elapsed_ms, doc_orm.id,
        )
        return {
            "document_id": doc_orm.id,
            "chunk_count": upserted,
            "latency_ms": elapsed_ms,
            "skipped": False,
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _guess_content_type(source_url: str | None) -> str:
    if not source_url:
        return "text/plain"
    url_lower = source_url.lower()
    if url_lower.endswith(".html") or url_lower.endswith(".htm"):
        return "text/html"
    if url_lower.endswith(".md") or url_lower.endswith(".markdown"):
        return "text/markdown"
    return "text/plain"


def _build_base_metadata(req: IngestRequest) -> dict[str, str | int]:
    meta: dict[str, str | int] = {
        "source_type": req.source_type.value,
        "document_type": req.document_type.value,
        "title": req.title,
    }
    for field in ("service_name", "environment", "team", "application", "version"):
        val = getattr(req, field, None)
        if val:
            meta[field] = val
    meta.update({k: v for k, v in req.metadata.items() if isinstance(v, (str, int))})
    return meta
