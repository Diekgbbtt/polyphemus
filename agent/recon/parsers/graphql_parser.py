"""Pure parser: `graphql-cop -o json` stdout -> two separate outputs.

Wraps the `dolevf/graphql-cop` CLI. graphql-cop emits a JSON array of
per-check result rows:

    [{"title": "Introspection", "description": "...", "severity"/"impact": "MEDIUM",
      "result": true, "curl_verify": "curl -X POST https://host/graphql ...", ...}, ...]

`result: true` means the check FAILED (misconfiguration present); `result:
false` means the server passed that check.

Design constraint (plan §5): GraphQL misconfigurations are Observations, not
Vulnerability/graph nodes. Observations are owned by the pod's triager step,
not by parsers (parsers only emit `AssetDelta`s). So this module exposes TWO
functions with a deliberate split of responsibility:

  - `parse(stdout, *, target_url=None) -> list[AssetDelta]`: the graph-asset
    side. Emits ONLY the GraphQL endpoint itself - a `BaseURL` + an
    `Endpoint` (method="POST", endpoint_type="graphql") with an inbound
    `HAS_ENDPOINT` edge - so the graph knows a GraphQL surface exists. This
    is the function registered in `PARSERS["graphql-cop"]`.
  - `parse_findings(stdout, *, target_url=None) -> list[dict]`: the finding
    side. Returns one normalized `{title, severity, evidence, anchor?}` dict
    per FAILED check (`result: true`), for the pod's triager to turn into
    `Observation`s. NOT registered in `PARSERS` - the triager calls this
    directly. The finding `anchor` is a `BaseURL` (not `Endpoint`): Observation
    anchors must be broad graph elements per `curator.ANCHOR_ALLOWLIST`
    (Domain/Subdomain/BaseURL/IP/Service), which excludes `Endpoint` -
    anchoring findings to `Endpoint` made `build_observation_cypher` raise
    and every graphql-cop Observation was silently dropped by `curate`.

graphql-cop's JSON output does not include a dedicated "target url" field.
When the pod triager knows the job's target (the input asset's URL), it
passes it as `target_url` (SP2 F1) - this is deterministic and takes
priority over any regex derivation, for both `parse`'s Endpoint identity and
`parse_findings`'s `BaseURL` anchor. When `target_url` is not given (e.g. called
outside the pod, or in tests), both functions fall back to the best-effort
`curl_verify` regex derivation (first http(s) URL found in that field). If
no URL can be derived from either source, `parse` returns an empty list and
`parse_findings` omits the `anchor` key from each finding (which
`finding_to_observation` treats as "drop this finding").

Pure, deterministic, tolerant of malformed JSON / non-list / non-dict
entries - never raises.
"""
import json
import re

from agent.recon.parsers._urls import base_and_path, url_to_deltas
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


def parse(stdout: str, *, target_url: str | None = None) -> list[AssetDelta]:
    checks = _load_checks(stdout)
    if not checks:
        return []

    endpoint_url = target_url or _derive_endpoint_url(checks)
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


def _finding_anchor(checks: list, *, target_url: str | None) -> dict | None:
    """Build a BaseURL anchor (broad, in `curator.ANCHOR_ALLOWLIST`) for
    findings, from `target_url` when given, else fall back to the
    best-effort curl_verify regex derivation. Returns `None` when neither
    source yields an absolute URL."""
    url = target_url or _derive_endpoint_url(checks)
    if not url:
        return None

    split = base_and_path(url)
    if split is None:
        return None

    baseurl, _path = split
    return {"type": "BaseURL", "identity": {"url": baseurl}}


def parse_findings(stdout: str, *, target_url: str | None = None) -> list[dict]:
    checks = _load_checks(stdout)
    findings: list[dict] = []

    anchor = _finding_anchor(checks, target_url=target_url)

    for check in checks:
        if check.get("result") is not True:
            continue

        title = check.get("title") or ""
        severity = check.get("severity") or check.get("impact") or "info"
        if not isinstance(severity, str) or not severity:
            severity = "info"

        evidence = check.get("curl_verify") or check.get("description") or ""

        finding = {
            "title": title,
            "severity": severity,
            "evidence": evidence,
        }
        if anchor is not None:
            finding["anchor"] = anchor

        findings.append(finding)

    return findings
