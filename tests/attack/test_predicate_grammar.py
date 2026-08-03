"""Unit tier: the typed applies-if predicate grammar + authoring-time validator.

The grammar and the validator are the spec's first two seams
(`docs/design/hunting-63-typed-applies-if-spec.md` sections 2.3 + 6):
the typed data structure that hardens the fault-KB `applies-if` slot, and the
authoring-time check that HARD-REJECTS unsupported clause forms, value clauses
over unvalidated facets, and malformed structure - never evaluated at runtime,
never silently dropped (C4 is the integration-tier mechanisation of the same
contract; this file drives the mechanics at the unit tier).

Expected values are taken from the spec, never recomputed the way the code
computes them: the six available clause forms, the D3-unlanded form, the
validated value vocabularies (system kinds, DataRelationship kinds), and the
D1/D2-unlanded value facets.
"""
import pytest
from typing import Any, cast

from polymerhus.attack.hunting.predicate import (
    Clause,
    ClauseForm,
    PredicateValidationError,
    TypedPredicate,
    render_clause,
    validate_predicate,
)


def _invalid(typ: type, *args, **kwargs):
    """Build a deliberately-invalid artifact bypassing the dataclass's static
    Literal types - the validator is the runtime check for artifacts
    hand-authored (e.g. from the fault-KB data), not only for typed code."""
    return cast(Any, typ)(*args, **kwargs)


# --- the grammar: the six available clause forms + the D3-unlanded form -------

def test_clause_forms_are_the_phase1_closed_set():
    forms = set(ClauseForm)
    assert forms == {
        ClauseForm.KIND_IS,
        ClauseForm.REACHABLE_VIA,
        ClauseForm.SPINE_PRESENT,
        ClauseForm.SPINE_EQUALS,
        ClauseForm.SERVES_UNITS_WITH,  # D3-unlanded: authoring-unavailable
        ClauseForm.DATA_EDGE_EXISTS,
        ClauseForm.DATA_RELATIONSHIP_KIND,
    }


def test_render_clause_is_deterministic_and_self_describing():
    # the canonical rendering rides the witness (section 2.4)
    assert render_clause(Clause(ClauseForm.REACHABLE_VIA, key="EXPOSED_VIA",
                                values=("GraphQLApi",))) == \
        "reachable-via(EXPOSED_VIA, {GraphQLApi})"
    assert render_clause(Clause(ClauseForm.KIND_IS, values=("CDN", "WAF"))) == \
        "kind-is({CDN, WAF})"  # value sets render sorted - deterministic
    assert render_clause(Clause(ClauseForm.SPINE_PRESENT, key="exposure")) == \
        "spine-present(exposure)"
    assert render_clause(Clause(ClauseForm.SPINE_EQUALS, key="kind",
                                values=("WAF",))) == 'spine-equals(kind, "WAF")'
    assert render_clause(Clause(ClauseForm.DATA_EDGE_EXISTS, key="consumes")) == \
        "data-edge-exists(consumes)"
    assert render_clause(Clause(ClauseForm.DATA_RELATIONSHIP_KIND,
                                values=("derived_from", "subset_of"))) == \
        "data-relationship-kind({derived_from, subset_of})"
    assert render_clause(Clause(ClauseForm.REACHABLE_VIA, key="AUTHORIZED_BY",
                                values=("AuthorizationSystem",),
                                role="admin")) == \
        'reachable-via(AUTHORIZED_BY, {AuthorizationSystem}, role="admin")'


# --- accept: every available form with valid operands -------------------------

def test_validator_accepts_kind_is_over_validated_kinds():
    p = TypedPredicate(target="Both", clauses=(Clause(ClauseForm.KIND_IS,
                                                      values=("WAF", "CDN")),))
    validate_predicate(p)  # must not raise


def test_validator_accepts_reachable_via_with_kind_and_optional_role():
    p = TypedPredicate(target="Service", clauses=(
        Clause(ClauseForm.REACHABLE_VIA, key="EXPOSED_VIA", values=("RESTApi",)),
        Clause(ClauseForm.REACHABLE_VIA, key="AUTHORIZED_BY",
               values=("AuthorizationSystem",), role="admin"),
    ))
    validate_predicate(p)


