#!/usr/bin/env python3
"""Pod-side jsluice bundle scanner (forward-decision D17/Q6+Q7).

This script runs INSIDE a Kali recon pod (base64-embedded into the pod command
by `polymerhus.recon.control.batching.build_jsluice_command`), not in the agent process. It
takes a batch of JS-bundle URLs as argv and, for each:

  1. fetches the bundle, runs `jsluice urls` + `jsluice secrets` over it;
  2. IDENTIFIES its sourcemap - the `sourceMappingURL` comment, else a
     fallback probe of `<bundle>.map`, else (a `.map` URL) the bundle itself;
  3. EXTRACTS original sources from the sourcemap JSON (`sources[]` +
     `sourcesContent[]`, fetching a source when its content is null),
     FILTERS out presentational/vendor noise, content-hash-dedups source
     bodies, and runs `jsluice urls` + `jsluice secrets` over each survivor.

Relative literals resolve against the scanned RESOURCE (each bundle's own URL),
not the origin root: `./commands-x.js` imported by `/assets/index-abc.js` means
`/assets/commands-x.js` (resolving against the origin minted 86 phantom `.js`
404s in the arm J comfyui trial). After the batch, every root-relative literal
is additionally re-minted once per runtime path prefix the batch discovered in
the same origin's bundles (`baseURL: "/api"`, or a joined segment like
`api_base+"/internal"+x`) - the `/api/login`-style candidates that no single
literal reveals. The batch grouping (batching.build_batches) keeps one origin's
bundles in one pod so this join is deterministic.

Every emitted line is jsluice's own `urls`/`secrets` JSONL, annotated with the
bundle origin as `base_url` and the scanned resource as `source_url` so
`jsluice_parser` anchors recovered `Secret`s (and endpoints) to the right
`BaseURL`. Stdout is therefore exactly what
`polymerhus.recon.domain.parsers.jsluice_parser.parse` already ingests
(chained records add `chained_prefix`/`chained_from` keys the parser props).

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

# Runtime request-path prefixes a first-party bundle assembles its URLs from -
# the base split across a config statement and a later literal, invisible to
# any single extraction. white-jotter: `defaults.baseURL="/api"` in the app
# bundle + `this.$axios.post("/login")` in a lazy chunk means
# `POST /api/login`. comfyui-manager: `api_base+"/internal"+route` turns the
# `/logs/raw` literal into `/internal/logs/raw`. Two conservative shapes:
# a static `baseURL` config, and a path string JOINED as a segment
# (`+ "/internal" +`). Absolute-URL bases (`baseURL:"https://api.comfy.org"`)
# are deliberately not captured - chaining them would mint cross-origin
# endpoints, outside the scanned origin's surface.
_BASEURL_CONFIG_RE = re.compile(r"""baseURL\s*[:=]\s*["'`](/[^"'`\s]{0,63})["'`]""")
_JOINED_PREFIX_RE = re.compile(r"""\+\s*["'`](/[A-Za-z][A-Za-z0-9_\-/]{0,31})["'`]\s*\+""")
_PREFIX_SHAPE_RE = re.compile(r"/[A-Za-z0-9_\-/]+")
# A chained candidate ending in one of these is the literal of a STATIC ASSET
# (a Vite `./commands-x.js` import, a stylesheet, an image), never an API route
# under the runtime prefix - the arm J comfyui bundle's 124 `./x-hash.js`
# literals would otherwise mint `/api/assets/*.js` phantoms by the hundred.
_STATIC_ASSET_EXT_RE = re.compile(
    r"\.(?:js|mjs|css|map|wasm|png|jpe?g|gif|svg|ico|webp|avif|woff2?|ttf|eot|mp4|webm)$",
    re.IGNORECASE,
)
_MAX_BASE_PREFIXES = 4
_MAX_BASE_PREFIX_LEN = 32


def _clean_base_prefix(raw: str) -> str | None:
    """Normalize one captured prefix; `None` when it is not usable as a
    request-path prefix (empty, root, file-shaped/dotted, over-long, or
    carrying characters no path segment has). Strips a trailing `/` so chaining
    never doubles up (`/api/` + `/login` -> `/api/login`)."""
    p = (raw or "").rstrip("/")
    if not p or "." in p or "?" in p or "#" in p:
        return None
    if len(p) > _MAX_BASE_PREFIX_LEN or not _PREFIX_SHAPE_RE.fullmatch(p):
        return None
    return p


