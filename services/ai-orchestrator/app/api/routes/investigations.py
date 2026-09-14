"""
Investigation endpoints.
POST /investigate — submit an investigation
GET  /investigate/{id} — retrieve a result
POST /investigate/{id}/feedback — submit feedback
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.context_builder import ContextBuilder
from app.agents.investigator import InvestigationAgent
from app.correlation.engine import CorrelationEngine
from app.db.session import get_db
from app.embeddings.provider import get_embedding_provider
from app.inference.openai_compat import get_llm_provider
from app.models.domain import (
    FeedbackRequest,
    InvestigationRequest,
    InvestigationResponse,
)
from app.models.orm import FeedbackORM, InvestigationORM
from app.rag.bm25 import BM25Encoder
from app.rag.retrieval import RetrievalPipeline
from app.rag.vector_store import QdrantVectorStore, make_qdrant_client
from app.security.auth import Principal, get_current_principal, require_role, sanitise_query
from app.telemetry.factory import get_telemetry_provider

logger = logging.getLogger(__name__)
router = APIRouter()


def _build_agent() -> InvestigationAgent:
    """Construct the investigation pipeline (singleton-like, cheap to rebuild)."""
    from app.config import get_settings
    s = get_settings()
    embedder = get_embedding_provider()
    qdrant_client = make_qdrant_client()
    vs = QdrantVectorStore(qdrant_client, s.qdrant_collection, embedder.dimension)
    bm25 = BM25Encoder()
    retrieval = RetrievalPipeline(vs, embedder, bm25)
    telemetry = get_telemetry_provider()
    correlation = CorrelationEngine(telemetry)
    return InvestigationAgent(
        correlation_engine=correlation,
        retrieval_pipeline=retrieval,
        llm_provider=get_llm_provider(),
        context_builder=ContextBuilder(),
    )


@router.post(
    "/investigate",
    response_model=InvestigationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_investigation(
    request: InvestigationRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "operator")),
) -> InvestigationResponse:
    """
    Submit an incident investigation request.
    Triggers the full dual-retrieval pipeline and LLM inference.
    """
    request.query = sanitise_query(request.query)
    agent = _build_agent()
    return await agent.investigate(request, db, principal)


@router.get("/investigate/{investigation_id}", response_model=InvestigationResponse)
async def get_investigation(
    investigation_id: str,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "operator", "viewer")),
) -> InvestigationResponse:
    """Retrieve a previously computed investigation by ID."""
    result = await db.execute(
        select(InvestigationORM).where(InvestigationORM.id == investigation_id)
    )
    orm = result.scalars().first()
    if not orm:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return InvestigationResponse.model_validate(orm.response_json)


@router.post("/investigate/{investigation_id}/feedback", status_code=status.HTTP_204_NO_CONTENT)
async def submit_feedback(
    investigation_id: str,
    feedback: FeedbackRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
) -> None:
    """Submit quality feedback for an investigation result."""
    # Verify investigation exists
    result = await db.execute(
        select(InvestigationORM).where(InvestigationORM.id == investigation_id)
    )
    if not result.scalars().first():
        raise HTTPException(status_code=404, detail="Investigation not found")

    fb = FeedbackORM(
        investigation_id=investigation_id,
        rating=feedback.rating,
        comment=feedback.comment,
        created_by=principal.subject,
    )
    db.add(fb)
    await db.flush()
