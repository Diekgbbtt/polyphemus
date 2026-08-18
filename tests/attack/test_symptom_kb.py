"""Unit tier: the typed retrieval seam into the external symptom-technique KB
(#66, spec section 7; FKB-5).

The seam's two contracts under assertion:

  * the typed query/response shapes - `SymptomTechniqueQuery(fault_id,
    technological_axis)` and `SymptomTechniqueResult(symptoms, techniques,
    source)` - and the injected-lookup shape, so a swap of the external KB is a
    seam change, never a hunting-agent rewrite;
  * fail-open readiness: a not-ready or erroring external KB returns an EMPTY
    `SymptomTechniqueResult` and NEVER crashes the caller; the caller degrades
    to the fault-KB's own materialisation content.

The technological-axis query field and the fault-KB entry's technical-axis
`enum_kinds` tag never share a field (FKB-6, the non-conflation rule) - the
query type carries the former only.
"""
import pytest

from polymerhus.attack.hunting.symptom_kb import (
    SymptomTechniqueQuery,
    SymptomTechniqueResult,
    query_symptom_technique,
)


# --- the typed shapes ----------------------------------------------------------

def test_query_shape_carries_fault_id_and_technological_axis():
    query = SymptomTechniqueQuery(fault_id="CWE-89",
                                  technological_axis=("PostgreSQL", "Django"))
    assert query.fault_id == "CWE-89"
    assert query.technological_axis == ("PostgreSQL", "Django")
    # FKB-6: no enum_kinds / SYSTEM_KIND vocabulary lives on the query type
    assert not hasattr(query, "enum_kinds")


def test_query_defaults_to_empty_technological_axis():
    query = SymptomTechniqueQuery(fault_id="CWE-89")
    assert query.technological_axis == ()


def test_result_shape_is_the_typed_response():
    result = SymptomTechniqueResult(
        symptoms=("error page on quote",),
        techniques=("boolean-based payloads",),
        source="OWASP testing guide",
    )
    assert result.symptoms == ("error page on quote",)
    assert result.techniques == ("boolean-based payloads",)
    assert result.source == "OWASP testing guide"


def test_result_defaults_to_empty_fail_open_signal():
    assert SymptomTechniqueResult() == SymptomTechniqueResult((), (), None)


# --- fail-open readiness -------------------------------------------------------

def test_not_ready_kb_returns_empty_result_without_crashing():
    result = query_symptom_technique(SymptomTechniqueQuery(fault_id="CWE-89"))
    assert result == SymptomTechniqueResult()


def test_erroring_kb_returns_empty_result_without_crashing():
    def broken(_query):
        raise RuntimeError("external KB down")

    result = query_symptom_technique(
        SymptomTechniqueQuery(fault_id="CWE-89"), lookup=broken)
    assert result == SymptomTechniqueResult()


def test_ready_kb_result_is_passed_through_unchanged():
    expected = SymptomTechniqueResult(
        symptoms=("stack trace",), techniques=("error-trigger probe",),
        source="operator KB")

    def ready(query):
        assert query.fault_id == "CWE-89"
        return expected

    result = query_symptom_technique(
        SymptomTechniqueQuery(fault_id="CWE-89"), lookup=ready)
    assert result == expected
