"""Pure parsers: gau / paramspider plain-text URL stdout -> list[AssetDelta].

Ported from Redamon's `helpers/resource_enum/gau_helpers.py::parse_gau_url_to_endpoint`
and `helpers/resource_enum/paramspider_helpers.py::run_paramspider_discovery` /
`merge_paramspider_into_by_base_url` (the latter reuses `parse_gau_url_to_endpoint`
for its own URL parsing).

Both tools emit one URL per line (plain text, NOT json):

    https://host/path?id=1&q=x

gau emits bare discovered URLs. paramspider emits URLs where query parameter
*values* are replaced with a placeholder (default `FUZZ`, e.g.
`https://host/path?id=FUZZ`) - only the parameter *names* matter here, so the
placeholder value is irrelevant and never leaks into node identity.

Each URL yields a `BaseURL` (scheme://netloc), an `Endpoint` (path/method under
that BaseURL, method fixed to "GET" since these are passive/historical URL
sources with no live method info) with a `HAS_ENDPOINT` edge, and one
`Parameter` per query-string key with a `HAS_PARAMETER` edge from the
`Endpoint`. The edge's `node_identity` reuses the exact same identity dict
object built for the Endpoint delta so it byte-matches for curation.

Pure, deterministic, tolerant of blank/malformed lines - never raises.
"""
from urllib.parse import parse_qs, urlparse

from agent.recon.types import AssetDelta, Edge


def _url_to_deltas(url: str, source: str) -> list[AssetDelta]:
    deltas: list[AssetDelta] = []

    try:
        parsed = urlparse(url)
    except ValueError:
        return deltas

    if not parsed.scheme or not parsed.netloc:
        return deltas

    baseurl = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path or "/"

    deltas.append(
        AssetDelta(
            type="BaseURL",
            identity={"url": baseurl},
        )
    )

    endpoint_identity = {"path": path, "method": "GET", "baseurl": baseurl}
    deltas.append(
        AssetDelta(
            type="Endpoint",
            identity=endpoint_identity,
            props={
                "url": url,
                "source": source,
            },
            edges=[
                Edge(
                    rel="HAS_ENDPOINT",
                    dir="in",
                    node_type="BaseURL",
                    node_identity={"url": baseurl},
                )
            ],
        )
    )

    query_params = parse_qs(parsed.query, keep_blank_values=True)
    for name in query_params:
        deltas.append(
            AssetDelta(
                type="Parameter",
                identity={
                    "name": name,
                    "position": "query",
                    "endpoint_path": path,
                    "baseurl": baseurl,
                },
                edges=[
                    Edge(
                        rel="HAS_PARAMETER",
                        dir="in",
                        node_type="Endpoint",
                        node_identity=endpoint_identity,
                    )
                ],
            )
        )

    return deltas


def _parse_lines(stdout: str, source: str) -> list[AssetDelta]:
    deltas: list[AssetDelta] = []

    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue

        deltas.extend(_url_to_deltas(line, source))

    return deltas


def parse_gau(stdout: str) -> list[AssetDelta]:
    return _parse_lines(stdout, source="gau")


def parse_paramspider(stdout: str) -> list[AssetDelta]:
    return _parse_lines(stdout, source="paramspider")