def extract_base_prefixes(text: str) -> list[str]:
    """Ordered, deduped, capped (`_MAX_BASE_PREFIXES`) runtime path prefixes a
    bundle assembles request URLs from. First-seen wins; the cap keeps a
    pathological bundle from multiplying every literal into hundreds of
    candidate URLs."""
    out: list[str] = []
    for m in _BASEURL_CONFIG_RE.finditer(text or ""):
        p = _clean_base_prefix(m.group(1))
        if p and p not in out:
            out.append(p)
    for m in _JOINED_PREFIX_RE.finditer(text or ""):
        p = _clean_base_prefix(m.group(1))
        if p and p not in out:
            out.append(p)
    return out[:_MAX_BASE_PREFIXES]


def _resource_dir(rec: dict) -> str:
    """Directory of the resource a literal was scanned in (`source_url`), or
    `/` when unknown - the base a bundle-relative literal resolved under."""
    source_url = rec.get("source_url")
    if not isinstance(source_url, str) or not source_url:
        return "/"
    try:
        p = urlparse(source_url)
    except ValueError:
        return "/"
    path = p.path or "/"
    if "/" not in path:
        return "/"
    return path.rsplit("/", 1)[0] or "/"


def _chained_record(origin: str, prefix: str, rec: dict) -> dict | None:
    """Re-mint one jsluice `urls` record under a discovered runtime prefix -
    the same path one base further out (`/login` -> `/api/login`). The ORIGINAL
    literal is never replaced (`/login` is also a real Vue route), so this is an
    additive candidate the reprofile probe pass arbitrates. `None` when there is
    nothing to mint:

    - foreign-origin record, root path, or a path that already carries the
      prefix;
    - a static-asset path (extension filter above);
    - a literal that resolved UNDER the resource's own directory: it is an
      asset/module reference (`import "./locales/en/main.json"`), not a
      request path. Only root-relative literals are runtime-prefix
      candidates - exactly the `/login`-under-`baseURL:"/api"` shape. Bundles
      served from the root directory keep every literal (no discriminator
      exists there)."""
    url = rec.get("url")
    if not isinstance(url, str) or not url:
        return None
    try:
        p = urlparse(url)
    except ValueError:
        return None
    if not p.netloc or f"{p.scheme}://{p.netloc}" != origin:
        return None
    path = p.path or "/"
    if path == "/" or path.endswith("/") or _STATIC_ASSET_EXT_RE.search(path):
        return None
    if path == prefix or path.startswith(prefix + "/"):
        return None
    resource_dir = _resource_dir(rec)
    if resource_dir != "/" and (
        path == resource_dir or path.startswith(resource_dir + "/")
    ):
        return None
    target = f"{p.scheme}://{p.netloc}{prefix}{path}"
    if p.query:
        target = f"{target}?{p.query}"
    out: dict = {
        "url": target,
        "method": rec.get("method") or "",
        "chained_prefix": prefix,
        "chained_from": url,
    }
    for key in ("queryParams", "bodyParams"):
        value = rec.get(key)
        if isinstance(value, list) and value:
            out[key] = list(value)
    return out


def bundle_origin(url: str) -> str:
    """`scheme://netloc` of `url` (the `base_url` anchor for recovered
    endpoints and secrets). `""` if unparseable."""
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


def _emit_jsluice(
    text: str, base: str, source_url: str, origin: str, run_jsluice, emit
) -> list[dict]:
    """Run both jsluice modes over `text`, emit every record annotated with
    `base_url` (the origin anchor) and `source_url` (the scanned resource), and
    return the url-bearing records for the caller's runtime-prefix chaining.

    `base` is the URL jsluice resolves relative literals against: the RESOURCE
    the literal lives in, never the origin root - a bundle at
    `/assets/index-abc.js` importing `./commands-x.js` means
    `/assets/commands-x.js`, and resolving against the origin minted the
    phantom `/commands-x.js` (2026-10-16 arm J diagnosis)."""
    url_records: list[dict] = []
    if not text:
        return url_records
    for mode in ("urls", "secrets"):
        out = run_jsluice(mode, text, base) or ""
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
            if mode == "urls" and isinstance(obj.get("url"), str) and obj["url"]:
                url_records.append(obj)
            emit(json.dumps(obj))
    return url_records


