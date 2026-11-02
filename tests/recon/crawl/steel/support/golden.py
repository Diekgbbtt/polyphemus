"""Compare a value to a checked-in golden file with a readable diff.

JSON goldens compare by value (key order and whitespace do not matter); text
goldens compare line for line with only the trailing newline normalised.
"""
from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel


def assert_matches_golden(
    actual: Any,
    golden_path: str | Path,
    *,
    label: str | None = None,
) -> None:
    """Assert `actual` matches the checked-in file, diffing loudly on mismatch."""
    path = Path(golden_path)
    try:
        golden_text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"golden file not found: {path}") from exc

    expected = _render_golden(golden_text, path.suffix)
    observed = _render_actual(actual, path.suffix)
    if observed == expected:
        return

    diff = "\n".join(
        difflib.unified_diff(
            expected.splitlines(),
            observed.splitlines(),
            fromfile=f"golden: {path}",
            tofile=f"actual: {label or path.name}",
            lineterm="",
        )
    )
    raise AssertionError(f"golden mismatch: {path}\n{diff}")


def _render_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False)


def _render_golden(text: str, suffix: str) -> str:
    if suffix == ".json":
        return _render_json(json.loads(text))
    return text.rstrip("\n")


def _render_actual(value: Any, suffix: str) -> str:
    if suffix == ".json":
        if isinstance(value, BaseModel):
            value = value.model_dump(mode="json")
        if isinstance(value, str):
            value = json.loads(value)
        return _render_json(value)
    return (value if isinstance(value, str) else str(value)).rstrip("\n")
