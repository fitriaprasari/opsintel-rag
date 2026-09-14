"""
TelemetryProvider interface.
All telemetry adapters must implement this protocol.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from app.models.domain import (
    Alert,
    Deployment,
    LogPattern,
    MetricAnomaly,
    RelevantLog,
    TraceAnomaly,
)


class TelemetryProvider(ABC):
    """
    Abstract base for live telemetry retrieval.
    Implementations: MockTelemetryProvider, DynatraceTelemetryProvider,
    GrafanaTelemetryProvider, OpenTelemetryProvider.
    """

    @abstractmethod
    async def get_alerts(
        self,
        services: list[str],
        environment: str,
        start: datetime,
        end: datetime,
    ) -> list[Alert]:
        """Return active/recent alerts for the given services and time window."""
        ...

    @abstractmethod
    async def get_metric_anomalies(
        self,
        services: list[str],
        environment: str,
        start: datetime,
        end: datetime,
    ) -> list[MetricAnomaly]:
        """Return metric anomalies detected in the time window."""
        ...

    @abstractmethod
    async def get_log_patterns(
        self,
        services: list[str],
        environment: str,
        start: datetime,
        end: datetime,
    ) -> list[LogPattern]:
        """Return log error/warn patterns with counts."""
        ...

    @abstractmethod
    async def get_relevant_logs(
        self,
        services: list[str],
        environment: str,
        start: datetime,
        end: datetime,
        limit: int = 50,
    ) -> list[RelevantLog]:
        """Return individual high-signal log entries."""
        ...

    @abstractmethod
    async def get_trace_anomalies(
        self,
        services: list[str],
        environment: str,
        start: datetime,
        end: datetime,
    ) -> list[TraceAnomaly]:
        """Return traces with errors or abnormal latency."""
        ...

    @abstractmethod
    async def get_recent_deployments(
        self,
        services: list[str],
        environment: str,
        start: datetime,
        end: datetime,
    ) -> list[Deployment]:
        """Return recent deployments in the window."""
        ...
