#!/usr/bin/env bash
# Idempotent gap-fill for the reused redamon-kali-sandbox image. Installs the
# recon tools it lacks into a persisted volume (/opt/localbin) + the venv, so
# recreation never recompiles.
set -e
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

echo "[postrun] gap-fill complete"
