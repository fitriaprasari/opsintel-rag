"""
Script: ingest_sample_docs.py
Populates the knowledge base with sample runbooks and operational documents.
Run this after starting the ai-orchestrator service.

Usage:
    python scripts/ingest_sample_docs.py [--url http://localhost:8000]
"""
from __future__ import annotations

import argparse
import json
import sys

import httpx

SAMPLE_DOCUMENTS = [
    {
        "title": "Order Service Connection Pool Runbook",
        "source_type": "runbook",
        "document_type": "runbook",
        "service_name": "order-service",
        "environment": "production",
        "content": """# Order Service Connection Pool Runbook

## Overview
This runbook covers diagnosis and remediation of HikariCP connection pool exhaustion
in the order-service.

## Symptoms
- HTTP 503 / 504 responses from order-service
- HikariPool-1 timeout messages in application logs
- db.connections.active metric at or near maximum
- Increasing response time P99 exceeding 5 seconds

## Investigation Steps
1. Check connection pool metrics: `db.connections.active` and `db.connections.pending`
2. Identify which database the pool is connecting to
3. Check for slow queries: `SELECT pid, query, duration FROM pg_stat_activity WHERE state='active'`
4. Review application logs for "Connection is not available" messages
5. Check for recent deployments that may have changed pool configuration
6. Verify database server health (CPU, memory, disk I/O)

## Remediation
### Immediate
1. Restart affected pods to release connections: `kubectl rollout restart deployment/order-service`
2. Increase pool size temporarily if load is legitimate:
   - Set `HIKARI_MAX_POOL_SIZE=150` in pod environment
   - Redeploy

### Root Cause Resolution
- If caused by slow queries: add indexes or optimise query plans
- If caused by connection leak: review code for unclosed connections
- If caused by traffic spike: enable circuit breaker for database calls
- If caused by deployment: roll back to previous version

## Prevention
- Enable HikariCP metrics export to Prometheus
- Set alert on pool_usage > 80%
- Perform load testing before releases that touch database code
""",
    },
    {
        "title": "Kubernetes OOMKilled Pod Resolution SOP",
        "source_type": "sop",
        "document_type": "sop",
        "service_name": None,
        "environment": "production",
        "content": """# Kubernetes OOMKilled Pod Resolution SOP

## Trigger
Pod status shows OOMKilled (exit code 137).

## Immediate Response
1. Check which pods are affected: `kubectl get pods --all-namespaces | grep OOMKilled`
2. Check pod events: `kubectl describe pod <pod-name> -n <namespace>`
3. Check current memory limits: `kubectl get pod <pod-name> -o jsonpath='{.spec.containers[*].resources}'`

## Investigation
1. Review JVM heap metrics over past 24h — look for gradual increase (leak indicator)
2. Check if memory growth correlates with recent deployment
3. Capture heap dump if pod is still running:
   `kubectl exec <pod> -- jmap -dump:format=b,file=/tmp/heap.hprof <pid>`
4. Review GC logs for promotion failure or continuous GC activity

## Remediation
### Immediate (< 5 min)
- Increase memory limits: edit deployment and bump `resources.limits.memory`
- Restart pod to clear memory state

### If memory leak confirmed
1. Roll back to last stable deployment
2. Open P1 incident for engineering team
3. Enable heap dump on OOM: add JVM flag `-XX:+HeapDumpOnOutOfMemoryError`

## Post-Incident
- Add memory leak detector to CI pipeline
- Set alert: pod_restart_count > 3 within 30 minutes
""",
    },
    {
        "title": "RCA: Payment Service Outage 2024-03-15",
        "source_type": "rca",
        "document_type": "rca",
        "service_name": "payment-service",
        "environment": "production",
        "content": """# Root Cause Analysis: Payment Service Outage
## Date: 2024-03-15
## Duration: 47 minutes (10:33 - 11:20 UTC)
## Severity: CRITICAL

## Summary
A memory leak introduced in version 2.14.1 of the payment-service caused progressive
heap exhaustion leading to OOMKilled pod restarts and a full service outage.

## Timeline
- 10:30 UTC: Deployment of payment-service 2.14.1 to production
- 10:33 UTC: First PagerDuty alert — HighMemoryUsage on payment-service
- 10:41 UTC: First OOMKilled restart observed
- 10:52 UTC: Pod restart loop detected, circuit breakers open upstream
- 11:05 UTC: Engineering team identifies root cause — local cache in 2.14.1 not bounded
- 11:15 UTC: Rollback to 2.13.4 initiated
- 11:20 UTC: Service restored, alerts cleared

## Root Cause
The new local caching layer introduced in 2.14.1 used an unbounded ConcurrentHashMap
for session data. Under production traffic, this map grew without eviction,
consuming the full 4GB heap within approximately 12 minutes per pod.

## Contributing Factors
1. Cache was tested against unit tests only — no load testing with production-like traffic
2. Memory limits were not increased to accommodate new caching behaviour
3. No memory leak detection ran in CI pipeline

## Corrective Actions
1. ✅ Rolled back to 2.13.4
2. ✅ Added bounded cache (Caffeine) with max size 10,000 entries
3. ✅ Added memory leak detector plugin to CI
4. ✅ Load test now mandatory for all deployments touching caching code
5. [ ] Increase staging environment memory to match production for pre-prod testing

## Lessons Learned
- Always bound in-memory caches in JVM services
- Load test all deployments that touch memory-intensive features before production
- Set memory growth rate alerts (rate_of_increase > 50MB/min over 5 minutes)
""",
    },
]


def main():
    parser = argparse.ArgumentParser(description="Ingest sample documents into OpsIntel RAG")
    parser.add_argument("--url", default="http://localhost:8000", help="AI Orchestrator base URL")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    ingested = 0
    skipped = 0
    errors = 0

    with httpx.Client(timeout=60) as client:
        for doc in SAMPLE_DOCUMENTS:
            print(f"  Ingesting: {doc['title'][:60]}...", end=" ", flush=True)
            try:
                resp = client.post(f"{base_url}/api/v1/ingest", json=doc)
                resp.raise_for_status()
                result = resp.json()
                if result.get("skipped"):
                    print("SKIPPED (already indexed)")
                    skipped += 1
                else:
                    print(f"OK ({result['chunk_count']} chunks, {result.get('latency_ms', '?')}ms)")
                    ingested += 1
            except httpx.HTTPStatusError as e:
                print(f"ERROR: HTTP {e.response.status_code}")
                errors += 1
            except Exception as e:
                print(f"ERROR: {e}")
                errors += 1

    print(f"\nDone. ingested={ingested} skipped={skipped} errors={errors}")
    sys.exit(0 if errors == 0 else 1)


if __name__ == "__main__":
    main()
