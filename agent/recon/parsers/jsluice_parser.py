"""Pure parser: jsluice `urls`/`secrets` JSONL stdout -> list[AssetDelta].

Ported from Redamon's `helpers/resource_enum/jsluice_helpers.py`
(`run_jsluice_analysis` + `merge_jsluice_into_by_base_url`). jsluice is run
in two modes against JS files discovered by the crawl phase, and both modes'
output can be interleaved line-by-line in this parser's input:

  - `jsluice urls` lines: `{"url": "...", "method": "GET", "type": "..."}`
    -> discovered endpoint, decomposed into BaseURL + Endpoint (+HAS_ENDPOINT
    edge) the same way `katana_parser` does.

  - `jsluice secrets` lines: `{"kind": "aws-access-key", "secret": "AKIA...",
    ...}` -> a redacted `Secret` node. The raw secret value is NEVER stored;
    only its sha1 hex digest (`value_hash`) is kept, and that hash is the
    Secret's sole identity key.

    Redamon's wrapper (`_extract_secrets_for_base`) annotates each secret
    dict with `base_url` (the BaseURL of the JS file it was extracted from)
    before merging. We honour that same field when present. Failing that, we
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
from urllib.parse import urlparse

from agent.recon.types import AssetDelta, Edge


def _baseurl_from(url: str) -> str | None:
    if not isinstance(url, str):
        return None
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def _parse_url_entry(entry: dict) -> list[AssetDelta]:
    url = entry.get("url")
    if not url or not isinstance(url, str):
        return []

    baseurl = _baseurl_from(url)
    if not baseurl:
        return []

    parsed = urlparse(url)
    path = parsed.path or "/"
    method = entry.get("method") or "GET"

    endpoint_identity = {"path": path, "method": method, "baseurl": baseurl}

    return [
        AssetDelta(type="BaseURL", identity={"url": baseurl}),
        AssetDelta(
            type="Endpoint",
            identity=endpoint_identity,
            props={"url": url, "source": "jsluice"},
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


def _parse_secret_entry(entry: dict) -> list[AssetDelta]:
    raw_secret = entry.get("secret")
    if not raw_secret or not isinstance(raw_secret, str):
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
        elif entry.get("kind") or entry.get("secret"):
            deltas.extend(_parse_secret_entry(entry))

    return deltas
