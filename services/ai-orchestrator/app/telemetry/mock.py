"""
Mock TelemetryProvider — generates realistic-looking synthetic telemetry.
Used during Milestone 1 development and testing before connecting
production Dynatrace/Grafana environments.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any

from app.models.domain import (
    Alert,
    Deployment,
    LogPattern,
    MetricAnomaly,
    RelevantLog,
    Severity,
    TraceAnomaly,
)
from app.telemetry.base import TelemetryProvider


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Pre-built realistic scenarios keyed by pattern name
_SCENARIOS: dict[str, dict[str, Any]] = {
    "database_connection_pool_exhausted": {
        "alerts": [
            {
                "name": "DatabaseConnectionPoolExhausted",
                "severity": Severity.CRITICAL,
                "message": "Connection pool exhausted: 0/100 connections available for postgres-primary",
            },
            {
                "name": "HighResponseTime",
                "severity": Severity.HIGH,
                "message": "P99 response time exceeded 5000ms for order-service",
            },
        ],
        "metric_anomalies": [
            {
                "metric_name": "db.connections.active",
                "value": 100.0,
                "baseline": 35.0,
                "deviation_pct": 186.0,
            },
            {
                "metric_name": "http.server.duration.p99",
                "value": 8200.0,
                "baseline": 250.0,
                "deviation_pct": 3180.0,
            },
        ],
        "log_patterns": [
            {
                "pattern": "could not connect to server: Connection refused",
                "count": 1842,
                "severity": "ERROR",
                "sample_message": "FATAL: could not connect to server: Connection refused\\n\\tIs the server running on host 'postgres-primary' and accepting TCP/IP connections on port 5432?",
            },
            {
                "pattern": "HikariPool-1 - Connection is not available, request timed out",
                "count": 743,
                "severity": "WARN",
                "sample_message": "HikariPool-1 - Connection is not available, request timed out after 30001ms.",
            },
        ],
        "trace_anomalies": [
            {
                "operation": "POST /api/v1/orders",
                "duration_ms": 31000.0,
                "status": "ERROR",
                "error_message": "Connection acquisition timed out after 30 seconds",
            },
        ],
        "deployments": [],
    },
    "memory_leak": {
        "alerts": [
            {
                "name": "HighMemoryUsage",
                "severity": Severity.HIGH,
                "message": "JVM heap usage at 94% for payment-service (pod payment-service-7d8b9c-xkp2q)",
            },
            {
                "name": "PodRestartingFrequently",
                "severity": Severity.MEDIUM,
                "message": "payment-service has restarted 6 times in the last 30 minutes (OOMKilled)",
            },
        ],
        "metric_anomalies": [
            {
                "metric_name": "jvm.memory.used",
                "value": 3.8e9,
                "baseline": 1.2e9,
                "deviation_pct": 217.0,
            },
            {
                "metric_name": "pod.restarts",
                "value": 6.0,
                "baseline": 0.1,
                "deviation_pct": 5900.0,
            },
        ],
        "log_patterns": [
            {
                "pattern": "java.lang.OutOfMemoryError: Java heap space",
                "count": 18,
                "severity": "ERROR",
                "sample_message": "java.lang.OutOfMemoryError: Java heap space\\n\\tat java.util.Arrays.copyOf(Arrays.java:3512)",
            },
        ],
        "trace_anomalies": [],
        "deployments": [
            {
                "version": "2.14.1",
                "change_summary": "Upgraded cache library from 1.8.3 to 2.0.1; enabled local caching",
            }
        ],
    },
}


class MockTelemetryProvider(TelemetryProvider):
    """
    Returns pre-built synthetic telemetry scenarios.
    The scenario is selected by hashing the incident_id mod number of scenarios.
    For unknown services, returns plausible generic telemetry.
    """

    def __init__(self, scenario: str | None = None) -> None:
        self._scenario = scenario

    def _pick_scenario(self, services: list[str]) -> dict[str, Any]:
        if self._scenario and self._scenario in _SCENARIOS:
            return _SCENARIOS[self._scenario]
        if services:
            idx = hash(services[0]) % len(_SCENARIOS)
            return list(_SCENARIOS.values())[idx]
        return list(_SCENARIOS.values())[0]

    async def get_alerts(self, services, environment, start, end) -> list[Alert]:
        scenario = self._pick_scenario(services)
        svc = services[0] if services else "unknown-service"
        alerts = []
        for i, a in enumerate(scenario.get("alerts", [])):
            alerts.append(
                Alert(
                    alert_id=f"mock-alert-{i+1}",
                    name=a["name"],
                    severity=a["severity"],
                    service=svc,
                    message=a["message"],
                    timestamp=start + timedelta(minutes=random.randint(1, 5)),
                    labels={"environment": environment, "service": svc},
                )
            )
        return alerts

    async def get_metric_anomalies(self, services, environment, start, end) -> list[MetricAnomaly]:
        scenario = self._pick_scenario(services)
        svc = services[0] if services else "unknown-service"
        anomalies = []
        for a in scenario.get("metric_anomalies", []):
            anomalies.append(
                MetricAnomaly(
                    metric_name=a["metric_name"],
                    service=svc,
                    value=a["value"],
                    baseline=a.get("baseline"),
                    deviation_pct=a.get("deviation_pct"),
                    timestamp=start + timedelta(minutes=random.randint(0, 3)),
                    labels={"environment": environment},
                )
            )
        return anomalies

    async def get_log_patterns(self, services, environment, start, end) -> list[LogPattern]:
        scenario = self._pick_scenario(services)
        svc = services[0] if services else "unknown-service"
        patterns = []
        for p in scenario.get("log_patterns", []):
            patterns.append(
                LogPattern(
                    pattern=p["pattern"],
                    count=p["count"],
                    severity=p["severity"],
                    service=svc,
                    first_seen=start,
                    last_seen=end,
                    sample_message=p.get("sample_message"),
                )
            )
        return patterns

    async def get_relevant_logs(self, services, environment, start, end, limit=50) -> list[RelevantLog]:
        svc = services[0] if services else "unknown-service"
        logs = []
        messages = [
            ("ERROR", "Database query timeout after 30000ms [query=SELECT * FROM orders WHERE status=?]"),
            ("ERROR", "Failed to acquire connection from pool within timeout period"),
            ("WARN",  "Retry attempt 3/3 for downstream call to inventory-service"),
            ("ERROR", "Transaction rolled back due to connection failure"),
            ("INFO",  "Circuit breaker OPEN for postgres-primary after 5 consecutive failures"),
        ]
        for i, (level, msg) in enumerate(messages[:limit]):
            logs.append(
                RelevantLog(
                    timestamp=start + timedelta(seconds=i * 30),
                    service=svc,
                    level=level,
                    message=msg,
                    trace_id=f"trace-mock-{i+1:04d}",
                    host=f"{svc}-pod-{i % 3:02d}",
                    attributes={"environment": environment},
                )
            )
        return logs

    async def get_trace_anomalies(self, services, environment, start, end) -> list[TraceAnomaly]:
        scenario = self._pick_scenario(services)
        svc = services[0] if services else "unknown-service"
        anomalies = []
        for i, t in enumerate(scenario.get("trace_anomalies", [])):
            anomalies.append(
                TraceAnomaly(
                    trace_id=f"trace-anomaly-mock-{i+1:04d}",
                    service=svc,
                    operation=t["operation"],
                    duration_ms=t["duration_ms"],
                    status=t["status"],
                    error_message=t.get("error_message"),
                    timestamp=start + timedelta(minutes=random.randint(0, 5)),
                )
            )
        return anomalies

    async def get_recent_deployments(self, services, environment, start, end) -> list[Deployment]:
        scenario = self._pick_scenario(services)
        svc = services[0] if services else "unknown-service"
        deployments = []
        for d in scenario.get("deployments", []):
            deployments.append(
                Deployment(
                    service=svc,
                    version=d["version"],
                    environment=environment,
                    deployed_at=start - timedelta(hours=2),
                    deployed_by="ci-pipeline",
                    change_summary=d.get("change_summary"),
                )
            )
        return deployments
