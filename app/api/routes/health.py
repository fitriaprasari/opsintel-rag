"""Health check endpoints."""
from __future__ import annotations

import httpx
from fastapi import APIRouter
from sqlalchemy import text

from app.config import get_settings
from app.db.session import _get_engine
from app.models.domain import HealthResponse
from app.rag.vector_store import make_qdrant_client

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Liveness probe — returns component health status."""
    s = get_settings()
    components: dict[str, str] = {}

    # PostgreSQL
    try:
        async with _get_engine().begin() as conn:
            await conn.execute(text("SELECT 1"))
        components["postgres"] = "ok"
    except Exception as exc:
        components["postgres"] = f"error: {exc}"

    # Qdrant
    try:
        client = make_qdrant_client()
        await client.get_collections()
        components["qdrant"] = "ok"
    except Exception as exc:
        components["qdrant"] = f"error: {exc}"

    # LLM backend (lightweight ping — non-fatal, mock provider always ok)
    if s.llm_provider == "mock":
        components["llm"] = "mock (no server required)"
    else:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{s.llm_base_url}/models")
                components["llm"] = "ok" if resp.status_code < 500 else f"http_{resp.status_code}"
        except Exception as exc:
            components["llm"] = f"unreachable: {exc}"

    # "ok" if every component is "ok" or a mock/skip value; "degraded" only on real errors
    def _is_healthy(v: str) -> bool:
        return v == "ok" or v.startswith("mock") or v.startswith("skip")

    overall = "ok" if all(_is_healthy(v) for v in components.values()) else "degraded"
    return HealthResponse(status=overall, version="0.1.0", components=components)


@router.get("/ready")
async def readiness_check():
    """Kubernetes readiness probe — just checks app is up."""
    return {"status": "ready"}
