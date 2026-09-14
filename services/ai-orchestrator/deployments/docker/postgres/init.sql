-- OpsIntel RAG — PostgreSQL initialisation
-- This script is run once when the container first starts.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- ── Incidents ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS incidents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_id     TEXT UNIQUE,
    title           TEXT NOT NULL,
    description     TEXT,
    severity        TEXT NOT NULL CHECK (severity IN ('CRITICAL','HIGH','MEDIUM','LOW','INFO')),
    status          TEXT NOT NULL DEFAULT 'OPEN'
                    CHECK (status IN ('OPEN','INVESTIGATING','RESOLVED','CLOSED')),
    environment     TEXT NOT NULL,
    services        TEXT[] DEFAULT '{}',
    cluster         TEXT,
    namespace       TEXT,
    region          TEXT,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Service catalog ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS services (
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

-- ── Service dependencies ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS service_dependencies (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_service  TEXT NOT NULL,
    target_service  TEXT NOT NULL,
    dependency_type TEXT NOT NULL DEFAULT 'http',
    environment     TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Users ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject         TEXT UNIQUE NOT NULL,
    email           TEXT UNIQUE NOT NULL,
    name            TEXT,
    roles           TEXT[] DEFAULT '{}',
    tenant_id       TEXT,
    active          BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at   TIMESTAMPTZ
);

-- ── RAG document registry ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS rag_documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title           TEXT NOT NULL,
    source_url      TEXT,
    source_type     TEXT NOT NULL,
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
    access_policy   JSONB DEFAULT '{"allowed_roles": ["admin","operator","viewer"]}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Investigation results ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS investigations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id     UUID REFERENCES incidents(id) ON DELETE SET NULL,
    query           TEXT NOT NULL,
    context_json    JSONB NOT NULL,
    response_json   JSONB NOT NULL,
    llm_model       TEXT,
    prompt_version  TEXT,
    rag_latency_ms  INTEGER,
    llm_latency_ms  INTEGER,
    total_tokens    INTEGER,
    created_by      UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Feedback ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS feedback (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    investigation_id    UUID REFERENCES investigations(id) ON DELETE CASCADE,
    rating              SMALLINT CHECK (rating BETWEEN 1 AND 5),
    comment             TEXT,
    created_by          UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Audit log ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_log (
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

-- ── Indexes ───────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_incidents_status        ON incidents(status);
CREATE INDEX IF NOT EXISTS idx_incidents_environment   ON incidents(environment);
CREATE INDEX IF NOT EXISTS idx_incidents_started_at    ON incidents(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_investigations_incident ON investigations(incident_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_actor         ON audit_log(actor_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_rag_docs_service        ON rag_documents(service_name, environment);
CREATE INDEX IF NOT EXISTS idx_services_env            ON services(name, environment);

-- ── Seed: default admin user (development only) ────────────────────────────
INSERT INTO users (subject, email, name, roles, tenant_id)
VALUES ('dev-admin', 'admin@opsintel.local', 'Dev Admin', ARRAY['admin','operator','viewer'], 'default')
ON CONFLICT (subject) DO NOTHING;
