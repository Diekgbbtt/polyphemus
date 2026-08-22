#!/usr/bin/env bash
set -euo pipefail
# Launch the capability-adaptive matrix harness (fake LLM + agent-matrix)
cd "$(dirname "$0")/.."
docker build -t polymerhus-agent:capability-matrix .
docker compose -f docker-compose.yml -f docker-compose.capability-matrix.yml up --build -d fake-llm agent-matrix
echo "Harness up. Run tests:"
echo "  docker compose -f docker-compose.yml -f docker-compose.capability-matrix.yml run --rm tests python -m pytest tests/integration/test_capability_adaptive_matrix.py -q"
