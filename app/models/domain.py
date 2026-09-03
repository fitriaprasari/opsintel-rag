"""
Domain models for the OpsIntel RAG platform.
All models are pure Pydantic — no ORM coupling here.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


# ── Enumerations ──────────────────────────────────────────────────────────────

class Severity(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class IncidentStatus(StrEnum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class DocumentType(StrEnum):
    RUNBOOK = "runbook"
    SOP = "sop"
    ARCHITECTURE = "architecture"
    RCA = "rca"
    INCIDENT = "incident"
    KNOWN_ERROR = "known_error"
    TROUBLESHOOTING = "troubleshooting"
    DEPLOYMENT_NOTE = "deployment_note"
    SERVICE_DOC = "service_doc"
    OTHER = "other"


class EvidenceType(StrEnum):
    FACT = "FACT"
    INFERENCE = "INFERENCE"
    HYPOTHESIS = "HYPOTHESIS"
    RECOMMENDATION = "RECOMMENDATION"


# ── Telemetry primitives ──────────────────────────────────────────────────────

class MetricAnomaly(BaseModel):
    metric_name: str
    service: str
    value: float
    baseline: float | None = None
    deviation_pct: float | None = None
    timestamp: datetime
    labels: dict[str, str] = Field(default_factory=dict)


class LogPattern(BaseModel):
    pattern: str
    count: int
    severity: str
    service: str
    first_seen: datetime
    last_seen: datetime
    sample_message: str | None = None


class TraceAnomaly(BaseModel):
    trace_id: str
    span_id: str | None = None
    service: str
    operation: str
    duration_ms: float
    status: str
    error_message: str | None = None
    timestamp: datetime


class Alert(BaseModel):
    alert_id: str
    name: str
    severity: Severity
    service: str
    message: str
    timestamp: datetime
    labels: dict[str, str] = Field(default_factory=dict)
    resolved: bool = False


class RelevantLog(BaseModel):
    timestamp: datetime
    service: str
    level: str
    message: str
    trace_id: str | None = None
    span_id: str | None = None
    host: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class Deployment(BaseModel):
    service: str
    version: str
    environment: str
    deployed_at: datetime
    deployed_by: str | None = None
    change_summary: str | None = None


# ── Retrieved documents ───────────────────────────────────────────────────────

class RetrievedDocument(BaseModel):
    document_id: str
    title: str
    source_type: str
    chunk_text: str
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── IncidentContext — canonical context handed to LLM ─────────────────────────

class IncidentContext(BaseModel):
    """
    Canonical structured context assembled from live telemetry + knowledge RAG.
    Every LLM investigation must receive this structured context.
    """
    incident_id: str
    timestamp: datetime
    query: str

    # Service / topology
    services: list[str] = Field(default_factory=list)
    environment: str = "unknown"
    cluster: str | None = None
    namespace: str | None = None
    region: str | None = None

    # Live telemetry
    alerts: list[Alert] = Field(default_factory=list)
    metric_anomalies: list[MetricAnomaly] = Field(default_factory=list)
    log_patterns: list[LogPattern] = Field(default_factory=list)
    relevant_logs: list[RelevantLog] = Field(default_factory=list)
    trace_anomalies: list[TraceAnomaly] = Field(default_factory=list)

    # Topology / change context
    dependencies: list[dict[str, str]] = Field(default_factory=list)
    recent_deployments: list[Deployment] = Field(default_factory=list)

    # RAG knowledge
    retrieved_documents: list[RetrievedDocument] = Field(default_factory=list)
    similar_incidents: list[dict[str, Any]] = Field(default_factory=list)

    # Correlation metadata
    correlation_window_start: datetime | None = None
    correlation_window_end: datetime | None = None


# ── LLM Output ────────────────────────────────────────────────────────────────

class RootCauseHypothesis(BaseModel):
    hypothesis: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_type: EvidenceType = EvidenceType.HYPOTHESIS
    supporting_evidence: list[str] = Field(default_factory=list)
    contradicting_evidence: list[str] = Field(default_factory=list)


class Observation(BaseModel):
    finding: str
    evidence_type: EvidenceType
    source: str | None = None


class InvestigationResponse(BaseModel):
    investigation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    incident_summary: str
    affected_services: list[str] = Field(default_factory=list)
    observations: list[Observation] = Field(default_factory=list)
    root_cause_hypotheses: list[RootCauseHypothesis] = Field(default_factory=list)
    recommended_checks: list[str] = Field(default_factory=list)
    recommended_remediation: list[str] = Field(default_factory=list)
    retrieved_sources: list[RetrievedDocument] = Field(default_factory=list)
    llm_model: str | None = None
    prompt_version: str | None = None
    rag_latency_ms: int | None = None
    llm_latency_ms: int | None = None
    total_tokens: int | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── API Request/Response models ───────────────────────────────────────────────

class InvestigationRequest(BaseModel):
    incident_id: str | None = None
    query: str = Field(..., min_length=3, max_length=2000)
    services: list[str] = Field(default_factory=list)
    environment: str = "production"
    time_range_minutes: int = Field(default=60, ge=1, le=10080)
    severity: Severity | None = None
    metadata_filter: dict[str, str] = Field(default_factory=dict)


class IngestRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    source_url: str | None = None
    source_type: DocumentType = DocumentType.OTHER
    document_type: DocumentType = DocumentType.OTHER
    service_name: str | None = None
    environment: str | None = None
    team: str | None = None
    application: str | None = None
    version: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    content: str = Field(..., min_length=1)


class FeedbackRequest(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    comment: str | None = Field(None, max_length=2000)


class HealthResponse(BaseModel):
    status: str
    version: str
    components: dict[str, str]
