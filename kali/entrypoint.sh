#!/usr/bin/env bash
# #196 Kali entrypoint: idempotent bootstrap, colocated mitmdump, readiness,
# MCP server, and a shutdown trap that tears the proxy down with the container.
#
# The proxy is passive: it records completed flows and transport errors, never
# mutates traffic. Capture failure must never take the exec server down, so the
# proxy is best-effort and the MCP server is always started.
set -u

export PATH="/opt/localbin:/root/go/bin:/opt/venv/bin:/usr/local/go/bin:${PATH}"
export PYTHONPATH="/opt:${PYTHONPATH:-}"

STORE_ROOT="${KALI_HTTP_HISTORY_ROOT:-/data}"
PROXY_HOST="${KALI_HTTP_PROXY_HOST:-127.0.0.1}"
PROXY_PORT="${KALI_HTTP_PROXY_PORT:-8080}"
CAPTURE_ENABLED="${KALI_HTTP_CAPTURE_ENABLED:-true}"
MITM_CONFDIR="${KALI_HTTP_MITM_CONFDIR:-$STORE_ROOT/mitmproxy}"
MITMDUMP_BIN="${KALI_HTTP_MITMDUMP_BIN:-/opt/mitmproxy-env/bin/mitmdump}"
MITMDUMP_LISTEN_HOST="${KALI_HTTP_MITMDUMP_LISTEN_HOST:-0.0.0.0}"
MITM_LOG="${KALI_HTTP_MITM_LOG:-/var/log/kali-mitmdump.log}"
MCP_BIN="${KALI_HTTP_MCP_BIN:-/opt/venv/bin/python}"
EDGE_TOKEN="${KALI_HTTP_HISTORY_EDGE_TOKEN:-}"
EDGE_HOST="${KALI_HTTP_HISTORY_EDGE_HOST:-0.0.0.0}"
EDGE_PORT="${KALI_HTTP_HISTORY_EDGE_PORT:-8002}"
EDGE_LOG="${KALI_HTTP_HISTORY_EDGE_LOG:-/var/log/kali-http-edge.log}"
# Browser pool (#359, W6). The feature is off unless the operator forwards the
# pool Docker socket into the container; the exec plane never depends on it.
BROWSER_STORE="${STEEL_SESSION_STORE:-/var/lib/steel/sessions}"
BROWSER_RUN_DIR="${KALI_BROWSER_MCP_RUN_DIR:-/run/steel-pool}"
BROWSER_PORT="${STEEL_MCP_PORT:-8003}"
BROWSER_LOG="${KALI_BROWSER_MCP_LOG:-/var/log/kali-browser-mcp.log}"
BROWSER_SOCKET_WAIT_S="${KALI_BROWSER_MCP_SOCKET_WAIT_S:-300}"
BROWSER_READY_WAIT_S="${KALI_BROWSER_MCP_READY_WAIT_S:-30}"

mkdir -p "$STORE_ROOT" /run/kali-http "$MITM_CONFDIR" "$BROWSER_RUN_DIR" 2>/dev/null || true
chmod 700 "$STORE_ROOT" /run/kali-http "$BROWSER_RUN_DIR" 2>/dev/null || true

PROXY_PID=""
MCP_PID=""
EDGE_PID=""
BROWSER_PID=""
FORWARD_PID=""

shutdown() {
  trap - EXIT TERM INT
  [ -n "$BROWSER_PID" ] && kill "$BROWSER_PID" 2>/dev/null || true
  [ -n "$FORWARD_PID" ] && kill "$FORWARD_PID" 2>/dev/null || true
  [ -n "$MCP_PID" ] && kill "$MCP_PID" 2>/dev/null || true
  [ -n "$EDGE_PID" ] && kill "$EDGE_PID" 2>/dev/null || true
  [ -n "$PROXY_PID" ] && kill "$PROXY_PID" 2>/dev/null || true
  wait 2>/dev/null || true
  exit 0
}
trap shutdown EXIT TERM INT

# 1) gap-fill + CA + namespace/NAT bootstrap. Best-effort by design (postrun.sh
#    never aborts), so a routing hiccup cannot stop the exec server.
bash /opt/kali/postrun.sh || true

