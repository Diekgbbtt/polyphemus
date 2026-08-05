"""The fault-KB loader - the two-facet read of the phase-1 catalogue (#66).

The catalogue (`data/fault-kb.yaml`) is a versioned static artifact produced
out-of-band by `tools/hunting/curate_fault_kb.py` (CWE v4.20 entered through
the reviewed OWASP Top 10 2025 seed mapping). This module reads it and exposes
the spec's two facets (spec section 6):

  * `load_fault_entries` - the MATCHING facet: each YAML entry projected into
    `fault_source.FaultEntry`. A typed `applies_if.predicate` is parsed back
    into the #63 `TypedPredicate` and validated against the same grammar the
    curation fold used - a malformed predicate is surfaced by the loader's own
    validation (the curation-time hard-error contract, surfaced again at read),
    never silently dropped.
  * `load_materialisation` - the MATERIALISATION facet: rich NL content by
    `fault_id` for the prompt-builder (probe-materialisation grounding).

Fail-open contract: a missing or malformed catalogue yields an EMPTY KB (an
empty tuple / empty mapping), never an exception to the caller - consistent
with the fail-open selection contract (an unhardened, untagged entry prunes
nothing). The loader imports no driver and performs no I/O at import; the
catalogue path resolves lazily on first call (CODING_STANDARD section 6).

This module mints no L0/L1 nodes and touches no database - it is the attack
context's own data seam, not a graph consumer.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Mapping

import yaml

from polymerhus.attack.hunting.fault_source import FaultEntry
from polymerhus.attack.hunting.predicate import (
    Clause,
    ClauseForm,
    TypedPredicate,
    validate_predicate,
)
from polymerhus.analysis.l1_curator import SYSTEM_KINDS

log = logging.getLogger(__name__)

_SYSTEM_KIND_IDS = frozenset(kind for kind, _desc in SYSTEM_KINDS)
_CLAUSE_FORMS = {form.value: form for form in ClauseForm}

# The in-repo catalogue (packaged beside this module). Callers may override
# with a fixture path in tests; resolution is lazy (no I/O at import).
_DEFAULT_CATALOGUE: Path | None = None


def _default_catalogue_path() -> Path:
    """The packaged catalogue path, resolved lazily on first use."""
    global _DEFAULT_CATALOGUE
    if _DEFAULT_CATALOGUE is None:
        _DEFAULT_CATALOGUE = (
            Path(resources.files("polymerhus.attack.hunting.data").joinpath(
                "fault-kb.yaml"))  # type: ignore[union-attr]
            if resources.files("polymerhus.attack.hunting.data").is_file()
            else Path(__file__).resolve().parent / "data" / "fault-kb.yaml"
        )
    return _DEFAULT_CATALOGUE


@dataclass(frozen=True)
class FaultMaterialisation:
    """The materialisation facet of one fault entry (spec section 4): the rich
    NL content a hunting agent consumes to materialise a probe."""

    fault_id: str
    name: str
    description: str
    extended_description: str | None = None
    alternate_terms: tuple[str, ...] = ()
    related_attack_patterns: tuple[str, ...] = ()
    likelihood: str | None = None
    common_consequences: tuple[str, ...] = ()


def _parse_predicate(raw: object, fault_id: str) -> TypedPredicate | None:
    """The catalogue's predicate mapping back into the #63 TypedPredicate,
    validated (the loader's own read-time validation). `None` stays `None`."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError(
            f"{fault_id}: applies_if.predicate must be a mapping or null, "
            f"got {type(raw).__name__}")
    target = raw.get("target")
    if target not in ("Service", "System", "Both"):
        raise ValueError(
            f"{fault_id}: predicate.target must be one of Service/System/Both, "
            f"got {target!r}")
    raw_clauses = raw.get("clauses")
    if not isinstance(raw_clauses, list) or not raw_clauses:
        raise ValueError(
            f"{fault_id}: predicate needs a non-empty 'clauses' list")
    clauses = []
    for raw_clause in raw_clauses:
        if not isinstance(raw_clause, dict):
            raise ValueError(
                f"{fault_id}: each predicate clause must be a mapping, "
                f"got {type(raw_clause).__name__}")
        form_raw = raw_clause.get("form")
        form = _CLAUSE_FORMS.get(form_raw) if isinstance(form_raw, str) else None
        if form is None:
            raise ValueError(
                f"{fault_id}: unsupported clause form {raw_clause.get('form')!r}")
        values = tuple(raw_clause.get("values") or ())
        key = raw_clause.get("key")
        if key is not None and not isinstance(key, str):
            raise ValueError(
                f"{fault_id}: clause key must be a string or null, "
                f"got {type(key).__name__}")
        role = raw_clause.get("role")
        clauses.append(Clause(form, key=key if isinstance(key, str) else None,
                              values=values, role=role))
    predicate = TypedPredicate(target=target, clauses=tuple(clauses))
    try:
        validate_predicate(predicate)
    except ValueError as exc:
        raise ValueError(f"{fault_id}: invalid predicate: {exc}") from exc
    return predicate


