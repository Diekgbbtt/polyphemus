#!/usr/bin/env bash
# Idempotent gap-fill for the Kali exec-node image (Dockerfile.kali). Installs
# the volume-persisted tools (massdns/puredns/kr/graphql-cop/...) into
# /opt/localbin + the venv, so recreation never recompiles.
# Best-effort by design (I1): a failed gap-fill step must NOT abort this script,
# because the compose entrypoint is `postrun.sh && mcp_server.py` — aborting here
# would take down the whole exec server (incl. tools that need no gap-fill).
# No `set -e`; script always exits 0 (see end).
export PATH="/opt/localbin:/root/go/bin:/opt/venv/bin:/usr/local/go/bin:$PATH"
mkdir -p /opt/localbin /resolvers

/opt/venv/bin/pip show fastmcp >/dev/null 2>&1 || /opt/venv/bin/pip install --no-cache-dir 'fastmcp<3'

command -v whois >/dev/null 2>&1 || { apt-get update -qq && apt-get install -y -qq --no-install-recommends whois; }
command -v iptables >/dev/null 2>&1 || { apt-get update -qq && apt-get install -y -qq --no-install-recommends iptables; }

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

# OpenVPN + iproute2, for targets reachable only over a VPN (e.g. a lab/CTF host
# on a tun route). iproute2 is REQUIRED, not optional: OpenVPN configures the
# tun interface via `ip`, and this Kali base ships without it, so a bare
# `openvpn` install (esp. with --no-install-recommends) connects then dies at
# "Linux ip addr add failed". The guard therefore requires BOTH binaries.
# Install only - the connection is a separate, credentialed step (feed a .ovpn
# profile and start `openvpn --daemon --config ...` in the BACKGROUND; a
# foreground openvpn here would block mcp_server.py, since the entrypoint is
# `postrun.sh && mcp_server.py`). Idempotent + root-native, matching whois above.
command -v openvpn >/dev/null 2>&1 && command -v ip >/dev/null 2>&1 || { apt-get update -qq && apt-get install -y -qq --no-install-recommends openvpn iproute2; }

# Self-heal the TUN device node in case the host device is not mapped in: the
# container keeps the default CAP_MKNOD, and NET_ADMIN (granted in compose) lets
# OpenVPN configure the interface. No-op when compose already mapped /dev/net/tun.
if [ ! -c /dev/net/tun ]; then
  mkdir -p /dev/net && mknod /dev/net/tun c 10 200 && chmod 600 /dev/net/tun
fi

# --- #196 HTTP-history bootstrap (idempotent, best-effort) ---------------------
# Owns CA trust, the namespace/veth pool prerequisites and the transparent
# routing/NAT rules. Every step is a no-op when already applied; every step is
# best-effort so a routing hiccup can never abort the exec server (I1).
if command -v ip >/dev/null 2>&1; then
  mkdir -p /run/netns /run/kali-http
  chmod 700 /run/kali-http 2>/dev/null || true
  sysctl -q -w net.ipv4.ip_forward=1 >/dev/null 2>&1 || true
fi

# Install mitmproxy's generated CA into the system trust store so interceptable
# HTTPS clients from leased namespaces validate. Idempotent: install +
# update-ca-certificates converge on the same file set.
MITM_CONFDIR="${KALI_HTTP_MITM_CONFDIR:-${KALI_HTTP_HISTORY_ROOT:-/data}/mitmproxy}"
MITM_CA="${MITM_CONFDIR}/mitmproxy-ca-cert.pem"
if [ -f "$MITM_CA" ]; then
  install -m 0644 "$MITM_CA" /usr/local/share/ca-certificates/mitmproxy-ca.crt 2>/dev/null || true
  command -v update-ca-certificates >/dev/null 2>&1 && update-ca-certificates >/dev/null 2>&1 || true
fi

# Leased namespaces (172.30.0.0/24) egress through the root namespace, whose
# VPN/Docker routes stay authoritative. HTTP/3 is explicitly NOT captured:
# QUIC (UDP/443) from a leased namespace is rejected and disclosed as a
# limitation rather than silently downgraded.
if command -v iptables >/dev/null 2>&1; then
  iptables -t nat -C POSTROUTING -s 172.30.0.0/24 -j MASQUERADE 2>/dev/null || \
    iptables -t nat -A POSTROUTING -s 172.30.0.0/24 -j MASQUERADE 2>/dev/null || true
  iptables -C FORWARD -s 172.30.0.0/24 -p udp --dport 443 -j REJECT 2>/dev/null || \
    iptables -A FORWARD -s 172.30.0.0/24 -p udp --dport 443 -j REJECT 2>/dev/null || true
fi

# --- Non-interactive login shells must stay silent ---------------------------
# Defense in depth for the exec runner's PATH fix (`default_runner` now uses
# `bash -c`, a NON-login shell, so the login profile no longer resets PATH -
# see kali/http_history/service.py). Any remaining login shell (an operator
# running `bash -lc` by hand, a future runner) still sources
# /etc/profile.d/zz-redamon-motd.sh from the redamon base image, which prints
# "⚡ redagraph - tenant-scoped graph CLI" on stdout even without a TTY and
# lands in front of every tool's output, polluting the parsers' input. The
# guard returns early when PS1 is unset, i.e. for any non-interactive shell.
# Idempotent (marker check) and best-effort like everything else here: a
# read-only /etc must never abort the composite entrypoint (I1).
MOTD=/etc/profile.d/zz-redamon-motd.sh
if [ -f "$MOTD" ] && ! grep -q POLYPHEMUS_NONINTERACTIVE_GUARD "$MOTD" 2>/dev/null; then
  sed -i '1i [ -z "$PS1" ] && return 0  # POLYPHEMUS_NONINTERACTIVE_GUARD' "$MOTD" 2>/dev/null || true
fi

echo "[postrun] gap-fill complete"
echo "[postrun] http-history bootstrap complete (idempotent)"
exit 0
