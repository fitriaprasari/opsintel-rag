"""
Provider factory — returns the correct TelemetryProvider based on config.
Extend this file to add new provider adapters (Dynatrace, Grafana, etc.).
"""
from __future__ import annotations

from app.config import get_settings
from app.telemetry.base import TelemetryProvider
from app.telemetry.mock import MockTelemetryProvider


def get_telemetry_provider() -> TelemetryProvider:
    """
    Return the configured TelemetryProvider.

    Configured via TELEMETRY_PROVIDER env var:
      mock         → MockTelemetryProvider (Milestone 1)
      dynatrace    → DynatraceTelemetryProvider (Milestone 2)
      grafana      → GrafanaTelemetryProvider (Milestone 2)
      opentelemetry → OpenTelemetryProvider (Milestone 2)
    """
    settings = get_settings()
    provider = settings.telemetry_provider

    if provider == "mock":
        return MockTelemetryProvider()

    if provider == "dynatrace":
        # Milestone 2: from app.telemetry.dynatrace import DynatraceTelemetryProvider
        # return DynatraceTelemetryProvider(url=settings.dynatrace_url, token=settings.dynatrace_token)
        raise NotImplementedError("Dynatrace provider not yet implemented. Set TELEMETRY_PROVIDER=mock.")

    if provider == "grafana":
        # Milestone 2: from app.telemetry.grafana import GrafanaTelemetryProvider
        raise NotImplementedError("Grafana provider not yet implemented. Set TELEMETRY_PROVIDER=mock.")

    if provider == "opentelemetry":
        raise NotImplementedError("OpenTelemetry provider not yet implemented. Set TELEMETRY_PROVIDER=mock.")

    raise ValueError(f"Unknown TELEMETRY_PROVIDER: {provider!r}")
