"""Pure parsers: DNS-resolution tool stdout -> list[AssetDelta].

Ported from Redamon's `main_recon_modules/domain_recon.py::dns_lookup` /
`resolve_all_dns` (record-type set: `DNS_RECORD_TYPES = ['A', 'AAAA', 'MX',
'NS', 'TXT', 'SOA', 'CNAME']`) and `run_puredns_resolve`. Only the
field-mapping logic is kept; all Docker/execution/accumulator/threading
code was dropped.

- `parse_dnsx`: Redamon itself resolves DNS via Python's `dns.resolver`,
  not the `dnsx` CLI, so there is no Redamon `-json` line to port
  directly. This parser instead targets the documented `dnsx -json`
  output shape (ProjectDiscovery's dnsx, ``-a -aaaa -cname -mx -ns -txt
  -soa -json``): one JSON object per line with a `host` key and one key
  per requested record type (`a`, `aaaa`, `cname`, `mx`, `ns`, `txt`,
  `soa`), each holding a list of record values. This mirrors Redamon's
  own `DNS_RECORD_TYPES` set, so the record-type mapping ported here
  (A/AAAA -> IP + RESOLVES_TO, all types -> DNSRecord + HAS_DNS_RECORD)
  is a faithful port of `dns_lookup`'s per-record-type structure onto
  dnsx's real wire format. Noted as a documented deviation from a
  literal Redamon source line range, not a guess.

- `parse_puredns`: Redamon's `run_puredns_resolve` invokes `puredns
  resolve <input> --write <output>` and reads the output file as plain
  resolved hostnames, one per line (no JSON, no address data) -
  `[line.strip() for line in f if line.strip()]`. This parser ports that
  exact shape: successful resolution only confirms the hostname has DNS
  records, so each emitted `Subdomain` is marked `has_dns_records=True`
  with no `DNSRecord`/`IP` deltas (puredns' output carries no record
  type or value).

Edge model has no `props` field (see `agent.recon.types.Edge`), so the
DNS record type cannot live on the `RESOLVES_TO`/`HAS_DNS_RECORD` edges
directly; it lives on the `DNSRecord` node's identity `type` field
instead, per design §10.3.

Both functions are pure, deterministic, and tolerate malformed lines
and missing optional keys.
"""
import json

from agent.recon.types import AssetDelta, Edge

# Record types resolved to an address (emit IP + RESOLVES_TO).
_ADDRESS_RECORD_TYPES = ("a", "aaaa")

# Full DNS record-type set ported from Redamon's DNS_RECORD_TYPES, in
# stable iteration order for deterministic delta emission.
_RECORD_TYPE_KEYS = ("a", "aaaa", "mx", "ns", "txt", "soa", "cname")


def parse_dnsx(stdout: str) -> list[AssetDelta]:
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

        edges: list[Edge] = []
        ips: list[str] = []
        records: list[tuple[str, str]] = []

        for key in _RECORD_TYPE_KEYS:
            values = entry.get(key) or []
            record_type = key.upper()
            for value in values:
                value = (value or "").strip() if isinstance(value, str) else value
                if not value:
                    continue

                records.append((record_type, value))
                edges.append(
                    Edge(
                        rel="HAS_DNS_RECORD",
                        dir="out",
                        node_type="DNSRecord",
                        node_identity={"type": record_type, "value": value, "subdomain": host},
                    )
                )

                if key in _ADDRESS_RECORD_TYPES:
                    ips.append(value)
                    edges.append(
                        Edge(
                            rel="RESOLVES_TO",
                            dir="out",
                            node_type="IP",
                            node_identity={"address": value},
                        )
                    )

        if not records:
            continue

        deltas.append(
            AssetDelta(
                type="Subdomain",
                identity={"name": host},
                props={"has_dns_records": True},
                edges=edges,
            )
        )

        for record_type, value in records:
            deltas.append(
                AssetDelta(
                    type="DNSRecord",
                    identity={"type": record_type, "value": value, "subdomain": host},
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


def parse_puredns(stdout: str) -> list[AssetDelta]:
    deltas: list[AssetDelta] = []

    for line in stdout.splitlines():
        host = line.strip().lower()
        if not host:
            continue
        if " " in host or "\t" in host:
            # Not a bare hostname (unexpected/malformed puredns output line).
            continue

        deltas.append(
            AssetDelta(
                type="Subdomain",
                identity={"name": host},
                props={"has_dns_records": True},
            )
        )

    return deltas
