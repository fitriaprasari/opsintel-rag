"""
Application configuration — all values sourced from environment variables.
No hard-coded credentials anywhere in this file.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ───────────────────────────────────────────────────────
    app_env: Literal["development", "staging", "production"] = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    secret_key: str = Field(..., min_length=32)

    # ── PostgreSQL ────────────────────────────────────────────────────────
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "opsintel"
    postgres_user: str = "opsintel"
    postgres_password: str = Field(..., min_length=1)

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # ── Qdrant ────────────────────────────────────────────────────────────
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_collection: str = "operational_knowledge"
    qdrant_api_key: str | None = None

    # ── Kafka ─────────────────────────────────────────────────────────────
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_topic_telemetry: str = "telemetry-raw"
    kafka_topic_incidents: str = "incident-events"
    kafka_topic_audit: str = "audit-events"
    kafka_topic_feedback: str = "rag-feedback"

    # ── LLM Provider ─────────────────────────────────────────────────────
    llm_provider: Literal["llamacpp", "vllm", "mock"] = "mock"
    llm_base_url: str = "http://localhost:8080/v1"
    llm_api_key: str = "not-required"
    llm_model_name: str = "mistral-7b-instruct"
    llm_max_tokens: int = 2048
    llm_temperature: float = 0.1
    llm_timeout_seconds: int = 120

    # ── Embeddings ────────────────────────────────────────────────────────
    embedding_model: str = "BAAI/bge-large-en-v1.5"
    embedding_device: str = "cpu"
    embedding_batch_size: int = 32

    # ── Reranker ─────────────────────────────────────────────────────────
    reranker_enabled: bool = True
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    reranker_top_k: int = 5

    # ── Retrieval ─────────────────────────────────────────────────────────
    retrieval_dense_top_k: int = 20
    retrieval_sparse_top_k: int = 20
    retrieval_fusion_top_k: int = 10
    retrieval_min_score: float = 0.3

    # ── Telemetry Provider ────────────────────────────────────────────────
    telemetry_provider: Literal["mock", "dynatrace", "grafana", "opentelemetry"] = "mock"
    dynatrace_url: str | None = None
    dynatrace_token: str | None = None
    grafana_url: str | None = None
    grafana_api_key: str | None = None
    loki_url: str | None = None
    tempo_url: str | None = None

    # ── OIDC / Auth ───────────────────────────────────────────────────────
    oidc_enabled: bool = False
    oidc_issuer: str = "https://keycloak:8080/realms/opsintel"
    oidc_audience: str = "opsintel-api"
    oidc_jwks_uri: str = "https://keycloak:8080/realms/opsintel/protocol/openid-connect/certs"

    # ── OTel Self-Instrumentation ─────────────────────────────────────────
    otel_enabled: bool = True
    otel_service_name: str = "ai-orchestrator"
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"

    # ── Correlation Engine ────────────────────────────────────────────────
    correlation_window_before_minutes: int = 10
    correlation_window_after_minutes: int = 5

    @field_validator("llm_temperature")
    @classmethod
    def validate_temperature(cls, v: float) -> float:
        if not 0.0 <= v <= 2.0:
            raise ValueError("temperature must be between 0.0 and 2.0")
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings. Raises on first call if env is invalid."""
    return Settings()
