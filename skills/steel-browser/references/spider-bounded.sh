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
SESSION_NAMED=0

release() {
  # Fires on success, error, and signal alike. The mark is set before `start`
  # (past the catalogue guard), so a signal inside the start window still gets a
  # named stop; a name never created is a harmless no-op, and the explicit stop
  # below clears the mark so the trap no-ops on the happy path.
  if [ "$SESSION_NAMED" = 1 ]; then
    steel browser stop --session "$SESSION" --json >/dev/null 2>&1 || true
  fi
}
trap release EXIT INT TERM

# Catalogue guard (D13 amended).
# This read is also the pre-call baseline: a `default` seen here is foreign and
# never addressed by this run.
if steel browser sessions --json 2>/dev/null | python3 -c '
import json,sys
try:
    names={s.get("name") for s in (json.load(sys.stdin).get("data") or []) if isinstance(s, dict)}
except Exception:
    sys.exit(1)  # cannot verify -> treat as free, never block the start
sys.exit(0 if sys.argv[1] in names else 1)
' "$SESSION"; then
  echo "refused: $SESSION is already live" >&2
  exit 3
fi

SESSION_NAMED=1
START_JSON=$(steel browser start --session "$SESSION" --session-timeout 600000 --json)
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

# Explicit stop, then prove the name is gone; the trap is the backstop.
steel browser stop --session "$SESSION" --json >/dev/null
SESSION_NAMED=0
steel browser sessions --json | python3 -c '
import json,sys
names={s.get("name") for s in (json.load(sys.stdin).get("data") or []) if isinstance(s, dict)}
print("released:", sys.argv[1] not in names)
' "$SESSION"

echo "spider complete (limit $LIMIT)"
