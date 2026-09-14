"""
CorrelationEngine — groups telemetry signals into a coherent IncidentContext
using configurable time windows and OpenTelemetry attribute correlation.

Correlation keys:
  trace_id, span_id, service.name, service.version, deployment.environment,
  host.name, k8s cluster/namespace/pod, timestamp, error type,
  HTTP status, database dependency, incident_id
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from app.config import get_settings
from app.models.domain import IncidentContext, InvestigationRequest
from app.telemetry.base import TelemetryProvider

logger = logging.getLogger(__name__)


class CorrelationEngine:
    """
    Builds an IncidentContext by:
    1. Computing a correlation time window around the incident timestamp.
    2. Querying all TelemetryProvider data sources in parallel.
    3. Merging all signals into a single IncidentContext.
    """

    def __init__(self, provider: TelemetryProvider) -> None:
        self._provider = provider

    async def build_context(
        self,
        request: InvestigationRequest,
        incident_timestamp: datetime | None = None,
    ) -> IncidentContext:
        """
        Build a complete IncidentContext for the given investigation request.

        Args:
            request: The InvestigationRequest from the API.
            incident_timestamp: Known incident start time (defaults to now).

        Returns:
            Populated IncidentContext ready for LLM injection.
        """
        _s = get_settings()
        now = incident_timestamp or datetime.now(timezone.utc)
        window_start = now - timedelta(minutes=_s.correlation_window_before_minutes)
        window_end = now + timedelta(minutes=_s.correlation_window_after_minutes)

        services = request.services or []
        environment = request.environment

        logger.info(
            "Building telemetry context for services=%s env=%s window=[%s → %s]",
            services, environment, window_start.isoformat(), window_end.isoformat(),
        )

        # Fetch all telemetry signals in parallel
        (
            alerts,
            metric_anomalies,
            log_patterns,
            relevant_logs,
            trace_anomalies,
            deployments,
        ) = await asyncio.gather(
            self._provider.get_alerts(services, environment, window_start, window_end),
            self._provider.get_metric_anomalies(services, environment, window_start, window_end),
            self._provider.get_log_patterns(services, environment, window_start, window_end),
            self._provider.get_relevant_logs(services, environment, window_start, window_end),
            self._provider.get_trace_anomalies(services, environment, window_start, window_end),
            self._provider.get_recent_deployments(services, environment, window_start, window_end),
        )

        incident_id = request.incident_id or str(uuid.uuid4())

        return IncidentContext(
            incident_id=incident_id,
            timestamp=now,
            query=request.query,
            services=services,
            environment=environment,
            alerts=alerts,
            metric_anomalies=metric_anomalies,
            log_patterns=log_patterns,
            relevant_logs=relevant_logs,
            trace_anomalies=trace_anomalies,
            recent_deployments=deployments,
            correlation_window_start=window_start,
            correlation_window_end=window_end,
            # retrieved_documents and similar_incidents populated later by ContextBuilder
            retrieved_documents=[],
            similar_incidents=[],
        )
