"""Pure parser: naabu `-json` stdout -> list[AssetDelta].

Ported from Redamon's `main_recon_modules/port_scan.py::parse_naabu_output`.
Only the field-mapping logic is kept; the by_host/by_ip aggregation,
AI-annotation and file-IO code was dropped in favour of a flat delta list.

Naabu emits one JSON object per line, one per (host, ip, port) tuple:
    {"host":"example.com","ip":"93.184.216.34","port":443}

`get_service_name` is a minimal, hand-ported subset of Redamon's
`helpers/iana_services.py::get_service_name_friendly` (which itself falls
back to a bundled IANA CSV); this subset covers the common ports called
out by the task brief. Unknown ports resolve to "unknown".

Pure, deterministic, tolerant of malformed/missing-key lines - never raises.
"""
import json

from agent.recon.types import AssetDelta, Edge

# Minimal common-port -> service-name map (subset of Redamon's IANA/friendly
# lookup). Unknown ports default to "unknown".
_SERVICE_NAMES: dict[int, str] = {
    21: "ftp",
    22: "ssh",
    23: "telnet",
    25: "smtp",
    53: "domain",
    80: "http",
    110: "pop3",
    143: "imap",
    443: "https",
    445: "microsoft-ds",
    993: "imaps",
    995: "pop3s",
    3306: "mysql",
    3389: "rdp",
    5432: "postgresql",
    5900: "vnc",
    6379: "redis",
    8080: "http-proxy",
    8443: "https-alt",
    27017: "mongodb",
}


def get_service_name(port: int) -> str:
    return _SERVICE_NAMES.get(port, "unknown")


def parse(stdout: str) -> list[AssetDelta]:
    deltas: list[AssetDelta] = []
    seen_ips: set[str] = set()
    seen_ports: set[tuple[int, str]] = set()

    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue

        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        ip = entry.get("ip")
        port = entry.get("port")
        if not ip or not port:
            continue

        if ip not in seen_ips:
            seen_ips.add(ip)
            version = "ipv6" if ":" in ip else "ipv4"
            deltas.append(
                AssetDelta(
                    type="IP",
                    identity={"address": ip},
                    props={"version": version},
                )
            )

        port_key = (port, ip)
        if port_key in seen_ports:
            continue
        seen_ports.add(port_key)

        port_identity = {"number": port, "protocol": "tcp", "ip_address": ip}
        deltas.append(
            AssetDelta(
                type="Port",
                identity=port_identity,
                props={"state": "open"},
                edges=[
                    Edge(
                        rel="HAS_PORT",
                        dir="in",
                        node_type="IP",
                        node_identity={"address": ip},
                    )
                ],
            )
        )

        service_name = get_service_name(port)
        deltas.append(
            AssetDelta(
                type="Service",
                identity={
                    "name": service_name,
                    "port_number": port,
                    "ip_address": ip,
                },
                edges=[
                    Edge(
                        rel="RUNS_SERVICE",
                        dir="in",
                        node_type="Port",
                        node_identity=port_identity,
                    )
                ],
            )
        )

    return deltas
