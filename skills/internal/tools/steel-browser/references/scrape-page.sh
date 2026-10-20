#!/usr/bin/env bash
# Operation family: one-shot scraping via `steel scrape` - no session, so there
# is no lifecycle to guard (the scrape opens its own throwaway browser).
# Runnable verbatim through steel_exec(script=<text>, script_lang="sh") or `bash <file>`.
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
set -euo pipefail

URL="${URL:-https://example.com}"

# One-shot: --json gives the {content, links, metadata} envelope; the read
# below is bounded to a slice.
RAW=$(steel scrape "$URL" --format markdown --json)
printf '%s' "$RAW" | python3 -c '
import json,sys
d=json.load(sys.stdin)["data"]
md=d["content"]["markdown"]
links=d.get("links",[])
print("scraped", d["metadata"]["urlSource"], "| title:", d["metadata"]["title"])
print("markdown chars:", len(md), "| links:", len(links))
print("markdown head:", " ".join(md.split())[:240])
print("first links:", ",".join(l["url"] for l in links[:3]))
'

echo "scrape complete (no session opened)"
