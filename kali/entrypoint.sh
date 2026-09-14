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
DNS_RELAY_ADDRESS="${KALI_HTTP_DNS_SERVER:-169.254.169.253}"
DNS_LOG="${KALI_HTTP_DNS_LOG:-/var/log/kali-dnsmasq.log}"

mkdir -p "$STORE_ROOT" /run/kali-http "$MITM_CONFDIR" 2>/dev/null || true
chmod 700 "$STORE_ROOT" /run/kali-http 2>/dev/null || true

PROXY_PID=""
MCP_PID=""
DNS_PID=""

shutdown() {
  trap - EXIT TERM INT
  [ -n "$MCP_PID" ] && kill "$MCP_PID" 2>/dev/null || true
  [ -n "$PROXY_PID" ] && kill "$PROXY_PID" 2>/dev/null || true
  [ -n "$DNS_PID" ] && kill "$DNS_PID" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap shutdown EXIT TERM INT

# 1) gap-fill + CA + namespace/NAT bootstrap. Best-effort by design (postrun.sh
#    never aborts), so a routing hiccup cannot stop the exec server.
bash /opt/kali/postrun.sh || true

# A leased netns cannot reach Docker's loopback-bound 127.0.0.11 resolver.
# Relay DNS in the root namespace, where Docker/VPN resolution remains
# authoritative, and let /etc/netns/<lease>/resolv.conf point here.
DNS_UPSTREAM=$(awk '/^nameserver[[:space:]]/{print $2; exit}' /etc/resolv.conf 2>/dev/null)
if command -v dnsmasq >/dev/null 2>&1 && [ -n "$DNS_UPSTREAM" ]; then
  dnsmasq --keep-in-foreground --bind-interfaces \
    --listen-address="$DNS_RELAY_ADDRESS" \
    --no-hosts --no-resolv --server="$DNS_UPSTREAM" --cache-size=0 \
    >"$DNS_LOG" 2>&1 &
  DNS_PID="$!"
  sleep 0.2
  if kill -0 "$DNS_PID" 2>/dev/null; then
    echo "[entrypoint] DNS relay ready on $DNS_RELAY_ADDRESS:53 (pid $DNS_PID)"
  else
    echo "[entrypoint] DNS relay failed to start; namespace DNS degraded"
    DNS_PID=""
  fi
else
  echo "[entrypoint] dnsmasq/upstream resolver unavailable; namespace DNS degraded"
fi

case "$(printf '%s' "$CAPTURE_ENABLED" | tr '[:upper:]' '[:lower:]')" in
  0|false|no|off)
    echo "[entrypoint] capture explicitly disabled; mitmdump not started"
    ;;
  *)
    if [ -x "$MITMDUMP_BIN" ]; then
      "$MITMDUMP_BIN" \
        --mode transparent \
        --listen-host "$MITMDUMP_LISTEN_HOST" --listen-port "$PROXY_PORT" \
        --set "confdir=$MITM_CONFDIR" \
        --set block_global=false \
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
