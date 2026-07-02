"""Observability e2e — the system correctly OBSERVES and DIAGNOSES a degraded
backend (the failure path that had zero coverage). Induces a real fault by
stopping neo4j, asserts /health reports degraded + surfaces WHY, then restores."""
import subprocess, httpx
from tests.conftest import wait_for

HEALTH = "http://localhost:8080/health"

def _health():
    return httpx.get(HEALTH, timeout=3).json()

def test_health_reports_and_diagnoses_degraded_backend():
    subprocess.run(["docker", "compose", "up", "-d", "--build"], check=True)
    wait_for(lambda: _health() if _health()["status"] == "ok" else None, timeout=600)
    subprocess.run(["docker", "compose", "stop", "neo4j"], check=True)
    try:
        body = wait_for(lambda: _health() if _health()["status"] == "degraded" else None,
                        timeout=60)
        assert body["checks"]["neo4j"] is False           # the fault is observed
        assert body["checks"]["postgres"] is True          # siblings unaffected
        assert body["errors"].get("neo4j"), "degraded backend must surface WHY"  # diagnosable
    finally:
        subprocess.run(["docker", "compose", "start", "neo4j"], check=True)
        wait_for(lambda: _health() if _health()["status"] == "ok" else None, timeout=180)
