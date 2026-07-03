"""Shared JSONL iteration + value-type guard helpers for the parser fleet.

Every JSONL-based parser (httpx, subfinder, amass, dnsx, naabu, katana, ...)
used to inline the same `for line in stdout.splitlines(): json.loads(line)`
loop, and several of them called `.get(...)` on the parsed object without
first checking it was actually a `dict` - a syntactically-valid-but-non-dict
JSON line (e.g. `42`, `[1,2,3]`, `"a"`, `null`) would then raise
`AttributeError` and abort the whole `parse()` call, discarding every delta
already accumulated for that tool run.

`iter_json_dicts` centralizes the tolerant-iteration contract: skip blank
lines, skip invalid JSON, skip valid-but-non-dict JSON, yield only dicts, in
input order. `safe_str` centralizes the value-type guard for `.get()`-sourced
fields that get passed to string ops (`urlparse`, `.encode()`, `.lower()`,
`.strip()`, `.split()`, ...) - a valid dict whose field holds a non-string
value (e.g. `{"url": 12345}`) must not crash those call sites either.

Both are pure, deterministic, and never raise.
"""
import json
from collections.abc import Iterator


def iter_json_dicts(stdout: str) -> Iterator[dict]:
    """Yield each JSONL line of `stdout` that decodes to a dict, in order.

    Blank lines, invalid JSON, and valid-but-non-dict JSON (numbers, lists,
    strings, null, bools) are silently skipped.
    """
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue

        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        if isinstance(obj, dict):
            yield obj


def safe_str(value: object) -> str | None:
    """Return `value` if it is a non-empty `str`, else `None`."""
    if isinstance(value, str) and value:
        return value
    return None
