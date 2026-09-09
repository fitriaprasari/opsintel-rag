"""
Ingestion Service — standalone FastAPI microservice.
Provides document upload endpoints backed by the shared RAG ingestion pipeline.

Endpoints:
  POST /ingest           — ingest plain text / markdown / HTML
  POST /ingest/file      — upload a file (multipart/form-data)
  GET  /health           — health check
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db.session import get_db
from app.embeddings.provider import get_embedding_provider
from app.models.domain import DocumentType, IngestRequest
from app.rag.bm25 import BM25Encoder
from app.rag.ingestion import IngestionPipeline
from app.rag.vector_store import QdrantVectorStore, make_qdrant_client

_settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure Qdrant collection exists on startup
    embedder = get_embedding_provider()
    client = make_qdrant_client()
    vs = QdrantVectorStore(client, _settings.qdrant_collection, embedder.dimension)
    await vs.ensure_collection()
    yield


app = FastAPI(
    title="OpsIntel — Ingestion Service",
    version="0.1.0",
    lifespan=lifespan,
)


def _make_pipeline() -> IngestionPipeline:
    embedder = get_embedding_provider()
    client = make_qdrant_client()
    vs = QdrantVectorStore(client, _settings.qdrant_collection, embedder.dimension)
    return IngestionPipeline(vs, embedder, BM25Encoder())


@app.post("/ingest", status_code=status.HTTP_202_ACCEPTED)
async def ingest(request: IngestRequest):
    """Ingest a document provided as JSON body."""
    async for db in get_db():
        pipeline = _make_pipeline()
        result = await pipeline.ingest(request, db)
        return result


@app.post("/ingest/file", status_code=status.HTTP_202_ACCEPTED)
async def ingest_file(
    file: UploadFile = File(...),
    title: str = Form(...),
    source_type: str = Form(default="other"),
    document_type: str = Form(default="other"),
    service_name: str | None = Form(default=None),
    environment: str | None = Form(default=None),
    team: str | None = Form(default=None),
):
    """Ingest a file upload (plain text, markdown, or HTML)."""
    raw = await file.read()
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded text.")

    request = IngestRequest(
        title=title,
        source_url=file.filename,
        source_type=DocumentType(source_type),
        document_type=DocumentType(document_type),
        service_name=service_name,
        environment=environment,
        team=team,
        content=content,
    )
    async for db in get_db():
        pipeline = _make_pipeline()
        result = await pipeline.ingest(request, db)
        return result


@app.get("/health")
async def health():
    return {"status": "ok", "service": "ingestion"}
