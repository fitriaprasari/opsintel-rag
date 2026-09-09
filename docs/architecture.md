# OpsIntel RAG — Architecture Document

> **Version:** 0.1.0  
> **Status:** Milestone 1 Design  
> **Authors:** Platform Engineering

---

## 1. Purpose

OpsIntel RAG is a production-grade Operational Intelligence platform that
combines a **dual-retrieval architecture** with LLM inference to provide
explainable incident investigation, root-cause hypotheses, and actionable
remediation guidance from enterprise observability signals.

The platform does **not** copy raw telemetry into a vector store. Instead it:

1. Retrieves **live telemetry** (logs, metrics, traces, alerts) at query time
   from observability systems via adapter interfaces.
2. Retrieves **operational knowledge** (runbooks, SOPs, prior incidents, RCA
   reports) from a vector store backed by indexed documents.
3. Merges both streams into a structured `IncidentContext` that is injected
   into the LLM prompt.

---

## 2. High-Level Component Diagram

```
                        ┌─────────────────────────────────────────┐
                        │             Clients / Dashboards         │
                        │  (Grafana, Ops Portal, CLI, API clients) │
                        └──────────────────┬──────────────────────┘
                                           │ HTTPS / WSS
                        ┌──────────────────▼──────────────────────┐
                        │              Go API Gateway              │
                        │  REST  │  SSE/WS  │  Auth  │  RBAC      │
                        └──────────────────┬──────────────────────┘
                                           │ HTTP (internal)
                        ┌──────────────────▼──────────────────────┐
                        │          AI Orchestrator (FastAPI)       │
                        │                                          │
                        │  ┌──────────────────────────────────┐   │
                        │  │       Incident Investigation      │   │
                        │  │  API  ─►  Context Builder  ──►   │   │
                        │  │           LLM Provider            │   │
                        │  └──────────────────────────────────┘   │
                        │                                          │
                        │  ┌───────────────┐ ┌─────────────────┐  │
                        │  │ Telemetry     │ │  Knowledge RAG  │  │
                        │  │ Retrieval     │ │  Retrieval      │  │
                        │  │ (live)        │ │  (vector store) │  │
                        │  └──────┬────────┘ └────────┬────────┘  │
                        └─────────┼───────────────────┼───────────┘
                                  │                   │
               ┌──────────────────▼──┐       ┌────────▼──────────────┐
               │  Telemetry Adapters  │       │  Qdrant Vector Store  │
               │                      │       │  (hybrid retrieval)   │
               │  ┌─────────────────┐ │       └───────────────────────┘
               │  │ OpenTelemetry   │ │
               │  │ Dynatrace       │ │       ┌───────────────────────┐
               │  │ Grafana         │ │       │  PostgreSQL            │
               │  │ Mock (M1)       │ │       │  metadata / catalog    │
               │  └─────────────────┘ │       └───────────────────────┘
               └──────────────────────┘
                                           ┌───────────────────────┐
                                           │  Apache Kafka          │
                                           │  (event streaming)    │
                                           └───────────────────────┘
                                           ┌───────────────────────┐
                                           │  LLM Backends          │
                                           │  llama.cpp | vLLM      │
                                           └───────────────────────┘
```

---

## 3. Component Responsibilities

### 3.1 Go API Gateway (`services/gateway`)
- TLS termination and HTTPS/WSS handling
- OIDC/JWT validation middleware
- RBAC policy enforcement
- Request routing to AI Orchestrator
- SSE streaming proxy
- Rate limiting
- Health and readiness endpoints (`/health`, `/ready`)
- Audit log emission (via Kafka topic `audit-events`)

### 3.2 AI Orchestrator (`services/ai-orchestrator`)
- FastAPI application (Python 3.12+)
- **Incident Investigation API** — primary entry point for queries
- **Context Builder** — merges telemetry evidence + RAG knowledge
- **Correlation Engine** — groups telemetry signals by time window + attributes
- **RAG Pipeline** — ingestion, chunking, embedding, indexing
- **Retrieval Pipeline** — hybrid dense + sparse + metadata filter + reranking
- **LLM Provider** — abstraction over llama.cpp / vLLM / other
- **Telemetry Adapter** — pluggable live retrieval (Mock, OTel, Dynatrace, Grafana)
- OpenTelemetry self-instrumentation

### 3.3 Ingestion Service (`services/ingestion`)
- Document upload API (PDF, Markdown, HTML, plain text)
- Document parsing and text extraction
- Semantic chunking
- Metadata enrichment
- Embedding generation
- Qdrant upsert

### 3.4 Qdrant (Vector Store)
- Stores document chunk embeddings + sparse BM25 vectors
- Metadata filtering on service_name, environment, document_type, etc.
- Collection-per-tenant or namespace strategy

