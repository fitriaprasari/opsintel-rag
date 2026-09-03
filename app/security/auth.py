"""
Security module: JWT validation, RBAC, audit logging, input sanitisation.

Design principles:
- No hard-coded secrets.
- OIDC-first when enabled; dev-mode bypass when OIDC_ENABLED=false.
- Prompt injection protection via content sanitisation.
- Every sensitive action emits an audit event.
"""
from __future__ import annotations

import re
import time
from typing import Any

import httpx
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import ExpiredSignatureError, JWTError, jwt
from pydantic import BaseModel

from app.config import get_settings

_bearer = HTTPBearer(auto_error=False)

# ── JWKS cache ────────────────────────────────────────────────────────────────
_jwks_cache: dict[str, Any] = {}
_jwks_fetched_at: float = 0.0
_JWKS_TTL = 3600.0  # seconds


async def _get_jwks() -> dict[str, Any]:
    global _jwks_cache, _jwks_fetched_at
    if time.monotonic() - _jwks_fetched_at < _JWKS_TTL and _jwks_cache:
        return _jwks_cache
    s = get_settings()
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(s.oidc_jwks_uri)
        resp.raise_for_status()
        _jwks_cache = resp.json()
        _jwks_fetched_at = time.monotonic()
    return _jwks_cache


# ── Token principal ───────────────────────────────────────────────────────────

class Principal(BaseModel):
    subject: str
    email: str = ""
    name: str = ""
    roles: list[str] = []
    tenant_id: str | None = None
    raw_claims: dict[str, Any] = {}


# ── Dev-mode bypass principal ─────────────────────────────────────────────────

_DEV_PRINCIPAL = Principal(
    subject="dev-admin",
    email="admin@opsintel.local",
    name="Dev Admin",
    roles=["admin", "operator", "viewer"],
    tenant_id="default",
)


async def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
) -> Principal:
    """
    FastAPI dependency.
    - When OIDC_ENABLED=false: returns the dev principal (development only).
    - When OIDC_ENABLED=true: validates the bearer JWT against JWKS.
    """
    s = get_settings()
    if not s.oidc_enabled:
        return _DEV_PRINCIPAL

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )
    token = credentials.credentials
    try:
        jwks = await _get_jwks()
        claims = jwt.decode(
            token,
            jwks,
            algorithms=["RS256", "ES256"],
            audience=s.oidc_audience,
            issuer=s.oidc_issuer,
        )
    except ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {exc}"
        )

    return Principal(
        subject=claims.get("sub", ""),
        email=claims.get("email", ""),
        name=claims.get("name", ""),
        roles=claims.get("realm_access", {}).get("roles", []),
        tenant_id=claims.get("tenant_id"),
        raw_claims=claims,
    )


# ── RBAC helpers ──────────────────────────────────────────────────────────────

def require_role(*required_roles: str):
    """FastAPI dependency factory — requires any of the listed roles."""

    async def _check(principal: Principal = Depends(get_current_principal)) -> Principal:
        if not any(r in principal.roles for r in required_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {required_roles}",
            )
        return principal

    return _check


# ── Input sanitisation ────────────────────────────────────────────────────────

# Patterns that could indicate prompt injection attempts
_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ignore\s+(previous|prior|above)\s+instructions?", re.IGNORECASE),
    re.compile(r"disregard\s+(all|previous)\s+", re.IGNORECASE),
    re.compile(r"system\s+prompt", re.IGNORECASE),
    re.compile(r"<\|im_start\|>", re.IGNORECASE),
    re.compile(r"\[INST\]", re.IGNORECASE),
    re.compile(r"###\s*instruction", re.IGNORECASE),
    re.compile(r"act\s+as\s+(if\s+you\s+are|a\s+)", re.IGNORECASE),
    re.compile(r"jailbreak", re.IGNORECASE),
    re.compile(r"DAN\s+mode", re.IGNORECASE),
]


def sanitise_query(query: str) -> str:
    """
    Light sanitisation for user queries.
    Raises HTTPException(400) on detected injection patterns.
    Does NOT remove legitimate operational text.
    """
    if len(query) > 5000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Query exceeds maximum length of 5000 characters",
        )
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(query):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Query contains disallowed patterns",
            )
    return query.strip()


def check_document_access(document_access_policy: dict[str, Any], principal: Principal) -> bool:
    """
    Return True if the principal is allowed to see this document.
    Policy shape: {"allowed_roles": [...], "allowed_tenants": [...]}
    """
    allowed_roles: list[str] = document_access_policy.get("allowed_roles", [])
    if allowed_roles and not any(r in principal.roles for r in allowed_roles):
        return False
    allowed_tenants: list[str] = document_access_policy.get("allowed_tenants", [])
    if allowed_tenants and principal.tenant_id not in allowed_tenants:
        return False
    return True
