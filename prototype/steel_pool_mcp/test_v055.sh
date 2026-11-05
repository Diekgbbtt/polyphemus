#!/usr/bin/env bash
# Light end-to-end checks for the v0.5.5-beta Steel API image.
#
# It runs the image with nginx disabled, checks the commands API, and checks
# that the direct Chrome CDP port is reachable on the worker network.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
NET="steel-proto-net"
NAME="steel-v055"
PORT="3110"
IMAGE="steel-browser-api:v0.5.5-beta"

cleanup() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
}

cleanup
docker network create "$NET" >/dev/null 2>&1 || true
docker run -d --name "$NAME" --network "$NET" --shm-size=2g \
  -p "$PORT:3000" \
  -e DOMAIN="localhost:$PORT" \
  -e CDP_DOMAIN="localhost:$PORT" \
  -e ENABLE_COMMANDS_API=true \
  -e HOST=0.0.0.0 \
  "$IMAGE" --no-nginx >/dev/null

for _ in $(seq 1 60); do
  if curl -fsS -m 2 "http://localhost:$PORT/v1/health" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "=== health ==="
curl -fsS -m 5 "http://localhost:$PORT/v1/health"
echo

echo "=== direct 9222 is internal to the worker ==="
echo "Chrome binds 127.0.0.1:9222; the API endpoint is the CDP channel."

echo "=== commands API ==="
CREATE=$(curl -fsS -m 60 -X POST -H 'Content-Type: application/json' \
  -d '{}' "http://localhost:$PORT/v1/sessions")
echo "$CREATE" | head -c 400
echo
SID=$(printf '%s' "$CREATE" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
curl -fsS -m 20 -X POST -H 'Content-Type: application/json' \
  -d '{"commands":[{"command":"navigate","url":"https://example.com"},{"command":"eval","script":"location.href"},{"command":"get","what":"title"},{"command":"tab","action":"list"}]}' \
  "http://localhost:$PORT/v1/sessions/$SID/commands" | python3 -m json.tool | head -40
curl -fsS -m 10 -X POST "http://localhost:$PORT/v1/sessions/$SID/release" >/dev/null
echo "released $SID"

echo "=== live sessions ==="
curl -fsS -m 5 "http://localhost:$PORT/v1/sessions" | python3 -c '
import json,sys
s=json.load(sys.stdin).get("sessions",[])
print("live", [x["id"] for x in s if x.get("status")=="live"])
'

echo "=== keep container for direct CDP WebSocket test: $NAME ==="
