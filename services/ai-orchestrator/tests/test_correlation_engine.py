"""
Unit tests for the CorrelationEngine.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.correlation.engine import CorrelationEngine
from app.models.domain import (
    Alert,
    Deployment,
    IncidentContext,
    InvestigationRequest,
    LogPattern,
    MetricAnomaly,
    RelevantLog,
    Severity,
    TraceAnomaly,
)
from app.telemetry.mock import MockTelemetryProvider


@pytest.fixture
def mock_provider():
    return MockTelemetryProvider(scenario="database_connection_pool_exhausted")


@pytest.fixture
def engine(mock_provider):
    return CorrelationEngine(mock_provider)


@pytest.fixture
def investigation_request():
    return InvestigationRequest(
        incident_id="INC-001",
        query="Why is the order service timing out?",
        services=["order-service"],
        environment="production",
        time_range_minutes=60,
    )


class TestCorrelationEngine:
    @pytest.mark.asyncio
    async def test_build_context_returns_incident_context(self, engine, investigation_request):
        context = await engine.build_context(investigation_request)
        assert isinstance(context, IncidentContext)

    @pytest.mark.asyncio
    async def test_context_has_correct_incident_id(self, engine, investigation_request):
        context = await engine.build_context(investigation_request)
        assert context.incident_id == "INC-001"

    @pytest.mark.asyncio
    async def test_context_has_correct_services(self, engine, investigation_request):
        context = await engine.build_context(investigation_request)
        assert context.services == ["order-service"]

    @pytest.mark.asyncio
    async def test_context_contains_alerts(self, engine, investigation_request):
        context = await engine.build_context(investigation_request)
        assert len(context.alerts) > 0

    @pytest.mark.asyncio
    async def test_context_contains_metric_anomalies(self, engine, investigation_request):
        context = await engine.build_context(investigation_request)
        assert len(context.metric_anomalies) > 0

    @pytest.mark.asyncio
    async def test_context_contains_log_patterns(self, engine, investigation_request):
        context = await engine.build_context(investigation_request)
        assert len(context.log_patterns) > 0

    @pytest.mark.asyncio
    async def test_context_correlation_window_set(self, engine, investigation_request):
        context = await engine.build_context(investigation_request)
        assert context.correlation_window_start is not None
        assert context.correlation_window_end is not None
        assert context.correlation_window_start < context.correlation_window_end

    @pytest.mark.asyncio
    async def test_context_window_before_incident(self, engine, investigation_request):
        from app.config import get_settings
        s = get_settings()
        now = datetime.now(timezone.utc)
        context = await engine.build_context(investigation_request, incident_timestamp=now)
        diff = (now - context.correlation_window_start).total_seconds() / 60
        assert abs(diff - s.correlation_window_before_minutes) < 1

    @pytest.mark.asyncio
    async def test_context_retrieved_documents_initially_empty(self, engine, investigation_request):
        """retrieved_documents should be empty until ContextBuilder enriches the context."""
        context = await engine.build_context(investigation_request)
        assert context.retrieved_documents == []

    @pytest.mark.asyncio
    async def test_auto_incident_id_when_none(self, engine):
        req = InvestigationRequest(
            query="Generic query with no incident ID",
            services=["api-gateway"],
            environment="staging",
        )
        context = await engine.build_context(req)
        assert context.incident_id  # auto-generated UUID
        assert len(context.incident_id) == 36  # UUID format
