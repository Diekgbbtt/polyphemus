"""Pure parser: Steel agentic-crawl manifest JSON -> list[AssetDelta].

This parser targets the fleet's flat `AssetDelta` contract, decomposing the
manifest shape:

    {"endpoints": [{"method": str, "url": str, "query": [...], "body": [...],
                    "status": int}], "js_urls": [str, ...]}

into a `BaseURL`, one `Endpoint` per manifest endpoint (props `url,
status_code, source="steel"`) with a `HAS_ENDPOINT` edge, and one
`Parameter` per query/body param name (position "query"/"body") with a
`HAS_PARAMETER` edge from the `Endpoint`. Each `js_urls[]` entry yields its
own `BaseURL`+`Endpoint` (method "GET", source "steel-js"), mirroring how
jsluice reports discovered JS-origin URLs.

`query`/`body` elements are, per the manifest contract, bare param-name
strings - but are handled defensively as `{"name": ...}` dicts too, since
the crawl loop's manifest builder can produce that richer shape when fed
already-classified params.

Pure, deterministic, tolerant of malformed/missing-key input - never raises.
"""
import json

from agent.recon.parsers._urls import base_and_path, url_to_deltas
from agent.recon.types import AssetDelta, Edge


def _param_name(item) -> str | None:
    if isinstance(item, str):
        return item or None
    if isinstance(item, dict):
        name = item.get("name")
        if isinstance(name, str) and name:
            return name
    return None


def _param_delta(name: str, position: str, *, path: str, baseurl: str, endpoint_identity: dict) -> AssetDelta:
    return AssetDelta(
        type="Parameter",
        identity={
            "name": name,
            "position": position,
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


def parse(stdout: str) -> list[AssetDelta]:
    try:
        manifest = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return []

    if not isinstance(manifest, dict):
        return []

    deltas: list[AssetDelta] = []

    endpoints = manifest.get("endpoints") or []
    if isinstance(endpoints, list):
        for entry in endpoints:
            if not isinstance(entry, dict):
                continue

            url = entry.get("url")
            method = entry.get("method") or "GET"

            endpoint_deltas = url_to_deltas(
                url,
                method=method,
                source="steel",
                extra_endpoint_props={"status_code": entry.get("status")},
            )
            if not endpoint_deltas:
                continue

            endpoint = next(d for d in endpoint_deltas if d.type == "Endpoint")
            endpoint_identity = endpoint.identity
            path = endpoint_identity["path"]
            baseurl = endpoint_identity["baseurl"]

            deltas.extend(endpoint_deltas)

            existing_query_names = {
                d.identity["name"] for d in endpoint_deltas if d.type == "Parameter"
            }
            query = entry.get("query")
            if not isinstance(query, list):
                query = []
            for item in query:
                name = _param_name(item)
                if name and name not in existing_query_names:
                    deltas.append(
                        _param_delta(
                            name, "query",
                            path=path, baseurl=baseurl, endpoint_identity=endpoint_identity,
                        )
                    )
                    existing_query_names.add(name)

            existing_body_names: set[str] = set()
            body = entry.get("body")
            if not isinstance(body, list):
                body = []
            for item in body:
                name = _param_name(item)
                if name and name not in existing_body_names:
                    deltas.append(
                        _param_delta(
                            name, "body",
                            path=path, baseurl=baseurl, endpoint_identity=endpoint_identity,
                        )
                    )
                    existing_body_names.add(name)

    js_urls = manifest.get("js_urls") or []
    if isinstance(js_urls, list):
        for url in js_urls:
            if not isinstance(url, str) or not base_and_path(url):
                continue
            deltas.extend(url_to_deltas(url, method="GET", source="steel-js"))

    return deltas