case "$(printf '%s' "$CAPTURE_ENABLED" | tr '[:upper:]' '[:lower:]')" in
  0|false|no|off)
    echo "[entrypoint] capture explicitly disabled; mitmdump not started"
    ;;
  *)
    if [ -x "$MITMDUMP_BIN" ]; then
      # Upstream verification: mitmproxy trusts its own CA source (certifi), NOT
      # the system store, so an operator CA (self-signed lab target) is only
      # honoured if it rides the bundle postrun.sh builds. Absent one, nothing
      # changes: the proxy verifies against its default store.
      MITM_TLS_ARGS=()
      UPSTREAM_BUNDLE="$MITM_CONFDIR/upstream-ca-bundle.pem"
      # Opt-in, tied to the knob: the bundle lives on the volume, so without
      # this guard a trust decision would survive an operator removing
      # KALI_HTTP_UPSTREAM_CA - and silently keep trusting that CA.
      if [ -n "${KALI_HTTP_UPSTREAM_CA:-}" ] && [ -f "$UPSTREAM_BUNDLE" ]; then
        MITM_TLS_ARGS=(--set "ssl_verify_upstream_trusted_ca=$UPSTREAM_BUNDLE")
      fi
      "$MITMDUMP_BIN" \
        --mode transparent \
        --listen-host "$MITMDUMP_LISTEN_HOST" --listen-port "$PROXY_PORT" \
        --set "confdir=$MITM_CONFDIR" \
        --set block_global=false \
        "${MITM_TLS_ARGS[@]}" \
        -s /opt/kali/http_history/addon_entry.py \
        >"$MITM_LOG" 2>&1 &
      PROXY_PID="$!"
      # readiness: the proxy port must accept before we serve the MCP surface
      for _ in $(seq 1 60); do
        if (exec 3<>"/dev/tcp/$PROXY_HOST/$PROXY_PORT") 2>/dev/null; then
          exec 3>&- 2>/dev/null || true
          echo "[entrypoint] mitmdump ready on $PROXY_HOST:$PROXY_PORT (pid $PROXY_PID)"
          break
        fi
        sleep 0.5
      done
      # the CA exists only after mitmdump's first run - install it now, and
      # re-run the idempotent bootstrap so the namespace/NAT rules are current.
      bash /opt/kali/postrun.sh || true
    else
      echo "[entrypoint] mitmdump not found at $MITMDUMP_BIN; capture degraded"
    fi
    ;;
esac

# 2) HTTP-history ingest edge. A separate process, never an MCP tool. It is
#    enabled only when the shared bearer token is set; the crawler reaches it
#    on the compose network and never through the MCP surface.
if [ -n "$EDGE_TOKEN" ]; then
  KALI_HTTP_HISTORY_EDGE_TOKEN="$EDGE_TOKEN" \
    KALI_HTTP_HISTORY_EDGE_HOST="$EDGE_HOST" \
    KALI_HTTP_HISTORY_EDGE_PORT="$EDGE_PORT" \
    "$MCP_BIN" /opt/kali/http_history/edge.py >"$EDGE_LOG" 2>&1 &
  EDGE_PID="$!"
  EDGE_READY=0
  for _ in $(seq 1 30); do
    if (exec 3<>"/dev/tcp/127.0.0.1/$EDGE_PORT") 2>/dev/null; then
      exec 3>&- 2>/dev/null || true
      echo "[entrypoint] HTTP-history edge ready on $EDGE_HOST:$EDGE_PORT (pid $EDGE_PID)"
      EDGE_READY=1
      break
    fi
    sleep 0.2
  done
  if [ "$EDGE_READY" -ne 1 ]; then
    # A token means the edge is expected. A silent failure here would turn
    # every crawl flush into a partial run with no visible cause.
    echo "[entrypoint] HTTP-history edge FAILED to start on $EDGE_HOST:$EDGE_PORT (pid $EDGE_PID); see $EDGE_LOG" >&2
  fi
else
  echo "[entrypoint] KALI_HTTP_HISTORY_EDGE_TOKEN unset; HTTP-history edge not started"
fi

