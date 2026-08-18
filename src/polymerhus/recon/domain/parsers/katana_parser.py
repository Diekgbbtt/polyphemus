"""Pure parser: katana `-jsonl` stdout -> list[AssetDelta].

This parser targets katana's `-jsonl` output shape (one JSON object per
crawled request):

    {"timestamp":..,"request":{"endpoint":"https://host/path?x=1","method":"GET"},
     "response":{"status_code":200,"headers":{"Content-Type":"text/html"}}}

Note: katana's response object has no top-level `content_type` key (confirmed
live, issue #52) - content-type sits in `response.headers["Content-Type"]`.

Each line yields a `BaseURL` (scheme://host), an `Endpoint` (path/method under
that BaseURL) with a `HAS_ENDPOINT` edge, and one `Parameter` per query-string
key with a `HAS_PARAMETER` edge from the `Endpoint`.

Pure, deterministic, tolerant of malformed/missing-key lines - never raises.
"""
from urllib.parse import urljoin

from polymerhus.recon.domain.noise_filter import classify_profile
from polymerhus.recon.domain.parsers._jsonlines import iter_json_dicts, safe_str
from polymerhus.recon.domain.parsers._urls import url_to_deltas
from polymerhus.recon.domain.types import AssetDelta, Edge


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
        response_headers = response.get("headers") or {}
        if not isinstance(response_headers, dict):
            response_headers = {}
        content_type = response_headers.get("Content-Type") or response_headers.get("content-type")

        # Crawl-time pre-fill (2026-07-31): the SAME pure classifier
        # httpx_reprofile uses, applied to katana's own content-type instead of
        # waiting on a dedicated re-probe. Deliberately a PRE-FILL, not the
        # authoritative signal - httpx_reprofile still runs over the FULL
        # unified Endpoint population (incl. endpoints only ffuf/paramspider/
        # arjun/steel_crawl/kiterunner/jsluice ever found, which katana itself
        # never crawled) and its MERGE (`curator.py` `SET n += $props`) always
        # runs after katana in phase order, so it always has the final word
        # for anything it reaches. This only matters for an endpoint katana
        # found that NO reprofile pass ever revisits.
        profile = classify_profile(content_type, endpoint)

        url_deltas = url_to_deltas(
            endpoint,
            method=method,
            source="katana",
            extra_endpoint_props={
                "status_code": status_code,
                "content_type": content_type,
                "profile": profile,
            },
        )
        deltas.extend(url_deltas)

        # Header + Technology mapping (2026-07-31): katana's own JSONL already
        # carries `response.headers` and (with `-td`) `response.technologies`
        # - the exact fields httpx_parser already maps to Header/Technology
        # nodes, via the IDENTICAL wappalyzergo dataset katana and httpx both
        # use for tech-detect. This was previously discarded; now mapped the
        # same shape as httpx_parser so both tools' output MERGEs onto the
        # same nodes regardless of which one discovered them.
        if url_deltas:
            baseurl_identity = url_deltas[0].identity
            if response_headers:
                for name, value in response_headers.items():
                    if not name or not isinstance(name, str):
                        continue
                    deltas.append(
                        AssetDelta(
                            type="Header",
                            identity={"name": name.lower(), "baseurl": baseurl_identity["url"]},
                            props={"value": str(value)},
                            edges=[
                                Edge(
                                    rel="HAS_HEADER",
                                    dir="in",
                                    node_type="BaseURL",
                                    node_identity=baseurl_identity,
                                )
                            ],
                        )
                    )

            technologies = response.get("technologies") or []
            if isinstance(technologies, list):
                for tech in technologies:
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
                                    node_identity=baseurl_identity,
                                )
                            ],
                        )
                    )

        # Param discovery: with `-fx` katana emits `response.forms[]` =
        # {method, action, enctype, parameters:[names]}. Each form's fields
        # become Parameter deltas anchored to the form's action Endpoint - body
        # params for a POST form, query params for a GET form. The action is
        # resolved against the crawled endpoint so a relative action still mints
        # the right BaseURL+Endpoint via the shared helper.
        forms = response.get("forms") or []
        if not isinstance(forms, list):
            forms = []
        for form in forms:
            if not isinstance(form, dict):
                continue
            names = [p for p in (form.get("parameters") or []) if isinstance(p, str) and p]
            if not names:
                continue
            fmethod = form.get("method") or "GET"
            if not isinstance(fmethod, str):
                fmethod = "GET"
            fmethod = fmethod.upper()
            action = form.get("action")
            if not isinstance(action, str) or not action:
                action = endpoint
            action_url = urljoin(endpoint, action)
            if fmethod == "POST":
                deltas.extend(
                    url_to_deltas(action_url, method=fmethod, source="katana", body_params=names)
                )
            else:
                deltas.extend(
                    url_to_deltas(action_url, method=fmethod, source="katana", query_params=names)
                )

    return deltas
