"""Pure parser: httpx `-json` stdout -> list[AssetDelta].

Ported from Redamon's `main_recon_modules/http_probe.py::parse_httpx_output`.
Only the field-mapping logic is kept; all Docker/execution/AI-annotation
code was dropped. Deterministic, tolerant of malformed JSONL lines.
"""
from agent.recon.noise_filter import classify_profile
from agent.recon.parsers._jsonlines import iter_json_dicts
from agent.recon.parsers._urls import url_to_deltas
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

        # F2 fix: normalize BaseURL/Endpoint.baseurl to scheme://netloc via
        # the shared helper (was the raw probe `url`, which is latently
        # path/port-bearing and would silently graph-split from every other
        # tool's normalized BaseURL for the same host). httpx never derives
        # Parameters from the probed URL's query string - only keep the
        # BaseURL+Endpoint deltas.
        # D16: webapp/webapi profile derived from httpx-observable signals, set
        # on both the BaseURL and its root Endpoint so API tools (kiterunner) can
        # be gated to `profile == "webapi"` via JobSpec.consumes_where.
        profile = classify_profile(content_type, url)

        url_deltas = url_to_deltas(
            url,
            method="GET",
            source="httpx",
            extra_endpoint_props={
                "status_code": status_code,
                "content_type": content_type,
                "content_length": content_length,
                "title": title,
                "server": server,
                "profile": profile,
            },
        )[:2]
        if not url_deltas:
            continue

        baseurl_delta, endpoint_delta = url_deltas
        baseurl_delta.props = {
            "scheme": scheme,
            "host": host,
            "status_code": status_code,
            "title": title,
            "content_type": content_type,
            "final_url": final_url,
            "server": server,
            "profile": profile,
        }
        # Strong constraint: every httpx BaseURL is linked back to the Subdomain
        # it was probed from - the `input` echoed by httpx is exactly that host
        # (httpx consumes Subdomain, so `input` == the Subdomain node's `name`).
        # Mirrors subdomain_parser's Subdomain-[:BELONGS_TO]->Domain, giving the
        # Domain -> Subdomain -> BaseURL chain (was orphaned: 24/24 BaseURLs had
        # no incoming edge). Falls back to the resolved `host` if `input` is
        # absent, so a BaseURL is never emitted without a source-host link.
        source_host = _first(entry, "input", "host")
        if isinstance(source_host, str) and source_host.strip():
            baseurl_delta.edges = [
                Edge(
                    rel="BELONGS_TO",
                    dir="out",
                    node_type="Subdomain",
                    node_identity={"name": source_host.strip().lower()},
                )
            ]
        deltas.append(baseurl_delta)
        deltas.append(endpoint_delta)

        # Response headers (httpx `-irh` -> the `header` map, name -> value,
        # names already lowercased by httpx). Each becomes a Header node keyed
        # on {name, baseurl} with the value as a prop and an inbound HAS_HEADER
        # edge from the BaseURL: (BaseURL)-[:HAS_HEADER]->(Header).
        headers = entry.get("header") or {}
        if isinstance(headers, dict):
            for name, value in headers.items():
                if not name or not isinstance(name, str):
                    continue
                deltas.append(
                    AssetDelta(
                        type="Header",
                        identity={"name": name.lower(), "baseurl": baseurl_delta.identity["url"]},
                        props={"value": str(value)},
                        edges=[
                            Edge(
                                rel="HAS_HEADER",
                                dir="in",
                                node_type="BaseURL",
                                node_identity=baseurl_delta.identity,
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
                            node_identity=baseurl_delta.identity,
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
                            node_identity=baseurl_delta.identity,
                        )
                    ],
                )
            )

    return deltas
