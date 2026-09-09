# OpsIntel RAG

**Production-grade Operational Intelligence RAG Platform**

Dual-retrieval architecture combining live telemetry evidence with enterprise
knowledge (runbooks, SOPs, RCA reports) for AI-assisted incident investigation.

---

## Architecture Overview

```
Clients / Dashboards
    ↓ HTTPS
Go API Gateway  (auth · RBAC · routing · SSE)
    ↓ HTTP
AI Orchestrator  (FastAPI · Python 3.12)
    ├── Correlation Engine  →  TelemetryProvider (Mock | Dynatrace | Grafana | OTel)
    ├── RAG Retrieval       →  Qdrant (dense + sparse + metadata filter + reranking)
    ├── Context Builder
    └── LLM Provider        →  llama.cpp | vLLM  (OpenAI-compatible)
         ↓
    InvestigationResponse (structured JSON)

Infrastructure: PostgreSQL · Qdrant · Apache Kafka · OTel Collector
```

Full architecture document: [`docs/architecture.md`](docs/architecture.md)

---

## Quick Start

### Prerequisites

| Tool | Version |
|------|---------|
| Docker | ≥ 24 |
| Docker Compose | ≥ 2.24 |
| Python | ≥ 3.12 (for local dev) |
| Go | ≥ 1.22 (for gateway dev) |

### 1. Clone and configure

```bash
git clone https://github.com/your-org/opsintel-rag.git
cd opsintel-rag
cp .env.example .env
# Edit .env — set SECRET_KEY and POSTGRES_PASSWORD at minimum
```

### 2. Start infrastructure services

```bash
cd deployments/docker
docker compose up -d postgres qdrant kafka zookeeper otel-collector
```

### 3. Start the AI Orchestrator (without LLM)

```bash
docker compose up -d ai-orchestrator ingestion
```

The orchestrator starts with `TELEMETRY_PROVIDER=mock` and `OIDC_ENABLED=false`,
so you can immediately make requests using the dev principal.

### 4. Verify health

```bash
curl http://localhost:8000/api/v1/health | python3 -m json.tool
```

### 5. (Optional) Start llama.cpp with a model

Download a GGUF model and mount it:

```bash
# Example using Mistral 7B Instruct Q4_K_M
wget https://huggingface.co/TheBloke/Mistral-7B-Instruct-v0.2-GGUF/resolve/main/mistral-7b-instruct-v0.2.Q4_K_M.gguf \
  -O deployments/docker/models/mistral-7b-instruct.gguf

LLAMACPP_MODEL_FILE=mistral-7b-instruct.gguf docker compose --profile llm up -d llamacpp
```

---

## API Reference

Swagger UI is available at `http://localhost:8000/docs` (development mode only).

### Investigate an Incident

```bash
curl -X POST http://localhost:8000/api/v1/investigate \
  -H "Content-Type: application/json" \
  -d '{
    "query": "The order service is timing out intermittently — what could be causing this?",
    "services": ["order-service"],
    "environment": "production",
    "time_range_minutes": 60
  }'
```

**Response (structured JSON):**

```json
{
  "investigation_id": "...",
  "incident_summary": "The order-service is experiencing connection pool exhaustion...",
  "affected_services": ["order-service"],
  "observations": [
    {"finding": "100% connection pool utilisation", "evidence_type": "FACT", "source": "metric"}
  ],
  "root_cause_hypotheses": [
    {
      "hypothesis": "Connection leak introduced by recent deployment",
      "confidence": 0.82,
      "evidence_type": "HYPOTHESIS",
      "supporting_evidence": ["Deployment 2.14.1 two hours prior", "Gradual pool increase"],
      "contradicting_evidence": []
    }
  ],
  "recommended_checks": ["Review connection pool metrics over 24h", "Check deployment logs"],
  "recommended_remediation": ["Restart order-service pods", "Roll back to 2.13.x"]
}
```

### Ingest a Runbook

```bash
curl -X POST http://localhost:8000/api/v1/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Order Service Connection Pool Runbook",
    "source_type": "runbook",
    "document_type": "runbook",
    "service_name": "order-service",
    "environment": "production",
    "content": "## Symptoms\nConnection pool exhausted...\n\n## Steps\n1. Check HikariCP metrics..."
  }'
```

### Create an Incident

```bash
curl -X POST http://localhost:8000/api/v1/incidents \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Order service connection pool exhausted",
    "severity": "CRITICAL",
    "environment": "production",
    "services": ["order-service"]
  }'
```

