#!/usr/bin/env bash
# Operation family: eval-driven interaction - submit one form end to end from JS.
# Each value is set with the events the page listens for (input/change), then the
# control's own behaviour is invoked on a chosen route (click | dispatch |
# requestsubmit | framework). Native constraint validation still gates the
# submit: an empty required field fires `invalid` and no navigation.
#
# Quoting discipline: the value-bearing payload is JSON-encoded by python and
# passed as a runtime variable in double quotes, so the shell never re-expands
# its contents; the value-free route payload is a single-quoted literal, so the
# shell cannot expand it at all. A mangled payload still returns success:true
# with a wrong result, so the reads below are the proof, not the envelope.
#
# Values arrive through the environment and are never hard-coded; a missing
# value is a loud refusal. Output is bounded to lengths, booleans, and counts -
# the password is never echoed, and no value-bearing command string is printed.
# One machine-parseable line is emitted on every path:
#   SUMMARY logged_in=true|false reason=<token>
# Runnable verbatim through steel_exec(script=<text>, script_lang="sh") or `bash <file>`.
# Usage: [URL=<login-url>] [ROUTE=click|dispatch|requestsubmit|framework]
#        FORM_USERNAME=<user> FORM_PASSWORD=<secret> bash eval-interact.sh
# FORM_USERNAME/FORM_PASSWORD are deliberately not USERNAME/PASSWORD: those
# standard shell variables are already exported and would silently shadow the input.
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
set -euo pipefail

FLOW="evalinteract"
URL="${URL:-https://the-internet.herokuapp.com/login}"
FORM_USERNAME="${FORM_USERNAME:-}"
FORM_PASSWORD="${FORM_PASSWORD:-}"
ROUTE="${ROUTE:-click}"
SESSION="${SESSION:-polymerhus-${FLOW}-$(date +%s)}"
SESSION_NAMED=0
LOGGED="false"
REASON="unset"

if [ -z "$FORM_USERNAME" ] || [ -z "$FORM_PASSWORD" ]; then
  echo "refused: export FORM_USERNAME and FORM_PASSWORD (values pass through the environment, never a file)" >&2
  exit 2
fi

# The chosen submit route, each invoking the control's own behaviour. click and
# requestsubmit honour submit handlers and native validation; dispatch does too.
# `framework` is the last resort: a jQuery trigger("submit") bypasses validation
# the way form.submit() does. The payloads carry no values, so they are
# single-quoted literals.
case "$ROUTE" in
  click)
    ROUTE_JS='(() => { const b=document.querySelector("#login button[type=submit]") || document.querySelector("button[type=submit]"); if (!b) return {found:false}; b.click(); return {found:true, route:"click"}; })()'
    ;;
  dispatch)
    ROUTE_JS='(() => { const b=document.querySelector("#login button[type=submit]") || document.querySelector("button[type=submit]"); if (!b) return {found:false}; const o={bubbles:true,cancelable:true,view:window,button:0}; for (const t of ["mousedown","mouseup","click"]) b.dispatchEvent(new MouseEvent(t,o)); return {found:true, route:"dispatch"}; })()'
    ;;
  requestsubmit)
    ROUTE_JS='(() => { const f=document.querySelector("#login") || document.querySelector("form"); if (!f) return {found:false}; f.requestSubmit(); return {found:true, route:"requestsubmit"}; })()'
    ;;
  framework)
    ROUTE_JS='(() => { const f=document.querySelector("#login") || document.querySelector("form"); if (!f) return {found:false}; if (typeof window.jQuery === "function") { window.jQuery(f).trigger("submit"); return {found:true, route:"jquery"}; } f.dispatchEvent(new Event("submit",{bubbles:true,cancelable:true})); return {found:true, route:"submit-event"}; })()'
    ;;
  *)
    echo "refused: ROUTE must be click|dispatch|requestsubmit|framework" >&2
    exit 2
    ;;
esac

finish() {
  # The single summary line, then the trap-owned stop. SESSION_NAMED is set
  # before `start` (past the catalogue guard), so a signal inside the start
  # window still gets a named stop; the refusal path leaves it down, so a
  # stranger's live name is never addressed.
  echo "SUMMARY logged_in=${LOGGED} reason=${REASON}"
  if [ "$SESSION_NAMED" = 1 ]; then
    steel browser stop --session "$SESSION" --json >/dev/null 2>&1 || true
  fi
}
trap finish EXIT INT TERM

# Catalogue guard (D13 amended): cannot verify -> treat the name as free.
if steel browser sessions --json 2>/dev/null | python3 -c '
import json,sys
try:
    names={s.get("name") for s in (json.load(sys.stdin).get("data") or []) if isinstance(s, dict)}
except Exception:
    sys.exit(1)
sys.exit(0 if sys.argv[1] in names else 1)
' "$SESSION"; then
  REASON="session-name-taken"
  exit 3
