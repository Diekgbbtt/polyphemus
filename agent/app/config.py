import os

class Config:
    NEO4J_URI = os.environ["NEO4J_URI"]
    NEO4J_USER = os.environ["NEO4J_USER"]
    NEO4J_PASSWORD = os.environ["NEO4J_PASSWORD"]
    POSTGRES_DSN = os.environ["POSTGRES_DSN"]
    KALI_MCP_URL = os.environ["KALI_MCP_URL"]
    PROJECT_ID = os.environ.get("PROJECT_ID", "default")
    HEARTBEAT_TICK_SECONDS = int(os.environ.get("HEARTBEAT_TICK_SECONDS", "10"))
    LIVENESS_TTL_SECONDS = int(os.environ.get("LIVENESS_TTL_SECONDS", "30"))
    REAP_TTL_SECONDS = int(os.environ.get("REAP_TTL_SECONDS", "30"))
    REAPER_SWEEP_SECONDS = int(os.environ.get("REAPER_SWEEP_SECONDS", "60"))

config = Config()
