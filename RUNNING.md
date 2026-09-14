# Running OpsIntel RAG Locally

Three options, ordered from fastest to most complete.

---

## Option A — Unit Tests Only (no Docker required, ~60 seconds)

Run the full test suite without any database, Qdrant, or LLM.  
Everything is mocked.

```bash
cd opcdsintel-rag/services/ai-orchestrator

# Create a Python 3.12 virtual environment
python3.12 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate

# Install core + dev dependencies (no torch, no sentence-transformers)
pip install -e ".[dev]"

# Run all unit test
```

Expected output:
```
tests/test_bm25.py              PASSED  (8 tests)
tests/test_chunker.py           PASSED  (8 tests)
tests/test_correlation_engine.py PASSED (9 tests)
tests/test_inference.py         PASSED  (11 tests)
tests/test_mock_telemetry.py    PASSED  (9 tests)
tests/test_models.py            PASSED  (12 tests)
tests/test_parser.py            PASSED  (8 tests)
tests/test_retrieval.py         PASSED  (8 tests)
tests/test_security.py          PASSED  (11 tests)

Coverage: 70%+ of app/
```

---

## Option B — Full API Running Locally (Docker + Python, ~5 minutes)

Runs the FastAPI service with real PostgreSQL and Qdrant.  
Uses mock LLM and mock embeddings — no model download needed.

### Step 1: Prerequisites

- Docker Desktop (or Docker Engine + Compose plugin)
- Python 3.12+

### Step 2: Start infrastructure (PostgreSQL + Qdrant)
```bash
cd opsintel-rag

# Start only postgres and qdrant
docker compose -f deployments/docker/docker-compose.minimal.yml up -d

# Verify both are healthy
docker compose -f deployments/docker/docker-compose.minimal.yml ps
```

Wait for both to show `healthy` (usually ~20 seconds).

### Step 3: Configure environment

```bash
cd opsintel-rag
cp .env.dev .env
```

The `.env.dev` file already sets:
- `EMBEDDING_MODEL=mock` — no model download
- `LLM_PROVIDER=mock` — no LLM server needed
- `TELEMETRY_PROVIDER=mock` — synthetic telemetry
- `OIDC_ENABLED=false` — open access in dev
- `RERANKER_ENABLED=false` — no reranker model download

### Step 4: Install and run the AI Orchestrator

```bash
cd opsintel-rag/services/ai-orchestrator

python3.12 -m venv .venv
source .venv/bin/activate

# Install core dependencies (no ML packages)
pip install -e ".[dev]"

# Run the server (reads .env from project root)
uvicorn app.main:app --reload --env-file ../../.env
```

You should see:
```
INFO  Starting OpsIntel AI Orchestrator  env=development  llm_provider=mock  embedding_model=mock
INFO  Qdrant collection ready            collection=operational_knowledge
INFO  AI Orchestrator ready              host=0.0.0.0  port=8000  docs=http://localhost:8000/docs
INFO  Application startup complete.
```

### Step 5: Verify health

```bash
curl http://localhost:8000/api/v1/health | python3 -m json.tool
```

Expected:
```json
{
  "status": "ok",
  "version": "0.1.0",
  "components": {
    "postgres": "ok",
    "qdrant": "ok",
    "llm": "mock (no server required)"
  }
}
```

### Step 6: Open Swagger UI

Open **http://localhost:8000/docs** in your browser.

---

## Trying the API

### Submit an investigation (returns mock LLM response)

```bash
curl -s -X POST http://localhost:8000/api/v1/investigate \
  -H "Content-Type: application/json" \
  -d '{
    "query": "The order service is timing out — what is the root cause?",
    "services": ["order-service"],
    "environment": "production",
    "time_range_minutes": 60
  }' | python3 -m json.tool
```

This exercises the **full pipeline**:
1. Mock telemetry fetched (alerts, metrics, logs, traces from the `database_connection_pool_exhausted` scenario)
2. RAG retrieval attempted against Qdrant (empty results until you ingest documents)
3. `ContextBuilder` builds a structured prompt
4. `MockLLMProvider` returns a canned response (clearly labelled as mock)
5. Response persisted to PostgreSQL

