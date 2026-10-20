"""Unit tier: the variant-basis vocabulary and the procedure diff (T9, S5 8.6).

The ten basis literals are the spec's table; the first seven are the procedure
gaps and map one-to-one onto the typed `SkillProcedure` fields in table order.
The diff tests the gap classes in that order and the first uncovered class wins.
The failure-mode fallback and the two execution triggers complete the minting
vocabulary; the duplicate guard compares a basis plus its detail.
"""
from polymerhus.attack.hunting.pod.variant_basis import (
    PROCEDURE_GAP_BASES,
    PROCEDURE_GAP_FIELD,
    VARIANT_BASES,
    first_uncovered_gap,
    is_duplicate_variant,
    mint_variant_basis,
)
from polymerhus.attack.hunting.pod.types import VariantSpec
from polymerhus.attack.hunting.spec_contract import (
    SKILL_PROCEDURE_FIELDS,
    SkillProcedure,
)


EXPECTED_BASES = (
    "recon-action",
    "bypass-technique",
    "technology-grounding",
    "pro-tips",
    "advanced-technique",
    "preliminary-chaining",
    "interpretation-pitfall",
    "failure-mode",
    "runner-failure",
    "runner-divergence",
)


def test_the_ten_basis_literals_are_the_spec_vocabulary():
    assert VARIANT_BASES == EXPECTED_BASES
    assert PROCEDURE_GAP_BASES == EXPECTED_BASES[:7]


def test_the_seven_gap_classes_map_one_to_one_to_the_procedure_fields():
    assert tuple(PROCEDURE_GAP_FIELD) == EXPECTED_BASES[:7]
    assert tuple(PROCEDURE_GAP_FIELD.values()) == SKILL_PROCEDURE_FIELDS


PROCEDURE = SkillProcedure(
    recon_action="crawl the listing page item ids",
    bypass_technique="swap the id in a signed URL",
    technology_grounding="the app is a Django REST API",
    pro_tips="compare the owner id in the response body",
    advanced_technique="chain the export endpoint",
    preliminary_chaining="mint a low-privilege session first",
    interpretation_pitfalls="a 403 is not proof the object is absent",
)


def test_the_first_uncovered_gap_class_wins_in_table_order():
    covered = {"recon-action", "bypass-technique"}
    assert first_uncovered_gap(PROCEDURE, covered) == "technology-grounding"
    covered = set(EXPECTED_BASES[:7]) - {"interpretation-pitfall"}
    assert first_uncovered_gap(PROCEDURE, covered) == "interpretation-pitfall"


def test_an_empty_procedure_field_is_a_skipped_class_not_a_gap():
    # T10 H1: there is no authored procedure to execute or cover, so an empty
    # section never becomes the basis and can never loop the pod.
    procedure = PROCEDURE.model_copy(update={"pro_tips": ""})
    covered = set(EXPECTED_BASES[:7])   # the triager claims everything is covered
    assert first_uncovered_gap(procedure, covered) is None
    # An empty class is skipped even when the triager did not claim it covered:
    # the next POPULATED uncovered class still wins.
    covered = set(EXPECTED_BASES[:7]) - {"pro-tips", "interpretation-pitfall"}
    assert first_uncovered_gap(procedure, covered) == "interpretation-pitfall"


def test_an_absent_procedure_excerpt_is_a_recorded_gap_not_a_diff():
    # S5 8.6 step 1: when the excerpt is absent, record the gap and go to the
    # failure-mode fallback - the diff does not invent a procedure gap.
    assert first_uncovered_gap(None, set()) is None


def test_a_fully_covered_procedure_mints_the_failure_mode_fallback():
    all_seven = set(EXPECTED_BASES[:7])
    assert mint_variant_basis(procedure=PROCEDURE, covered=all_seven,
                              failure_mode_plausible=True) == "failure-mode"


def test_the_fallback_is_not_minted_when_no_failure_mode_is_plausible():
    all_seven = set(EXPECTED_BASES[:7])
    assert mint_variant_basis(procedure=PROCEDURE, covered=all_seven,
                              failure_mode_plausible=False) is None


def test_each_procedure_gap_basis_is_minted_from_its_own_condition():
    for i, basis in enumerate(EXPECTED_BASES[:7]):
        covered = set(EXPECTED_BASES[:i])
        assert mint_variant_basis(procedure=PROCEDURE, covered=covered) == basis


def test_an_absent_excerpt_goes_straight_to_the_failure_mode_fallback():
    assert mint_variant_basis(procedure=None, covered=[],
                              failure_mode_plausible=True) == "failure-mode"
    assert mint_variant_basis(procedure=None, covered=[],
                              failure_mode_plausible=False) is None


def test_a_runner_failure_mints_the_recovery_basis():
    assert mint_variant_basis(procedure=None, covered=[],
                              runner_failed=True) == "runner-failure"


def test_a_runner_divergence_mints_the_recovery_basis():
    assert mint_variant_basis(procedure=None, covered=[],
                              runner_diverged=True) == "runner-divergence"


def test_an_execution_trigger_outranks_the_procedure_diff():
    # A failed or diverged execution makes the procedure diff meaningless: the
    # recovery basis is the variant, never a gap class the runner did not reach.
    assert mint_variant_basis(procedure=PROCEDURE, covered=set(),
                              runner_failed=True) == "runner-failure"
    assert mint_variant_basis(procedure=PROCEDURE, covered=set(),
                              runner_diverged=True) == "runner-divergence"


def test_no_coverage_assessment_mints_nothing_deterministic():
    # A triager that does not state which classes it covered leaves the basis to
    # its own claim; the graph never invents a gap from a missing assessment.
    assert mint_variant_basis(procedure=PROCEDURE, covered=None) is None


def test_the_duplicate_guard_compares_the_basis_and_the_detail():
    prior = [VariantSpec(ref="v0", spec={}),
             VariantSpec(ref="v1", parent_ref="v0",
                         declined_attribute="bypass-technique",
                         spec={"rationale": "swap the id"})]
    assert is_duplicate_variant(
        prior, "bypass-technique", {"rationale": "swap the id"}) is True
    assert is_duplicate_variant(
        prior, "bypass-technique", {"rationale": "swap the owner field"}) is False
    assert is_duplicate_variant(
        prior, "recon-action", {"rationale": "swap the id"}) is False
    assert is_duplicate_variant(
        prior, "recon-action", {"rationale": "crawl the listing"}) is False
