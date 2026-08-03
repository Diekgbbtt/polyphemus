"""The typed applies-if predicate grammar + authoring-time validator (#63).

The typed predicate is the hardened form of the fault-KB `applies-if` slot
(`docs/design/hunting-63-typed-applies-if-spec.md` section 2.3, D-C): ONE
predicate per fault entry, `target` declaration + an AND of 1..N
necessary-condition clauses, evaluated deterministically at the head of
FaultSource selection (section 2.1).

This module owns the grammar and the validator only - never evaluation. The
authoring-time validator HARD-REJECTS unsupported clause forms, value clauses
over unvalidated facets, and malformed structure (C4), mirroring the
`DATA_RELATIONSHIP_KINDS` hard-reject discipline (`l1_curator.py:109-116`):
a bad predicate is caught at authoring, never at runtime, never silently
dropped.

The controlled vocabularies are single-sourced from the analysis context -
never duplicated here, so the predicate can never drift from what L1 can type:
the 12-kind System vocabulary and the §6 System-edge families
(`l1_curator.py:83-101,129-133`), the six DataRelationship kinds
(`l1_curator.py:109-116`), the data-flow edge types (`_DATA_FLOW_RELS`), and
the typed spine keys (`index_card.py:27-30`). `_SPINE_KEYS` and `_DATA_FLOW_RELS`
are private analysis constants; importing them is the established
single-source pattern of this codebase (e.g. `_PENDING_PROJECT_ID` is imported
by the impure orchestrators). The spec's D4 note documents the spine-key
superset semantics.

The `serves-units-with` clause form is part of the phase-1 closed grammar
(section 2.3) but is UNAVAILABLE to authors until D3 (the System-to-Services
inverse read) lands - the validator always rejects it, an inert dormant seam
named rather than faked (CODING_STANDARD section 12).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal

from polymerhus.analysis.index_card import _SPINE_KEYS
from polymerhus.analysis.l1_curator import (
    DATA_RELATIONSHIP_KINDS,
    SYSTEM_EDGE_RELS,
    SYSTEM_KINDS,
    _DATA_FLOW_RELS,
)

# Validated value vocabularies, single-sourced from the analysis write boundary.
_SYSTEM_KIND_SET = frozenset(kind for kind, _desc in SYSTEM_KINDS)
_DATA_REL_KIND_SET = frozenset(kind for kind, _desc in DATA_RELATIONSHIP_KINDS)
_DATA_EDGE_FAMILIES = frozenset(_DATA_FLOW_RELS.values())  # PRODUCES / CONSUMES
_SPINE_KEY_SET = frozenset(_SPINE_KEYS)

# The predicate's fault direction (D-B); feeds #69 candidate-minting.
TARGETS: tuple[Literal["Service", "System", "Both"], ...] = (
    "Service", "System", "Both",
)

# The only value-equality facets today. `exposure` value clauses are D1-unlanded
# (no curator-boundary EXPOSURE_VALUES constant yet); rendering/navigation are
# D2-unlanded (still NL-in-description); service_contract and the remaining
# spine keys are NL/non-facet. The technological axis is NEVER a facet (#66
# non-conflation: no typed L1 handle exists).
_SPINE_EQUALS_KEYS = frozenset({"kind"})
_D1_UNLANDED_KEYS = frozenset({"exposure"})
_D2_UNLANDED_KEYS = frozenset({"rendering_model", "navigation_model"})


class ClauseForm(str, Enum):
    """The phase-1 closed set of clause forms (spec 2.3)."""

    KIND_IS = "kind-is"
    REACHABLE_VIA = "reachable-via"
    SPINE_PRESENT = "spine-present"
    SPINE_EQUALS = "spine-equals"
    # In the grammar; D3-unlanded, so unavailable to authors (validator rejects).
    SERVES_UNITS_WITH = "serves-units-with"
    DATA_EDGE_EXISTS = "data-edge-exists"
    DATA_RELATIONSHIP_KIND = "data-relationship-kind"


@dataclass(frozen=True)
class Clause:
    """One necessary-condition clause.

    `key` is the edge family (REACHABLE_VIA / DATA_EDGE_EXISTS), the spine key
    (SPINE_PRESENT / SPINE_EQUALS / SERVES_UNITS_WITH), or unused.
    `values` is the validated value set (KIND_IS / REACHABLE_VIA kinds /
    DATA_RELATIONSHIP_KIND) or the single value (SPINE_EQUALS).
    `role` is the free-string role-presence constraint of REACHABLE_VIA
    (presence only, never value equality - L1D-21 rides on props).
    """

    form: ClauseForm
    key: str | None = None
    values: tuple[str, ...] = ()
    role: str | None = None


@dataclass(frozen=True)
class TypedPredicate:
    """The typed applies-if predicate artifact (spec 2.3).

    Composition is AND only - all clauses are necessary conditions; the closed
    form has no negation, no NL operands, no nested predicates. The
    `composition` field pins that invariant in the structure itself so a
    hand-authored artifact claiming another composition is validator-rejected
    (C4-d), exactly like a `kind` value outside the controlled vocabulary.
    """

    target: Literal["Service", "System", "Both"]
    clauses: tuple[Clause, ...]
    composition: Literal["AND"] = "AND"


class PredicateValidationError(ValueError):
    """A malformed predicate was rejected at authoring time (C4)."""


def render_clause(clause: Clause) -> str:
    """Canonical, deterministic rendering of one clause.

    Value sets render SORTED, so two authorings of the same clause cannot
    produce two witness strings. This rendering IS the clause id the
    deterministic stage carries as its witness (spec 2.4): self-describing,
    deterministic, and fault-agnostic on the wire (C7).
    """
    values = ", ".join(sorted(clause.values))
    if clause.form is ClauseForm.KIND_IS:
        return f"kind-is({{{values}}})"
    if clause.form is ClauseForm.REACHABLE_VIA:
        role = f', role="{clause.role}"' if clause.role is not None else ""
        return f"reachable-via({clause.key}, {{{values}}}{role})"
    if clause.form is ClauseForm.SPINE_PRESENT:
        return f"spine-present({clause.key})"
    if clause.form is ClauseForm.SPINE_EQUALS:
        return f'spine-equals({clause.key}, "{next(iter(clause.values))}")'
    if clause.form is ClauseForm.SERVES_UNITS_WITH:
        return f"serves-units-with({clause.key})"
    if clause.form is ClauseForm.DATA_EDGE_EXISTS:
        return f"data-edge-exists({clause.key})"
    return f"data-relationship-kind({{{values}}})"


def validate_predicate(predicate: TypedPredicate) -> None:
    """Authoring-time check: raise PredicateValidationError on any malformed
    class (C4). A valid predicate is always evaluable (section 2.6)."""
    if not isinstance(predicate, TypedPredicate):
        raise PredicateValidationError(
            f"expected a TypedPredicate, got {type(predicate).__name__}")
    if predicate.composition != "AND":
        raise PredicateValidationError(
            f"composition is AND only (phase-1 closed form), got "
            f"{predicate.composition!r}")
    if predicate.target not in TARGETS:
        raise PredicateValidationError(
            f"invalid target {predicate.target!r}; must be one of {TARGETS}")
    if not predicate.clauses:
        raise PredicateValidationError(
            "a predicate needs at least one clause")
    for clause in predicate.clauses:
        _validate_clause(clause)


def _validate_clause(clause: Clause) -> None:
    if not isinstance(clause.form, ClauseForm):
        raise PredicateValidationError(
            f"unsupported clause form {clause.form!r}")

    if clause.form is ClauseForm.KIND_IS:
        _require_values(clause, "kind-is")
        _validate_kinds(clause, "kind-is")
    elif clause.form is ClauseForm.REACHABLE_VIA:
        if clause.key not in SYSTEM_EDGE_RELS:
            raise PredicateValidationError(
                f"reachable-via over unknown edge family {clause.key!r}; "
                f"the §6 taxonomy is {sorted(SYSTEM_EDGE_RELS)}")
        _require_values(clause, "reachable-via")
        _validate_kinds(clause, "reachable-via")
        # role is presence-only (a free string) - never validated.
    elif clause.form is ClauseForm.SPINE_PRESENT:
        if clause.key not in _SPINE_KEY_SET:
            raise PredicateValidationError(
                f"spine-present over unknown spine key {clause.key!r}; "
                f"the typed spine is {sorted(_SPINE_KEY_SET)}")
    elif clause.form is ClauseForm.SPINE_EQUALS:
        if len(clause.values) != 1:
            raise PredicateValidationError(
                "spine-equals needs exactly a single value "
                "(value-EQUALITY is one value; the OR-over-set is kind-is)")
        if clause.key not in _SPINE_EQUALS_KEYS:
            _reject_unvalidated_value_facet(clause)
        elif clause.values[0] not in _SYSTEM_KIND_SET:
            raise PredicateValidationError(
                f"spine-equals(kind, ...) over unknown system kind "
                f"{clause.values[0]!r}; not in SYSTEM_KINDS")
    elif clause.form is ClauseForm.SERVES_UNITS_WITH:
        raise PredicateValidationError(
            "serves-units-with is D3-unlanded: the System-to-Services inverse "
            "read does not exist yet, so the clause form is unavailable to "
            "authors (spec 2.6 whole-stage degrade)")
    elif clause.form is ClauseForm.DATA_EDGE_EXISTS:
        if clause.key not in _DATA_EDGE_FAMILIES:
            raise PredicateValidationError(
                f"data-edge-exists over unknown data-edge family "
                f"{clause.key!r}; the data axis edges are "
                f"{sorted(_DATA_EDGE_FAMILIES)}")
    elif clause.form is ClauseForm.DATA_RELATIONSHIP_KIND:
        _require_values(clause, "data-relationship-kind")
        for value in clause.values:
            if value not in _DATA_REL_KIND_SET:
                raise PredicateValidationError(
                    f"data-relationship-kind over unknown kind {value!r}; "
                    f"not in DATA_RELATIONSHIP_KINDS")


def _require_values(clause: Clause, form: str) -> None:
    if not clause.values:
        raise PredicateValidationError(f"{form} needs at least one value")


def _validate_kinds(clause: Clause, form: str) -> None:
    for value in clause.values:
        if value not in _SYSTEM_KIND_SET:
            raise PredicateValidationError(
                f"{form} over unknown system kind {value!r}; "
                f"not in SYSTEM_KINDS")


def _reject_unvalidated_value_facet(clause: Clause) -> None:
    if clause.key in _D1_UNLANDED_KEYS:
        raise PredicateValidationError(
            f"spine-equals({clause.key}, ...) is D1-unlanded: exposure values "
            f"are not yet validated at the curator write boundary, so value "
            f"equality over them is not sound - exposure clauses are "
            f"spine-present only until D1 lands")
    if clause.key in _D2_UNLANDED_KEYS:
        raise PredicateValidationError(
            f"spine-equals({clause.key}, ...) is D2-unlanded: "
            f"rendering/navigation values are still NL-in-description, not "
            f"validated typed attributes - value equality over them is not "
            f"sound; the default is reachable-via(EXPOSED_VIA, "
            f"{{WebPresentation}}) existence until D2 lands")
    raise PredicateValidationError(
        f"spine-equals over {clause.key!r} is rejected: not a predicate "
        f"facet - it has no validated value vocabulary (no L1 handle); the "
        f"technological axis is never a facet (#66 non-conflation)")
