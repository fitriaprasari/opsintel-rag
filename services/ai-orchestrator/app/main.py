"""
FastAPI application entry point.
Wires together all services, applies middleware, registers routes.
"""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from app.config import get_settings
from app.rag.vector_store import make_qdrant_client, QdrantVectorStore
from app.embeddings.provider import get_embedding_provider

_settings = get_settings()

# ── Structured logging ────────────────────────────────────────────────────────
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer() if _settings.app_env == "development"
        else structlog.processors.JSONRenderer(),
    ]
)
logger = structlog.get_logger(__name__)

# ── Prometheus metrics ────────────────────────────────────────────────────────
REQUEST_COUNT = Counter(
    "opsintel_http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)
REQUEST_LATENCY = Histogram(
    "opsintel_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "endpoint"],
)
INVESTIGATION_COUNT = Counter(
    "opsintel_investigations_total",
    "Total investigation requests",
    ["environment"],
)
RAG_LATENCY = Histogram(
    "opsintel_rag_latency_seconds",
    "RAG retrieval latency",
)
LLM_LATENCY = Histogram(
    "opsintel_llm_latency_seconds",
    "LLM inference latency",
)


# ── Application lifespan ──────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup tasks (all non-fatal — service starts even if infra is temporarily down):
    1. Ensure Qdrant collection exists (skipped if Qdrant unreachable)
    2. Log startup banner
    """
    logger.info(
        "Starting OpsIntel AI Orchestrator",
        env=_settings.app_env,
        llm_provider=_settings.llm_provider,
        embedding_model=_settings.embedding_model,
        telemetry_provider=_settings.telemetry_provider,
    )
    try:
        qdrant_client = make_qdrant_client()
        embedder = get_embedding_provider()
        vs = QdrantVectorStore(qdrant_client, _settings.qdrant_collection, embedder.dimension)
        await vs.ensure_collection()
        logger.info("Qdrant collection ready", collection=_settings.qdrant_collection)
    except Exception as exc:
        logger.warning(
            "Qdrant not reachable at startup (non-fatal — will retry on first request)",
            error=str(exc),
        )
    logger.info(
        "AI Orchestrator ready",
        host=_settings.app_host,
        port=_settings.app_port,
        docs="http://localhost:%d/docs" % _settings.app_port,
    )
    yield
    logger.info("Shutting down AI Orchestrator")


# ── FastAPI app ───────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    app = FastAPI(
        title="OpsIntel RAG — AI Orchestrator",
        description="Operational Intelligence RAG platform with dual retrieval architecture.",
        version="0.1.0",
        docs_url="/docs" if _settings.app_env != "production" else None,
        redoc_url="/redoc" if _settings.app_env != "production" else None,
        lifespan=lifespan,
    )

    # CORS (tighten in production via allowed_origins config)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if _settings.app_env == "development" else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Request timing middleware ─────────────────────────────────────────
    @app.middleware("http")
    async def timing_middleware(request: Request, call_next):
        t0 = time.monotonic()
        response = await call_next(request)
        duration = time.monotonic() - t0
        endpoint = request.url.path
        REQUEST_COUNT.labels(request.method, endpoint, response.status_code).inc()
        REQUEST_LATENCY.labels(request.method, endpoint).observe(duration)
        response.headers["X-Request-Duration-Ms"] = str(int(duration * 1000))
        return response

    # ── Register routers ──────────────────────────────────────────────────
    from app.api.routes import health, investigations, documents, incidents

    app.include_router(health.router, prefix="/api/v1", tags=["health"])
    app.include_router(investigations.router, prefix="/api/v1", tags=["investigations"])
    app.include_router(documents.router, prefix="/api/v1", tags=["documents"])
    app.include_router(incidents.router, prefix="/api/v1", tags=["incidents"])

    # Prometheus metrics endpoint
    @app.get("/api/v1/metrics", include_in_schema=False)
    async def metrics_endpoint():
        from fastapi.responses import Response
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    # Global exception handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error("Unhandled exception", path=request.url.path, error=str(exc))
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    return app


app = create_app()
