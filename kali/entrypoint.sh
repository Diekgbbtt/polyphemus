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

mkdir -p "$STORE_ROOT" /run/kali-http "$MITM_CONFDIR" 2>/dev/null || true
chmod 700 "$STORE_ROOT" /run/kali-http 2>/dev/null || true

PROXY_PID=""
MCP_PID=""

shutdown() {
  trap - EXIT TERM INT
  [ -n "$MCP_PID" ] && kill "$MCP_PID" 2>/dev/null || true
  [ -n "$PROXY_PID" ] && kill "$PROXY_PID" 2>/dev/null || true
  wait 2>/dev/null || true
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
      if [ -f "$UPSTREAM_BUNDLE" ]; then
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

# 2) MCP server. Runs in the foreground lane; the trap owns teardown.
"$MCP_BIN" /opt/kali/mcp_server.py &
MCP_PID="$!"
wait "$MCP_PID"
