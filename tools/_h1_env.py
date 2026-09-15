"""Shared env normaliser for the H1 live harness.

Strips surrounding quotes from any LANGFUSE_* value (a shell/dotenv habit that
breaks the OTLP URL) and fills any missing var from the repo `.env`, so the
live run is independent of how the caller quoted its shell assignment.
"""
import os
from pathlib import Path


def load_langfuse_env() -> None:
    env_file = Path(__file__).resolve().parents[1] / ".env"
    file_vals = {}
    if env_file.is_file():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("LANGFUSE_") and "=" in line:
                k, _, v = line.partition("=")
                file_vals[k.strip()] = v.strip().strip('"').strip("'")
    for key in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST"):
        cur = os.environ.get(key, "").strip().strip('"').strip("'")
        if not cur:
            cur = file_vals.get(key, "")
        if cur:
            os.environ[key] = cur
