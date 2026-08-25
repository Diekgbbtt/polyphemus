from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

QueryPattern = Literal["target_state", "bypass", "chaining"]
ConfidenceLevel = Literal["high", "medium", "low"]
RetrievalMode = Literal["naive", "local", "global", "hybrid", "mix"]
AuthenticationState = Literal["unknown", "unauthenticated", "authenticated", "mixed"]
SafetyLevel = Literal["non_destructive", "low_impact", "manual_review"]
SourceTier = Literal["validated_base", "review_overlay"]
MAX_METHODOLOGY_CANDIDATES = 3
MAX_COMPACT_TEXT_CHARS = 280
MAX_SUMMARY_CHARS = 360
MAX_LIST_ITEMS = 6
MAX_EVIDENCE_REFS = 8
_FORBIDDEN_META_TEXT = (
    "I need to",
    "Let me",
    "Based on the provided context",
    "Here is how",
)
EntityType = Literal[
    "PreconditionEnvironment",
    "TechnologyStack",
    "DefensiveControl",
    "VulnerabilityClass",
    "AttackGoal",
    "AttackerCapability",
    "AttackTechnique",
    "PayloadPattern",
    "Artifact",
    "ObservableSignal",
]
RelationType = str


def _require_non_blank(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be blank")
    return value


def _require_compact_text(
    value: str,
    field_name: str,
    *,
    max_chars: int = MAX_COMPACT_TEXT_CHARS,
) -> str:
    value = _require_non_blank(value, field_name).strip()
    if len(value) > max_chars:
        raise ValueError(f"{field_name} must be <= {max_chars} characters")
    if value.count("\n") > 1:
        raise ValueError(f"{field_name} must be at most 1-2 lines")
    lowered = value.casefold()
    for marker in _FORBIDDEN_META_TEXT:
        if marker.casefold() in lowered:
            raise ValueError(f"{field_name} contains forbidden meta text")
    return value


def _clean_str_list(values: list[str], field_name: str) -> list[str]:
    cleaned = []
    for value in values:
        cleaned.append(_require_non_blank(value, field_name))
    return cleaned


def _clean_compact_str_list(
    values: list[str],
    field_name: str,
    *,
    max_items: int = MAX_LIST_ITEMS,
    max_chars: int = 180,
) -> list[str]:
    if len(values) > max_items:
        raise ValueError(f"{field_name} must contain <= {max_items} items")
    return [
        _require_compact_text(value, field_name, max_chars=max_chars)
        for value in values
    ]


class EvidenceRef(BaseModel):
    source_id: str
    locator: str
    document_title: str | None = None
    url: str | None = None
    quote: str | None = None

    @field_validator("source_id", "locator")
    @classmethod
    def _required_strings(cls, value):  # noqa: N805
        return _require_non_blank(value, "value")

    @field_validator("document_title", "url", "quote")
    @classmethod
    def _optional_strings(cls, value):  # noqa: N805
        if value is None:
            return value
        return _require_non_blank(value, "value")


class EntityRef(BaseModel):
    entity_type: EntityType
    canonical_name: str

    @field_validator("canonical_name")
    @classmethod
    def _canonical_name_required(cls, value):  # noqa: N805
        return _require_non_blank(value, "canonical_name")


class RelationPathStep(BaseModel):
    source: EntityRef
    relation: RelationType
    target: EntityRef
    applicability: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    confidence: ConfidenceLevel = "medium"

    @field_validator("applicability", "limitations")
    @classmethod
    def _string_lists(cls, value):  # noqa: N805
        return _clean_str_list(value, "value")

    @field_validator("relation")
    @classmethod
    def _relation_required(cls, value):  # noqa: N805
        return _require_non_blank(value, "relation")

    @field_validator("evidence_refs")
    @classmethod
    def _relation_step_requires_evidence(cls, value):  # noqa: N805
        if not value:
            raise ValueError("relation path steps require evidence_refs")
        return value


class TechniqueRef(BaseModel):
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)

    @field_validator("canonical_name")
    @classmethod
    def _canonical_name_required(cls, value):  # noqa: N805
        return _require_non_blank(value, "canonical_name")

    @field_validator("aliases")
    @classmethod
    def _aliases_not_blank(cls, value):  # noqa: N805
        return _clean_str_list(value, "aliases")


class CandidateRelevance(BaseModel):
    relation_path: list[RelationPathStep] = Field(default_factory=list)
    rationale: str

    @field_validator("rationale")
    @classmethod
    def _rationale_required(cls, value):  # noqa: N805
        return _require_compact_text(value, "rationale")


