"""Shared URL -> graph-delta decomposition helpers.

Extracted from the ~6 near-identical BaseURL+Endpoint(+HAS_ENDPOINT)+
Parameter(+HAS_PARAMETER) implementations that had accreted across the
parser fleet (katana, passive_url, active_param arjun/ffuf/kiterunner,
jsluice, graphql, httpx) - see the SP2 whole-fleet review, findings F2-F5.

Routing every URL-emitting parser through `url_to_deltas`/`base_and_path`
guarantees the same URL discovered by two different tools always MERGEs to
one `BaseURL`/`Endpoint` node in the graph: identical normalization
(`scheme://netloc` for baseurl, `.upper()` for method) everywhere instead of
six independent, silently-divergable copies.

Pure, deterministic, tolerant of malformed input - never raises.
"""
from urllib.parse import parse_qs, urlparse

from polymerhus.recon.domain.noise_filter import (
    CACHE_BUST_KEYS,
    is_malformed_concat_path,
)
from polymerhus.recon.domain.types import AssetDelta, Edge


def base_and_path(url: str) -> tuple[str, str] | None:
    """Return `(scheme://netloc, path)` for an absolute URL, else `None`.

    `path` defaults to `"/"` when empty. No further normalization (e.g.
    default-port stripping) is performed - this is the single source of
    `baseurl` identity truth for every URL-emitting parser.
    """
    if not isinstance(url, str) or not url:
        return None

    try:
        parsed = urlparse(url)
    except ValueError:
        return None

    if not parsed.scheme or not parsed.netloc:
        return None

    return f"{parsed.scheme}://{parsed.netloc}", (parsed.path or "/")


def url_to_deltas(
    url: str,
    *,
    method: str = "GET",
    source: str,
    extra_endpoint_props: dict | None = None,
    query_params: list[str] | None = None,
    body_params: list[str] | None = None,
) -> list[AssetDelta]:
    """Decompose one discovered URL into BaseURL + Endpoint(+edge) + Parameters(+edges).

    - `BaseURL{url: scheme://netloc}` (no props).
    - `Endpoint{path, method, baseurl}` identity, `props={url, source, **extra}`,
      with an inbound `HAS_ENDPOINT` edge from the `BaseURL` reusing the exact
      `BaseURL` identity dict object.
    - One `Parameter{name, position:"query", endpoint_path, baseurl}` per
      query-string key, with an inbound `HAS_PARAMETER` edge from the
      `Endpoint` reusing the exact `Endpoint` identity dict object.

    Returns `[]` if `url` is not an absolute (scheme+netloc) URL.
    `method` is `.upper()`-normalized; a non-string method defaults to `"GET"`.
    """
    split = base_and_path(url)
    if split is None:
        return []

    baseurl, path = split

    # A JS string-concatenation fragment is not a real path - drop the whole
    # URL (endpoint + any params) so it never becomes an Endpoint (AMV-8).
    if is_malformed_concat_path(path):
        return []

    if not isinstance(method, str) or not method:
        method = "GET"
    method = method.upper()

    deltas: list[AssetDelta] = [
        AssetDelta(type="BaseURL", identity={"url": baseurl}),
    ]

    endpoint_props = {"url": url, "source": source}
    if extra_endpoint_props:
        endpoint_props.update(extra_endpoint_props)

    endpoint_identity = {"path": path, "method": method, "baseurl": baseurl}
    deltas.append(
        AssetDelta(
            type="Endpoint",
            identity=endpoint_identity,
            props=endpoint_props,
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

    def _param(name: str, position: str) -> AssetDelta:
        return AssetDelta(
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

    # Query parameters: the URL's own query string PLUS any explicit
    # `query_params` a caller passes (jsluice's `queryParams`, katana GET-form
    # fields). Body parameters (`body_params`: jsluice `bodyParams`, katana
    # POST-form fields) are never in the query string. Deduped on (name,
    # position) so a name appearing in both the URL and the explicit list is one
    # node. Cache-bust stamps are still never parameters (AMV-8).
    seen: set[tuple[str, str]] = set()
    url_query = parse_qs(urlparse(url).query, keep_blank_values=True)
    for name in list(url_query) + list(query_params or []):
        if name.lower() in CACHE_BUST_KEYS:
            continue
        key = (name, "query")
        if key in seen:
            continue
        seen.add(key)
        deltas.append(_param(name, "query"))
    for name in body_params or []:
        key = (name, "body")
        if key in seen:
            continue
        seen.add(key)
        deltas.append(_param(name, "body"))

    return deltas


def registrable_domain(host: str) -> str:
    """Last-two-labels heuristic for a host's registrable parent domain.

    Deliberately naive (no public-suffix-list awareness) - kept AS-IS per
    the SP2 fix-bundle brief; a PSL-aware upgrade is deferred to a later
    sub-plan. Moved here from the byte-identical `_parent_domain` copies in
    `subdomain_parser` and `takeover_parser`.
    """
    labels = host.split(".")
    if len(labels) <= 2:
        return host
    return ".".join(labels[-2:])