def _parse_entry(raw: object) -> FaultEntry:
    """One YAML entry into the matching-facet shape, validated."""
    if not isinstance(raw, dict):
        raise ValueError(
            f"catalogue entry must be a mapping, got {type(raw).__name__}")
    fault_id = raw.get("fault_id")
    if not isinstance(fault_id, str) or not fault_id:
        raise ValueError("catalogue entry missing a string fault_id")
    applies_if = raw.get("applies_if")
    if not isinstance(applies_if, dict):
        raise ValueError(f"{fault_id}: missing applies_if mapping")
    predicate = _parse_predicate(applies_if.get("predicate"), fault_id)
    enum_kinds_raw = raw.get("enum_kinds") or ()
    enum_kinds = frozenset(enum_kinds_raw)
    unknown = enum_kinds - _SYSTEM_KIND_IDS
    if unknown:
        raise ValueError(
            f"{fault_id}: enum_kinds {sorted(unknown)} not in SYSTEM_KINDS")
    return FaultEntry(fault_id=fault_id, predicate=predicate,
                      enum_kinds=enum_kinds)


def _parse_materialisation(raw: object) -> FaultMaterialisation | None:
    """One YAML entry into the materialisation shape (None if malformed: the
    matching facet is the load-bearing read, content failure degrades)."""
    if not isinstance(raw, dict):
        return None
    fault_id = raw.get("fault_id")
    materialisation = raw.get("materialisation")
    if not isinstance(fault_id, str) or not isinstance(materialisation, dict):
        return None
    return FaultMaterialisation(
        fault_id=fault_id,
        name=str(raw.get("name") or ""),
        description=str(materialisation.get("description") or ""),
        extended_description=(
            str(materialisation["extended_description"])
            if materialisation.get("extended_description") else None),
        alternate_terms=tuple(str(t) for t in
                              (materialisation.get("alternate_terms") or ())),
        related_attack_patterns=tuple(
            str(p) for p in
            (materialisation.get("related_attack_patterns") or ())),
        likelihood=(str(materialisation["likelihood"])
                    if materialisation.get("likelihood") else None),
        common_consequences=tuple(
            str(c) for c in
            (materialisation.get("common_consequences") or ())),
    )


def _read_catalogue(path: Path | str | None) -> list[object]:
    """Read + parse the catalogue file. Raises on I/O or YAML failure; the
    public seam converts that into the fail-open empty KB."""
    resolved = Path(path) if path is not None else _default_catalogue_path()
    with open(resolved, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if data is None:
        return []
    if not isinstance(data, list):
        raise ValueError(
            f"catalogue {resolved}: expected a list of entries, "
            f"got {type(data).__name__}")
    return data


def load_fault_entries(path: Path | str | None = None) -> tuple[FaultEntry, ...]:
    """The MATCHING facet (spec section 6): the catalogue as the selection
    entry consumes it.

    A missing or malformed catalogue fails open to an EMPTY KB (never crashes
    the caller); a malformed ENTRY is skipped with a logged diagnostic, never
    dropped silently - the remaining entries stay usable (fail-open per entry,
    consistent with the per-entry degrade contract).
    """
    try:
        rows = _read_catalogue(path)
    except Exception as exc:  # noqa: BLE001 - fail-open is the contract
        log.warning("fault-KB catalogue read failed (fail-open to empty): %s",
                    exc)
        return ()
    entries: list[FaultEntry] = []
    for row in rows:
        try:
            entries.append(_parse_entry(row))
        except Exception as exc:  # noqa: BLE001 - per-entry fail-open
            log.warning("skipping malformed fault-KB entry: %s", exc)
    return tuple(entries)


def load_materialisation(
        path: Path | str | None = None) -> Mapping[str, FaultMaterialisation]:
    """The MATERIALISATION facet (spec section 6): rich NL content by
    `fault_id` for the prompt-builder. Fail-open to an empty map on a missing
    or malformed catalogue."""
    try:
        rows = _read_catalogue(path)
    except Exception as exc:  # noqa: BLE001 - fail-open is the contract
        log.warning("fault-KB catalogue read failed (fail-open to empty): %s",
                    exc)
        return {}
    by_id: dict[str, FaultMaterialisation] = {}
    for row in rows:
        materialisation = _parse_materialisation(row)
        if materialisation is not None:
            by_id[materialisation.fault_id] = materialisation
    return by_id
