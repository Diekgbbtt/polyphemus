"""Bundle reduction + pod batching for high-volume, per-item jobs (D17/Q6).

jsluice must analyze every first-party JS bundle, but a large target yields
hundreds (houseofhr: 653 distinct bundle paths) against a fixed `MAX_PODS`
budget. One-pod-per-bundle blows the budget ~33x, so instead we BATCH: cheap
reductions first, then distribute the survivors across `<= max_pods` pods, each
pod running one command over its whole batch (`build_jsluice_command`).

Reductions (cheapest, before batching):
  1. same-origin / first-party filter - drop third-party CDN bundles that are
     out of scope and carry no value (`assets.allegrostatic.com`, tag managers);
  2. dedup by exact bundle URL;
  3. dedup FINGERPRINTED basenames across hosts - the same content-hashed SPA
     bundle set duplicated across tenant subdomains collapses to one scan. A
     generic basename (`main.js`, `index.js` with no hash) is NOT deduped
     across hosts: each host's copy may be genuinely distinct, so it survives
     to the pod, where the md5 source-body dedup is the finer, fetch-aware net.

All functions are pure and deterministic (stable ordering) so the reductions
and batch construction are unit-testable without Neo4j or a pod.
"""
from __future__ import annotations

import base64
import re
import shlex
from pathlib import Path
from urllib.parse import urlparse

from polymerhus.recon.domain.parsers._urls import base_and_path, registrable_domain
from polymerhus.recon.domain.types import JobSpec

# This file is recon/control/batching.py; the runner lives at recon/scripts/,
# so it is parents[1] (recon) / "scripts".
_RUNNER = Path(__file__).resolve().parents[1] / "scripts" / "jsluice_scan.py"

# Fingerprint definition MIRRORS D15's `src/polymerhus/recon/domain/noise_filter.py` rule (that
# stream is on a separate unmerged branch, so the regex/marker set is replicated
# here rather than imported; DRY them on consolidation). A filename is
# "fingerprinted" when it carries a >=8-char hex content hash delimited before a
# js/css/mjs extension, OR contains a bundler-marker token. Only fingerprinted
# basenames are content-stable enough to dedup across hosts.
_FINGERPRINT_RE = re.compile(r"[.\-_][0-9a-f]{8,}\.(?:js|css|mjs)$")
_BUNDLER_MARKER_RE = re.compile(r"(?:^|[.\-_])(?:chunk|runtime|polyfill|vendor)(?:[.\-_]|$)")
_BUNDLE_EXTS = frozenset({"js", "css", "mjs"})


def _is_fingerprinted(filename: str) -> bool:
    """True when `filename` is a content-hashed / bundler-marked bundle name -
    the D15 fingerprint rule. Such names identify identical content across
    hosts; generic names (`main.js`) do not."""
    if _FINGERPRINT_RE.search(filename):
        return True
    ext = filename.rpartition(".")[2].lower() if "." in filename else ""
    return ext in _BUNDLE_EXTS and bool(_BUNDLER_MARKER_RE.search(filename))


def bundle_url(asset: dict) -> str | None:
    """The absolute bundle URL an Endpoint asset points at: its `url` prop, else
    reconstructed from `baseurl` + `path`. `None` if neither is derivable."""
    url = asset.get("url")
    if isinstance(url, str) and url:
        return url
    baseurl = asset.get("baseurl")
    path = asset.get("path")
    if isinstance(baseurl, str) and baseurl and isinstance(path, str) and path:
        return baseurl.rstrip("/") + path
    return None


def is_first_party(url: str, apex_registrable: str) -> bool:
    """True when `url`'s host shares the target's registrable domain. `apex_
    registrable` is expected already-registrable (e.g. `houseofhr.com`)."""
    try:
        host = urlparse(url).netloc.split("@")[-1].split(":")[0]
    except ValueError:
        return False
    if not host:
        return False
    return registrable_domain(host) == apex_registrable


def _basename(url: str) -> str:
    """Filename of the URL path (`/static/app.4f3a.js` -> `app.4f3a.js`). Falls
    back to the whole URL when there is no path segment, so an empty basename
    never collapses unrelated URLs together."""
    path = urlparse(url).path
    name = path.rsplit("/", 1)[-1]
    return name or url


def reduce_bundles(assets: list[dict], *, apex_registrable: str | None = None) -> list[str]:
    """Apply the three cheap reductions and return the surviving bundle URLs in
    stable first-seen order."""
    urls: list[str] = []
    for a in assets:
        u = bundle_url(a)
        if u is not None:
            urls.append(u)

    if apex_registrable:
        urls = [u for u in urls if is_first_party(u, apex_registrable)]

    seen_urls: set[str] = set()
    seen_fingerprints: set[str] = set()
    reduced: list[str] = []
    for u in urls:
        if u in seen_urls:
            continue
        seen_urls.add(u)
        base = _basename(u)
        # Cross-host basename dedup is gated on the fingerprint rule: a hashed
        # bundle name is content-stable, so a second host's identical copy is
        # dropped; a generic name (main.js) is kept per host (recall-safe).
        if _is_fingerprinted(base):
            if base in seen_fingerprints:
                continue
            seen_fingerprints.add(base)
        reduced.append(u)
    return reduced


