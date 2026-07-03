"""Pure parser: httpx `-json` stdout -> list[AssetDelta].

Ported from Redamon's `main_recon_modules/http_probe.py::parse_httpx_output`.
Only the field-mapping logic is kept; all Docker/execution/AI-annotation
code was dropped. Deterministic, tolerant of malformed JSONL lines.
"""
from urllib.parse import urlparse

from agent.recon.parsers._jsonlines import iter_json_dicts
from agent.recon.types import AssetDelta, Edge


def _first(entry: dict, *keys):
    for key in keys:
        value = entry.get(key)
        if value is not None:
            return value
    return None


def parse(stdout: str) -> list[AssetDelta]:
    deltas: list[AssetDelta] = []

    for entry in iter_json_dicts(stdout):
        url = _first(entry, "url", "input")
        if not url or not isinstance(url, str):
            continue

        status_code = _first(entry, "status_code", "status-code")
        content_type = _first(entry, "content_type", "content-type")
        content_length = _first(entry, "content_length", "content-length")
        title = entry.get("title")
        server = _first(entry, "webserver", "server")
        final_url = _first(entry, "final_url", "url")
        scheme = entry.get("scheme")
        host = entry.get("host")

        deltas.append(
            AssetDelta(
                type="BaseURL",
                identity={"url": url},
                props={
                    "scheme": scheme,
                    "host": host,
                    "status_code": status_code,
                    "title": title,
                    "content_type": content_type,
                    "final_url": final_url,
                    "server": server,
                },
            )
        )

        path = urlparse(url).path or "/"
        deltas.append(
            AssetDelta(
                type="Endpoint",
                identity={"path": path, "method": "GET", "baseurl": url},
                props={
                    "status_code": status_code,
                    "content_type": content_type,
                    "content_length": content_length,
                    "title": title,
                    "server": server,
                    "source": "http_probe",
                },
                edges=[
                    Edge(
                        rel="HAS_ENDPOINT",
                        dir="in",
                        node_type="BaseURL",
                        node_identity={"url": url},
                    )
                ],
            )
        )

        techs = _first(entry, "tech", "technologies") or []
        if not isinstance(techs, list):
            techs = []
        for tech in techs:
            if not tech or not isinstance(tech, str):
                continue
            deltas.append(
                AssetDelta(
                    type="Technology",
                    identity={"name": tech, "version": ""},
                    edges=[
                        Edge(
                            rel="USES_TECHNOLOGY",
                            dir="in",
                            node_type="BaseURL",
                            node_identity={"url": url},
                        )
                    ],
                )
            )

        tls = entry.get("tls") or {}
        if not isinstance(tls, dict):
            tls = {}
        subject_cn = tls.get("subject_cn")
        if subject_cn and isinstance(subject_cn, str):
            issuer = _first(tls, "issuer_org", "issuer_dn", "issuer")
            san = _first(tls, "subject_an", "san") or []
            if not isinstance(san, list):
                san = []
            deltas.append(
                AssetDelta(
                    type="Certificate",
                    identity={"subject_cn": subject_cn},
                    props={
                        "issuer": issuer,
                        "san": san,
                        "not_before": tls.get("not_before"),
                        "not_after": tls.get("not_after"),
                    },
                    edges=[
                        Edge(
                            rel="HAS_CERTIFICATE",
                            dir="in",
                            node_type="BaseURL",
                            node_identity={"url": url},
                        )
                    ],
                )
            )

    return deltas
