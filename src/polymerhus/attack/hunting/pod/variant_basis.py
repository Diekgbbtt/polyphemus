"""The variant bases and the first-uncovered procedure diff (S5 8.6).

On a variant decision the triager names ONE basis: a procedure gap or an
execution-trigger recovery. The eleven literals below are the spec's table; the
first nine are the procedure gaps and map one-to-one
onto the typed `SkillConcretisedProcedure` fields
(`spec_contract.SKILL_CONCRETISED_PROCEDURE_FIELDS`, same order), so the diff can test each field's class in the table order and the
first uncovered class is the basis.

The diff helpers are PURE: they take the typed procedure, the triager's coverage
assessment of the executed D6 trail, and the trigger/fallback conditions, and
return a basis literal - no I/O, no LLM. The graph reconciles the triager's
claim against them and records the resolved basis in
`VariantSpec.declined_attribute` (S5 8.6: the record shape is unchanged; the
field's meaning is the basis).
"""
from __future__ import annotations

import json
from typing import Collection, Iterable, Literal

from polymerhus.attack.hunting.pod.types import VariantSpec
from polymerhus.attack.hunting.spec_contract import SkillConcretisedProcedure

# --- the eleven basis literals (S5 8.6, table order) -------------------------

RECON_ACTION = "recon-action"
BYPASS_TECHNIQUE = "bypass-technique"
TECHNOLOGY_GROUNDING = "technology-grounding"
PRO_TIPS = "pro-tips"
ADVANCED_TECHNIQUE = "advanced-technique"
PRELIMINARY_CHAINING = "preliminary-chaining"
PAYLOAD_VECTOR = "payload-vector"
TECHNOLOGY_MISCONFIGURATION = "technology-misconfiguration"
INTERPRETATION_PITFALL = "interpretation-pitfall"
RUNNER_FAILURE = "runner-failure"
RUNNER_DIVERGENCE = "runner-divergence"

VariantBasis = Literal[
    "recon-action",
    "bypass-technique",
    "technology-grounding",
    "pro-tips",
    "advanced-technique",
    "preliminary-chaining",
    "payload-vector",
    "technology-misconfiguration",
    "interpretation-pitfall",
    "runner-failure",
    "runner-divergence",
]

VARIANT_BASES: tuple[VariantBasis, ...] = (
    RECON_ACTION, BYPASS_TECHNIQUE, TECHNOLOGY_GROUNDING, PRO_TIPS,
    ADVANCED_TECHNIQUE, PRELIMINARY_CHAINING, PAYLOAD_VECTOR,
    TECHNOLOGY_MISCONFIGURATION, INTERPRETATION_PITFALL,
    RUNNER_FAILURE, RUNNER_DIVERGENCE,
)

PROCEDURE_GAP_FIELD: dict[VariantBasis, str] = {
    RECON_ACTION: "recon_action",
    BYPASS_TECHNIQUE: "bypass_technique",
    TECHNOLOGY_GROUNDING: "technology_grounding",
    PRO_TIPS: "pro_tips",
    ADVANCED_TECHNIQUE: "advanced_technique",
    PRELIMINARY_CHAINING: "preliminary_chaining",
    PAYLOAD_VECTOR: "payload_vector",
    TECHNOLOGY_MISCONFIGURATION: "technology_misconfiguration",
    INTERPRETATION_PITFALL: "interpretation_pitfalls",
}
"""The nine procedure-gap bases, in table order, each naming its typed
`SkillConcretisedProcedure` field. The one-to-one mapping IS the diff's
iteration order."""

PROCEDURE_GAP_BASES: tuple[VariantBasis, ...] = tuple(PROCEDURE_GAP_FIELD)


def first_uncovered_gap(
        procedure: SkillConcretisedProcedure | None,
        covered: Collection[str]) -> VariantBasis | None:
    """The first procedure-gap class the executed procedure does not cover.

    Iterates the seven fields in the S5 8.6 table order. A field the skill left
    EMPTY is a SKIPPED class, not a gap: there is no authored procedure for the
    triager to execute or the variant to cover, so re-minting it every lap
    would threat to the budget cap without a new prediction (T10 H1). A populated
    class is covered only when the triager judged its action, technique, or
    check present in the D6 trail. An ABSENT excerpt is not a diff at all: the
    caller records the gap and no variant basis is derivable."""
    if procedure is None:
        return None
    for basis, field in PROCEDURE_GAP_FIELD.items():
        if not str(getattr(procedure, field)).strip():
            continue
        if basis not in covered:
            return basis
    return None


def mint_variant_basis(
        *,
        procedure: SkillConcretisedProcedure | None,
        covered: Collection[str] | None,
        runner_failed: bool = False,
        runner_diverged: bool = False) -> VariantBasis | None:
    """The basis the triager's variant decision must carry (S5 8.6).

    The execution triggers come first (S5 8.6 steps 3): a failed or diverged
    runner never yields a meaningful procedure diff, so its recovery basis is
    the variant. Then the seven populated classes in table order - the first
    uncovered class wins; an empty class is skipped. When the excerpt is absent,
    the gap is recorded and no variant basis is derivable.
    `covered=None` means the triager stated no coverage assessment, so no
    deterministic gap exists; the caller keeps the triager's own valid basis.
    `None` means no basis is derivable."""
    if runner_diverged:
        return RUNNER_DIVERGENCE
    if runner_failed:
        return RUNNER_FAILURE
    if procedure is None:
        return None
    if covered is None:
        return None
    gap = first_uncovered_gap(procedure, covered)
    if gap is not None:
        return gap
    return None


def variant_detail(spec: dict) -> str:
    """The canonical detail key of a derived variant spec: key-sorted JSON with
    no insignificant whitespace, so a re-authored identical spec compares equal
    while a changed field does not."""
    return json.dumps(spec, sort_keys=True, separators=(",", ":"), default=str)


def is_duplicate_variant(prior: Iterable[VariantSpec], basis: str, spec: dict) -> bool:
    """Whether `(basis, detail)` is already in the experiment log (S5 8.6 step
    6): a basis and its derived spec already recorded is never re-minted. The
    detail is the derived spec itself - the `VariantSpec.spec` payload - so the
    guard reads the log the triager already holds.

    The comparison is EXACT TEXT over the canonical key-sorted JSON (S5 8.6):
    two semantically equivalent specs with different key order compare equal,
    while a changed field does not. A re-worded but semantically identical spec
    is NOT caught; the guard's intent is to stop a literal re-mint, not to
    semantic-diff the triager's prose."""
    detail = variant_detail(spec)
    return any(v.declined_attribute == basis and variant_detail(v.spec) == detail
               for v in prior)


__all__ = [
    "ADVANCED_TECHNIQUE",
    "BYPASS_TECHNIQUE",
    "INTERPRETATION_PITFALL",
    "PRELIMINARY_CHAINING",
    "PROCEDURE_GAP_BASES",
    "PROCEDURE_GAP_FIELD",
    "PRO_TIPS",
    "RECON_ACTION",
    "RUNNER_DIVERGENCE",
    "RUNNER_FAILURE",
    "TECHNOLOGY_GROUNDING",
    "VARIANT_BASES",
    "VariantBasis",
    "first_uncovered_gap",
    "is_duplicate_variant",
    "mint_variant_basis",
    "variant_detail",
]
