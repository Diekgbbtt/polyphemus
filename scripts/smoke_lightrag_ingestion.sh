#!/usr/bin/env sh
set -eu

ENV_FILE="${ENV_FILE:-.env}"
COMPOSE="docker compose --env-file ${ENV_FILE} --profile lightrag"
STAMP="$(date +%Y%m%d%H%M%S)"
NAME="smoke-${STAMP}.md"
DUP_NAME="smoke-${STAMP}-duplicate.md"
SOURCE_KEY="file:inbox/${NAME}"
DUP_SOURCE_KEY="file:inbox/${DUP_NAME}"

mkdir -p data/ingestion/inbox data/ingestion/processed data/ingestion/failed

cat > "data/ingestion/inbox/${NAME}" <<'EOF'
# Polyphemus Smoke Ingestion

This Markdown document verifies watched-folder ingestion.

```http
GET /smoke HTTP/1.1
Host: example.test
```

The content mentions SQL injection payload methodology and authentication bypass.
EOF
printf '\nSmoke run id: %s\n' "$STAMP" >> "data/ingestion/inbox/${NAME}"

poll_status() {
  key="$1"
  expected="$2"
  attempts=36
  while [ "$attempts" -gt 0 ]; do
    status="$($COMPOSE exec -T postgres psql -U polymerhus -d polymerhus -Atc "select j.status from ingestion_jobs j where j.source_key = '${key}' order by j.created_at desc limit 1;" || true)"
    if [ "$status" = "$expected" ]; then
      return 0
    fi
    echo "waiting for ${key}: expected=${expected} current=${status:-missing}"
    sleep 5
    attempts=$((attempts - 1))
  done
  echo "Timed out waiting for ${key} to reach ${expected}; last status=${status:-missing}" >&2
  return 1
}

wait_for_file() {
  path="$1"
  attempts=12
  while [ "$attempts" -gt 0 ]; do
    if [ -f "$path" ]; then
      return 0
    fi
    echo "waiting for file: ${path}"
    sleep 5
    attempts=$((attempts - 1))
  done
  echo "Timed out waiting for file ${path}" >&2
  return 1
}

poll_status "$SOURCE_KEY" "PROCESSED"
wait_for_file "data/ingestion/processed/${NAME}"

cp "data/ingestion/processed/${NAME}" "data/ingestion/inbox/${DUP_NAME}"
poll_status "$DUP_SOURCE_KEY" "SKIPPED_DUPLICATE"
wait_for_file "data/ingestion/processed/${DUP_NAME}"

echo "smoke ok: ${SOURCE_KEY} processed and ${DUP_SOURCE_KEY} skipped duplicate"
