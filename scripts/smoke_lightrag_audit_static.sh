#!/bin/sh
set -eu

# Static audit smoke test: run only the local audit unit tests.
# No network, Docker, LightRAG live, or external LLM calls are made.

python -m pytest tests/ingestion/test_audit.py "$@"

echo "Static audit smoke test passed"