def scan_bundles(bundle_urls, *, fetch, run_jsluice, emit) -> None:
    """Core flow (injected `fetch(url)->str|None`, `run_jsluice(mode,text,base)
    ->str`, `emit(line)`), so tests drive it with no network/binary.

    Relative literals resolve against each scanned resource's URL. After the
    batch, every buffered root-relative literal of an origin is re-minted once
    per runtime path prefix the batch discovered in that origin's bundles
    (`chained_prefix` on the record) - the cross-bundle join per-bundle
    scanning alone cannot do. Dedups processed sourcemap URLs and
    content-hash-dedups source bodies so the same map / identical source
    across bundles is scanned once."""
    processed_maps: set[str] = set()
    seen_source_hashes: set[str] = set()
    prefixes_by_origin: dict[str, list[str]] = {}
    pending: list[tuple[str, dict]] = []

    def note_prefixes(text: str, origin: str) -> None:
        bucket = prefixes_by_origin.setdefault(origin, [])
        for prefix in extract_base_prefixes(text):
            if prefix not in bucket and len(bucket) < _MAX_BASE_PREFIXES:
                bucket.append(prefix)

    for burl in bundle_urls:
        origin = bundle_origin(burl)
        if not origin:
            continue

        # A direct `.map` URL IS the sourcemap - never fetch it as a bundle
        # (that would double-fetch and defeat the processed-map dedup).
        content = None
        if not burl.endswith(".map"):
            content = fetch(burl)
            if content:
                note_prefixes(content, origin)
                pending.extend(
                    (origin, rec)
                    for rec in _emit_jsluice(content, burl, burl, origin, run_jsluice, emit)
                )

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
            note_prefixes(body, origin)
            pending.extend(
                (origin, rec)
                for rec in _emit_jsluice(body, burl, burl, origin, run_jsluice, emit)
            )

    seen_chained: set[str] = set()
    for origin, rec in pending:
        for prefix in prefixes_by_origin.get(origin, ()):
            chained = _chained_record(origin, prefix, rec)
            if chained is None or chained["url"] in seen_chained:
                continue
            seen_chained.add(chained["url"])
            chained.setdefault("base_url", origin)
            source_url = rec.get("source_url")
            if isinstance(source_url, str) and source_url:
                chained.setdefault("source_url", source_url)
            emit(json.dumps(chained))


# --------------------------------------------------------------------------- #
# Real collaborators (used only when executed as a script inside the pod).     #
# --------------------------------------------------------------------------- #
def _real_fetch(url: str) -> str | None:
    import ssl
    import urllib.request

    # Recon egress fetches bundles from arbitrary, often-misconfigured targets
    # (a local vuln-by-design app with a self-signed cert, a mis-issued prod
    # cert). A TLS verification failure must NOT silently turn every https
    # bundle into a None fetch - the Go crawlers (katana/httpx) already ignore
    # cert errors, so this fetch would otherwise be the one link in the JS chain
    # that refuses a self-signed target. Disable verification for the fetch.
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "polymerhus-recon/jsluice"})
        with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:  # noqa: S310 (recon egress)
            raw = resp.read()
        return raw.decode("utf-8", "replace")
    except Exception:  # best-effort: an unreachable bundle/map degrades to skip
        return None


def _real_run_jsluice(mode: str, text: str, baseurl: str) -> str:
    import subprocess

    # `-j`/`--raw-input`: read the JS body from stdin. Without it jsluice treats
    # each stdin token as a FILENAME to open, so the piped bundle source is
    # scanned as zero files and jsluice emits nothing (the D17-rewrite
    # regression: the pre-D17 template was `jsluice urls -j -R <base>`; the `-j`
    # was lost when the job moved to this fetch-then-pipe scanner).
    args = ["jsluice", mode, "-j"]
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
