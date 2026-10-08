#!/usr/bin/env python3
"""Pod-side webpack chunk-map resolver (#185).

This script runs INSIDE a Kali recon pod (base64-embedded into the pod command
by `polymerhus.recon.control.batching.build_webpack_chunks_command`), not in the
agent process. It takes a batch of crawled JS-bundle URLs as argv and, for each,
fetches the bundle and looks for the webpack runtime's static chunk map: the
object literal `{<chunk-id>: "<content-hash>", ...}` that maps a lazy chunk's id
to its emitted filename hash.

Each entry resolves to a lazy-loaded chunk file at
`<bundle-directory>/<chunk-id>.<hash>.js` (webpack's default
`[id].[contenthash].js` under the runtime's own output directory - the observed
white-jotter layout). Every resolved chunk URL is emitted as one JSONL record
`{"webpack_chunk_url": "<url>"}`, which `webpack_chunks_parser` turns into an
Endpoint. jsluice, running in the next phase, then scans those endpoints (and
its own URL/secret extraction sees the chunk bodies).

Pure, deterministic helpers plus a `scan_bundles(...)` core with injected
`fetch`/`emit`, so the whole flow is unit-testable without network.
"""
from __future__ import annotations

import json
import re
import sys

# The webpack runtime object that maps chunk ids to content hashes. A candidate
# is a `{...}` whose entries are all `<key>: "<hex>"` pairs - the key a chunk id
# (numeric, or a webpack-5 module-ish name) and the value a content hash of at
# least 8 hex characters. Requiring two-or-more all-hash entries keeps an
# ordinary config flag map (`{"name":"app"}`) out.
_CHUNK_MAP_RE = re.compile(
    r"\{((?:\s*(?:\"[^\"]+\"|'[^']+'|[A-Za-z0-9_$]+)\s*:\s*\"[0-9a-fA-F]{8,}\"\s*,?)+)\s*\}"
)
_ENTRY_RE = re.compile(
    r"(?:\"([^\"]+)\"|'([^']+)'|([A-Za-z0-9_$]+))\s*:\s*\"([0-9a-fA-F]{8,})\""
)


def extract_webpack_chunk_map(text: str) -> dict[str, str]:
    """The first webpack chunk map found in `text`, as `{chunk_id: content_hash}`.

    `{}` when no `{...}` object carries two-or-more `key: "<hex hash>"` entries.
    Tolerant of quoted or bare chunk-id keys and of surrounding whitespace.
    """
    if not text:
        return {}
    for match in _CHUNK_MAP_RE.finditer(text):
        chunk_map: dict[str, str] = {}
        for dq, sq, bare, content_hash in _ENTRY_RE.findall(match.group(1)):
            key = dq or sq or bare
            chunk_map[key] = content_hash
        if len(chunk_map) >= 2:
            return chunk_map
    return {}


def resolve_chunk_url(bundle_url: str, chunk_id: str, chunk_hash: str) -> str:
    """The absolute URL of a lazy chunk: the bundle's own directory plus
    `<chunk_id>.<chunk_hash>.js`. Any query/fragment on `bundle_url` is ignored."""
    clean = bundle_url.split("#", 1)[0].split("?", 1)[0]
    idx = clean.rfind("/")
    base = clean[: idx + 1] if idx >= 0 else clean
    return f"{base}{chunk_id}.{chunk_hash}.js"


def scan_bundles(bundle_urls, *, fetch, emit) -> None:
    """Core flow (injected `fetch(url) -> str | None`, `emit(line)`), so tests
    drive it with no network. Fetches each bundle, resolves its chunk map, and
    emits one record per distinct resolved chunk URL."""
    seen: set[str] = set()
    for burl in bundle_urls:
        content = fetch(burl)
        if not content:
            continue
        chunk_map = extract_webpack_chunk_map(content)
        for chunk_id, chunk_hash in chunk_map.items():
            url = resolve_chunk_url(burl, chunk_id, chunk_hash)
            if url in seen:
                continue
            seen.add(url)
            emit(json.dumps({"webpack_chunk_url": url}))


# --------------------------------------------------------------------------- #
# Real collaborator (used only when executed as a script inside the pod).      #
# --------------------------------------------------------------------------- #
def _real_fetch(url: str) -> str | None:
    import ssl
    import urllib.request

    # Same contract as jsluice_scan._real_fetch: recon egress fetches bundles
    # from arbitrary/misconfigured targets (self-signed certs), and a TLS
    # verification failure must not silently turn every https bundle into a
    # None fetch. The Go crawlers already ignore cert errors.
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "polymerhus-recon/webpack"})
        with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:  # noqa: S310 (recon egress)
            raw = resp.read()
        return raw.decode("utf-8", "replace")
    except Exception:  # best-effort: an unreachable bundle degrades to skip
        return None


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    scan_bundles(
        argv,
        fetch=_real_fetch,
        emit=lambda line: print(line, flush=True),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