fi

SESSION_NAMED=1
START_JSON=$(steel browser start --session "$SESSION" --session-timeout 600000 --json)
printf '%s' "$START_JSON" | python3 -c \
  'import json,sys; d=json.load(sys.stdin)["data"]; print("started", d["name"], "remainingMs", d.get("remainingMs"))'

if ! steel browser navigate "$URL" --wait-until domcontentloaded --session "$SESSION" --json >/dev/null; then
  REASON="navigate-failed"
  exit 5
fi
# Inner clock 15000 ms, well below the 600000 ms session budget.
steel browser wait --load-state networkidle --timeout 15000 --session "$SESSION" --json >/dev/null 2>&1 || true

# Set both values with the events the page listens for. python JSON-encodes the
# runtime values, so a quote, `$`, or backtick in a secret cannot break out of
# the JS string; the result reports lengths and validity only, never a value.
SET_JS=$(python3 - "$FORM_USERNAME" "$FORM_PASSWORD" <<'PY'
import json,sys
u,p=json.dumps(sys.argv[1]),json.dumps(sys.argv[2])
print('(() => {'
      ' const set=(s,v)=>{const el=document.querySelector(s); if(!el) return -1;'
      ' const d=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,"value");'
      ' d.set.call(el,v);'
      ' for (const t of ["input","change","blur","keyup"]) el.dispatchEvent(new Event(t,{bubbles:true}));'
      ' return el.value.length;};'
      ' const ul=set("#username",%s), pl=set("#password",%s);'
      ' const ue=document.querySelector("#username"), pe=document.querySelector("#password");'
      ' return {u_len:ul, p_len:pl, u_valid: !!(ue && ue.checkValidity()), p_valid: !!(pe && pe.checkValidity())};'
      '})()' % (u,p))
PY
)
if ! steel browser eval "$SET_JS" --session "$SESSION" --json | python3 -c '
import json,sys
try:
    data=json.load(sys.stdin).get("data") or {}
except Exception:
    sys.exit(2)
ok=isinstance(data,dict) and data.get("u_len",0)>0 and data.get("p_len",0)>0 and data.get("u_valid") and data.get("p_valid")
print("values set:", ok, "| valid:", bool(data.get("u_valid")), bool(data.get("p_valid")))
sys.exit(0 if ok else 1)
'; then
  REASON="values-not-set-or-invalid"
  exit 6
fi

# The chosen route: a value-free, single-quoted payload.
steel browser eval "$ROUTE_JS" --session "$SESSION" --json | python3 -c '
import json,sys
try:
    data=json.load(sys.stdin).get("data") or {}
except Exception:
    sys.exit(2)
print("route", data.get("route"), "| found:", data.get("found"))
sys.exit(0 if isinstance(data,dict) and data.get("found") else 1)
' || { REASON="route-not-found"; exit 7; }

# Synchronise on the verdict's own signal: a load-state wait can observe
# networkidle before the click-triggered navigation has begun, so it would race
# straight through. The verdict is a UI signal read as a COUNT, never
# `is visible` (which reads only the first matching node) and never a cookie name.
steel browser wait --selector 'a[href="/logout"]' --timeout 15000 --session "$SESSION" --json >/dev/null 2>&1 || true
URL_NOW=$(steel browser get url --session "$SESSION" --json 2>/dev/null \
  | python3 -c 'import json,sys; print(json.load(sys.stdin).get("data",""))' 2>/dev/null || true)
LOGOUTS=$(steel browser get count 'a[href="/logout"]' --session "$SESSION" --json 2>/dev/null \
  | python3 -c 'import json,sys; d=json.load(sys.stdin).get("data") or {}; print(d.get("count",0) if isinstance(d,dict) else 0)' 2>/dev/null || true)
case "$URL_NOW" in
  *"/secure"*) URL_OK=true ;;
  *) URL_OK=false ;;
esac
if [ "$URL_OK" = true ] && [ "${LOGOUTS:-0}" -ge 1 ]; then
  LOGGED=true; REASON="url-secure-and-logout-link"
elif [ "$URL_OK" = true ]; then
  REASON="url-secure-no-logout-link"
else
  REASON="still-on-login-url"
fi

# Explicit stop so this run prints its own clean-catalogue proof; the trap stays
# armed as the backstop and no-ops because SESSION_NAMED is cleared.
steel browser stop --session "$SESSION" --json >/dev/null 2>&1 || true
SESSION_NAMED=0
steel browser sessions --json | python3 -c '
import json,sys
names={s.get("name") for s in (json.load(sys.stdin).get("data") or []) if isinstance(s, dict)}
print("released:", sys.argv[1] not in names)
' "$SESSION"

# REASON already carries the verdict; the EXIT trap prints it as the SUMMARY.
exit 0
