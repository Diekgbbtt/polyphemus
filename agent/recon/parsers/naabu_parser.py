"""Pure parser: naabu `-json` stdout -> list[AssetDelta].

Naabu emits one JSON object per line, one per (host, ip, port) tuple:
    {"host":"example.com","ip":"93.184.216.34","port":443}

`get_service_name` is a minimal IANA/friendly service-name lookup covering
the common ports called out by the task brief. Unknown ports resolve to
"unknown".

Pure, deterministic, tolerant of malformed/missing-key lines - never raises.
"""
from agent.recon.parsers._jsonlines import iter_json_dicts, safe_str
from agent.recon.types import AssetDelta, Edge

# Minimal common-port -> service-name map (IANA/friendly lookup).
# Unknown ports default to "unknown".
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

    for entry in iter_json_dicts(stdout):
        ip = safe_str(entry.get("ip"))
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
