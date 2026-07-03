"""Pure parsers: arjun / ffuf / kiterunner stdout -> list[AssetDelta].

Ported from Redamon's `helpers/resource_enum/{arjun,ffuf,kiterunner}_helpers.py`.
These are *active* discovery tools (unlike the passive gau/paramspider/katana
sources) - arjun brute-forces parameter names on known endpoints, ffuf and
kiterunner brute-force routes/paths.

Confirmed raw tool output shapes (read from the Redamon source, not the
wrapper-transformed intermediate structures):

arjun `-oJ <file>` JSON (parsed in `_run_arjun_single_method`, ~line 145):

    {"https://host/path": {"params": ["id", "q"], "method": "GET"}, ...}

Arjun discovers *parameters*, not new routes - each key is a URL that was
tested, mapped to the parameter names found on it and the method used.
POST/JSON/XML methods carry their parameters in the body; GET (or any other
method) carries them in the query string (mirrors
`merge_arjun_into_by_base_url`'s `param_position` logic).

ffuf `-of json -o <file>` JSON (parsed in `_fuzz_single_target`, ~line 103):

    {"results": [{"url": .., "status": .., "input": {"FUZZ": ..}, ...}, ...]}

ffuf is a directory/path fuzzer with no method info - method is fixed "GET".

kiterunner `-o json` (parsed in `run_kiterunner_discovery`, ~line 180) emits
one JSON object per line on stdout:

    {"method": "GET", "target": "https://host", "path": "/v1/users",
     "responses": [{"sc": 200, "len": 512}], "time": "..."}

Lines carrying `level`/`message` are kiterunner's own log noise and are
skipped (mirrors the helper's `if 'level' in data or 'message' in data`
guard). Kiterunner also has a documented plain-text fallback format for
non-JSON output: `METHOD STATUS_CODE URL [content_length]`.

Target schema (SDD §10.3):
- arjun -> `Parameter (name, position, endpoint_path, baseurl)` with a
  `HAS_PARAMETER` edge from the parent `Endpoint (path, method, baseurl)`;
  the parent `Endpoint` and its `BaseURL` are emitted too so the graph links.
- ffuf/kiterunner -> discovered `Endpoint (path, method, baseurl)` with
  `status_code`/`source` props and a `HAS_ENDPOINT` edge from `BaseURL`.

Edge `node_identity` always reuses the exact identity dict object built for
the referenced node so it byte-matches for curation.

Pure, deterministic, tolerant of malformed/missing-key input - never raises.
"""
import json
from urllib.parse import urlparse

from agent.recon.types import AssetDelta, Edge

_BODY_METHODS = {"POST", "JSON", "XML"}
_VALID_HTTP_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}


def _split_url(url: str) -> tuple[str, str] | None:
    """Return (baseurl, path) or None if the url is not absolute/parseable."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return None

    if not parsed.scheme or not parsed.netloc:
        return None

    return f"{parsed.scheme}://{parsed.netloc}", (parsed.path or "/")


def parse_arjun(stdout: str) -> list[AssetDelta]:
    deltas: list[AssetDelta] = []

    try:
        arjun_output = json.loads(stdout)
    except json.JSONDecodeError:
        return deltas

    if not isinstance(arjun_output, dict):
        return deltas

    for url, url_data in arjun_output.items():
        if not isinstance(url_data, dict):
            continue

        params = url_data.get("params") or []
        if not isinstance(params, list):
            continue

        method = str(url_data.get("method") or "GET").upper()
        position = "body" if method in _BODY_METHODS else "query"

        split = _split_url(url)
        if split is None:
            continue
        baseurl, path = split

        deltas.append(AssetDelta(type="BaseURL", identity={"url": baseurl}))

        endpoint_identity = {"path": path, "method": method, "baseurl": baseurl}
        deltas.append(
            AssetDelta(
                type="Endpoint",
                identity=endpoint_identity,
                props={"url": url, "source": "arjun"},
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

        for name in params:
            if not name or not isinstance(name, str):
                continue
            deltas.append(
                AssetDelta(
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
            )

    return deltas


def parse_ffuf(stdout: str) -> list[AssetDelta]:
    deltas: list[AssetDelta] = []

    try:
        ffuf_output = json.loads(stdout)
    except json.JSONDecodeError:
        return deltas

    if not isinstance(ffuf_output, dict):
        return deltas

    results = ffuf_output.get("results")
    if not isinstance(results, list):
        return deltas

    for entry in results:
        if not isinstance(entry, dict):
            continue

        url = entry.get("url")
        if not url or not isinstance(url, str):
            continue

        split = _split_url(url)
        if split is None:
            continue
        baseurl, path = split

        deltas.append(AssetDelta(type="BaseURL", identity={"url": baseurl}))

        endpoint_identity = {"path": path, "method": "GET", "baseurl": baseurl}
        deltas.append(
            AssetDelta(
                type="Endpoint",
                identity=endpoint_identity,
                props={
                    "url": url,
                    "status_code": entry.get("status", 0),
                    "source": "ffuf",
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

    return deltas


def _kiterunner_json_line(data: dict) -> list[AssetDelta] | None:
    if "level" in data or "message" in data:
        return None
    if "method" not in data:
        return None

    method = str(data.get("method") or "GET").upper()
    target = data.get("target") or ""
    path = data.get("path") or ""
    if not target or not path or not isinstance(target, str) or not isinstance(path, str):
        return None

    status = 0
    responses = data.get("responses")
    if isinstance(responses, list) and responses and isinstance(responses[0], dict):
        status = responses[0].get("sc", 0)

    baseurl = target.rstrip("/")
    return _kiterunner_endpoint_deltas(baseurl, path, method, status)


def _kiterunner_endpoint_deltas(
    baseurl: str, path: str, method: str, status: object
) -> list[AssetDelta]:
    endpoint_identity = {"path": path, "method": method, "baseurl": baseurl}
    return [
        AssetDelta(type="BaseURL", identity={"url": baseurl}),
        AssetDelta(
            type="Endpoint",
            identity=endpoint_identity,
            props={"status_code": status, "source": "kiterunner"},
            edges=[
                Edge(
                    rel="HAS_ENDPOINT",
                    dir="in",
                    node_type="BaseURL",
                    node_identity={"url": baseurl},
                )
            ],
        ),
    ]


def _kiterunner_text_line(line: str) -> list[AssetDelta] | None:
    parts = line.split()
    if len(parts) < 3:
        return None

    method = parts[0].upper()
    if method not in _VALID_HTTP_METHODS:
        return None

    try:
        status = int(parts[1])
    except ValueError:
        return None

    split = _split_url(parts[2])
    if split is None:
        return None
    baseurl, path = split

    return _kiterunner_endpoint_deltas(baseurl, path, method, status)


def parse_kiterunner(stdout: str) -> list[AssetDelta]:
    deltas: list[AssetDelta] = []

    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue

        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            fallback = _kiterunner_text_line(line)
            if fallback:
                deltas.extend(fallback)
            continue

        if not isinstance(data, dict):
            continue

        parsed = _kiterunner_json_line(data)
        if parsed is not None:
            deltas.extend(parsed)

    return deltas
