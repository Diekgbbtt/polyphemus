"""Pure parser: subdomain-takeover scanner stdout -> two separate outputs.

Layers a Subjack + Nuclei + BadDNS pipeline. Subjack's own JSON output (the
primary, DNS-first layer) is an array of `Result` rows:

    {"subdomain": "old.example.com", "vulnerable": true,
     "service": "aws/s3", "cname": "dangling-bucket.s3.amazonaws.com"}

`vulnerable: true` means the row is a confirmed takeover candidate;
`vulnerable: false` rows are exhaustive noise (every scanned subdomain gets a
row) and are filtered out entirely - they never reach either output. The
`cname` field carries the dangling CNAME target when one was observed (empty
or absent when the candidacy came from a non-CNAME check, e.g. NS/SPF/MX).

Some emitters (subzy, nuclei-takeover-style wrappers) emit newline-delimited
JSON instead of a JSON array; both shapes are accepted (`_load_rows` tries a
JSON-array parse first, then falls back to JSONL).

Design constraint (plan §5): subdomain-takeover results are Observations, not
Vulnerability/graph nodes. Observations are owned by the pod's triager step,
not by parsers (parsers only emit `AssetDelta`s). So this module exposes TWO
functions with a deliberate split of responsibility, mirroring
`graphql_parser.py`:

  - `parse(stdout) -> list[AssetDelta]`: the graph-asset side. Emits ONLY
    what's confirmable as a graph asset - when a vulnerable row carries a
    dangling CNAME target, that target is an `ExternalDomain (domain)` with
    an inbound `HAS_EXTERNAL_DOMAIN` edge from the `Domain (name)` that is
    the registrable parent of the vulnerable subdomain (so the graph records
    "this org's DNS points at an external domain that may be unclaimed").
    Vulnerable rows with no CNAME target (NS/SPF/MX-style candidacy) yield no
    asset - there's nothing external to anchor. This is the function
    registered in `PARSERS["subdomain_takeover"]`.
  - `parse_findings(stdout) -> list[dict]`: the finding side. Returns one
    `{title: "potential_subdomain_takeover", severity, evidence, anchor}`
    dict per vulnerable row, anchored to the `Subdomain` itself (not the
    external domain - the takeover risk lives on the org's own subdomain),
    for the pod's triager to turn into `Observation`s. NOT registered in
    `PARSERS` - the triager calls this directly.

Pure, deterministic, tolerant of malformed JSON / non-list / non-dict /
non-string entries - never raises.
"""
import json

from agent.recon.parsers._urls import registrable_domain as _parent_domain
from agent.recon.types import AssetDelta, Edge


def _load_rows(stdout: str) -> list[dict]:
    stripped = stdout.strip()
    if not stripped:
        return []

    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        data = None

    if isinstance(data, list):
        return [entry for entry in data if isinstance(entry, dict)]

    if data is not None:
        # Valid JSON but not a list (e.g. `{}`, `null`, a bare dict) - not
        # a recognized shape.
        return []

    # Fall back to JSONL: one JSON object per non-blank line.
    rows: list[dict] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict):
            rows.append(entry)
    return rows


def _vulnerable_rows(stdout: str) -> list[dict]:
    rows = _load_rows(stdout)
    vulnerable: list[dict] = []

    for row in rows:
        if row.get("vulnerable") is not True:
            continue

        subdomain = row.get("subdomain")
        if not isinstance(subdomain, str) or not subdomain.strip():
            continue

        vulnerable.append(row)

    return vulnerable


def parse(stdout: str) -> list[AssetDelta]:
    deltas: list[AssetDelta] = []

    for row in _vulnerable_rows(stdout):
        subdomain = row["subdomain"].strip().lower()

        cname = row.get("cname")
        if not isinstance(cname, str) or not cname.strip():
            continue

        external_domain = cname.strip().lower()
        parent_domain = _parent_domain(subdomain)

        deltas.append(
            AssetDelta(
                type="ExternalDomain",
                identity={"domain": external_domain},
                edges=[
                    Edge(
                        rel="HAS_EXTERNAL_DOMAIN",
                        dir="in",
                        node_type="Domain",
                        node_identity={"name": parent_domain},
                    )
                ],
            )
        )

    return deltas


def parse_findings(stdout: str) -> list[dict]:
    findings: list[dict] = []

    for row in _vulnerable_rows(stdout):
        subdomain = row["subdomain"].strip().lower()

        service = row.get("service")
        service = service.strip() if isinstance(service, str) else ""

        cname = row.get("cname")
        cname = cname.strip() if isinstance(cname, str) else ""

        evidence = f"Potential takeover: {service or 'unknown service'}"
        if cname:
            evidence += f" (CNAME -> {cname})"

        severity = row.get("severity")
        if not isinstance(severity, str) or not severity:
            severity = "high"

        findings.append(
            {
                "title": "potential_subdomain_takeover",
                "severity": severity,
                "evidence": evidence,
                "anchor": {"type": "Subdomain", "identity": {"name": subdomain}},
            }
        )

    return findings
