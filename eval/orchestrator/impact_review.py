"""The `impact_review.yaml` schema and its validation.

The assessor writes one review beside `verdicts.yaml`. It labels each unit's
scope against the injected `threat_model_scope` and each impact row's mining
quality, so the measurement can distinguish a legitimate capability row from an
under-mined one. The file is optional for legacy runs and required when the eval
harness is configured with `EVAL_REQUIRE_IMPACT_REVIEW=1`.

A reviewed row may carry the scored identity of the schema-5 assessment row it
judges - `impact_description`, `exploitability_description`, `factors`, `risk`,
and `risk_vector` - so the label is paired with the values it judged. The
retired `damage` field is refused by name: the old vocabulary must not return.
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

# The eight authored CVSS 4.0 base factors of a schema-5 assessment row. The
# names mirror the hunting risk module; the standalone eval harness imports no
# polymerhus module, so the tuple is repeated here. A review that copies the
# factors must copy all eight: a partial factor set is malformed.
FACTOR_KEYS = (
    "attack_vector",
    "attack_complexity",
    "attack_requirements",
    "privileges_required",
    "user_interaction",
    "confidentiality",
    "integrity",
    "availability",
)
# The scored row's identity under schema 5 (spec 13). Every field is optional so
# a legacy review still loads, but a field that is present must be well formed.
SCORED_ROW_FIELDS = (
    "impact_description",
    "exploitability_description",
    "factors",
    "risk",
    "risk_vector",
)
# The retired schema-4 field. Refused with its replacement named, before the
# unknown-field check, so a stale assessor gets the actionable message.
RETIRED_ROW_FIELDS = ("damage",)
_ROW_FIELDS = frozenset({"id", "mining", "rationale", *SCORED_ROW_FIELDS})


class ReviewError(ValueError):
    """The impact review is malformed."""


@dataclass(frozen=True)
class ReviewedRow:
    id: str
    mining: str
    rationale: str
    impact_description: str | None = None
    exploitability_description: str | None = None
    factors: Mapping[str, Any] | None = None
    risk: float | None = None
    risk_vector: str | None = None


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


def _optional_text(mapping: Mapping[str, Any], key: str, label: str) -> str | None:
    value = mapping.get(key)
    return None if value is None else _text(value, label)


def _optional_number(mapping: Mapping[str, Any], key: str, label: str) -> float | None:
    """A numeric field; a bool is an int in Python and is not a score."""
    value = mapping.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ReviewError(f"{label} must be a number")
    return float(value)


def _optional_factors(
    mapping: Mapping[str, Any], key: str, label: str,
) -> Mapping[str, Any] | None:
    """The copied factor set: all eight base factors, each a value token."""
    value = mapping.get(key)
    if value is None:
        return None
    factors = _mapping(value, label)
    missing = [name for name in FACTOR_KEYS if name not in factors]
    if missing:
        raise ReviewError(f"{label} is missing factor(s): {', '.join(missing)}")
    for name in FACTOR_KEYS:
        _text(factors.get(name), f"{label}.{name}")
    return factors


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
            label = f"units[{index}].rows[{row_index}]"
            row = _mapping(raw_row, label)
            row_id = _text(row.get("id"), f"{label}.id")
            if row_id in seen_rows:
                raise ReviewError(
                    f"units[{index}].rows[{row_index}].id={row_id!r} is duplicated"
                )
            seen_rows.add(row_id)
            for retired in RETIRED_ROW_FIELDS:
                if retired in row:
                    raise ReviewError(
                        f"{label}.{retired} is retired; use impact_description"
                    )
            unknown = sorted(set(row) - _ROW_FIELDS)
            if unknown:
                raise ReviewError(f"{label}: unknown field(s) {', '.join(unknown)}")
            mining = _text(row.get("mining"), f"{label}.mining")
            if mining not in MINING:
                raise ReviewError(
                    f"{label}.mining={mining!r} is not {MINING}"
                )
            reviewed_rows.append(
                ReviewedRow(
                    id=row_id,
                    mining=mining,
                    rationale=str(row.get("rationale") or ""),
                    impact_description=_optional_text(
                        row, "impact_description", f"{label}.impact_description"),
                    exploitability_description=_optional_text(
                        row, "exploitability_description",
                        f"{label}.exploitability_description"),
                    factors=_optional_factors(row, "factors", f"{label}.factors"),
                    risk=_optional_number(row, "risk", f"{label}.risk"),
                    risk_vector=_optional_text(
                        row, "risk_vector", f"{label}.risk_vector"),
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