def test_validator_accepts_spine_present_over_spine_keys():
    p = TypedPredicate(target="Service", clauses=(
        Clause(ClauseForm.SPINE_PRESENT, key="exposure"),
        Clause(ClauseForm.SPINE_PRESENT, key="service_contract"),
    ))
    validate_predicate(p)


def test_validator_accepts_spine_equals_kind_over_system_kind_vocabulary():
    # the ONLY validated value facet available today: the system-kind vocabulary
    # (exposure is D1-unlanded, rendering/navigation are D2-unlanded)
    p = TypedPredicate(target="System", clauses=(
        Clause(ClauseForm.SPINE_EQUALS, key="kind", values=("WAF",)),
    ))
    validate_predicate(p)


def test_validator_accepts_data_axis_clauses():
    p = TypedPredicate(target="Both", clauses=(
        Clause(ClauseForm.DATA_EDGE_EXISTS, key="CONSUMES"),
        Clause(ClauseForm.DATA_RELATIONSHIP_KIND, values=("derived_from",)),
    ))
    validate_predicate(p)


def test_validator_accepts_all_three_target_values_and_multi_clause():
    for target in ("Service", "System", "Both"):
        validate_predicate(TypedPredicate(target=target, clauses=(
            Clause(ClauseForm.SPINE_PRESENT, key="exposure"),)))
    validate_predicate(TypedPredicate(target="Both", clauses=(
        Clause(ClauseForm.SPINE_PRESENT, key="exposure"),
        Clause(ClauseForm.KIND_IS, values=("WAF",)),
        Clause(ClauseForm.REACHABLE_VIA, key="FRONTED_BY", values=("WAF",)),
    )))


# --- C4: hard-reject every malformed class (spec 2.3, Appendix A) -------------

def test_rejects_unsupported_clause_form():
    with pytest.raises(PredicateValidationError, match="unsupported clause form"):
        validate_predicate(TypedPredicate(target="Both", clauses=(
            _invalid(Clause, "contains-text", key="service_contract"),)))


def test_rejects_value_clause_over_unvalidated_facet_d2_unlanded():
    # spine-equals(rendering_model, "CSR") BEFORE D2 - the facet's value is not
    # validated at the write boundary, so value equality over it is not sound
    with pytest.raises(PredicateValidationError, match="D2"):
        validate_predicate(TypedPredicate(target="Both", clauses=(
            Clause(ClauseForm.SPINE_EQUALS, key="rendering_model",
                   values=("CSR",)),)))


def test_rejects_value_clause_over_unvalidated_facet_d1_unlanded():
    # spine-equals(exposure, ...) needs D1 (the curator-boundary EXPOSURE_VALUES
    # constant); without it exposure clauses are spine-present only
    with pytest.raises(PredicateValidationError, match="D1"):
        validate_predicate(TypedPredicate(target="Both", clauses=(
            Clause(ClauseForm.SPINE_EQUALS, key="exposure",
                   values=("public",)),)))


def test_rejects_value_clause_over_non_facet_technological_axis():
    # the technological axis has NO L1 handle (spec 2.2 non-facets): a value
    # clause over it is not just unvalidated, it ranges over nothing
    with pytest.raises(PredicateValidationError, match="technological axis|not a facet|no L1 handle"):
        validate_predicate(TypedPredicate(target="Both", clauses=(
            Clause(ClauseForm.SPINE_EQUALS, key="tech_axis", values=("nginx",)),)))


def test_rejects_non_and_composition():
    # composition is AND only - the closed form has no OR; a predicate that
    # claims another composition is malformed
    with pytest.raises(PredicateValidationError, match="AND"):
        validate_predicate(_invalid(TypedPredicate, target="Both", composition="OR",
                                    clauses=(Clause(ClauseForm.SPINE_PRESENT,
                                                    key="exposure"),)))


def test_rejects_empty_clause_list():
    with pytest.raises(PredicateValidationError, match="at least one clause"):
        validate_predicate(TypedPredicate(target="Both", clauses=()))


