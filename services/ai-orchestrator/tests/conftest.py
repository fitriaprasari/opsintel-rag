"""pytest configuration and shared fixtures."""
from __future__ import annotations

import os

import pytest

# ── Set ALL required env vars before any app imports ─────────────────────────
# These use mock/no-op providers so tests run with zero external dependencies.
os.environ.setdefault("SECRET_KEY", "test-secret-key-minimum-32-chars-ok")
os.environ.setdefault("POSTGRES_PASSWORD", "testpass")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("QDRANT_HOST", "localhost")
# mock LLM — no HTTP calls, instant response
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("LLM_BASE_URL", "http://localhost:8080/v1")
# mock embeddings — zero vectors, no model download
os.environ.setdefault("EMBEDDING_MODEL", "mock")
os.environ.setdefault("RERANKER_ENABLED", "false")
# mock telemetry — synthetic scenarios, no Dynatrace/Grafana
os.environ.setdefault("TELEMETRY_PROVIDER", "mock")
# disable OIDC and OTel exporter for tests
os.environ.setdefault("OIDC_ENABLED", "false")
os.environ.setdefault("OTEL_ENABLED", "false")


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"