### 3.5 PostgreSQL (Relational Store)
- Incident metadata and lifecycle
- Service catalog
- Service dependency graph
- Users and RBAC assignments
- RAG document registry
- Embedding feedback
- Audit log

### 3.6 Apache Kafka (Event Bus)
- Topic `telemetry-raw`: inbound OTel events
- Topic `incident-events`: incident state changes
- Topic `audit-events`: security audit records
- Topic `rag-feedback`: user feedback for RLHF loop

### 3.7 LLM Backends
- **llama.cpp** — local, CPU/GPU, OpenAI-compatible `/v1/chat/completions`
- **vLLM** — GPU-accelerated serving, OpenAI-compatible
- Switchable via `LLM_PROVIDER` env var

---

## 4. Data Flow

### 4.1 Incident Investigation Flow

```
1. Client submits InvestigationRequest (incident_id, query, services, time_range)
   → Go Gateway (auth + RBAC check)
   → AI Orchestrator /api/v1/investigate

2. Orchestrator:
   a. Load incident metadata from PostgreSQL
   b. Dispatch TelemetryAdapter.get_context(incident) → live evidence
   c. CorrelationEngine.correlate(signals, time_window) → grouped signals
   d. RAGRetrieval.retrieve(query, metadata_filter) → ranked doc chunks
   e. ContextBuilder.build(telemetry, rag_docs) → IncidentContext

3. LLMProvider.complete(system_prompt, incident_context) → structured JSON

4. Persist investigation to PostgreSQL
5. Emit feedback event to Kafka
6. Return InvestigationResponse to client (SSE or JSON)
```

### 4.2 Document Ingestion Flow

```
1. Operator POSTs document to /api/v1/ingest
2. DocumentParser extracts text
3. TextNormalizer cleans and normalises
4. SemanticChunker splits into chunks
5. MetadataEnricher adds service_name, environment, document_type, etc.
6. Embedder generates dense vector (e.g. sentence-transformers)
7. BM25Indexer generates sparse vector
8. QdrantClient upserts point (dense + sparse + metadata)
9. PostgreSQL registry updated with document metadata
```

### 4.3 Telemetry Event Streaming Flow

```
OTel Collector → Kafka topic: telemetry-raw
                → TelemetryConsumer → CorrelationEngine → IncidentEvent
                → Kafka topic: incident-events
                → AI Orchestrator subscription
```

---

## 5. Database Schema

### 5.1 PostgreSQL

```sql
-- Incidents
CREATE TABLE incidents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_id     TEXT UNIQUE,
    title           TEXT NOT NULL,
    description     TEXT,
    severity        TEXT NOT NULL CHECK (severity IN ('CRITICAL','HIGH','MEDIUM','LOW','INFO')),
    status          TEXT NOT NULL DEFAULT 'OPEN'
                    CHECK (status IN ('OPEN','INVESTIGATING','RESOLVED','CLOSED')),
    environment     TEXT NOT NULL,
    services        TEXT[],
    cluster         TEXT,
    namespace       TEXT,
    region          TEXT,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Service catalog
CREATE TABLE services (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    version         TEXT,
    environment     TEXT NOT NULL,
    team            TEXT,
    application     TEXT,
    cluster         TEXT,
    namespace       TEXT,
    region          TEXT,
    host            TEXT,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (name, environment)
);

-- Service dependencies
CREATE TABLE service_dependencies (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_service  TEXT NOT NULL,
    target_service  TEXT NOT NULL,
    dependency_type TEXT NOT NULL DEFAULT 'http',
    environment     TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Users
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject         TEXT UNIQUE NOT NULL,   -- OIDC sub claim
    email           TEXT UNIQUE NOT NULL,
    name            TEXT,
    roles           TEXT[] DEFAULT '{}',
    tenant_id       TEXT,
    active          BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at   TIMESTAMPTZ
);

-- RAG document registry
CREATE TABLE rag_documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title           TEXT NOT NULL,
    source_url      TEXT,
    source_type     TEXT NOT NULL,  -- runbook, sop, rca, incident, etc.
    document_type   TEXT NOT NULL,
    service_name    TEXT,
    environment     TEXT,
    team            TEXT,
    application     TEXT,
    version         TEXT,
    chunk_count     INTEGER DEFAULT 0,
    indexed_at      TIMESTAMPTZ,
    content_hash    TEXT UNIQUE,
    metadata        JSONB DEFAULT '{}',
    access_policy   JSONB DEFAULT '{}',  -- RBAC: allowed_roles, allowed_tenants
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Investigation results
CREATE TABLE investigations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id     UUID REFERENCES incidents(id),
    query           TEXT NOT NULL,
    context_json    JSONB NOT NULL,
    response_json   JSONB NOT NULL,
    llm_model       TEXT,
    prompt_version  TEXT,
    rag_latency_ms  INTEGER,
    llm_latency_ms  INTEGER,
    total_tokens    INTEGER,
    created_by      UUID REFERENCES users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Feedback
CREATE TABLE feedback (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    investigation_id UUID REFERENCES investigations(id),
    rating          SMALLINT CHECK (rating BETWEEN 1 AND 5),
    comment         TEXT,
    created_by      UUID REFERENCES users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Audit log
CREATE TABLE audit_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id        UUID,
    actor_email     TEXT,
    action          TEXT NOT NULL,
    resource_type   TEXT NOT NULL,
    resource_id     TEXT,
    details         JSONB DEFAULT '{}',
    ip_address      TEXT,
    user_agent      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_incidents_status        ON incidents(status);
CREATE INDEX idx_incidents_environment   ON incidents(environment);
CREATE INDEX idx_incidents_started_at    ON incidents(started_at DESC);
CREATE INDEX idx_investigations_incident ON investigations(incident_id);
CREATE INDEX idx_audit_log_actor         ON audit_log(actor_id, created_at DESC);
CREATE INDEX idx_rag_docs_service        ON rag_documents(service_name, environment);
```

