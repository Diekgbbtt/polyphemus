"""Pure parser: katana `-jsonl` stdout -> list[AssetDelta].

This parser targets katana's `-jsonl` output shape (one JSON object per
crawled request):

    {"timestamp":..,"request":{"endpoint":"https://host/path?x=1","method":"GET"},
     "response":{"status_code":200,"content_type":"text/html"}}

Each line yields a `BaseURL` (scheme://host), an `Endpoint` (path/method under
that BaseURL) with a `HAS_ENDPOINT` edge, and one `Parameter` per query-string
key with a `HAS_PARAMETER` edge from the `Endpoint`.

Pure, deterministic, tolerant of malformed/missing-key lines - never raises.
"""
from urllib.parse import urljoin

from polymerhus.recon.domain.parsers._jsonlines import iter_json_dicts, safe_str
from polymerhus.recon.domain.parsers._urls import url_to_deltas
from polymerhus.recon.domain.types import AssetDelta


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

        deltas.extend(
            url_to_deltas(
                endpoint,
                method=method,
                source="katana",
                extra_endpoint_props={
                    "status_code": status_code,
                    "content_type": content_type,
                },
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