class CandidateApplicability(BaseModel):
    satisfied_conditions: list[str] = Field(default_factory=list)
    missing_conditions: list[str] = Field(default_factory=list)
    conflicting_conditions: list[str] = Field(default_factory=list)

    @field_validator("satisfied_conditions", "missing_conditions", "conflicting_conditions")
    @classmethod
    def _condition_lists(cls, value):  # noqa: N805
        return _clean_str_list(value, "value")


class ExpectedEffect(BaseModel):
    produces_condition: str | None = None
    enables_next_action: str | None = None

    @field_validator("produces_condition", "enables_next_action")
    @classmethod
    def _optional_strings(cls, value):  # noqa: N805
        if value is None:
            return value
        return _require_non_blank(value, "value")


class MethodologyCandidate(BaseModel):
    technique: TechniqueRef
    relevance: CandidateRelevance
    applicability: CandidateApplicability = Field(default_factory=CandidateApplicability)
    expected_effect: ExpectedEffect = Field(default_factory=ExpectedEffect)
    confidence: ConfidenceLevel = "medium"
    evidence_refs: list[EvidenceRef]
    observables: list[str] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)
    mitigation_checks: list[str] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)
    source_tier: SourceTier = "validated_base"

    @field_validator("evidence_refs")
    @classmethod
    def _candidate_requires_evidence(cls, value):  # noqa: N805
        if not value:
            raise ValueError("methodology candidates require evidence_refs")
        return value

    @field_validator("observables", "mitigation_checks")
    @classmethod
    def _compact_lists(cls, value):  # noqa: N805
        return _clean_compact_str_list(value, "value")


class CompactMethodologyCandidate(BaseModel):
    technique: str = Field(min_length=1, max_length=120)
    relevance: str = Field(min_length=1, max_length=MAX_COMPACT_TEXT_CHARS)
    satisfied_conditions: list[str] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)
    missing_conditions: list[str] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)
    observables: list[str] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)
    mitigation_checks: list[str] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)
    confidence: ConfidenceLevel = "medium"
    evidence_refs: list[str] = Field(min_length=1, max_length=MAX_EVIDENCE_REFS)
    source_tier: SourceTier = "validated_base"

    @field_validator("technique", "relevance")
    @classmethod
    def _compact_text(cls, value, info):  # noqa: N805
        return _require_compact_text(value, info.field_name)

    @field_validator(
        "satisfied_conditions",
        "missing_conditions",
        "observables",
        "mitigation_checks",
        "evidence_refs",
    )
    @classmethod
    def _compact_text_lists(cls, value, info):  # noqa: N805
        return _clean_compact_str_list(value, info.field_name, max_chars=180)


class CompactMethodologyBundle(BaseModel):
    query_id: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=MAX_SUMMARY_CHARS)
    candidates: list[CompactMethodologyCandidate] = Field(
        default_factory=list,
        max_length=MAX_METHODOLOGY_CANDIDATES,
    )
    knowledge_gaps: list[str] = Field(default_factory=list, max_length=MAX_EVIDENCE_REFS)
    source_tier: SourceTier = "validated_base"

    @field_validator("query_id", "summary")
    @classmethod
    def _compact_text(cls, value, info):  # noqa: N805
        max_chars = 120 if info.field_name == "query_id" else MAX_SUMMARY_CHARS
        return _require_compact_text(value, info.field_name, max_chars=max_chars)

    @field_validator("knowledge_gaps")
    @classmethod
    def _knowledge_gaps_compact(cls, value):  # noqa: N805
        return _clean_compact_str_list(value, "knowledge_gaps", max_items=MAX_EVIDENCE_REFS)

    @model_validator(mode="after")
    def _empty_candidates_need_gap(self):
        if not self.candidates and not self.knowledge_gaps:
            raise ValueError("empty compact methodology bundles require knowledge_gaps")
        return self


class SourceChunk(BaseModel):
    chunk_id: str
    source_id: str
    locator: str
    text: str

    @field_validator("chunk_id", "source_id", "locator", "text")
    @classmethod
    def _required_strings(cls, value):  # noqa: N805
        return _require_non_blank(value, "value")


class FaultContext(BaseModel):
    symptom: str | None = None
    symptoms: list[str] = Field(default_factory=list)
    vulnerability_hypothesis: str | None = None
    observed_conditions: list[str] = Field(default_factory=list)
    defenses_present: list[str] = Field(default_factory=list)
    available_capabilities: list[str] = Field(default_factory=list)
    blocked_technique: str | None = None
    desired_condition: str | None = None

    @field_validator("symptom", "vulnerability_hypothesis", "blocked_technique", "desired_condition")
    @classmethod
    def _optional_strings(cls, value):  # noqa: N805
        if value is None:
            return value
        return _require_non_blank(value, "value")

    @field_validator("symptoms", "observed_conditions", "defenses_present", "available_capabilities")
    @classmethod
    def _string_lists(cls, value):  # noqa: N805
        return _clean_str_list(value, "value")


