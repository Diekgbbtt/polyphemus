import os
import time

# Unit tests import config-backed modules (agent.app.config eager-reads these
# env vars at import time). setdefault fills safe dummies ONLY when the var is
# absent, so a real sourced .env (live-docker tests) is never overridden, while
# a clean-env unit run (CI / fresh clone) can still import + collect.
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test")
os.environ.setdefault("POSTGRES_DSN", "postgresql://postgres:postgres@localhost:5432/postgres")
os.environ.setdefault("KALI_MCP_URL", "http://localhost:8000/mcp")

def wait_for(fn, timeout=120, interval=2):
    """Poll fn() until truthy or non-raising; re-raise last error on timeout."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            r = fn()
            if r:
                return r
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(interval)
    if last:
        raise last
    raise TimeoutError(f"wait_for timed out after {timeout}s")
