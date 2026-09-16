#!/usr/bin/env bash
# Operation family: bounded spidering - enumerate a page's links, then fetch and
# parse a small same-host slice. The set is capped in the JS projection AND in
# the resolver, so the flow can never fan out unbounded from one seed.
# Runnable verbatim through steel_exec(script=<text>, script_lang="sh") or `bash <file>`.
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
set -euo pipefail

FLOW="spider"
URL="${URL:-https://quotes.toscrape.com}"
LIMIT="${LIMIT:-3}"
SESSION="${SESSION:-polymerhus-${FLOW}-$(date +%s)}"
STARTED=0

release() {
  if [ "$STARTED" = 1 ]; then
    steel browser stop --session "$SESSION" --json >/dev/null 2>&1 || true
  fi
}
trap release EXIT INT TERM

if steel browser live --session "$SESSION" --json >/dev/null 2>&1; then
  echo "refused: $SESSION is already used" >&2
  exit 3
fi

START_JSON=$(steel browser start --session "$SESSION" --session-timeout 600000 --json)
STARTED=1
printf '%s' "$START_JSON" | python3 -c \
  'import json,sys; d=json.load(sys.stdin)["data"]; print("started", d["name"])'

steel browser navigate "$URL" --wait-until domcontentloaded --session "$SESSION" --json >/dev/null

# Enumerate a bounded, de-duplicated slice inside the page; never return the
# full anchor list into context.
LINKS_JSON=$(steel browser eval \
  "JSON.stringify(Array.from(new Set(Array.from(document.querySelectorAll('a[href]')).map(a => a.getAttribute('href')))).slice(0, ${LIMIT}))" \
  --session "$SESSION" --json)

# Resolve relative hrefs against the seed and keep the same host; stdout carries
# only URLs, the count goes to stderr, so the loop below sees links alone.
printf '%s' "$LINKS_JSON" | python3 -c '
import json,sys,urllib.parse
base=sys.argv[1]
host=urllib.parse.urlparse(base).netloc
hrefs=json.loads(json.loads(sys.stdin.read())["data"])
urls=[u for u in (urllib.parse.urljoin(base,h) for h in hrefs)
      if urllib.parse.urlparse(u).netloc == host]
sys.stderr.write("candidate links: %d\n" % len(urls))
for u in urls:
    print(u)
' "$URL" | while IFS= read -r link; do
  TITLE_JSON=$(steel browser navigate "$link" --wait-until domcontentloaded --session "$SESSION" --json)
  printf '%s' "$TITLE_JSON" | python3 -c '
import json,sys
d=json.load(sys.stdin)["data"]
print("  visited", d["url"], "|", d["title"])
'
done

echo "spider complete (limit $LIMIT); the trap releases $SESSION on exit"
