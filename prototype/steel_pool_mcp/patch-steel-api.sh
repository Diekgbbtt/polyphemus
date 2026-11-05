#!/bin/sh
# Local prototype patch for the Steel API image.
#
# 1. The API root CDP proxy must rewrite the Host header.
#    Chrome rejects the container hostname on its DevTools endpoint.
# 2. The 9223 CDP proxy must send Host: localhost for the same reason.
#
# This patch is a local experiment. The production fix belongs in the Steel
# API image or a pinned image that carries the same behaviour.
set -e

CDP=/app/api/build/services/cdp/cdp.service.js
NGINX=/app/api/nginx.conf

if [ -f "$CDP" ] && ! grep -q "changeOrigin: true" "$CDP"; then
  sed -i 's/^            target: this.wsEndpoint,$/            target: this.wsEndpoint,\n            changeOrigin: true,/' "$CDP"
fi

if [ -f "$NGINX" ] && grep -q 'proxy_set_header Host \$host;' "$NGINX"; then
  sed -i 's/proxy_set_header Host \$host;/proxy_set_header Host localhost;/' "$NGINX"
fi

exec /usr/bin/tini -- /app/api/entrypoint.sh
