"""Unit tier: the graph's variant minting (T9, S5 8.6).

Drives `arun_pod` with a scripted triager decision and a scripted experiment
log. The graph resolves the variant basis against the typed `SkillProcedure` in
the spec provenance: the first uncovered gap class wins, the failure-mode
fallback covers a fully covered procedure, the execution triggers mint the
recovery bases, and a duplicate basis plus detail is not re-minted. The
`VariantSpec` record keeps its four-field shape; `declined_attribute` carries the
basis.
"""
import asyncio

from polymerhus.attack.hunting.pod import arun_pod
from polymerhus.attack.hunting.pod.agents import TriagerDecision, symbolic_runner_step_fn
from polymerhus.attack.hunting.pod.types import TERMINAL_REASONS
from polymerhus.attack.hunting.pod.variant_basis import (
    PROCEDURE_GAP_BASES,
    VARIANT_BASES,
)
from polymerhus.recon.domain.types import ExecResult

PROCEDURE = {
    "recon_action": "crawl the item ids from the listing page",
    "bypass_technique": "swap the id in a signed URL",
    "technology_grounding": "the app is a Django REST API",
    "pro_tips": "compare the owner id in the response body",
    "advanced_technique": "chain the export endpoint",
    "preliminary_chaining": "mint a low-privilege session first",
    "interpretation_pitfalls": "a 403 is not proof the object is absent",
}
ALL_GAPS = set(PROCEDURE_GAP_BASES)

SPEC = {
    "target_identity": {"url": "http://soupmarket.shop/",
                        "unit_id": "service:web:soupmarket"},
    "verification_symptoms": ["the response leaks another user's order id"],
    "assumptions": ["the session cookie is the only auth factor"],
    "rationale": "IDOR over the order endpoint",
    "provenance": {"loop_id": "loop-1", "unit_id": "service:web:soupmarket",
                   "canonical_class": "IDOR", "web_vulnerability_class": "idor",
                   "skill_procedure": PROCEDURE},
}

_ABSENT = "not found\n__POD_HTTP_STATUS__:404\n__POD_HTTP_TIME__:0.02"

TERMINATE = {"classification": "symptom-absent", "action": "terminate",
             "verdict": "unsuccessful", "terminal_reason": "no-symptom-evidence",
             "clean": False, "note": "no further variant"}


def _exec(command, timeout_s):
    return ExecResult(stdout=_ABSENT, stderr="", returncode=0, duration_ms=1)


def _no_trace(_run_id):
    return []


def _run(coro):
    return asyncio.run(coro)


def _variant(**overrides):
    decision = {"classification": "symptom-absent", "action": "variant",
                "declined_attribute": "", "variant_spec": {},
                "feedback": "cover the gap", "note": "mining a variant"}
    decision.update(overrides)
    return decision


def _drive(decisions, spec=SPEC):
    it = iter(decisions)

    def triager(s, obs, messages, log):
        try:
            return dict(next(it))
        except StopIteration:
            return dict(TERMINATE)

    return _run(arun_pod(spec, exec_fn=_exec, runner_step_fn=symbolic_runner_step_fn,
                         triager_fn=triager, trace_fn=_no_trace))


def test_the_graph_mints_the_first_uncovered_gap_as_the_basis():
    derived = {**SPEC, "rationale": "ground the Django stack before the id swap"}
    env = _drive([
        _variant(declined_attribute="pro-tips",
                 covered_gap_classes=["recon-action", "bypass-technique"],
                 variant_spec=derived),
        TERMINATE,
    ])
    variants = env["evidence"]["variant_specs"]
    assert [v["ref"] for v in variants] == ["v0", "v1"]
    assert variants[1]["declined_attribute"] == "technology-grounding"


def test_an_empty_procedure_section_is_skipped_not_minted():
    # T10 H1: an empty section is a skipped class. Even when the triager claims
    # full coverage, the diff never loops on the empty pro-tips section; the
    # plausible failure mode is the only derivable variant.
    spec = {**SPEC, "provenance": {
        **SPEC["provenance"],
        "skill_procedure": {**PROCEDURE, "pro_tips": ""}}}
    derived = {**spec, "rationale": "test one more observable failure mode"}
    env = _drive([
        _variant(declined_attribute="pro-tips",
                 covered_gap_classes=sorted(ALL_GAPS),
                 failure_mode_plausible=True, variant_spec=derived),
        TERMINATE,
    ], spec=spec)
    assert env["evidence"]["variant_specs"][1]["declined_attribute"] == "failure-mode"


