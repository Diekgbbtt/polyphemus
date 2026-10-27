"""The `impact_review.yaml` schema and its validation.

The assessor writes one review beside `verdicts.yaml`. It labels each unit's
scope against the injected `threat_model_scope` and each impact row's mining
quality, so the measurement can distinguish a legitimate capability row from an
under-mined one. The file is optional for legacy runs and required when the eval
harness is configured with `EVAL_REQUIRE_IMPACT_REVIEW=1`.

A malformed review is rejected loudly before the close verification passes.
Import performs no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from orchestrator.files import FileStore

REVIEW_FILENAME = "impact_review.yaml"
SCOPES = ("in", "out")
MINING = ("sufficient", "under_mined")


class ReviewError(ValueError):
    """The impact review is malformed."""


@dataclass(frozen=True)
class ReviewedRow:
    id: str
    mining: str
    rationale: str


@dataclass(frozen=True)
class ReviewedUnit:
    unit: str
    scope: str
    scope_reason: str
    rows: tuple[ReviewedRow, ...]


def review_path(destination: str | Path) -> Path:
    """The review sibling of an assessment destination (`verdicts.yaml`)."""
    target = Path(destination)
    return target.with_name(REVIEW_FILENAME)


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReviewError(f"{label} must be a mapping")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReviewError(f"{label} must be a non-empty string")
    return value.strip()


def load_review(path: str | Path, *, files: FileStore) -> tuple[ReviewedUnit, ...]:
    """Parse and validate one review document.

    Every unit names its scope and every row names its mining verdict. A row id
    is unique within its unit; the same id in two units is valid because the
    measurement keys the label by `unit::id`.
    """
    raw = yaml.safe_load(files.read_text(path))
    document = _mapping(raw, "impact_review")
    units = document.get("units")
    if not isinstance(units, list) or not units:
        raise ReviewError("impact_review.units must be a non-empty list")
    reviewed: list[ReviewedUnit] = []
    seen_units: set[str] = set()
    for index, item in enumerate(units):
        unit = _mapping(item, f"units[{index}]")
        unit_id = _text(unit.get("unit"), f"units[{index}].unit")
        if unit_id in seen_units:
            raise ReviewError(f"units[{index}].unit={unit_id!r} is duplicated")
        seen_units.add(unit_id)
        scope = _text(unit.get("scope"), f"units[{index}].scope")
        if scope not in SCOPES:
            raise ReviewError(f"units[{index}].scope={scope!r} is not {SCOPES}")
        scope_reason = str(unit.get("scope_reason") or "")
        rows = unit.get("rows")
        if not isinstance(rows, list) or not rows:
            raise ReviewError(f"units[{index}].rows must be a non-empty list")
        seen_rows: set[str] = set()
        reviewed_rows: list[ReviewedRow] = []
        for row_index, raw_row in enumerate(rows):
            row = _mapping(raw_row, f"units[{index}].rows[{row_index}]")
            row_id = _text(row.get("id"), f"units[{index}].rows[{row_index}].id")
            if row_id in seen_rows:
                raise ReviewError(
                    f"units[{index}].rows[{row_index}].id={row_id!r} is duplicated"
                )
            seen_rows.add(row_id)
            mining = _text(row.get("mining"), f"units[{index}].rows[{row_index}].mining")
            if mining not in MINING:
                raise ReviewError(
                    f"units[{index}].rows[{row_index}].mining={mining!r} is not {MINING}"
                )
            reviewed_rows.append(
                ReviewedRow(
                    id=row_id,
                    mining=mining,
                    rationale=str(row.get("rationale") or ""),
                )
            )
        reviewed.append(
            ReviewedUnit(
                unit=unit_id,
                scope=scope,
                scope_reason=scope_reason,
                rows=tuple(reviewed_rows),
            )
        )
    return tuple(reviewed)
