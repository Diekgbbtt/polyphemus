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

    query_params = parse_qs(urlparse(url).query, keep_blank_values=True)
    for name in query_params:
        deltas.append(
            AssetDelta(
                type="Parameter",
                identity={
                    "name": name,
                    "position": "query",
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