def build_batches(items: list[str], max_pods: int) -> list[list[str]]:
    """Distribute `items` round-robin into `min(max_pods, len(items))` batches so
    sizes differ by at most one. Returns `[]` for no items; every returned batch
    is non-empty."""
    n = len(items)
    if n == 0 or max_pods <= 0:
        return []
    k = min(max_pods, n)
    batches: list[list[str]] = [[] for _ in range(k)]
    for i, item in enumerate(items):
        batches[i % k].append(item)
    return batches


def build_batch_assets(
    assets: list[dict], *, apex_registrable: str | None, max_pods: int
) -> list[dict]:
    """Reduce then batch a job's read-back input assets into synthetic per-pod
    input assets, each carrying a `batch` list of bundle URLs. This is the seam
    that bends the one-input-asset-per-pod model: the pipeline swaps the raw
    per-bundle assets for these before pod fan-out, so the existing 1:1
    `preprocess_fn` cap maps one batch -> one pod."""
    reduced = reduce_bundles(assets, apex_registrable=apex_registrable)
    return [{"batch": batch} for batch in build_batches(reduced, max_pods)]


def build_jsluice_command(bundle_urls: list[str]) -> str:
    """Self-contained pod command: base64-embed `scripts/jsluice_scan.py` and
    run it over the batch's bundle URLs (shell-quoted argv). Embedding keeps the
    command portable - no Kali-image rebuild to ship the scanner."""
    script_b64 = base64.b64encode(_RUNNER.read_bytes()).decode()
    args = " ".join(shlex.quote(u) for u in bundle_urls)
    cmd = f"echo {script_b64} | base64 -d | python3 - {args}"
    return cmd.rstrip()


def build_batch_command(job: JobSpec, batch: list[str]) -> str:
    """Build the pod command for a batched job. Dispatches on tool; jsluice is
    the only batched tool today, but the seam is explicit so a future batched
    tool registers here rather than special-casing the pod configurator."""
    if job.tool == "jsluice":
        return build_jsluice_command(batch)
    raise ValueError(f"no batch command builder registered for tool {job.tool!r}")


# --------------- endpoint-profiling input-prep (D16 per-endpoint split) --------------- #
# The reprofile pass consumes the Endpoint population and actively re-probes each
# endpoint's own URL so it carries its OWN `profile` (not just the BaseURL root).
# Two preparations keep that bounded + complete on a resource-constrained host:
# dedup dynamic routes to one probe, and materialise a root `/` per BaseURL so
# the root mirror is always set. Pure + deterministic; unit-tested in test_batching.
_HEXISH = frozenset("0123456789abcdefABCDEF-")


def _path_template(path: str) -> str:
    """Collapse dynamic segments (numeric ids, long hex/uuid tokens) to '*', so
    `/users/1` and `/users/2` share one probe template."""
    out = []
    for seg in path.split("/"):
        if seg and (seg.isdigit() or (len(seg) >= 8 and all(c in _HEXISH for c in seg))):
            out.append("*")
        else:
            out.append(seg)
    return "/".join(out)


def _endpoint_baseurl(asset: dict) -> str | None:
    """The BaseURL of an Endpoint asset: its `baseurl`, else derived from `url`."""
    b = asset.get("baseurl")
    if isinstance(b, str) and b:
        return b
    url = asset.get("url")
    if isinstance(url, str):
        split = base_and_path(url)
        if split is not None:
            return split[0]
    return None


def prepare_endpoint_profile_assets(assets: list[dict]) -> list[dict]:
    """Prepare the endpoint-profiling pass's probe set (D16 per-endpoint split).

    1. Dedup to one probe per `(baseurl, method, path-template)`, so dynamic
       routes (`/users/1`, `/users/2`) cost a single request, not one each.
    2. Materialise a synthetic root `/` Endpoint for every BaseURL lacking one,
       so the root is always probed and `BaseURL.profile` (its root mirror) set.

    Pure + deterministic: survivors keep input order, synthesised roots follow in
    first-seen baseurl order. Assets with no derivable baseurl are dropped.
    """
    seen: set[tuple] = set()
    kept: list[dict] = []
    baseurl_order: list[str] = []
    baseurl_set: set[str] = set()
    has_root: set[str] = set()

    for asset in assets:
        baseurl = _endpoint_baseurl(asset)
        if baseurl is None:
            continue
        if baseurl not in baseurl_set:
            baseurl_set.add(baseurl)
            baseurl_order.append(baseurl)
        path = asset.get("path") or "/"
        method = (asset.get("method") or "GET").upper()
        if path == "/":
            has_root.add(baseurl)
        key = (baseurl, method, _path_template(path))
        if key in seen:
            continue
        seen.add(key)
        kept.append(asset)

    synth = [
        {"url": f"{baseurl}/", "baseurl": baseurl, "path": "/", "method": "GET"}
        for baseurl in baseurl_order
        if baseurl not in has_root
    ]
    return kept + synth
