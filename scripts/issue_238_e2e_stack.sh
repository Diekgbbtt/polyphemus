#!/bin/sh
# #238 E2E stack lifecycle (Tasks 15 + 18).
#
# Every command is PINNED to one Compose project and one pair of files, so the
# gate can never address (or disturb) the operator's own stack.
#
#   config | build | up | health | assert-clean | reset-targets
#   | gate-once <name> | gate-twice <artifact-dir> | down
set -eu

PROJECT="${POLYPHEMUS_E2E_PROJECT:-polyphemus-238-e2e}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
API="${POLYPHEMUS_API_BASE:-http://localhost:18080}"
PY="${POLYPHEMUS_PY:-$ROOT/.venv/bin/python}"
SERVICES="postgres neo4j rate-limit-llm rate-matrix-no-limiter rate-matrix-high-limit rate-matrix-low-limit rate-matrix-false-bypass rate-matrix-burst-inconclusive kali agent"
E2E_TEST="tests/e2e/test_llm_rate_aware_recon_configurator_e2e.py"

compose() {
    docker compose -p "$PROJECT" -f "$ROOT/docker-compose.yml" -f "$ROOT/docker-compose.e2e.yml" "$@"
}

build() {
    SOURCE_REVISION="$(git -C "$ROOT" rev-parse HEAD)" compose build agent kali
}

up() {
    # shellcheck disable=SC2086
    compose up -d --wait $SERVICES
}

health() {
    # The agent runs schema migrations before it binds the API, so poll rather
    # than trust the container's healthcheck turn.
    attempts=0
    until compose exec -T agent python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=5).read()" >/dev/null 2>&1; do
        attempts=$((attempts + 1))
        test "$attempts" -lt 40 || { echo "[health] agent API never came up"; return 1; }
        sleep 3
    done
    compose exec -T kali /opt/venv/bin/python -c "from kali.http_history.capabilities import supported_policy_versions, wordlist_cardinality, FFUF_WORDLIST_PATH; assert 'traffic-policy/v2' in supported_policy_versions(); assert wordlist_cardinality(FFUF_WORDLIST_PATH) == 4750; print('[health] kali policy v2 + wordlist 4750')"
}

reset_targets() {
    compose cp "$ROOT/scripts/issue_238_reset_targets.py" agent:/tmp/issue_238_reset_targets.py
    compose exec -T agent python /tmp/issue_238_reset_targets.py
}

assert_clean() {
    runs="$(compose exec -T postgres psql -U polymerhus -d polymerhus -Atc 'select count(*) from recon_runs')"
    test "$runs" = "0" || { echo "[assert-clean] recon_runs=$runs (want 0)"; exit 1; }
    compose exec -T rate-limit-llm python -c "import json,urllib.request; assert json.load(urllib.request.urlopen('http://127.0.0.1:8080/health'))['requests'] == 0, 'provider served requests'"
    reset_targets
}

reset_state() {
    # The independent-reset boundary: wipe every run row and restart the
    # deterministic provider so its per-server counters start at zero. Run B
    # therefore shares NO run id, project id, generation or provider count with
    # Run A, while the cached tool volumes (not run state) survive.
    compose exec -T postgres psql -U polymerhus -d polymerhus -Atc \
        'TRUNCATE recon_jobs, recon_runs, projects RESTART IDENTITY CASCADE' >/dev/null
    compose restart rate-limit-llm >/dev/null
    attempts=0
    until compose exec -T rate-limit-llm python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3).read()" >/dev/null 2>&1; do
        attempts=$((attempts + 1))
        test "$attempts" -lt 20 || { echo "[reset] provider never came back"; return 1; }
        sleep 2
    done
}

gate_once() {
    name="${1:?run name required}"
    echo "[gate:$name] provider"
    POLYPHEMUS_API_BASE="$API" "$PY" -m pytest "$ROOT/tests/e2e/test_deterministic_llm_provider.py" -q -p no:cacheprovider
    echo "[gate:$name] functional matrix"
    POLYPHEMUS_API_BASE="$API" "$PY" -m pytest "$ROOT/$E2E_TEST" -q -rs -p no:cacheprovider
}

gate_twice() {
    artifacts="${1:?artifact directory required}"
    mkdir -p "$artifacts"
    for run in run-a run-b; do
        compose down --remove-orphans
        up
        health
        reset_state
        assert_clean > "$artifacts/$run-clean.json"
        # Redirect rather than pipe: `set -e` cannot see a failure through `tee`.
        if ! gate_once "$run" > "$artifacts/$run.log" 2>&1; then
            cat "$artifacts/$run.log"
            echo "[gate:$run] FAILED (see $artifacts/$run.log)"
            exit 1
        fi
        echo "[gate:$run] PASSED"
    done
}

case "${1:-}" in
    config) compose config --quiet ;;
    build) build ;;
    up) up ;;
    health) health ;;
    assert-clean) assert_clean ;;
    reset-targets) reset_targets ;;
    gate-once) shift; gate_once "$@" ;;
    gate-twice) shift; gate_twice "$@" ;;
    down) compose down --remove-orphans ;;
    *) echo "usage: $0 {config|build|up|health|assert-clean|reset-targets|gate-once NAME|gate-twice DIR|down}" >&2; exit 64 ;;
esac
