"""Pure parser: katana `-jsonl` stdout -> list[AssetDelta].

Ported from Redamon's `helpers/resource_enum/katana_helpers.py::run_katana_crawler`,
which historically consumed plain `-silent` URL lines. This parser instead
targets katana's `-jsonl` output shape (one JSON object per crawled request):

    {"timestamp":..,"request":{"endpoint":"https://host/path?x=1","method":"GET"},
     "response":{"status_code":200,"content_type":"text/html"}}

Each line yields a `BaseURL` (scheme://host), an `Endpoint` (path/method under
that BaseURL) with a `HAS_ENDPOINT` edge, and one `Parameter` per query-string
key with a `HAS_PARAMETER` edge from the `Endpoint`.

Pure, deterministic, tolerant of malformed/missing-key lines - never raises.
"""
from urllib.parse import parse_qs, urlparse

from agent.recon.parsers._jsonlines import iter_json_dicts, safe_str
from agent.recon.types import AssetDelta, Edge


def parse(stdout: str) -> list[AssetDelta]:
    deltas: list[AssetDelta] = []

    for entry in iter_json_dicts(stdout):
        request = entry.get("request") or {}
        if not isinstance(request, dict):
            request = {}
        endpoint = safe_str(request.get("endpoint"))
        if not endpoint:
            continue

        method = request.get("method") or "GET"
        if not isinstance(method, str):
            method = "GET"

        response = entry.get("response") or {}
        if not isinstance(response, dict):
            response = {}
        status_code = response.get("status_code")
        content_type = response.get("content_type")

        parsed = urlparse(endpoint)
        if not parsed.scheme or not parsed.netloc:
            continue

        baseurl = f"{parsed.scheme}://{parsed.netloc}"
        path = parsed.path or "/"

        deltas.append(
            AssetDelta(
                type="BaseURL",
                identity={"url": baseurl},
            )
        )

        endpoint_identity = {"path": path, "method": method, "baseurl": baseurl}
        deltas.append(
            AssetDelta(
                type="Endpoint",
                identity=endpoint_identity,
                props={
                    "url": endpoint,
                    "status_code": status_code,
                    "content_type": content_type,
                    "source": "resource_enum",
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