def test_rejects_invalid_target_value():
    with pytest.raises(PredicateValidationError, match="target"):
        validate_predicate(_invalid(TypedPredicate, target="Service, System", clauses=(
            Clause(ClauseForm.SPINE_PRESENT, key="exposure"),)))


def test_rejects_clause_over_unknown_edge_family():
    # EXPOSED_BY is not a §6 family; RENDERED_BY was deleted by FR-MODELFIX
    with pytest.raises(PredicateValidationError, match="edge family"):
        validate_predicate(TypedPredicate(target="Both", clauses=(
            Clause(ClauseForm.REACHABLE_VIA, key="EXPOSED_BY",
                   values=("WAF",)),)))
    with pytest.raises(PredicateValidationError, match="edge family"):
        validate_predicate(TypedPredicate(target="Both", clauses=(
            Clause(ClauseForm.REACHABLE_VIA, key="RENDERED_BY",
                   values=("WebPresentation",)),)))


def test_rejects_kind_is_over_unvalidated_kind():
    with pytest.raises(PredicateValidationError, match="kind"):
        validate_predicate(TypedPredicate(target="Both", clauses=(
            Clause(ClauseForm.KIND_IS, values=("Authentication",)),)))


def test_rejects_reachable_via_over_unvalidated_kind():
    with pytest.raises(PredicateValidationError, match="kind"):
        validate_predicate(TypedPredicate(target="Both", clauses=(
            Clause(ClauseForm.REACHABLE_VIA, key="EXPOSED_VIA",
                   values=("GraphQL",)),)))


def test_rejects_empty_value_set():
    for form in (ClauseForm.KIND_IS, ClauseForm.DATA_RELATIONSHIP_KIND):
        with pytest.raises(PredicateValidationError, match="at least one value"):
            validate_predicate(TypedPredicate(target="Both", clauses=(
                Clause(form),)))


def test_rejects_spine_present_over_unknown_key():
    with pytest.raises(PredicateValidationError, match="spine key"):
        validate_predicate(TypedPredicate(target="Both", clauses=(
            Clause(ClauseForm.SPINE_PRESENT, key="not_a_spine_key"),)))


def test_rejects_spine_equals_with_multi_value_set():
    # value-EQUALITY is a single value, not a set (the OR-over-set is kind-is)
    with pytest.raises(PredicateValidationError, match="single value"):
        validate_predicate(TypedPredicate(target="Both", clauses=(
            Clause(ClauseForm.SPINE_EQUALS, key="kind", values=("WAF", "CDN")),)))


def test_rejects_data_edge_exist_over_unknown_family():
    with pytest.raises(PredicateValidationError, match="data-edge"):
        validate_predicate(TypedPredicate(target="Both", clauses=(
            Clause(ClauseForm.DATA_EDGE_EXISTS, key="exports"),)))


def test_rejects_data_relationship_kind_over_unvalidated_kind():
    with pytest.raises(PredicateValidationError, match="data-relationship"):
        validate_predicate(TypedPredicate(target="Both", clauses=(
            Clause(ClauseForm.DATA_RELATIONSHIP_KIND, values=("hashes_to",)),)))


def test_rejects_serves_units_with_until_d3_lands():
    # D3 (the System-to-Services inverse read) is unlanded: the clause form is
    # part of the grammar (section 2.3) but UNAVAILABLE to authors (section 2.6)
    with pytest.raises(PredicateValidationError, match="D3"):
        validate_predicate(TypedPredicate(target="System", clauses=(
            Clause(ClauseForm.SERVES_UNITS_WITH, key="exposure"),)))


def test_validation_is_pure_and_state_free():
    # a rejected predicate leaves nothing behind: re-running the same predicate
    # through the validator yields the identical rejection, and a valid
    # predicate validates after a rejected one
    bad = TypedPredicate(target="Both", clauses=(
        Clause(ClauseForm.SPINE_EQUALS, key="rendering_model", values=("CSR",)),))
    with pytest.raises(PredicateValidationError):
        validate_predicate(bad)
    with pytest.raises(PredicateValidationError):
        validate_predicate(bad)  # identical rejection, deterministic
    validate_predicate(TypedPredicate(target="Both", clauses=(
        Clause(ClauseForm.SPINE_PRESENT, key="exposure"),)))
