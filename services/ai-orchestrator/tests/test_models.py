"""
Unit tests for IncidentContext and domain model validation.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models.domain import (
    Alert,
    EvidenceType,
    IncidentContext,
    InvestigationRequest,
    InvestigationResponse,
    Observation,
    RetrievedDocument,
    RootCauseHypothesis,
    Severity,
)


class TestIncidentContext:
    def _make_context(self, **kwargs) -> IncidentContext:
        defaults = {
            "incident_id": "INC-TEST-001",
            "timestamp": datetime.now(timezone.utc),
            "query": "Why is the service slow?",
            "environment": "production",
        }
        defaults.update(kwargs)
        return IncidentContext(**defaults)

    def test_minimal_context_valid(self):
        ctx = self._make_context()
        assert ctx.incident_id == "INC-TEST-001"
        assert ctx.environment == "production"
        assert ctx.alerts == []
        assert ctx.retrieved_documents == []

    def test_context_model_dump_is_serialisable(self):
        ctx = self._make_context()
        data = ctx.model_dump(mode="json")
        assert isinstance(data, dict)
        assert data["incident_id"] == "INC-TEST-001"

    def test_model_copy_does_not_mutate_original(self):
        doc = RetrievedDocument(
            document_id="doc-1",
            title="Runbook",
            source_type="runbook",
            chunk_text="Restart the service.",
            score=0.9,
        )
        ctx = self._make_context()
        enriched = ctx.model_copy(update={"retrieved_documents": [doc]})
        assert ctx.retrieved_documents == []
        assert len(enriched.retrieved_documents) == 1


class TestInvestigationRequest:
    def test_query_required(self):
        with pytest.raises(Exception):
            InvestigationRequest(query="")  # too short

    def test_default_environment_is_production(self):
        req = InvestigationRequest(query="test query")
        assert req.environment == "production"

    def test_metadata_filter_is_empty_by_default(self):
        req = InvestigationRequest(query="test query")
        assert req.metadata_filter == {}


class TestInvestigationResponse:
    def _make_response(self) -> InvestigationResponse:
        return InvestigationResponse(
            incident_summary="Database connection pool exhausted.",
            affected_services=["order-service"],
            observations=[
                Observation(finding="100/100 connections active", evidence_type=EvidenceType.FACT, source="metric")
            ],
            root_cause_hypotheses=[
                RootCauseHypothesis(
                    hypothesis="Connection leak in order-service",
                    confidence=0.85,
                    supporting_evidence=["100% pool usage", "gradual increase over 2h"],
                    contradicting_evidence=[],
                )
            ],
            recommended_checks=["Check connection pool configuration", "Review recent deployments"],
            recommended_remediation=["Restart order-service pod", "Increase pool size temporarily"],
        )

    def test_response_construction(self):
        resp = self._make_response()
        assert resp.incident_summary
        assert len(resp.root_cause_hypotheses) == 1
        assert resp.root_cause_hypotheses[0].confidence == 0.85

    def test_hypothesis_confidence_clamped(self):
        with pytest.raises(Exception):
            RootCauseHypothesis(hypothesis="test", confidence=1.5)

    def test_response_has_investigation_id(self):
        resp = self._make_response()
        assert resp.investigation_id
        assert len(resp.investigation_id) == 36  # UUID

    def test_evidence_type_enum(self):
        assert EvidenceType.FACT == "FACT"
        assert EvidenceType.HYPOTHESIS == "HYPOTHESIS"
        assert EvidenceType.RECOMMENDATION == "RECOMMENDATION"
        assert EvidenceType.INFERENCE == "INFERENCE"