---

## Project Structure

```
opsintel-rag/
├── services/
│   ├── ai-orchestrator/          # Python 3.12 FastAPI — core AI service
│   │   ├── app/
│   │   │   ├── api/routes/       # FastAPI route handlers
│   │   │   ├── agents/           # InvestigationAgent, ContextBuilder
│   │   │   ├── rag/              # Chunker, Parser, BM25, VectorStore, Ingestion, Retrieval
│   │   │   ├── telemetry/        # TelemetryProvider interface + Mock/Dynatrace/Grafana
│   │   │   ├── correlation/      # CorrelationEngine
│   │   │   ├── inference/        # LLMProvider, LlamaCppProvider, VLLMProvider
│   │   │   ├── embeddings/       # EmbeddingProvider (sentence-transformers)
│   │   │   ├── models/           # Pydantic domain models + SQLAlchemy ORM
│   │   │   ├── security/         # JWT auth, RBAC, sanitisation
│   │   │   ├── db/               # Async SQLAlchemy session
│   │   │   └── config.py         # Pydantic Settings (env-based)
│   │   └── tests/                # pytest unit tests
│   ├── ingestion/                # Standalone ingestion microservice
│   └── gateway/                  # Go API Gateway
│       ├── cmd/gateway/          # main.go
│       └── internal/             # config, middleware, proxy, routes
├── deployments/
│   ├── docker/                   # Docker Compose + service configs
│   │   ├── docker-compose.yml
│   │   ├── postgres/init.sql
│   │   ├── qdrant/config.yaml
│   │   └── otel/collector-config.yaml
│   └── kubernetes/               # (Milestone 4)
├── docs/
│   └── architecture.md
├── .env.example
└── README.md
```

---

## Configuration

All configuration is via environment variables. Copy `.env.example` to `.env`.

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `llamacpp` | LLM backend: `llamacpp` or `vllm` |
| `LLM_BASE_URL` | `http://llamacpp:8080/v1` | OpenAI-compatible endpoint |
| `TELEMETRY_PROVIDER` | `mock` | Telemetry source: `mock`, `dynatrace`, `grafana` |
| `OIDC_ENABLED` | `false` | Enable OIDC JWT validation |
| `EMBEDDING_MODEL` | `BAAI/bge-large-en-v1.5` | HuggingFace embedding model |
| `RERANKER_ENABLED` | `true` | Enable cross-encoder reranking |
| `CORRELATION_WINDOW_BEFORE_MINUTES` | `10` | Time window before incident |

See `.env.example` for the full list.

---

## Running Tests

```bash
cd services/ai-orchestrator
pip install -e ".[dev]"
pytest tests/ -v
```

Tests are self-contained and do not require running databases or LLM servers.
All external I/O is mocked.

---

## Switching LLM Backends

**llama.cpp (local CPU/GPU):**
```env
LLM_PROVIDER=llamacpp
LLM_BASE_URL=http://llamacpp:8080/v1
LLM_MODEL_NAME=mistral-7b-instruct
```

**vLLM (GPU accelerated):**
```env
LLM_PROVIDER=vllm
LLM_BASE_URL=http://vllm:8000/v1
LLM_MODEL_NAME=mistralai/Mistral-7B-Instruct-v0.2
```

No code changes required — only environment variable changes.

---

## Security

- **Authentication:** OIDC/OAuth2 JWT when `OIDC_ENABLED=true`. Dev bypass when false.
- **Authorization:** RBAC — roles `admin`, `operator`, `viewer`, `ingest`.
- **Prompt injection protection:** Input sanitisation on all query fields.
- **Document access control:** Per-document `access_policy` enforced at retrieval.
- **No hard-coded credentials:** All secrets via environment variables.
- **Audit logging:** Every action written to `audit_log` table.

---

## Roadmap

| Milestone | Status | Description |
|-----------|--------|-------------|
| 1 | ✅ Complete | Foundation: RAG pipeline, mock telemetry, llama.cpp |
| 2 | Planned | Live telemetry: Dynatrace, Grafana, Kafka consumers |
| 3 | Planned | Full Go gateway: OIDC, SSE streaming, rate limiting |
| 4 | Planned | Kubernetes Helm charts, multi-replica, Qdrant cluster |

---

## Contributing

1. Fork the repository.
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Write tests for all new code.
4. Ensure `pytest` passes: `pytest services/ai-orchestrator/tests/ -v`
5. Submit a pull request.

---

## License

Apache 2.0 — see `LICENSE` file.
