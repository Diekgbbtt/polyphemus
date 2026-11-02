#!/usr/bin/env bash
# Operation family: the authenticated-context oracle - ask one URL whether the
# loaded browser session is authenticated.
#
# Contract (#223 amendment, 2026-10-29):
#   - 2xx with no followed redirect -> authenticated
#   - 401, 403, or any 3xx          -> unauthenticated
#   - anything else                 -> indeterminate (never a pass)
#
# The request runs in the live page, so it carries the session cookies. Run
# it from a page on the probe's origin: a cross-origin fetch without CORS is
# indeterminate, never a pass. A navigation envelope hides a followed 302 (it
# reports success and the final 200 URL); the fetch's `redirected` flag
# exposes it.
#
# Usage:
#   SESSION=<live-name> bash auth-oracle.sh <probe-url>
#   bash auth-oracle.sh --session <live-name> <probe-url>
#
# The probe URL is usually the absolute URL read from `overview.auth_probe`
# (the store keeps a deployment-neutral path; the app resolves it).
# This script never starts or stops a session: the operator owns the name.
# Runnable verbatim through steel_exec(script=<text>, script_lang="sh") or
# `bash <file>`.
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
set -euo pipefail

SESSION="${SESSION:-}"
if [ "${1:-}" = "--session" ]; then
  SESSION="${2:-}"
  shift 2
fi
URL="${1:-${URL:-}}"
if [ -z "$SESSION" ] || [ -z "$URL" ]; then
  echo "usage: SESSION=<live-name> bash auth-oracle.sh <probe-url>" >&2
  exit 2
fi

# Build the JS with a JSON-quoted URL: a quote or backslash in the URL cannot
# break out of the fetch call.
JS=$(python3 -c '
import json, sys
url = sys.argv[1]
print(
    "(async()=>{try{const r=await fetch(" + json.dumps(url) + ","
    "{redirect:\"follow\",credentials:\"include\",cache:\"no-store\"});"
    "return {status:r.status,redirected:r.redirected,url:r.url};}"
    "catch(e){return {error:String(e)};}})()"
)
' "$URL")

EVAL_JSON=$(steel browser eval "$JS" --session "$SESSION" --json)
printf '%s' "$EVAL_JSON" | python3 -c '
import json, sys

probe = sys.argv[1]
try:
    envelope = json.load(sys.stdin)
except Exception:
    print(json.dumps({"outcome": "indeterminate", "probe": probe,
                      "reason": "unparseable eval envelope", "success": False}))
    raise SystemExit(0)
data = envelope.get("data") if isinstance(envelope, dict) else None
if not isinstance(data, dict):
    print(json.dumps({"outcome": "indeterminate", "probe": probe,
                      "reason": "eval returned no response object",
                      "success": False}))
    raise SystemExit(0)
if data.get("error"):
    print(json.dumps({"outcome": "indeterminate", "probe": probe,
                      "reason": str(data.get("error")), "success": False}))
    raise SystemExit(0)
status = data.get("status")
redirected = bool(data.get("redirected"))
if redirected or (isinstance(status, int) and 300 <= status <= 399):
    outcome = "unauthenticated"
elif isinstance(status, int) and 200 <= status <= 299:
    outcome = "authenticated"
elif status in (401, 403):
    outcome = "unauthenticated"
else:
    outcome = "indeterminate"
print(json.dumps({
    "outcome": outcome,
    "probe": probe,
    "status": status,
    "redirected": redirected,
    "final_url": data.get("url"),
    "success": outcome == "authenticated",
}))
' "$URL"