### 5.2 Qdrant Collection Schema

```yaml
collection: operational_knowledge
vectors:
  dense:
    size: 1024          # depends on embedding model
    distance: Cosine
  sparse:
    name: bm25
    modifier: idf
payload_schema:
  document_id:    keyword
  chunk_index:    integer
  title:          text
  source_type:    keyword   # runbook | sop | rca | incident | architecture
  document_type:  keyword
  service_name:   keyword
  service_version:keyword
  environment:    keyword
  application:    keyword
  team:           keyword
  incident_id:    keyword
  severity:       keyword
  timestamp:      datetime
  source:         keyword
  cluster:        keyword
  namespace:      keyword
  host:           keyword
  region:         keyword
  content:        text      # stored for retrieval display
```

---

## 6. API Specification (Summary)

Full OpenAPI spec generated at runtime via FastAPI. Key endpoints:

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/investigate` | Submit incident investigation |
| GET  | `/api/v1/investigate/{id}` | Retrieve investigation result |
| POST | `/api/v1/investigate/{id}/feedback` | Submit feedback |
| POST | `/api/v1/ingest` | Ingest a document |
| GET  | `/api/v1/documents` | List indexed documents |
| DELETE | `/api/v1/documents/{id}` | Remove document |
| POST | `/api/v1/incidents` | Create incident record |
| GET  | `/api/v1/incidents/{id}` | Get incident detail |
| GET  | `/api/v1/services` | List service catalog |
| GET  | `/api/v1/health` | Health check |
| GET  | `/api/v1/metrics` | Prometheus metrics |

---

## 7. Security Model

| Concern | Approach |
|---------|----------|
| Authentication | OIDC / OAuth2 bearer JWT (Keycloak or any OIDC provider) |
| Authorization | RBAC — roles: `admin`, `operator`, `viewer`, `ingest` |
| Transport | TLS everywhere (Gateway terminates external TLS) |
| Secrets | Environment variables; Vault integration hook provided |
| Audit | Every read/write action logged to `audit_log` table + Kafka |
| Prompt injection | Input sanitisation + system prompt hardening |
| Document access | Per-document `access_policy` (roles/tenants), enforced at retrieval |
| Tenant isolation | `tenant_id` on users; Qdrant metadata filter on retrieval |
| Credentials | No hard-coded secrets; `.env.example` with placeholders only |

---

## 8. Phased Implementation Plan

### Milestone 1 — Foundation (current)
- Architecture documents ✓
- Repository structure and Docker Compose
- FastAPI AI Orchestrator: skeleton, config, models
- PostgreSQL schema and migrations (Alembic)
- Qdrant hybrid collection setup
- Document ingestion + chunking + embedding pipeline
- Hybrid retrieval (dense + sparse + metadata filter + reranking)
- Mock TelemetryProvider
- IncidentContext model + CorrelationEngine stub
- llama.cpp LLM provider (OpenAI-compatible)
- Basic investigation API endpoint
- Unit tests (pytest, 80%+ coverage target)
- README

### Milestone 2 — Live Telemetry Integration
- OpenTelemetry Collector integration
- Kafka consumer/producer
- Real TelemetryProvider adapters: Grafana, Dynatrace
- Correlation engine: signal grouping by trace_id, service, time window
- Deployment annotations feed
- Alert→incident correlation

### Milestone 3 — Go Gateway
- Full Go gateway with OIDC JWT validation
- RBAC middleware
- SSE streaming endpoint
- Rate limiting (token bucket)
- Audit log emission

### Milestone 4 — Production Hardening
- Kubernetes Helm charts
- Horizontal scaling (multiple Orchestrator replicas)
- Qdrant cluster mode
- Reranker model integration (CrossEncoder)
- Feedback-driven reranking tuning
- Full OTel self-instrumentation
- SLO dashboards
