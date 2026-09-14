"""
InvestigationAgent — orchestrates the full investigation pipeline:

  InvestigationRequest
    → CorrelationEngine.build_context()     [telemetry]
    → RetrievalPipeline.retrieve()          [knowledge RAG]
    → ContextBuilder.enrich() + to_prompt()
    → LLMProvider.complete()
    → Parse + validate response
    → Persist to PostgreSQL
    → Return InvestigationResponse
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.context_builder import ContextBuilder, PROMPT_VERSION
from app.config import get_settings
from app.correlation.engine import CorrelationEngine
from app.inference.base import LLMProvider
from app.models.domain import (
    EvidenceType,
    IncidentContext,
    InvestigationRequest,
    InvestigationResponse,
    Observation,
    RetrievedDocument,
    RootCauseHypothesis,
)
from app.models.orm import InvestigationORM
from app.rag.retrieval import RetrievalPipeline
from app.security.auth import Principal

logger = logging.getLogger(__name__)


class InvestigationAgent:
    def __init__(
        self,
        correlation_engine: CorrelationEngine,
        retrieval_pipeline: RetrievalPipeline,
        llm_provider: LLMProvider,
        context_builder: ContextBuilder,
    ) -> None:
        self._correlation = correlation_engine
        self._retrieval = retrieval_pipeline
        self._llm = llm_provider
        self._ctx_builder = context_builder

    async def investigate(
        self,
        request: InvestigationRequest,
        db: AsyncSession,
        principal: Principal | None = None,
    ) -> InvestigationResponse:
        """
        Full investigation pipeline.
        Returns a structured InvestigationResponse.
        """
        t_start = time.monotonic()

        # 1. Build telemetry context
        context: IncidentContext = await self._correlation.build_context(request)

        # 2. RAG retrieval
        t_rag_start = time.monotonic()
        metadata_filter = _build_rag_filter(request)
        rag_docs: list[RetrievedDocument] = await self._retrieval.retrieve(
            query=request.query,
            metadata_filter=metadata_filter,
            principal=principal,
        )
        rag_latency_ms = int((time.monotonic() - t_rag_start) * 1000)

        # 3. Enrich context with RAG docs
        enriched_context = self._ctx_builder.enrich(context, rag_docs)

        # 4. Build prompt
        system_prompt, user_message = self._ctx_builder.to_prompt(enriched_context)

        # 5. LLM inference
        t_llm_start = time.monotonic()
        llm_response = await self._llm.complete(system_prompt, user_message)
        llm_latency_ms = int((time.monotonic() - t_llm_start) * 1000)

        # 6. Parse LLM JSON output
        investigation_data = _parse_llm_response(llm_response.content)

        # 7. Build response
        response = InvestigationResponse(
            incident_summary=investigation_data.get("incident_summary", "No summary provided."),
            affected_services=investigation_data.get("affected_services", request.services),
            observations=[
                Observation(
                    finding=o.get("finding", ""),
                    evidence_type=_safe_evidence_type(o.get("evidence_type", "INFERENCE")),
                    source=o.get("source"),
                )
                for o in investigation_data.get("observations", [])
            ],
            root_cause_hypotheses=[
                RootCauseHypothesis(
                    hypothesis=h.get("hypothesis", ""),
                    confidence=_clamp(h.get("confidence", 0.0)),
                    evidence_type=EvidenceType.HYPOTHESIS,
                    supporting_evidence=h.get("supporting_evidence", []),
                    contradicting_evidence=h.get("contradicting_evidence", []),
                )
                for h in investigation_data.get("root_cause_hypotheses", [])
            ],
            recommended_checks=investigation_data.get("recommended_checks", []),
            recommended_remediation=investigation_data.get("recommended_remediation", []),
            retrieved_sources=rag_docs,
            llm_model=llm_response.model,
            prompt_version=PROMPT_VERSION,
            rag_latency_ms=rag_latency_ms,
            llm_latency_ms=llm_latency_ms,
            total_tokens=llm_response.total_tokens,
        )

        # 8. Persist
        await _persist_investigation(
            db=db,
            request=request,
            context=enriched_context,
            response=response,
            principal=principal,
        )

        total_ms = int((time.monotonic() - t_start) * 1000)
        logger.info(
            "Investigation complete: incident=%s rag=%dms llm=%dms total=%dms tokens=%d",
            context.incident_id, rag_latency_ms, llm_latency_ms, total_ms,
            llm_response.total_tokens,
        )
        return response


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_rag_filter(request: InvestigationRequest) -> dict[str, str]:
    """Build Qdrant metadata filter from investigation request."""
    f: dict[str, str] = {}
    if request.environment:
        f["environment"] = request.environment
    if request.metadata_filter:
        f.update(request.metadata_filter)
    return f if f else {}


def _parse_llm_response(content: str) -> dict:
    """
    Attempt to parse LLM response as JSON.
    Falls back to a minimal error dict on parse failure.
    """
    content = content.strip()
    # Strip markdown code fences if present
    if content.startswith("```"):
        lines = content.splitlines()
        content = "\n".join(
            line for line in lines
            if not line.startswith("```")
        )
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        logger.warning("LLM response was not valid JSON. Raw: %s", content[:200])
        return {
            "incident_summary": "LLM returned non-JSON output. Manual review required.",
            "affected_services": [],
            "observations": [
                {
                    "finding": f"Raw LLM output: {content[:500]}",
                    "evidence_type": "INFERENCE",
                    "source": "llm",
                }
            ],
            "root_cause_hypotheses": [],
            "recommended_checks": [],
            "recommended_remediation": [],
        }


def _safe_evidence_type(value: str) -> EvidenceType:
    try:
        return EvidenceType(value.upper())
    except ValueError:
        return EvidenceType.INFERENCE


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


async def _persist_investigation(
    db: AsyncSession,
    request: InvestigationRequest,
    context: IncidentContext,
    response: InvestigationResponse,
    principal: Principal | None,
) -> None:
    orm = InvestigationORM(
        incident_id=request.incident_id,
        query=request.query,
        context_json=context.model_dump(mode="json"),
        response_json=response.model_dump(mode="json"),
        llm_model=response.llm_model,
        prompt_version=response.prompt_version,
        rag_latency_ms=response.rag_latency_ms,
        llm_latency_ms=response.llm_latency_ms,
        total_tokens=response.total_tokens,
        created_by=principal.subject if principal else None,
    )
    db.add(orm)
    await db.flush()
