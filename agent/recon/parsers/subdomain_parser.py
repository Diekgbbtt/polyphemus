"""Pure parsers: subdomain-discovery tool stdout -> list[AssetDelta].

Ported from Redamon's `main_recon_modules/domain_recon.py::run_subfinder`
and `run_amass`. Only the field-mapping logic is kept; all Docker/
execution/accumulator code was dropped.

- `parse_subfinder`: subfinder `-json -silent` emits one JSON object per
  line with a `host` key (`entry.get('host', '')`).
- `parse_amass`: Redamon's own `run_amass` shells out to `amass enum`
  *without* `-json` and regex-scrapes the plain-text `... (FQDN) --> ...`
  output. That shape carries no structured `addresses`, so it cannot
  satisfy this task's target schema (Subdomain + resolved IP/RESOLVES_TO).
  This parser instead targets the documented `amass enum -json` line
  shape (`name`, `domain`, `addresses: [{"ip": ...}, ...]`), which is
  OWASP Amass's standard structured-output format. Noted as a documented
  deviation from the literal Redamon source, not a guess.

Both functions are pure, deterministic, and tolerate malformed lines
(`json.JSONDecodeError` -> skip) and missing optional keys.

Edge model has no `props` field (see `agent.recon.types.Edge`), so the
`record_type` of a DNS resolution (e.g. "A") cannot be attached to the
`RESOLVES_TO` edge. Only a plain `RESOLVES_TO` edge + `IP` delta is
emitted here; `record_type` capture is deferred to the dnsx/puredns
parser (Task 2), whose target schema puts `record_type` on a `DNSRecord`
node instead.
"""
import json

from agent.recon.types import AssetDelta, Edge


def _parent_domain(host: str) -> str:
    labels = host.split(".")
    if len(labels) <= 2:
        return host
    return ".".join(labels[-2:])


def parse_subfinder(stdout: str) -> list[AssetDelta]:
    deltas: list[AssetDelta] = []

    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue

        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        host = (entry.get("host") or "").strip().lower()
        if not host:
            continue

        deltas.append(
            AssetDelta(
                type="Subdomain",
                identity={"name": host},
                edges=[
                    Edge(
                        rel="BELONGS_TO",
                        dir="out",
                        node_type="Domain",
                        node_identity={"name": _parent_domain(host)},
                    )
                ],
            )
        )

    return deltas


def parse_amass(stdout: str) -> list[AssetDelta]:
    deltas: list[AssetDelta] = []

    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue

        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        name = (entry.get("name") or "").strip().lower()
        if not name:
            continue

        domain = (entry.get("domain") or "").strip().lower() or _parent_domain(name)

        edges = [
            Edge(
                rel="BELONGS_TO",
                dir="out",
                node_type="Domain",
                node_identity={"name": domain},
            )
        ]

        addresses = entry.get("addresses") or []
        ips: list[str] = []
        for addr in addresses:
            ip = (addr.get("ip") or "").strip()
            if not ip:
                continue
            ips.append(ip)
            edges.append(
                Edge(
                    rel="RESOLVES_TO",
                    dir="out",
                    node_type="IP",
                    node_identity={"address": ip},
                )
            )

        deltas.append(
            AssetDelta(
                type="Subdomain",
                identity={"name": name},
                edges=edges,
            )
        )

        for ip in ips:
            deltas.append(
                AssetDelta(
                    type="IP",
                    identity={"address": ip},
                )
            )

    return deltas
