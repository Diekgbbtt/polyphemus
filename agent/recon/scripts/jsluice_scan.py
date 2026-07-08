#!/usr/bin/env python3
"""Pod-side jsluice bundle scanner (forward-decision D17/Q6+Q7).

This script runs INSIDE a Kali recon pod (base64-embedded into the pod command
by `agent.recon.batching.build_jsluice_command`), not in the agent process. It
takes a batch of JS-bundle URLs as argv and, for each:

  1. fetches the bundle, runs `jsluice urls` + `jsluice secrets` over it;
  2. IDENTIFIES its sourcemap - the `sourceMappingURL` comment, else a
     fallback probe of `<bundle>.map`, else (a `.map` URL) the bundle itself;
  3. EXTRACTS original sources from the sourcemap JSON (`sources[]` +
     `sourcesContent[]`, fetching a source when its content is null),
     FILTERS out presentational/vendor noise, content-hash-dedups source
     bodies, and runs `jsluice urls` + `jsluice secrets` over each survivor.

Every emitted line is jsluice's own `urls`/`secrets` JSONL, annotated with the
bundle origin as `base_url`/`source_url` so `jsluice_parser` anchors recovered
`Secret`s (and endpoints) to the right `BaseURL`. Stdout is therefore exactly
what `agent.recon.parsers.jsluice_parser.parse` already ingests.

Replicates the identification/filtering/extraction behavior of the operator's
reference `secret_scanner.py` (spec, not a dependency). Pure helpers plus a
`scan_bundles(...)` core with injected `fetch`/`run_jsluice`/`emit` so the
whole flow is unit-testable without network or the jsluice binary.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from urllib.parse import urljoin, urlparse

# `//# sourceMappingURL=app.js.map` or `//@ sourceMappingURL=...map` - the last
# `.map` reference in a bundle. Non-greedy up to `.map` so a trailing token
# (jsluice appends none, but browsers tolerate) does not over-capture.
_SOURCEMAP_RE = re.compile(r"//[#@]\s*sourceMappingURL=(.+?\.map)")

# Sources that are never worth scanning: presentational assets, sourcemaps
# themselves, and (below) bundler internals / third-party modules.
_NOISE_EXT_RE = re.compile(r"\.(css|scss|png|jpg|jpeg|gif|svg|map)$", re.IGNORECASE)


def bundle_origin(url: str) -> str:
    """`scheme://netloc` of `url` (the `-R` resolve base for jsluice urls and
    the `base_url` anchor for recovered secrets). `""` if unparseable."""
    try:
        p = urlparse(url)
    except ValueError:
        return ""
    if not p.scheme or not p.netloc:
        return ""
    return f"{p.scheme}://{p.netloc}"


def extract_sourcemap_url(bundle_content: str, bundle_url: str) -> str | None:
    """Absolute URL of the sourcemap referenced by the bundle's
    `sourceMappingURL` comment, resolved against `bundle_url`. `None` if the
    bundle carries no such comment."""
    if not bundle_content:
        return None
    m = _SOURCEMAP_RE.search(bundle_content)
    if not m:
        return None
    return urljoin(bundle_url, m.group(1).strip())


def sourcemap_candidate(bundle_content: str, bundle_url: str) -> str | None:
    """The single sourcemap URL to try for a bundle, per the resolved D17/Q7
    identification order:

      (iii) a bundle URL already ending `.map` IS the sourcemap;
      (i)   otherwise the `sourceMappingURL` comment, if present;
      (ii)  otherwise fall back to probing `<bundle_url>.map`.
    """
    if bundle_url.endswith(".map"):
        return bundle_url
    ident = extract_sourcemap_url(bundle_content, bundle_url)
    if ident:
        return ident
    return bundle_url + ".map"


def should_scan_source(path: str) -> bool:
    """Noise filter over a sourcemap `sources[]` path (D17/Q7 filtering):
    drop presentational/sourcemap extensions, `/webpack/` internals, and
    `/node_modules/` paths UNLESS they also contain `/internal/`."""
    p = path or ""
    if _NOISE_EXT_RE.search(p):
        return False
    if re.search(r"(^|/)webpack/", p):
        return False
    if re.search(r"(^|/)node_modules/", p) and "/internal/" not in p:
        return False
    return True


def sanitize_source_path(path: str) -> str:
    """Neutralize a sourcemap source path before use (D17/Q7 sanitize): strip a
    leading `webpack://<host>/`, then any `scheme://`, then a leading `./`, then
    remove `..` traversal tokens and any leading slashes."""
    p = path or ""
    p = re.sub(r"^webpack://[^/]*/", "", p)
    p = re.sub(r"^[a-z]+://", "", p)
    p = re.sub(r"^\./", "", p)
    p = p.replace("..", "")
    return p.lstrip("/")


def iter_sourcemap_sources(sourcemap: dict):
    """Yield `(source_path, embedded_content_or_None)` for each entry in a
    parsed sourcemap, index-mapping `sources[]` to `sourcesContent[]`."""
    sources = sourcemap.get("sources") or []
    contents = sourcemap.get("sourcesContent") or []
    for i, src in enumerate(sources):
        if not isinstance(src, str):
            continue
        content = contents[i] if i < len(contents) else None
        yield src, (content if isinstance(content, str) else None)


def _emit_jsluice(text: str, origin: str, source_url: str, run_jsluice, emit) -> None:
    """Run both jsluice modes over `text` and emit each output line annotated
    with `base_url`/`source_url` so the parser can anchor findings."""
    if not text:
        return
    for mode in ("urls", "secrets"):
        out = run_jsluice(mode, text, origin) or ""
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            obj.setdefault("base_url", origin)
            obj.setdefault("source_url", source_url)
            emit(json.dumps(obj))


def scan_bundles(bundle_urls, *, fetch, run_jsluice, emit) -> None:
    """Core flow (injected `fetch(url)->str|None`, `run_jsluice(mode,text,base)
    ->str`, `emit(line)`), so tests drive it with no network/binary.

    Dedups processed sourcemap URLs and content-hash-dedups source bodies so
    the same map / identical source across bundles is scanned once."""
    processed_maps: set[str] = set()
    seen_source_hashes: set[str] = set()

    for burl in bundle_urls:
        origin = bundle_origin(burl)

        # A direct `.map` URL IS the sourcemap - never fetch it as a bundle
        # (that would double-fetch and defeat the processed-map dedup).
        content = None
        if not burl.endswith(".map"):
            content = fetch(burl)
            if content:
                _emit_jsluice(content, origin, burl, run_jsluice, emit)

        map_url = sourcemap_candidate(content or "", burl)
        if not map_url or map_url in processed_maps:
            continue
        processed_maps.add(map_url)

        map_text = fetch(map_url)
        if not map_text:
            continue
        try:
            sourcemap = json.loads(map_text)
        except json.JSONDecodeError:
            continue
        if not isinstance(sourcemap, dict):
            continue

        for src_path, embedded in iter_sourcemap_sources(sourcemap):
            if not should_scan_source(src_path):
                continue
            body = embedded if embedded is not None else fetch(urljoin(map_url, src_path))
            if not body:
                continue
            digest = hashlib.md5(body.encode("utf-8", "ignore")).hexdigest()
            if digest in seen_source_hashes:
                continue
            seen_source_hashes.add(digest)
            _emit_jsluice(body, origin, origin, run_jsluice, emit)


# --------------------------------------------------------------------------- #
# Real collaborators (used only when executed as a script inside the pod).     #
# --------------------------------------------------------------------------- #
def _real_fetch(url: str) -> str | None:
    import urllib.request

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "polymerhus-recon/jsluice"})
        with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 (recon egress)
            raw = resp.read()
        return raw.decode("utf-8", "replace")
    except Exception:  # best-effort: an unreachable bundle/map degrades to skip
        return None


def _real_run_jsluice(mode: str, text: str, baseurl: str) -> str:
    import subprocess

    args = ["jsluice", mode]
    if mode == "urls" and baseurl:
        args += ["-R", baseurl]
    try:
        proc = subprocess.run(
            args, input=text, capture_output=True, text=True, timeout=60, check=False
        )
        return proc.stdout or ""
    except Exception:  # jsluice missing / crash on one blob must not abort batch
        return ""


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    scan_bundles(
        argv,
        fetch=_real_fetch,
        run_jsluice=_real_run_jsluice,
        emit=lambda line: print(line, flush=True),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
