#!/usr/bin/env bash
# Idempotent gap-fill for the reused redamon-kali-sandbox image. Installs the
# recon tools it lacks into a persisted volume (/opt/localbin) + the venv, so
# recreation never recompiles.
# Best-effort by design (I1): a failed gap-fill step must NOT abort this script,
# because the compose entrypoint is `postrun.sh && mcp_server.py` — aborting here
# would take down the whole exec server (incl. tools that need no gap-fill).
# No `set -e`; script always exits 0 (see end).
export PATH="/opt/localbin:/root/go/bin:/opt/venv/bin:/usr/local/go/bin:$PATH"
mkdir -p /opt/localbin /resolvers

/opt/venv/bin/pip show fastmcp >/dev/null 2>&1 || /opt/venv/bin/pip install --no-cache-dir 'fastmcp<3'

command -v whois >/dev/null 2>&1 || { apt-get update -qq && apt-get install -y -qq --no-install-recommends whois; }

if ! command -v graphql-cop >/dev/null 2>&1; then
  if [ ! -d /opt/graphql-cop ]; then
    git clone --depth 1 https://github.com/dolevf/graphql-cop.git /opt/graphql-cop
    [ -f /opt/graphql-cop/requirements.txt ] && \
      /opt/venv/bin/pip install --no-cache-dir -r /opt/graphql-cop/requirements.txt 2>/dev/null || true
  fi
  # Find and wrap the main entry point
  GC_MAIN=""
  for _p in /opt/graphql-cop/graphql_cop/graphql_cop.py /opt/graphql-cop/graphql_cop.py; do
    [ -f "$_p" ] && GC_MAIN="$_p" && break
  done
  if [ -z "$GC_MAIN" ]; then
    GC_MAIN=$(find /opt/graphql-cop -name "*.py" -maxdepth 2 | head -1)
  fi
  printf '#!/usr/bin/env bash\nexec /opt/venv/bin/python "%s" "$@"\n' "$GC_MAIN" > /opt/localbin/graphql-cop
  chmod +x /opt/localbin/graphql-cop
fi

if [ ! -x /opt/localbin/massdns ]; then
  rm -rf /tmp/massdns && git clone --depth 1 https://github.com/blechschmidt/massdns.git /tmp/massdns
  make -C /tmp/massdns && cp /tmp/massdns/bin/massdns /opt/localbin/
fi

[ -x /opt/localbin/puredns ] || GOBIN=/opt/localbin go install github.com/d3mondev/puredns/v2@latest

if [ ! -x /opt/localbin/kr ]; then
  _ARCH=$(uname -m)
  case "$_ARCH" in
    aarch64|arm64) _KR_ARCH="linux_arm64" ;;
    *) _KR_ARCH="linux_amd64" ;;
  esac
  curl -sL "https://github.com/assetnote/kiterunner/releases/download/v1.0.2/kiterunner_1.0.2_${_KR_ARCH}.tar.gz" \
    | tar xz -C /opt/localbin kr
fi
[ -f /opt/localbin/routes-small.kite ] || curl -sL https://wordlists-cdn.assetnote.io/data/kiterunner/routes-small.kite.tar.gz \
  | tar xz -C /opt/localbin

[ -f /resolvers/resolvers.txt ] || curl -sL https://raw.githubusercontent.com/trickest/resolvers/main/resolvers.txt -o /resolvers/resolvers.txt

# OpenVPN + iproute2, for targets reachable only over a VPN. iproute2 is
# REQUIRED, not optional: OpenVPN configures the tun interface via `ip`, and this
# Kali base ships without it, so a bare `openvpn` install (esp. with
# --no-install-recommends) connects then dies at "Linux ip addr add failed". The
# guard requires BOTH. Install only - the connection is a separate, backgrounded
# step (a foreground openvpn here would block mcp_server.py, since the entrypoint
# is `postrun.sh && mcp_server.py`). Idempotent + root-native, matching whois.
command -v openvpn >/dev/null 2>&1 && command -v ip >/dev/null 2>&1 || { apt-get update -qq && apt-get install -y -qq --no-install-recommends openvpn iproute2; }

# Self-heal the TUN device node in case the host device is not mapped in: the
# container keeps the default CAP_MKNOD, and NET_ADMIN (granted in compose) lets
# OpenVPN configure the interface. No-op when compose already mapped /dev/net/tun.
if [ ! -c /dev/net/tun ]; then
  mkdir -p /dev/net && mknod /dev/net/tun c 10 200 && chmod 600 /dev/net/tun
fi

echo "[postrun] gap-fill complete"
exit 0
