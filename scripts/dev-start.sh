#!/usr/bin/env bash
# dev-start.sh — start the full development stack
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
COMPOSE_FILE="$PROJECT_ROOT/deployments/docker/docker-compose.yml"

if [ ! -f "$PROJECT_ROOT/.env" ]; then
  echo "ERROR: .env file not found. Copy .env.example to .env and configure it."
  exit 1
fi

echo "Starting infrastructure services..."
docker compose -f "$COMPOSE_FILE" --env-file "$PROJECT_ROOT/.env" \
  up -d postgres qdrant kafka zookeeper otel-collector

echo "Waiting for PostgreSQL to be ready..."
until docker compose -f "$COMPOSE_FILE" exec postgres pg_isready -U opsintel -d opsintel 2>/dev/null; do
  sleep 2
done

echo "Starting AI Orchestrator and Ingestion services..."
docker compose -f "$COMPOSE_FILE" --env-file "$PROJECT_ROOT/.env" \
  up -d ai-orchestrator ingestion

echo ""
echo "Stack started. Services:"
echo "  AI Orchestrator : http://localhost:8000"
echo "  API Docs        : http://localhost:8000/docs"
echo "  Qdrant UI       : http://localhost:6333/dashboard"
echo "  PostgreSQL      : localhost:5432"
echo ""
echo "Ingest sample documents:"
echo "  python scripts/ingest_sample_docs.py"
