#!/usr/bin/env bash
# Operation family: the survey read - live sessions, bounded.
# No session is opened, so there is no lifecycle to guard.
# Runnable verbatim through steel_exec(script=<text>, script_lang="sh") or `bash <file>`.
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
set -euo pipefail

# The catalogue is the reliable live list (name, mode, status), visible across
# processes and workdirs. Viewer URLs are withheld: they are session bearers.
steel browser sessions --json | python3 -c '
import json,sys
data=json.load(sys.stdin).get("data") or []
print("live sessions:", len(data))
for s in data:
    print("  -", s.get("name"), "| mode", s.get("mode"), "| status", s.get("status"))
'
