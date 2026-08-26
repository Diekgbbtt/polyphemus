#!/usr/bin/env sh
set -eu

ENV_FILE="${ENV_FILE:-.env}"
COMPOSE="docker compose --env-file ${ENV_FILE} --profile lightrag"
STAMP="$(date +%Y%m%d%H%M%S)"
NAME="update-smoke-${STAMP}.md"
SOURCE_KEY="file:inbox/${NAME}"

mkdir -p lightrag/data/ingestion/inbox lightrag/data/ingestion/processed lightrag/data/ingestion/failed

write_version() {
  version="$1"
  marker="$2"
  cat > "lightrag/data/ingestion/inbox/${NAME}" <<EOF
# Polyphemus Update Smoke ${version}

This Markdown document verifies safe replacement of an already indexed source.

\`\`\`http
GET /update-smoke/${marker} HTTP/1.1
Host: example.test
\`\`\`

The unique update marker is ${marker}.
EOF
}

query_pg() {
  sql="$1"
  $COMPOSE exec -T postgres psql -U polymerhus -d polymerhus -Atc "$sql"
}

poll_processed_with_hash_change() {
  previous_hash="$1"
  attempts=48
  while [ "$attempts" -gt 0 ]; do
    row="$(query_pg "select j.status || '|' || coalesce(s.content_hash, '') || '|' || coalesce(s.lightrag_document_id, '') from ingestion_jobs j join ingestion_sources s on s.source_key=j.source_key where j.source_key='${SOURCE_KEY}' order by j.created_at desc limit 1;" || true)"
    status="$(printf '%s' "$row" | cut -d'|' -f1)"
    content_hash="$(printf '%s' "$row" | cut -d'|' -f2)"
    if [ "$status" = "PROCESSED" ] && [ -n "$content_hash" ] && [ "$content_hash" != "$previous_hash" ]; then
      printf '%s\n' "$row"
      return 0
    fi
    echo "waiting for update: expected PROCESSED with changed hash, current=${row:-missing}"
    sleep 5
    attempts=$((attempts - 1))
  done
  echo "Timed out waiting for ${SOURCE_KEY} update; last=${row:-missing}" >&2
  return 1
}

poll_status() {
  expected="$1"
  attempts=48
  while [ "$attempts" -gt 0 ]; do
    row="$(query_pg "select j.status || '|' || coalesce(s.content_hash, '') || '|' || coalesce(s.lightrag_document_id, '') from ingestion_jobs j join ingestion_sources s on s.source_key=j.source_key where j.source_key='${SOURCE_KEY}' order by j.created_at desc limit 1;" || true)"
    status="$(printf '%s' "$row" | cut -d'|' -f1)"
    if [ "$status" = "$expected" ]; then
      printf '%s\n' "$row"
      return 0
    fi
    echo "waiting for ${SOURCE_KEY}: expected=${expected} current=${row:-missing}"
    sleep 5
    attempts=$((attempts - 1))
  done
  echo "Timed out waiting for ${SOURCE_KEY} to reach ${expected}; last=${row:-missing}" >&2
  return 1
}

wait_for_processed_file() {
  attempts=12
  while [ "$attempts" -gt 0 ]; do
    if [ -f "lightrag/data/ingestion/processed/${NAME}" ]; then
      return 0
    fi
    echo "waiting for processed file: lightrag/data/ingestion/processed/${NAME}"
    sleep 5
    attempts=$((attempts - 1))
  done
  echo "Timed out waiting for processed file lightrag/data/ingestion/processed/${NAME}" >&2
  return 1
}

write_version "v1" "first-${STAMP}"
first_row="$(poll_status "PROCESSED")"
wait_for_processed_file
first_hash="$(printf '%s' "$first_row" | cut -d'|' -f2)"

write_version "v2" "second-${STAMP}"
second_row="$(poll_processed_with_hash_change "$first_hash")"
wait_for_processed_file
second_hash="$(printf '%s' "$second_row" | cut -d'|' -f2)"

echo "update smoke ok: ${SOURCE_KEY} hash ${first_hash} -> ${second_hash}"
