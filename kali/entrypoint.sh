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
# #238: the egress governor is a SEPARATE switch from capture, but both planes
# live in the SAME mitmdump process - so the proxy must come up when EITHER is
# on. Capture-off must never disarm an armed TrafficPolicy.
GOVERNOR_ENABLED="${KALI_HTTP_GOVERNOR_ENABLED:-true}"
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

PROXY_ENABLED=false
for _flag in "$CAPTURE_ENABLED" "$GOVERNOR_ENABLED"; do
  case "$(printf '%s' "$_flag" | tr '[:upper:]' '[:lower:]')" in
    0|false|no|off) ;;
    *) PROXY_ENABLED=true ;;
  esac
done

if [ "$PROXY_ENABLED" = "true" ]; then
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
        -s "${KALI_HTTP_ADDON_ENTRY:-/opt/kali/http_history/addon_entry.py}" \
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
      echo "[entrypoint] mitmdump not found at $MITMDUMP_BIN; capture/governance degraded"
    fi
else
  echo "[entrypoint] capture and governance explicitly disabled; mitmdump not started"
fi

# 2) MCP server. Runs in the foreground lane; the trap owns teardown.
"$MCP_BIN" /opt/kali/mcp_server.py &
MCP_PID="$!"
wait "$MCP_PID"