# 3a) The worker-port relay. The pool manager derives `localhost:<port>`
#     worker URLs by design. When the operator's SSH forward lands on the
#     Docker host rather than inside this container, the relay restores that
#     contract on both loopback families; it never rewrites the Host header.
start_browser_forwards() {
  if [ -z "${STEEL_POOL_FORWARD_PORTS:-}" ]; then
    echo "[entrypoint] STEEL_POOL_FORWARD_PORTS is unset; worker relays not started"
    return 0
  fi
  "$MCP_BIN" /opt/kali/steel_pool/forward.py >>"$BROWSER_LOG" 2>&1 &
  FORWARD_PID="$!"
  ports=$(printf '%s' "$STEEL_POOL_FORWARD_PORTS" | tr ',' ' ')
  for port in $ports; do
    bound=0
    for _ in $(seq 1 40); do
      if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
        exec 3>&- 2>/dev/null || true
        bound=1
        break
      fi
      if ! kill -0 "$FORWARD_PID" 2>/dev/null; then
        echo "[entrypoint] worker relay exited during startup; see $BROWSER_LOG" >&2
        FORWARD_PID=""
        return 0
      fi
      sleep 0.25
    done
    if [ "$bound" -ne 1 ]; then
      echo "[entrypoint] worker relay did not open 127.0.0.1:$port within 10s" >&2
      return 0
    fi
  done
  echo "[entrypoint] worker relay ready on 127.0.0.1 ports: $ports (pid $FORWARD_PID)"
  return 0
}

# 3) The browser pool MCP (#359, W6). It is optional: the pool manager has no
#    SSH logic, so without the operator's forwarded Docker socket it cannot
#    discover a worker. A browser-plane failure is logged and never stops the
#    exec server, which is the container's primary lane.
start_browser_mcp() {
  if [ -z "${STEEL_POOL_DOCKER_SOCKET:-}" ]; then
    echo "[entrypoint] STEEL_POOL_DOCKER_SOCKET is unset; browser MCP not started"
    return 0
  fi
  # The store refuses a root that is not owner-only, so fix the volume mode
  # before the process validates it.
  if ! mkdir -p "$BROWSER_STORE" 2>/dev/null || ! chmod 700 "$BROWSER_STORE" 2>/dev/null; then
    echo "[entrypoint] session store $BROWSER_STORE is not usable; browser MCP not started" >&2
    return 0
  fi
  # The operator's tunnel may land after the container, so wait for its socket
  # instead of failing the feature on a start-order race.
  for _ in $(seq 1 "$BROWSER_SOCKET_WAIT_S"); do
    [ -S "$STEEL_POOL_DOCKER_SOCKET" ] && break
    sleep 1
  done
  if [ ! -S "$STEEL_POOL_DOCKER_SOCKET" ]; then
    echo "[entrypoint] Docker socket $STEEL_POOL_DOCKER_SOCKET is absent after ${BROWSER_SOCKET_WAIT_S}s; browser MCP not started" >&2
    return 0
  fi
  "$MCP_BIN" /opt/kali/browser_mcp_server.py >>"$BROWSER_LOG" 2>&1 &
  BROWSER_PID="$!"
  for _ in $(seq 1 "$((BROWSER_READY_WAIT_S * 2))"); do
    if (exec 3<>"/dev/tcp/127.0.0.1/$BROWSER_PORT") 2>/dev/null; then
      exec 3>&- 2>/dev/null || true
      echo "[entrypoint] browser MCP ready on 127.0.0.1:$BROWSER_PORT (pid $BROWSER_PID)"
      return 0
    fi
    if ! kill -0 "$BROWSER_PID" 2>/dev/null; then
      echo "[entrypoint] browser MCP exited during startup; see $BROWSER_LOG" >&2
      BROWSER_PID=""
      return 0
    fi
    sleep 0.5
  done
  echo "[entrypoint] browser MCP did not open 127.0.0.1:$BROWSER_PORT within ${BROWSER_READY_WAIT_S}s; see $BROWSER_LOG" >&2
  return 0
}

# 4) Exec MCP server. Runs in the foreground lane; the trap owns teardown.
"$MCP_BIN" /opt/kali/mcp_server.py &
MCP_PID="$!"
start_browser_forwards
start_browser_mcp
wait "$MCP_PID"
