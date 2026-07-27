"""Pure parser: jsluice `urls`/`secrets` JSONL stdout -> list[AssetDelta].

jsluice is run in two modes against the JS-bundle Endpoints katana
discovers - and, via the sourcemap-extraction wrapper
(`scripts/jsluice_scan.py`, D17/Q7), against the
original sources recovered from each bundle's `.map`. Both modes' output can be
interleaved line-by-line in this parser's input:

  - `jsluice urls` lines: `{"url": "...", "method": "GET", "type": "...",
    "queryParams": [...], "bodyParams": [...]}` -> discovered endpoint,
    decomposed into BaseURL + Endpoint (+HAS_ENDPOINT edge) the same way
    `katana_parser` does, PLUS a Parameter per queryParams entry (position
    query) and per bodyParams entry (position body), each with a HAS_PARAMETER
    edge from the Endpoint (jsluice's built-in param discovery).

  - `jsluice secrets` lines: `{"kind": "aws-access-key", "secret": "AKIA...",
    ...}` -> a redacted `Secret` node. The raw secret value is NEVER stored;
    only its sha1 hex digest (`value_hash`) is kept, and that hash is the
    Secret's sole identity key.

    Each secret dict may carry a `base_url` (the BaseURL of the JS file it
    was extracted from), which we honour when present. Failing that, we
    fall back to deriving a base URL from a `source_url` field (the JS
    file's own URL) if one is present. If neither is available there is no
    reliable anchor, so the Secret delta is emitted without a `HAS_SECRET`
    edge rather than guessing.

Line-kind discrimination: a line with a truthy `url` key is a discovered
endpoint; a line with a `kind` or `secret` key (and no `url` key) is a
secret finding. Anything else - or invalid JSON - is skipped.

Pure, deterministic, tolerant of malformed/missing-key lines - never raises.
"""
import hashlib
import json

from polymerhus.recon.domain.parsers._urls import base_and_path, url_to_deltas
from polymerhus.recon.domain.types import AssetDelta, Edge


def _baseurl_from(url: str) -> str | None:
    split = base_and_path(url)
    return split[0] if split is not None else None


def _parse_url_entry(entry: dict) -> list[AssetDelta]:
    url = entry.get("url")
    if not url or not isinstance(url, str):
        return []

    method = entry.get("method") or "GET"

    # Param discovery: jsluice `urls` mode emits `queryParams`/`bodyParams`
    # arrays per discovered URL (built-in). Feed them to the shared helper so
    # they become Parameter deltas (query params at position=query, body params
    # at position=body) anchored to the Endpoint - no longer dropped.
    query_params = entry.get("queryParams")
    body_params = entry.get("bodyParams")
    return url_to_deltas(
        url,
        method=method,
        source="jsluice",
        query_params=query_params if isinstance(query_params, list) else None,
        body_params=body_params if isinstance(body_params, list) else None,
    )


def _extract_secret_value(entry: dict) -> str | None:
    """The sensitive value to hash for identity. Real jsluice nests it under a
    `data` OBJECT (e.g. `{"key": "...", "secret": "..."}`) - NOT a top-level
    `secret` string, which the tool never emits (the old code read the latter and
    so dropped every real finding). Prefer `data.secret`, then `data.key`, then a
    canonical serialisation of the whole `data` object; fall back to a legacy
    top-level `secret` string for backward compatibility. The value is only ever
    HASHED (below), never stored, so serialising `data` here does not leak it."""
    data = entry.get("data")
    if isinstance(data, dict) and data:
        for key in ("secret", "key", "value", "token"):
            v = data.get(key)
            if isinstance(v, str) and v:
                return v
        # No known sub-field: hash a stable serialisation so distinct findings
        # still get distinct identities (never store the object itself).
        return json.dumps(data, sort_keys=True)
    if isinstance(data, str) and data:
        return data
    legacy = entry.get("secret")  # backward-compat with the pre-`data` shape
    return legacy if isinstance(legacy, str) and legacy else None


def _parse_secret_entry(entry: dict) -> list[AssetDelta]:
    raw_secret = _extract_secret_value(entry)
    if not raw_secret:
        return []

    kind = entry.get("kind")
    value_hash = hashlib.sha1(raw_secret.encode()).hexdigest()

    baseurl = entry.get("base_url")
    if not baseurl:
        source_url = entry.get("source_url")
        if source_url:
            baseurl = _baseurl_from(source_url)

    edges = []
    if baseurl:
        edges.append(
            Edge(
                rel="HAS_SECRET",
                dir="in",
                node_type="BaseURL",
                node_identity={"url": baseurl},
            )
        )

    deltas: list[AssetDelta] = []
    if baseurl:
        deltas.append(AssetDelta(type="BaseURL", identity={"url": baseurl}))

    deltas.append(
        AssetDelta(
            type="Secret",
            identity={"value_hash": value_hash},
            props={"kind": kind, "source": "jsluice", "redacted": True},
            edges=edges,
        )
    )
    return deltas


def parse(stdout: str) -> list[AssetDelta]:
    deltas: list[AssetDelta] = []

    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue

        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        if not isinstance(entry, dict):
            continue

        if entry.get("url"):
            deltas.extend(_parse_url_entry(entry))
        elif entry.get("kind") or entry.get("data") or entry.get("secret"):
            deltas.extend(_parse_secret_entry(entry))

    return deltas
