"""
Unit tests for the mock TelemetryProvider.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.domain import Alert, MetricAnomaly, RelevantLog, Severity
from app.telemetry.mock import MockTelemetryProvider


@pytest.fixture
def provider():
    return MockTelemetryProvider(scenario="database_connection_pool_exhausted")


@pytest.fixture
def time_range():
    now = datetime.now(timezone.utc)
    return now - timedelta(minutes=10), now + timedelta(minutes=5)


class TestMockTelemetryProvider:
    @pytest.mark.asyncio
    async def test_get_alerts_returns_list(self, provider, time_range):
        start, end = time_range
        alerts = await provider.get_alerts(["order-service"], "production", start, end)
        assert isinstance(alerts, list)
        assert len(alerts) > 0
        assert all(isinstance(a, Alert) for a in alerts)

    @pytest.mark.asyncio
    async def test_alert_has_required_fields(self, provider, time_range):
        start, end = time_range
        alerts = await provider.get_alerts(["order-service"], "production", start, end)
        for alert in alerts:
            assert alert.alert_id
            assert alert.name
            assert alert.severity in list(Severity)
            assert alert.service
            assert alert.message
            assert alert.timestamp

    @pytest.mark.asyncio
    async def test_get_metric_anomalies(self, provider, time_range):
        start, end = time_range
        anomalies = await provider.get_metric_anomalies(["order-service"], "production", start, end)
        assert isinstance(anomalies, list)
        assert all(isinstance(a, MetricAnomaly) for a in anomalies)

    @pytest.mark.asyncio
    async def test_get_relevant_logs_limit_respected(self, provider, time_range):
        start, end = time_range
        logs = await provider.get_relevant_logs(["order-service"], "production", start, end, limit=3)
        assert len(logs) <= 3

    @pytest.mark.asyncio
    async def test_get_log_patterns_returns_patterns(self, provider, time_range):
        start, end = time_range
        patterns = await provider.get_log_patterns(["order-service"], "production", start, end)
        assert isinstance(patterns, list)
        for p in patterns:
            assert p.count > 0
            assert p.pattern

    @pytest.mark.asyncio
    async def test_empty_services_does_not_crash(self, provider, time_range):
        start, end = time_range
        alerts = await provider.get_alerts([], "staging", start, end)
        assert isinstance(alerts, list)

    @pytest.mark.asyncio
    async def test_memory_leak_scenario(self, time_range):
        p = MockTelemetryProvider(scenario="memory_leak")
        start, end = time_range
        alerts = await p.get_alerts(["payment-service"], "production", start, end)
        # Memory leak scenario should include an OOM-related alert
        alert_names = [a.name for a in alerts]
        assert any("Memory" in n or "OOM" in n or "Restart" in n for n in alert_names)

    @pytest.mark.asyncio
    async def test_deployments_present_in_memory_leak_scenario(self, time_range):
        p = MockTelemetryProvider(scenario="memory_leak")
        start, end = time_range
        deployments = await p.get_recent_deployments(["payment-service"], "production", start, end)
        assert len(deployments) > 0
        assert deployments[0].service == "payment-service"