def test_an_unknown_coverage_token_invalidates_the_assessment():
    # T10 H4: an unknown token is not a subset of the seven-class table, so the
    # assessment is ignored and the triager's claimed basis stands (rather than
    # the garbage token reading as an uncovered class).
    env = _drive([
        _variant(declined_attribute="pro-tips",
                 covered_gap_classes=["not-a-gap-class"],
                 variant_spec={**SPEC, "rationale": "use the pro tip"}),
        TERMINATE,
    ])
    assert env["evidence"]["variant_specs"][1]["declined_attribute"] == "pro-tips"


def test_a_derived_spec_keeps_the_base_provenance():
    # T10 H6 / S5 8.6 step 7: the graph restores the base provenance even when
    # the triager's derived spec omits it, so the next stretch keeps its diff
    # material.
    omitting = {"rationale": "test one more observable failure mode"}
    env = _drive([
        _variant(covered_gap_classes=sorted(ALL_GAPS),
                 failure_mode_plausible=True, variant_spec=omitting),
        TERMINATE,
    ])
    record = env["evidence"]["variant_specs"][1]
    assert record["spec"]["provenance"] == SPEC["provenance"]
    assert record["spec"]["rationale"] == omitting["rationale"]


def test_a_fully_covered_procedure_mints_a_failure_mode_variant():
    derived = {**SPEC, "rationale": "test one more observable failure mode"}
    env = _drive([
        _variant(covered_gap_classes=sorted(ALL_GAPS),
                 failure_mode_plausible=True, variant_spec=derived),
        TERMINATE,
    ])
    assert env["evidence"]["variant_specs"][1]["declined_attribute"] == "failure-mode"


def test_a_runner_failure_mints_the_recovery_basis():
    derived = {**SPEC, "rationale": "recover the failed execution"}
    env = _drive([
        _variant(runner_failed=True, variant_spec=derived),
        TERMINATE,
    ])
    assert env["evidence"]["variant_specs"][1]["declined_attribute"] == "runner-failure"


def test_a_runner_divergence_mints_the_recovery_basis():
    derived = {**SPEC, "rationale": "return the execution to the spec"}
    env = _drive([
        _variant(runner_diverged=True, variant_spec=derived),
        TERMINATE,
    ])
    assert env["evidence"]["variant_specs"][1]["declined_attribute"] == "runner-divergence"


def test_a_duplicate_basis_and_detail_is_not_re_minted():
    first = _variant(covered_gap_classes=sorted(ALL_GAPS - {"bypass-technique"}),
                     variant_spec={**SPEC, "rationale": "swap the id in the signed URL"})
    second = _variant(covered_gap_classes=sorted(ALL_GAPS - {"bypass-technique"}),
                      variant_spec=None)   # None -> the current spec, i.e. v1's detail
    env = _drive([first, second, TERMINATE])
    variants = env["evidence"]["variant_specs"]
    assert [v["ref"] for v in variants] == ["v0", "v1"]
    assert variants[1]["declined_attribute"] == "bypass-technique"
    assert env["evidence"]["terminal_reason"] == "no-symptom-evidence"
    assert env["evidence"]["clean"] is False
    assert env["evidence"]["iterations"] == 2
    assert any("duplicate" in i["note"].lower() for i in env["evidence"]["interpretations"])


def test_the_variant_record_keeps_its_shape_and_carries_the_basis():
    derived = {**SPEC, "rationale": "chain the export endpoint"}
    env = _drive([
        _variant(covered_gap_classes=sorted(ALL_GAPS - {"advanced-technique"}),
                 variant_spec=derived),
        TERMINATE,
    ])
    record = env["evidence"]["variant_specs"][1]
    assert set(record) == {"ref", "parent_ref", "declined_attribute", "spec"}
    assert record["parent_ref"] == "v0"
    assert record["declined_attribute"] == "advanced-technique"
    assert record["spec"] == {**derived, "skills": []}


