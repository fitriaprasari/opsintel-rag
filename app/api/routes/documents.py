"""
Document management endpoints.
POST /ingest      — ingest a document into the knowledge base
GET  /documents   — list registered documents
DELETE /documents/{id} — remove a document
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_db
from app.embeddings.provider import get_embedding_provider
from app.models.domain import IngestRequest
from app.models.orm import RagDocumentORM
from app.rag.bm25 import BM25Encoder
from app.rag.ingestion import IngestionPipeline
from app.rag.vector_store import QdrantVectorStore, make_qdrant_client
from app.security.auth import Principal, require_role

router = APIRouter()


def _build_ingestion_pipeline() -> IngestionPipeline:
    s = get_settings()
    embedder = get_embedding_provider()
    client = make_qdrant_client()
    vs = QdrantVectorStore(client, s.qdrant_collection, embedder.dimension)
    return IngestionPipeline(vs, embedder, BM25Encoder())


@router.post("/ingest", status_code=status.HTTP_202_ACCEPTED)
async def ingest_document(
    request: IngestRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "ingest")),
):
    """
    Ingest a document into the knowledge base.
    Returns document_id and chunk_count on success.
    """
    pipeline = _build_ingestion_pipeline()
    result = await pipeline.ingest(request, db)
    return result


@router.get("/documents")
async def list_documents(
    service_name: str | None = None,
    environment: str | None = None,
    document_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "operator", "viewer")),
):
    """List all indexed documents with optional filters."""
    query = select(RagDocumentORM)
    if service_name:
        query = query.where(RagDocumentORM.service_name == service_name)
    if environment:
        query = query.where(RagDocumentORM.environment == environment)
    if document_type:
        query = query.where(RagDocumentORM.document_type == document_type)
    query = query.order_by(RagDocumentORM.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    docs = result.scalars().all()
    return [
        {
            "id": d.id,
            "title": d.title,
            "source_type": d.source_type,
            "document_type": d.document_type,
            "service_name": d.service_name,
            "environment": d.environment,
            "chunk_count": d.chunk_count,
            "indexed_at": d.indexed_at,
        }
        for d in docs
    ]


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
):
    """Remove a document record from PostgreSQL (Qdrant cleanup requires separate job)."""
    result = await db.execute(
        select(RagDocumentORM).where(RagDocumentORM.id == document_id)
    )
    doc = result.scalars().first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await db.delete(doc)
    await db.flush()
