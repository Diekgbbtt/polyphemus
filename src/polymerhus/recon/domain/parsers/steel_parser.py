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

from polymerhus.recon.domain.parsers._urls import base_and_path, url_to_deltas
from polymerhus.recon.domain.types import AssetDelta, Edge


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

    if manifest.get("schema_version") == "steel-crawl/v2":
        return _parse_v2(manifest)
    return _parse_v1(manifest)


def _parse_v1(manifest: dict) -> list[AssetDelta]:
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


def _parse_v2(manifest: dict) -> list[AssetDelta]:
    """Parse the `steel-crawl/v2` graph input (spec 11, 8.4).

    Endpoints and parameters carry both provenances; the manifest is the only
    place the two are distinct, so the parser preserves the `provenance` prop
    rather than merging the records. A parameter whose endpoint is not in the
    manifest is skipped: the graph anchor would be missing. Scripts mint their
    script URL as an Endpoint; realtime and error records are not graph nodes.
    """
    deltas: list[AssetDelta] = []
    endpoint_by_id: dict[str, dict] = {}
    endpoints = manifest.get("endpoints") or []
    if isinstance(endpoints, list):
        for entry in endpoints:
            if not isinstance(entry, dict):
                continue
            url = entry.get("url")
            if not isinstance(url, str) or not base_and_path(url):
                continue
            endpoint_deltas = url_to_deltas(
                url,
                method=entry.get("method") or "GET",
                source=entry.get("source") or "steel-crawl",
                extra_endpoint_props=_present(
                    {
                        "provenance": entry.get("provenance"),
                        "status_code": entry.get("status_code"),
                        "resource_type": entry.get("resource_type"),
                        "http_artifact_id": entry.get("http_artifact_id"),
                        "source_page_id": entry.get("source_page_id"),
                        "action_id": entry.get("action_id"),
                        "enctype": entry.get("enctype"),
                        "field_names": list(entry.get("field_names") or []),
                    }
                ),
                query_params=[],
                body_params=[],
            )
            # The v2 manifest owns the parameter records (both provenances), so
            # the URL's automatic query projection is dropped here; otherwise a
            # manifest parameter and its URL twin would both mint the same node.
            endpoint_deltas = [
                delta for delta in endpoint_deltas if delta.type != "Parameter"
            ]
            endpoint = next(
                (delta for delta in endpoint_deltas if delta.type == "Endpoint"),
                None,
            )
            if endpoint is None:
                continue
            endpoint_id = entry.get("endpoint_id")
            if isinstance(endpoint_id, str) and endpoint_id:
                endpoint_by_id[endpoint_id] = endpoint.identity
            deltas.extend(endpoint_deltas)

    parameters = manifest.get("parameters") or []
    if isinstance(parameters, list):
        for entry in parameters:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            if not isinstance(name, str) or not name:
                continue
            endpoint_id = entry.get("endpoint_id")
            identity = (
                endpoint_by_id.get(endpoint_id)
                if isinstance(endpoint_id, str)
                else None
            )
            if identity is None:
                continue
            options = entry.get("options")
            props = _present(
                {
                    "provenance": entry.get("provenance"),
                    "value_shape": entry.get("value_shape"),
                    "http_artifact_id": entry.get("http_artifact_id"),
                    "content_type": entry.get("content_type"),
                    "field_type": entry.get("field_type"),
                    "label": entry.get("label"),
                    "options": list(options) if isinstance(options, list) else None,
                    "pattern": entry.get("pattern"),
                    "min": entry.get("min"),
                    "max": entry.get("max"),
                }
            )
            deltas.append(
                AssetDelta(
                    type="Parameter",
                    identity={
                        "name": name,
                        "position": entry.get("position") or "query",
                        "endpoint_path": entry.get("endpoint_path")
                        or identity["path"],
                        "baseurl": entry.get("baseurl") or identity["baseurl"],
                    },
                    props=props,
                    edges=[
                        Edge(
                            rel="HAS_PARAMETER",
                            dir="in",
                            node_type="Endpoint",
                            node_identity=identity,
                        )
                    ],
                )
            )

    scripts = manifest.get("scripts") or []
    if isinstance(scripts, list):
        for entry in scripts:
            if not isinstance(entry, dict):
                continue
            url = entry.get("script_url")
            if not isinstance(url, str) or not base_and_path(url):
                continue
            deltas.extend(
                url_to_deltas(
                    url,
                    method="GET",
                    source="steel-script",
                    extra_endpoint_props=_present(
                        {
                            "script_id": entry.get("script_id"),
                            "provenance": entry.get("provenance"),
                        }
                    ),
                    query_params=[],
                    body_params=[],
                )
            )
    return deltas


def _present(values: dict) -> dict:
    """Drop absent keys; a present empty list or dict is still meaningful."""
    return {key: value for key, value in values.items() if value is not None}
