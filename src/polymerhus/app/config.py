import os
import math


def _csv_env(name: str, default: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in os.environ.get(name, default).split(",") if part.strip())


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name, str(default))
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a float, got {raw!r}") from exc
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite positive float, got {raw!r}")
    return value


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer, got {raw!r}")
    return value


class Config:
    NEO4J_URI = os.environ["NEO4J_URI"]
    NEO4J_USER = os.environ["NEO4J_USER"]
    NEO4J_PASSWORD = os.environ["NEO4J_PASSWORD"]
    POSTGRES_DSN = os.environ["POSTGRES_DSN"]
    KALI_MCP_URL = os.environ["KALI_MCP_URL"]
    PROJECT_ID = os.environ.get("PROJECT_ID", "default")
    HEARTBEAT_TICK_SECONDS = int(os.environ.get("HEARTBEAT_TICK_SECONDS", "10"))
    LIVENESS_TTL_SECONDS = int(os.environ.get("LIVENESS_TTL_SECONDS", "30"))
    # How long a run can go without a heartbeat before being reaped
    REAP_TTL_SECONDS = int(os.environ.get("REAP_TTL_SECONDS", "300"))
    REAPER_SWEEP_SECONDS = int(os.environ.get("REAPER_SWEEP_SECONDS", "60"))
    # Number of worker threads used by the async executor
    WORKER_THREADS = int(os.environ.get("WORKER_THREADS", "64"))
    LIGHTRAG_APPROVED_SOURCES = _csv_env(
        "LIGHTRAG_APPROVED_SOURCES",
        "data/lightrag/inputs,docs/design/lightrag",
    )
    LIGHTRAG_WORK_DIR = os.environ.get("LIGHTRAG_WORK_DIR", "/tmp/polyphemus-lightrag")
    LIGHTRAG_STORAGE_DIR = os.environ.get(
        "LIGHTRAG_STORAGE_DIR",
        "/data/lightrag/rag_storage",
    )
    LIGHTRAG_MAX_CANDIDATES = int(os.environ.get("LIGHTRAG_MAX_CANDIDATES", "5"))
    LIGHTRAG_API_URL = os.environ.get("LIGHTRAG_API_URL", "http://lightrag:9621")
    LIGHTRAG_BASE_API_URL = os.environ.get("LIGHTRAG_BASE_API_URL", LIGHTRAG_API_URL)
    LIGHTRAG_WRITEUP_API_URL = os.environ.get(
        "LIGHTRAG_WRITEUP_API_URL",
        "http://lightrag-writeups:9621",
    )
    LIGHTRAG_API_KEY = os.environ.get("LIGHTRAG_API_KEY", "")
    LIGHTRAG_TIMEOUT_SECONDS = float(os.environ.get("LIGHTRAG_TIMEOUT_SECONDS", "30"))
    LIGHTRAG_INGESTION_TIMEOUT_SECONDS = _float_env(
        "LIGHTRAG_INGESTION_TIMEOUT_SECONDS",
        1800.0,
    )
    LIGHTRAG_POLL_INTERVAL_SECONDS = _float_env("LIGHTRAG_POLL_INTERVAL_SECONDS", 2.0)
    QUERY_LLM_BASE_URL = os.environ.get(
        "QUERY_LLM_BASE_URL", "https://api.swissai.svc.cscs.ch/v1"
    )
    QUERY_LLM_API_KEY = os.environ.get("QUERY_LLM_API_KEY", "")
    QUERY_LLM_MODEL = os.environ.get(
        "QUERY_LLM_MODEL", "RCP-AIaaS/deepseek-ai/DeepSeek-V4-Flash-0731"
    )
    QUERY_LLM_MAX_TOKENS = _int_env("QUERY_LLM_MAX_TOKENS", 4096)
    QUERY_LLM_TIMEOUT_SECONDS = _float_env("QUERY_LLM_TIMEOUT_SECONDS", 120.0)
    QUERY_PIPELINE_MOCK = os.environ.get("QUERY_PIPELINE_MOCK", "") == "1"
    INGESTION_ROOT = os.environ.get("INGESTION_ROOT", "/data/ingestion")
    INGESTION_NORMALIZED_DIR = os.environ.get("INGESTION_NORMALIZED_DIR", "/data/ingestion/normalized")
    URL_DOWNLOAD_CONNECT_TIMEOUT = _float_env("URL_DOWNLOAD_CONNECT_TIMEOUT", 10.0)
    URL_DOWNLOAD_READ_TIMEOUT = _float_env("URL_DOWNLOAD_READ_TIMEOUT", 30.0)
    URL_DOWNLOAD_TOTAL_TIMEOUT = _float_env("URL_DOWNLOAD_TOTAL_TIMEOUT", 120.0)
    URL_DOWNLOAD_MAX_REDIRECTS = _int_env("URL_DOWNLOAD_MAX_REDIRECTS", 5)
    URL_DOWNLOAD_MAX_WIRE_BYTES = _int_env("URL_DOWNLOAD_MAX_WIRE_BYTES", 10 * 1024 * 1024)
    URL_DOWNLOAD_MAX_DECODED_BYTES = _int_env("URL_DOWNLOAD_MAX_DECODED_BYTES", 10 * 1024 * 1024)
    URL_DOWNLOAD_STREAM_CHUNK_SIZE = _int_env("URL_DOWNLOAD_STREAM_CHUNK_SIZE", 64 * 1024)
    # The per-analysis-module pass gate width (#121): replaces the legacy
    # process-wide ANALYSER_PASS_SEMAPHORE with a gate owned by the analysis
    # module, so analysis can pause/resume while recon and hunting keep running.
    ANALYSIS_PASS_GATE_WIDTH = int(os.environ.get("ANALYSIS_PASS_GATE_WIDTH", "1"))
    HUNTING_LIGHTRAG_TOOL = os.environ.get("HUNTING_LIGHTRAG_TOOL", "") == "1"

config = Config()
