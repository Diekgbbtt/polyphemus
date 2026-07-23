"""Pure parsers: gau / paramspider plain-text URL stdout -> list[AssetDelta].

Both tools emit one URL per line (plain text, NOT json):

    https://host/path?id=1&q=x

gau emits bare discovered URLs. paramspider emits URLs where query parameter
*values* are replaced with a placeholder (default `FUZZ`, e.g.
`https://host/path?id=FUZZ`) - only the parameter *names* matter here, so the
placeholder value is irrelevant and never leaks into node identity.

Each URL yields a `BaseURL` (scheme://netloc), an `Endpoint` (path/method under
that BaseURL, method fixed to "GET" since these are passive/historical URL
sources with no live method info) with a `HAS_ENDPOINT` edge, and one
`Parameter` per query-string key with a `HAS_PARAMETER` edge from the
`Endpoint`. The edge's `node_identity` reuses the exact same identity dict
object built for the Endpoint delta so it byte-matches for curation.

Pure, deterministic, tolerant of blank/malformed lines - never raises.
"""
from polymerhus.recon.domain.parsers._urls import url_to_deltas
from polymerhus.recon.domain.types import AssetDelta


def _url_to_deltas(url: str, source: str) -> list[AssetDelta]:
    return url_to_deltas(url, method="GET", source=source)


def _parse_lines(stdout: str, source: str) -> list[AssetDelta]:
    deltas: list[AssetDelta] = []

    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue

        deltas.extend(_url_to_deltas(line, source))

    return deltas


def parse_gau(stdout: str) -> list[AssetDelta]:
    return _parse_lines(stdout, source="gau")


def parse_paramspider(stdout: str) -> list[AssetDelta]:
    return _parse_lines(stdout, source="paramspider")
