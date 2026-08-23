#!/usr/bin/env python3
"""Stream a query_lightrag answer chunk-by-chunk (offline demo)."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from polymerhus.lightrag.query_spec import QuerySpecV1
from polymerhus.lightrag.tool import build_lightrag_tool

spec = QuerySpecV1.model_validate_json(
    Path("examples/lightrag-query-simulation/P6B-EASY-01.json").read_text()
)
for event in build_lightrag_tool().stream(spec):
    if event["type"] == "delta":
        print(event["text"], end="", flush=True)
    elif event["type"] == "answer":
        print("\n\naccepted:", event["accepted"])
