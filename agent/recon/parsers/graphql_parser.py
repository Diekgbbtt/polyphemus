"""Pure parser: `graphql-cop -o json` stdout -> two separate outputs.

Ported from Redamon's `recon/graphql_scan/misconfig.py::run_graphql_cop` /
`_normalize_findings`, which wraps the `dolevf/graphql-cop` CLI. graphql-cop
emits a JSON array of per-check result rows:

    [{"title": "Introspection", "description": "...", "severity"/"impact": "MEDIUM",
      "result": true, "curl_verify": "curl -X POST https://host/graphql ...", ...}, ...]

`result: true` means the check FAILED (misconfiguration present); `result:
false` means the server passed that check.

Design constraint (plan §5): GraphQL misconfigurations are Observations, not
Vulnerability/graph nodes. Observations are owned by the pod's triager step,
not by parsers (parsers only emit `AssetDelta`s). So this module exposes TWO
functions with a deliberate split of responsibility:

  - `parse(stdout) -> list[AssetDelta]`: the graph-asset side. Emits ONLY the
    GraphQL endpoint itself - a `BaseURL` + an `Endpoint` (method="POST",
    endpoint_type="graphql") with an inbound `HAS_ENDPOINT` edge - so the
    graph knows a GraphQL surface exists. This is the function registered in
    `PARSERS["graphql-cop"]`.
  - `parse_findings(stdout) -> list[dict]`: the finding side. Returns one
    normalized `{title, severity, evidence}` dict per FAILED check
    (`result: true`), for the pod's triager to turn into `Observation`s.
    NOT registered in `PARSERS` - the triager calls this directly.

graphql-cop's JSON output does not include a dedicated "target url" field;
the tested endpoint is only recoverable from the `curl_verify` field's
embedded URL (best-effort, first http(s) URL found in that string). If no
check row yields a URL, `parse` returns an empty list - graphql-cop's own
plain output offers no fallback (no target arg is passed to this parser to
keep the `parse(stdout)` signature uniform with every other parser in this
registry).

Pure, deterministic, tolerant of malformed JSON / non-list / non-dict
entries - never raises.
"""
import json
import re

from agent.recon.parsers._urls import url_to_deltas
from agent.recon.types import AssetDelta

_URL_RE = re.compile(r"https?://[^\s'\"]+")


def _load_checks(stdout: str) -> list:
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return []

    if not isinstance(data, list):
        return []

    return [entry for entry in data if isinstance(entry, dict)]


def _derive_endpoint_url(checks: list) -> str | None:
    for check in checks:
        curl_verify = check.get("curl_verify")
        if not isinstance(curl_verify, str):
            continue

        match = _URL_RE.search(curl_verify)
        if match:
            return match.group(0)

    return None


def parse(stdout: str) -> list[AssetDelta]:
    checks = _load_checks(stdout)
    if not checks:
        return []

    endpoint_url = _derive_endpoint_url(checks)
    if not endpoint_url:
        return []

    # graphql-cop's `curl_verify` never carries a query string, but be
    # defensive and only keep the BaseURL+Endpoint deltas from the shared
    # helper - this parser has never emitted Parameter deltas.
    return url_to_deltas(
        endpoint_url,
        method="POST",
        source="graphql-cop",
        extra_endpoint_props={"endpoint_type": "graphql"},
    )[:2]


def parse_findings(stdout: str) -> list[dict]:
    checks = _load_checks(stdout)
    findings: list[dict] = []

    for check in checks:
        if check.get("result") is not True:
            continue

        title = check.get("title") or ""
        severity = check.get("severity") or check.get("impact") or "info"
        if not isinstance(severity, str) or not severity:
            severity = "info"

        evidence = check.get("curl_verify") or check.get("description") or ""

        findings.append(
            {
                "title": title,
                "severity": severity,
                "evidence": evidence,
            }
        )

    return findings