### Ingest a runbook

```bash
curl -s -X POST http://localhost:8000/api/v1/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Order Service Connection Pool Runbook",
    "source_type": "runbook",
    "document_type": "runbook",
    "service_name": "order-service",
    "environment": "production",
    "content": "## Symptoms\nConnection pool exhausted.\n\n## Steps\n1. Check HikariCP metrics.\n2. Restart pods if needed.\n3. Investigate slow queries."
  }' | python3 -m json.tool
```

### Ingest all sample documents at once

```bash
cd opsintel-rag
pip install httpx   # if not already installed
python scripts/ingest_sample_docs.py
```

### Create an incident

```bash
curl -s -X POST http://localhost:8000/api/v1/incidents \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Order service connection pool exhausted",
    "severity": "CRITICAL",
    "environment": "production",
    "services": ["order-service"]
  }' | python3 -m json.tool
```

---

## Option C — Connect a Real LLM

Once you have Option B working, upgrade to a real LLM.

### Using llama.cpp (CPU, no GPU needed)

```bash
# 1. Download a GGUF model (Mistral 7B Q4 ~4 GB)
mkdir -p opsintel-rag/models
wget https://huggingface.co/TheBloke/Mistral-7B-Instruct-v0.2-GGUF/resolve/main/mistral-7b-instruct-v0.2.Q4_K_M.gguf \
     -O opsintel-rag/models/mistral-7b-instruct.gguf

# 2. Start llama.cpp server
docker run --rm -p 8080:8080 \
  -v $(pwd)/opsintel-rag/models:/models \
  ghcr.io/ggerganov/llama.cpp:server \
  --model /models/mistral-7b-instruct.gguf \
  --host 0.0.0.0 --port 8080 --ctx-size 4096 --n-gpu-layers 0

# 3. Update .env
LLM_PROVIDER=llamacpp
LLM_BASE_URL=http://localhost:8080/v1
LLM_MODEL_NAME=mistral-7b-instruct

# 4. Restart uvicorn — real AI responses will now come back
```

### Using a smaller model first

For a fast test with a much smaller download (~1.5 GB):

```bash
wget https://huggingface.co/TheBloke/phi-2-GGUF/resolve/main/phi-2.Q4_K_M.gguf \
     -O opsintel-rag/models/phi-2.gguf
```

---

## Adding Real Embeddings (Optional)

When you want semantic search to actually work (rather than zero vectors):

```bash
# Install ML dependencies (~2 GB download first time)
pip install -e ".[embeddings]"

# Update .env — use the small model for dev
EMBEDDING_MODEL=BAAI/bge-small-en-v1.5   # ~130 MB, good for dev
# or for production quality:
# EMBEDDING_MODEL=BAAI/bge-large-en-v1.5  # ~1.3 GB

RERANKER_ENABLED=true
```

The model downloads on **first API call** (lazy load) — not at startup.

---

## Qdrant Dashboard

After starting Qdrant, browse to:

**http://localhost:6333/dashboard**

You'll see the `operational_knowledge` collection after ingesting the first document.

--- z

## Stopping Everything

```bash
# Stop infrastructure
docker compose -f deployments/docker/docker-compose.minimal.yml down

# Stop uvicorn: Ctrl+C in its terminal
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `POSTGRES_PASSWORD validation error` | Make sure `.env` file exists in `opsintel-rag/` root. Run `cp .env.dev .env` |
| `Connection refused` to Postgres/Qdrant | Wait for containers: `docker compose ... ps` should show `healthy` |
| `ModuleNotFoundError: sentence_transformers` | Normal with `EMBEDDING_MODEL=mock`. Only install with `pip install -e ".[embeddings]"` if you need real vectors |
| `uvicorn: command not found` | Activate the venv: `source .venv/bin/activate` |
| Slow startup | Normal on first run — Python imports take a few seconds. Subsequent restarts are faster |
| Investigation returns "mock" response | Expected! Change `LLM_PROVIDER=llamacpp` and start a llama.cpp server for real responses |
