"""Deterministic scoring of DeepSeek answers against a hand-marked golden set.

This is a rehearsal loop tool: run a scenario, save the answer, score it. The
metrics are bounded and reproducible; they are NOT a substitute for the
two-reviewer-plus-adjudicator standard required before production claims.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from lightrag.generation import AnswerBundleV1
from lightrag.query_spec import QuerySpecV1

_NEGATORS = (
    "no ",
    "not ",
    "never",
    "avoid",
    "without",
    "deny",
    "denied",
    "does not",
    "do not",
    "ruled out",
    "unlikely",
)


class GoldenEntryV1(BaseModel):
    """Hand-marked expectation for one scenario."""

    spec: QuerySpecV1
    expected_entity_types: list[str] = Field(default_factory=list)
    expected_entity_names: list[str] = Field(default_factory=list)
    min_knowledge_gaps: int = 0


class GoldenSetV1(BaseModel):
    schema_version: str = "lightrag-eval/v1"
    entries: list[GoldenEntryV1]

    def by_scenario(self, scenario_id: str) -> GoldenEntryV1 | None:
        for entry in self.entries:
            if entry.spec.scenario_id == scenario_id:
                return entry
        return None


class EvaluationMetricsV1(BaseModel):
    schema_valid: bool
    entity_type_coverage: float
    entity_name_coverage: float
    forbidden_claim_violations: int
    fabricated_references: list[str]
    citation_discipline: float
    grounded_explanations_rate: float
    no_hypothesis_compliant: bool | None = None
    knowledge_gaps_satisfied: bool
    composite: float


class EvaluationResultV1(BaseModel):
    scenario_id: str
    metrics: EvaluationMetricsV1
    notes: list[str] = Field(default_factory=list)


def _lower(value: str) -> str:
    return value.casefold().strip()


def _violates_claim(text: str, claim: str) -> bool:
    """Naive negator-guarded scan: claim present without a nearby negation."""
    lowered = _lower(text)
    needle = _lower(claim)
    start = 0
    while True:
        index = lowered.find(needle, start)
        if index == -1:
            return False
        window = lowered[max(0, index - 80) : index]
        if not any(negator in window for negator in _NEGATORS):
            return True
        start = index + len(needle)


def evaluate_answer(
    bundle: AnswerBundleV1,
    *,
    entry: GoldenEntryV1,
    allowed_reference_ids: list[str],
) -> EvaluationResultV1:
    """Score one bundle against one golden entry."""
    notes: list[str] = []
    spec = entry.spec

    emitted_types = {e.entity_type for e in bundle.ontology_explanations}
    expected_types = set(entry.expected_entity_types)
    type_coverage = (
        len(emitted_types & expected_types) / len(expected_types)
        if expected_types
        else 1.0
    )

    haystack = _lower(
        " ".join(
            [
                bundle.summary,
                *[e.entity_name for e in bundle.ontology_explanations],
                *[e.explanation for e in bundle.ontology_explanations],
            ]
        )
    )
    name_hits = sum(
        1 for name in entry.expected_entity_names if _lower(name) in haystack
    )
    name_coverage = (
        name_hits / len(entry.expected_entity_names)
        if entry.expected_entity_names
        else 1.0
    )

    violations = 0
    for claim in spec.unsupported_claims:
        for field in [bundle.summary, *[e.explanation for e in bundle.ontology_explanations]]:
            if _violates_claim(field, claim):
                violations += 1
                notes.append(f"forbidden_claim_present: {claim}")
                break

    allowed = set(allowed_reference_ids)
    citations: list[str] = []
    for explanation in bundle.ontology_explanations:
        citations.extend(explanation.evidence_references)
    citations.extend(bundle.provenance_references)
    unique_citations = list(dict.fromkeys(citations))
    fabricated = [c for c in unique_citations if c not in allowed]
    citation_discipline = (
        1.0
        if not unique_citations
        else max(0.0, 1.0 - len(fabricated) / len(unique_citations))
    )

    grounded = sum(
        1
        for explanation in bundle.ontology_explanations
        if any(ref in allowed for ref in explanation.evidence_references)
    )
    grounded_rate = (
        grounded / len(bundle.ontology_explanations)
        if bundle.ontology_explanations
        else 1.0
    )

    no_hypothesis_compliant: bool | None = None
    if spec.expected_no_hypothesis:
        no_hypothesis_compliant = not bundle.ontology_explanations
        if not no_hypothesis_compliant:
            notes.append("expected_no_hypothesis_but_explanations_present")

    gaps_ok = len(bundle.knowledge_gaps) >= entry.min_knowledge_gaps
    if not gaps_ok:
        notes.append("insufficient_knowledge_gaps")

    composite = round(
        0.25 * type_coverage
        + 0.25 * name_coverage
        + 0.20 * citation_discipline
        + 0.15 * grounded_rate
        + 0.15 * (1.0 if no_hypothesis_compliant is not False else 0.0)
        + (0.0 if violations else 0.0),
        4,
    )
    if violations:
        composite = round(min(composite, 0.75), 4)

    return EvaluationResultV1(
        scenario_id=spec.scenario_id,
        metrics=EvaluationMetricsV1(
            schema_valid=True,
            entity_type_coverage=round(type_coverage, 4),
            entity_name_coverage=round(name_coverage, 4),
            forbidden_claim_violations=violations,
            fabricated_references=fabricated,
            citation_discipline=round(citation_discipline, 4),
            grounded_explanations_rate=round(grounded_rate, 4),
            no_hypothesis_compliant=no_hypothesis_compliant,
            knowledge_gaps_satisfied=gaps_ok,
            composite=composite,
        ),
        notes=notes,
    )
