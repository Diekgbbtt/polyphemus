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
  3. dedup by basename across hosts - the same fingerprinted SPA bundle set
     duplicated across tenant subdomains collapses to one scan (content-hash of
     the recovered *sources* is a second, finer dedup inside the pod).

All functions are pure and deterministic (stable ordering) so the reductions
and batch construction are unit-testable without Neo4j or a pod.
"""
from __future__ import annotations

import base64
import shlex
from pathlib import Path
from urllib.parse import urlparse

from agent.recon.parsers._urls import registrable_domain
from agent.recon.types import JobSpec

_RUNNER = Path(__file__).resolve().parent / "scripts" / "jsluice_scan.py"


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
    seen_basenames: set[str] = set()
    reduced: list[str] = []
    for u in urls:
        if u in seen_urls:
            continue
        seen_urls.add(u)
        base = _basename(u)
        if base in seen_basenames:
            continue
        seen_basenames.add(base)
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