class QueryConstraints(BaseModel):
    scope: list[str] = Field(default_factory=list)
    authentication_state: AuthenticationState = "unknown"
    safety_level: SafetyLevel = "non_destructive"
    excluded_techniques: list[str] = Field(default_factory=list)

    @field_validator("scope", "excluded_techniques")
    @classmethod
    def _string_lists(cls, value):  # noqa: N805
        return _clean_str_list(value, "value")


class RetrievalOptions(BaseModel):
    mode: RetrievalMode = "hybrid"
    max_candidates: int = Field(default=5, gt=0, le=50)


class KnowledgeQuery(BaseModel):
    query_id: str
    pattern: QueryPattern
    objective: str
    symptom: str | None = None
    taxonomy_tags: list[str] = Field(default_factory=list)
    fault_context: FaultContext = Field(default_factory=FaultContext)
    constraints: QueryConstraints = Field(default_factory=QueryConstraints)
    retrieval: RetrievalOptions = Field(default_factory=RetrievalOptions)

    @field_validator("query_id", "objective", "symptom")
    @classmethod
    def _required_strings(cls, value):  # noqa: N805
        if value is None:
            return value
        return _require_non_blank(value, "value")

    @field_validator("taxonomy_tags")
    @classmethod
    def _taxonomy_tags_not_blank(cls, value):  # noqa: N805
        return _clean_str_list(value, "taxonomy_tags")

    @model_validator(mode="after")
    def _pattern_required_context(self):
        context = self.fault_context
        if self.pattern == "target_state":
            if not context.vulnerability_hypothesis:
                raise ValueError("target_state requires vulnerability_hypothesis")
            if not context.observed_conditions:
                raise ValueError("target_state requires observed_conditions")
        elif self.pattern == "bypass":
            if not context.blocked_technique:
                raise ValueError("bypass requires blocked_technique")
            if not context.defenses_present:
                raise ValueError("bypass requires defenses_present")
        elif self.pattern == "chaining":
            if not context.desired_condition:
                raise ValueError("chaining requires desired_condition")
            if not (context.available_capabilities or context.observed_conditions):
                raise ValueError("chaining requires available_capabilities or observed_conditions")
        return self

    def to_retrieval_prompt(self) -> str:
        """Stable text form for generic retrievers that do not consume Pydantic objects."""
        context: dict[str, Any]
        if hasattr(self.fault_context, "model_dump"):
            context = self.fault_context.model_dump()
        else:
            context = self.fault_context.dict()
        fault_symptoms = []
        if self.symptom:
            fault_symptoms.append(self.symptom)
        if self.fault_context.symptom:
            fault_symptoms.append(self.fault_context.symptom)
        fault_symptoms.extend(self.fault_context.symptoms)
        return (
            "Given Symptom -> Retrieve Testing Techniques\n"
            f"pattern: {self.pattern}\n"
            f"objective: {self.objective}\n"
            f"fault_symptoms: {fault_symptoms}\n"
            f"taxonomy_tags: {self.taxonomy_tags}\n"
            f"fault_context: {context}\n"
            f"max_candidates: {self.retrieval.max_candidates}"
        )


class MethodologyBundle(BaseModel):
    query_id: str
    summary: str
    candidates: list[MethodologyCandidate] = Field(
        default_factory=list,
        max_length=MAX_METHODOLOGY_CANDIDATES,
    )
    knowledge_gaps: list[str] = Field(default_factory=list, max_length=MAX_EVIDENCE_REFS)
    source_tier: SourceTier = "validated_base"
    source_chunks: list[SourceChunk] = Field(default_factory=list)
    retrieval_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("query_id", "summary")
    @classmethod
    def _required_strings(cls, value):  # noqa: N805
        if value is None:
            return value
        return _require_compact_text(value, "value", max_chars=MAX_SUMMARY_CHARS)

    @field_validator("knowledge_gaps")
    @classmethod
    def _knowledge_gaps_not_blank(cls, value):  # noqa: N805
        return _clean_compact_str_list(value, "knowledge_gaps", max_items=MAX_EVIDENCE_REFS)

    @model_validator(mode="after")
    def _empty_candidates_need_gap(self):
        if not self.candidates and not self.knowledge_gaps:
            raise ValueError("empty methodology bundles require at least one knowledge_gap")
        return self
