"""Shared response-header identity normalization for the parser fleet.

httpx's `-irh` JSON emits header keys with UNDERSCORES (`accept_ranges`,
`content_type` - verified live 2026-10-15), while katana's JSONL keeps the wire
form with dashes (`accept-ranges`, `content-type`). Both parsers identity a
`Header` node on `{name, baseurl}`, so without ONE canonical rule the same real
header becomes TWO L0 nodes and the two tools' observations never MERGE - the
same node-merge guarantee `_urls.py` states for URLs, restated for headers.

Canonical form: lowercase, with dashes, surrounding whitespace stripped.
The `_` -> `-` mapping is safe for real header tokens here: the underscore form
is a JSON-marshalling artifact of the tool, not a wire name.
"""
from __future__ import annotations


def canonical_header_name(name: str) -> str:
    """The canonical (`lowercase-with-dashes`) form of a header name.

    Returns `\"\"` for a non-string or blank name so callers skip it, never crash."""
    if not isinstance(name, str):
        return ""
    return name.strip().lower().replace("_", "-")
