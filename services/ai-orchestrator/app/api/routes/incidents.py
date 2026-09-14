"""
Incident CRUD endpoints.
POST /incidents       — create incident record
GET  /incidents       — list incidents
GET  /incidents/{id}  — get incident detail
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.domain import IncidentStatus, Severity
from app.models.orm import IncidentORM
from app.security.auth import Principal, require_role

router = APIRouter()


class CreateIncidentRequest(BaseModel):
    title: str = Field(..., min_length=3, max_length=500)
    description: str | None = None
    severity: Severity = Severity.MEDIUM
    environment: str = "production"
    services: list[str] = Field(default_factory=list)
    cluster: str | None = None
    namespace: str | None = None
    region: str | None = None
    external_id: str | None = None


@router.post("/incidents", status_code=status.HTTP_201_CREATED)
async def create_incident(
    req: CreateIncidentRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "operator")),
) -> dict[str, Any]:
    """Create a new incident record."""
    orm = IncidentORM(
        title=req.title,
        description=req.description,
        severity=req.severity.value,
        status=IncidentStatus.OPEN.value,
        environment=req.environment,
        services=req.services,
        cluster=req.cluster,
        namespace=req.namespace,
        region=req.region,
        external_id=req.external_id,
        started_at=datetime.now(timezone.utc),
    )
    db.add(orm)
    await db.flush()
    await db.refresh(orm)
    return {"id": orm.id, "title": orm.title, "status": orm.status}


@router.get("/incidents")
async def list_incidents(
    status_filter: str | None = None,
    environment: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "operator", "viewer")),
) -> list[dict[str, Any]]:
    """List incidents with optional status/environment filter."""
    query = select(IncidentORM)
    if status_filter:
        query = query.where(IncidentORM.status == status_filter.upper())
    if environment:
        query = query.where(IncidentORM.environment == environment)
    query = query.order_by(IncidentORM.started_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    incidents = result.scalars().all()
    return [
        {
            "id": i.id,
            "title": i.title,
            "severity": i.severity,
            "status": i.status,
            "environment": i.environment,
            "services": i.services,
            "started_at": i.started_at,
        }
        for i in incidents
    ]


@router.get("/incidents/{incident_id}")
async def get_incident(
    incident_id: str,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "operator", "viewer")),
) -> dict[str, Any]:
    """Get full incident detail."""
    result = await db.execute(
        select(IncidentORM).where(IncidentORM.id == incident_id)
    )
    incident = result.scalars().first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return {
        "id": incident.id,
        "title": incident.title,
        "description": incident.description,
        "severity": incident.severity,
        "status": incident.status,
        "environment": incident.environment,
        "services": incident.services,
        "cluster": incident.cluster,
        "namespace": incident.namespace,
        "region": incident.region,
        "external_id": incident.external_id,
        "started_at": incident.started_at,
        "resolved_at": incident.resolved_at,
        "created_at": incident.created_at,
    }
