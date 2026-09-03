"""
Mock LLM provider — returns a canned structured investigation response.
Used when LLM_PROVIDER=mock (local dev, tests, CI).
No HTTP calls made. Instant response.
"""
from __future__ import annotations

import json
import logging

from app.inference.base import LLMProvider, LLMResponse

logger = logging.getLogger(__name__)

_CANNED_RESPONSE = {
    "incident_summary": (
        "The service is experiencing elevated error rates and latency. "
        "Live telemetry shows active alerts and metric anomalies. "
        "This is a MOCK LLM response — connect a real LLM for production investigations."
    ),
    "affected_services": ["mock-service"],
    "observations": [
        {
            "finding": "Mock LLM provider active — LLM_PROVIDER=mock in .env",
            "evidence_type": "FACT",
            "source": "system",
        },
        {
            "finding": "Live telemetry was successfully retrieved from the mock telemetry provider",
            "evidence_type": "FACT",
            "source": "telemetry",
        },
        {
            "finding": "RAG retrieval executed against Qdrant (results depend on indexed documents)",
            "evidence_type": "FACT",
            "source": "rag",
        },
    ],
    "root_cause_hypotheses": [
        {
            "hypothesis": "Replace LLM_PROVIDER=mock with llamacpp or vllm for real analysis",
            "confidence": 1.0,
            "evidence_type": "RECOMMENDATION",
            "supporting_evidence": ["This is a development placeholder response"],
            "contradicting_evidence": [],
        }
    ],
    "recommended_checks": [
        "Set LLM_PROVIDER=llamacpp in .env and start the llama.cpp server",
        "Or set LLM_PROVIDER=vllm and start a vLLM instance",
        "Then re-submit this investigation for a real AI analysis",
    ],
    "recommended_remediation": [
        "See RUNNING.md for instructions on connecting a real LLM backend"
    ],
    "retrieved_sources": [],
}


class MockLLMProvider(LLMProvider):
    """
    Instant mock LLM that returns a fixed canned response.
    Verifies the full pipeline (telemetry fetch, RAG retrieval, context build)
    works end-to-end without a real LLM.
    """

    @property
    def model_name(self) -> str:
        return "mock-llm"

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResponse:
        logger.info(
            "MockLLMProvider returning canned response (LLM_PROVIDER=mock). "
            "Set LLM_PROVIDER=llamacpp or vllm for real inference."
        )
        content = json.dumps(_CANNED_RESPONSE)
        return LLMResponse(
            content=content,
            model="mock-llm",
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            finish_reason="stop",
        )