def test_an_absent_excerpt_is_recorded_and_uses_the_failure_mode_fallback():
    spec = {**SPEC, "provenance": {"loop_id": "loop-1"}}
    derived = {**spec, "rationale": "test an additional observable failure mode"}
    env = _drive([
        _variant(covered_gap_classes=[], failure_mode_plausible=True,
                 variant_spec=derived),
        TERMINATE,
    ], spec=spec)
    assert env["evidence"]["variant_specs"][1]["declined_attribute"] == "failure-mode"
    notes = " ".join(i["note"] for i in env["evidence"]["interpretations"])
    assert "recorded gap" in notes.lower()


def test_a_variant_without_a_derivable_basis_degrades_to_a_terminal():
    env = _drive([_variant(covered_gap_classes=None)])
    assert [v["ref"] for v in env["evidence"]["variant_specs"]] == ["v0"]
    assert env["evidence"]["terminal_reason"] == "no-symptom-evidence"
    assert env["evidence"]["clean"] is False


def test_a_fully_covered_procedure_cannot_mint_a_claimed_gap_basis():
    """When the triager states full coverage and no failure mode is plausible,
    no variant exists: its claimed gap basis must not override the diff."""
    env = _drive([
        _variant(declined_attribute="bypass-technique",
                 covered_gap_classes=sorted(ALL_GAPS),
                 variant_spec={**SPEC, "rationale": "unjustified re-mint"}),
        TERMINATE,
    ])
    assert [v["ref"] for v in env["evidence"]["variant_specs"]] == ["v0"]
    assert env["evidence"]["terminal_reason"] == "no-symptom-evidence"


def test_the_terminal_vocabulary_is_unchanged():
    # The ten bases are a DECISION vocabulary; the terminal_reason vocabulary
    # stays the six Q3-amended literals and never absorbs a basis.
    assert set(VARIANT_BASES) & set(TERMINAL_REASONS) == set()
    assert TERMINAL_REASONS == {
        "symptom-confirmed", "space-exhausted", "technical-infeasibility",
        "specific-defence-prevention", "no-symptom-evidence", "budget-timeout"}


def test_the_triager_decision_carries_the_coverage_assessment():
    # The production triager's structured schema carries the material the
    # deterministic diff needs; an omitted coverage assessment stays None.
    decision = TriagerDecision()
    assert decision.covered_gap_classes is None
    assert decision.failure_mode_plausible is False
    assert decision.runner_failed is False
    assert decision.runner_diverged is False
    filled = TriagerDecision(covered_gap_classes=["recon-action"],
                             failure_mode_plausible=True)
    assert filled.model_dump()["covered_gap_classes"] == ["recon-action"]


# --- the off-spec guard -------------------------------------------------------

def test_an_off_spec_variant_is_recorded_as_a_derived_spec():
    """A variant that changes the verification symptoms is a DERIVED spec, not a
    confirmation of the base spec. The record keeps the changed symptoms and the
    interpretation note carries the off-spec marker, so a later audit can see
    that the base symptom was never confirmed."""
    off_spec = {**SPEC,
                "verification_symptoms": ["the response leaks another user's email"],
                "rationale": "confirm the authority field selects the upstream account"}
    env = _drive([
        _variant(covered_gap_classes=sorted(ALL_GAPS - {"bypass-technique"}),
                 variant_spec=off_spec),
        TERMINATE,
    ])
    variants = env["evidence"]["variant_specs"]
    assert [v["ref"] for v in variants] == ["v0", "v1"]
    assert variants[1]["spec"]["verification_symptoms"] == [
        "the response leaks another user's email"]
    assert variants[0]["spec"]["verification_symptoms"] == [
        "the response leaks another user's order id"]
    assert any("off-spec" in i["note"].lower()
               for i in env["evidence"]["interpretations"])


def test_a_same_symptom_variant_has_no_off_spec_note():
    derived = {**SPEC, "rationale": "cover the unexecuted bypass technique"}
    env = _drive([
        _variant(covered_gap_classes=sorted(ALL_GAPS - {"bypass-technique"}),
                 variant_spec=derived),
        TERMINATE,
    ])
    assert not any("off-spec" in i["note"].lower()
                   for i in env["evidence"]["interpretations"])
