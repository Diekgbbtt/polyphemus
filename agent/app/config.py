import os


def _csv_env(name: str, default: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in os.environ.get(name, default).split(",") if part.strip())


class Config:
    NEO4J_URI = os.environ["NEO4J_URI"]
    NEO4J_USER = os.environ["NEO4J_USER"]
    NEO4J_PASSWORD = os.environ["NEO4J_PASSWORD"]
    POSTGRES_DSN = os.environ["POSTGRES_DSN"]
    KALI_MCP_URL = os.environ["KALI_MCP_URL"]
    PROJECT_ID = os.environ.get("PROJECT_ID", "default")
    HEARTBEAT_TICK_SECONDS = int(os.environ.get("HEARTBEAT_TICK_SECONDS", "10"))
    LIVENESS_TTL_SECONDS = int(os.environ.get("LIVENESS_TTL_SECONDS", "30"))
    # Reaping a run only because its heartbeat went stale must tolerate heavy
    # phases (crawl/fuzz) + transient DB slowness; 30s was aggressive enough to
    # flip healthy runs to "failed" (D1). At a 10s tick this is 30 missed ticks.
    REAP_TTL_SECONDS = int(os.environ.get("REAP_TTL_SECONDS", "300"))
    REAPER_SWEEP_SECONDS = int(os.environ.get("REAPER_SWEEP_SECONDS", "60"))
    # Worker-thread pool for offloaded blocking work (pod graph.invoke + all
    # sync pg/neo4j calls). The asyncio default (~cpu+4=12) is far too small for
    # phase fan-out (MAX_PODS=20 x several jobs), which starves the heartbeat/DB
    # calls behind long-held pod threads. Sized generously; work is I/O-bound.
    WORKER_THREADS = int(os.environ.get("WORKER_THREADS", "64"))
    LIGHTRAG_APPROVED_SOURCES = _csv_env(
        "LIGHTRAG_APPROVED_SOURCES",
        "data/lightrag/inputs,docs/design/lightrag",
    )
    LIGHTRAG_WORK_DIR = os.environ.get("LIGHTRAG_WORK_DIR", "/tmp/polyphemus-lightrag")
    LIGHTRAG_MAX_CANDIDATES = int(os.environ.get("LIGHTRAG_MAX_CANDIDATES", "5"))
    LIGHTRAG_API_URL = os.environ.get("LIGHTRAG_API_URL", "http://lightrag:9621")
    LIGHTRAG_API_KEY = os.environ.get("LIGHTRAG_API_KEY", "")
    LIGHTRAG_TIMEOUT_SECONDS = float(os.environ.get("LIGHTRAG_TIMEOUT_SECONDS", "30"))

config = Config()
