"""Pure parsers: subdomain-discovery tool stdout -> list[AssetDelta].

- `parse_subfinder`: subfinder `-json -silent` emits one JSON object per
  line with a `host` key (`entry.get('host', '')`).
- `parse_amass`: targets the documented `amass enum -json` line shape
  (`name`, `domain`, `addresses: [{"ip": ...}, ...]`), which is OWASP
  Amass's standard structured-output format.

Both functions are pure, deterministic, and tolerate malformed lines
(`json.JSONDecodeError` -> skip) and missing optional keys.

Edge model has no `props` field (see `polymerhus.recon.domain.types.Edge`), so the
`record_type` of a DNS resolution (e.g. "A") cannot be attached to the
`RESOLVES_TO` edge. Only a plain `RESOLVES_TO` edge + `IP` delta is
emitted here; `record_type` capture is deferred to the dnsx/puredns
parser (Task 2), whose target schema puts `record_type` on a `DNSRecord`
node instead.
"""
from polymerhus.recon.domain.parsers._jsonlines import iter_json_dicts, safe_str
from polymerhus.recon.domain.parsers._urls import registrable_domain as _parent_domain
from polymerhus.recon.domain.types import AssetDelta, Edge


def parse_subfinder(stdout: str) -> list[AssetDelta]:
    deltas: list[AssetDelta] = []

    for entry in iter_json_dicts(stdout):
        host = safe_str(entry.get("host"))
        host = host.strip().lower() if host else ""
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

    for entry in iter_json_dicts(stdout):
        name = safe_str(entry.get("name"))
        name = name.strip().lower() if name else ""
        if not name:
            continue

        domain = safe_str(entry.get("domain"))
        domain = domain.strip().lower() if domain else ""
        domain = domain or _parent_domain(name)

        edges = [
            Edge(
                rel="BELONGS_TO",
                dir="out",
                node_type="Domain",
                node_identity={"name": domain},
            )
        ]

        addresses = entry.get("addresses") or []
        if not isinstance(addresses, list):
            addresses = []
        ips: list[str] = []
        for addr in addresses:
            if not isinstance(addr, dict):
                continue
            ip = safe_str(addr.get("ip"))
            ip = ip.strip() if ip else ""
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
