"""Pure predicate matching for `JobSpec.consumes_where` (forward-decision D17/Q5).

`read_assets` narrows a job's input population by label first; a job that wants
a sub-slice of that label (jsluice: only the `.js`/`.mjs` bundles among all
`Endpoint`s) declares an `AssetSelector` and the pipeline filters the read-back
dicts through `apply_selector` here. The selector is a plain data structure and
this module is the single place its ops are interpreted - reusable across any
future label-plus-predicate consumer, not a jsluice special case.

Kept pure and tolerant: a non-string field value never matches (returns False)
rather than raising, so a malformed/absent property degrades to exclusion.
"""
from __future__ import annotations

from agent.recon.types import AssetSelector


def selector_matches(asset: dict, selector: AssetSelector) -> bool:
    """True when `asset[selector.field]` (a string) satisfies the op against any
    of `selector.values`. A missing or non-string field value is False."""
    value = asset.get(selector.field)
    if not isinstance(value, str):
        return False

    op = selector.op
    if op == "ends_with":
        return any(value.endswith(v) for v in selector.values)
    if op == "starts_with":
        return any(value.startswith(v) for v in selector.values)
    if op == "contains":
        return any(v in value for v in selector.values)
    if op == "equals":
        return value in selector.values
    return False


def apply_selector(assets: list[dict], selector: AssetSelector | None) -> list[dict]:
    """Filter `assets` to those matching `selector`. `None` selector is a
    pass-through (identity), so callers can apply it unconditionally."""
    if selector is None:
        return list(assets)
    return [a for a in assets if selector_matches(a, selector)]
