#!/usr/bin/env bash
# Run the Steel pool MCP prototype scenarios.
#
# Usage:
#   ./run_scenarios.sh concurrent
#   ./run_scenarios.sh exhaust
#   ./run_scenarios.sh outlier
#   ./run_scenarios.sh stop
#   ./run_scenarios.sh crawler
#   ./run_scenarios.sh all
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
COMPOSE="$ROOT/prototype/steel_pool_mcp/compose.prototype.yml"
LOGS="$ROOT/prototype/steel_pool_mcp/logs"
NET="steel-proto-net"
AGENT_IMAGE="polymerhus-agent:latest"
SERVER="steel-pool-proto-steel-mcp-1"
MCP_URL="http://steel-mcp:8003/mcp"

mkdir -p "$LOGS"

cleanup_agents() {
  for name in proto-a1 proto-a2 proto-h1 proto-h2 proto-wait proto-out \
              proto-s1 proto-s2 proto-stop proto-status proto-crawl; do
    docker rm -f "$name" >/dev/null 2>&1 || true
  done
}

run_agent() {
  local name="$1"
  shift
  local envargs=(-e "STEEL_MCP_URL=$MCP_URL" -e "OWNER=proto")
  for kv in "$@"; do
    envargs+=(-e "$kv")
  done
  docker rm -f "$name" >/dev/null 2>&1 || true
  docker run -d --name "$name" --network "$NET" \
    -v "$ROOT:/srv:ro" "${envargs[@]}" \
    --entrypoint python "$AGENT_IMAGE" \
    /srv/prototype/steel_pool_mcp/client.py >/dev/null
}

wait_agent() {
  local name="$1"
  docker wait "$name" >/dev/null 2>&1 || true
  docker logs "$name" 2>&1 | tee "$LOGS/$name.log"
}

start_stack() {
  docker rm -f steel-proto-1 steel-proto-2 kali-proto >/dev/null 2>&1 || true
  docker network create "$NET" >/dev/null 2>&1 || true
  docker compose -f "$COMPOSE" --project-directory "$ROOT" \
    up -d --wait steel-1 steel-2 steel-mcp
  for _ in $(seq 1 30); do
    if docker logs "$SERVER" 2>&1 | grep -q '"event": "startup"'; then
      return 0
    fi
    sleep 1
  done
  echo "server did not log startup" >&2
  docker logs "$SERVER" 2>&1 | tail -40 >&2
  return 1
}

save_server_log() {
  docker logs "$SERVER" 2>&1 | tee "$LOGS/server.log"
}

scenario_concurrent() {
  echo "=== concurrent: two agents, two workers ==="
  run_agent proto-a1 CLIENT_ID=agent-1 HOLD_S=6
  run_agent proto-a2 CLIENT_ID=agent-2 HOLD_S=6
  wait_agent proto-a1 >"$LOGS/agent-1.log" &
  wait_agent proto-a2 >"$LOGS/agent-2.log" &
  wait
  run_agent proto-status CLIENT_ID=status STATUS_ONLY=1
  wait_agent proto-status >"$LOGS/status-concurrent.log"
}

scenario_exhaust() {
  echo "=== exhaust: two holders, one waiter ==="
  run_agent proto-h1 CLIENT_ID=holder-1 HOLD_S=25
  run_agent proto-h2 CLIENT_ID=holder-2 HOLD_S=25
  sleep 7
  run_agent proto-wait CLIENT_ID=waiter WAIT_ONLY=1
  wait_agent proto-wait >"$LOGS/waiter.log"
  docker rm -f proto-h1 proto-h2 >/dev/null 2>&1 || true
  echo "killed holders; waiting for TTL"
  sleep 19
  run_agent proto-status CLIENT_ID=status-after-ttl STATUS_ONLY=1
  wait_agent proto-status >"$LOGS/status-after-ttl.log"
}

scenario_outlier() {
  echo "=== outlier: killed client, TTL release ==="
  run_agent proto-out CLIENT_ID=outlier OUTLIER=1 HOLD_S=45
  sleep 5
  docker kill proto-out >/dev/null 2>&1 || true
  echo "killed outlier; waiting for TTL"
  sleep 19
  run_agent proto-status CLIENT_ID=status-after-outlier STATUS_ONLY=1
  wait_agent proto-status >"$LOGS/status-after-outlier.log"
}

scenario_stop() {
  echo "=== stop: owner release clears the table ==="
  run_agent proto-s1 CLIENT_ID=stop-1 HOLD_S=30
  run_agent proto-s2 CLIENT_ID=stop-2 HOLD_S=30
  sleep 7
  run_agent proto-stop CLIENT_ID=stop RELEASE_OWNER=1
  wait_agent proto-stop >"$LOGS/stop.log"
  run_agent proto-status CLIENT_ID=status-after-stop STATUS_ONLY=1
  wait_agent proto-status >"$LOGS/status-after-stop.log"
  docker rm -f proto-s1 proto-s2 >/dev/null 2>&1 || true
}

scenario_crawler() {
  echo "=== crawler: three navigations through one lease ==="
  run_agent proto-crawl CLIENT_ID=crawler CRAWLER=1
  wait_agent proto-crawl >"$LOGS/crawler.log"
}

case "${1:-all}" in
  concurrent) cleanup_agents; start_stack; scenario_concurrent; save_server_log ;;
  exhaust)    cleanup_agents; start_stack; scenario_exhaust; save_server_log ;;
  outlier)    cleanup_agents; start_stack; scenario_outlier; save_server_log ;;
  stop)       cleanup_agents; start_stack; scenario_stop; save_server_log ;;
  crawler)    cleanup_agents; start_stack; scenario_crawler; save_server_log ;;
  all)
    cleanup_agents
    start_stack
    scenario_concurrent
    scenario_exhaust
    scenario_outlier
    scenario_stop
    scenario_crawler
    save_server_log
    ;;
  down)
    docker compose -f "$COMPOSE" --project-directory "$ROOT" down -v
    cleanup_agents
    ;;
  *)
    echo "unknown scenario: $1" >&2
    exit 2
    ;;
esac
