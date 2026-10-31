"""The unit threat model schema and the pure completion checker (S2 5 and 7).

One model exists per discretely testable L1 unit (the unit id IS the model id).
The schema is **partial** at the intermediate workflow gates and **complete** at
`COMPLETED`: every section has an empty default, so a gate write extends one
document instead of re-authoring it.  Unknown fields are forbidden at every
level, so a typo can never silently persist.

Schema 5 (2026-10-31) is the CVSS 4.0 risk model.  The assessment row is the
scored claim: it carries the eight authored `RiskMetrics` factors and the
derived `risk` / `risk_vector`.  The threat is the dispatch grain: it references
the row through `impact_ref` and mirrors the derived `risk` for the mover.  The
model never authors a score, so the write shape (`ThreatWrite`) and the
canonical `Threat` differ by exactly `risk`, and `ModelSections.threats` carries
the write shape.

The entity names are the artifact contract's (`UnitThreatModel`,
`RawThreatModel`, `TechnicalSharpening`, `TrustModel`, `TrustAgreement`,
`DynamicStateTrust`, `Assumption`, `Fault`, `Vulnerability`, `PriorArt`,
`Precursor`, `ImpactAssessment`, `Threat`, `ThreatWrite`, `Evidence`,
`Confidence`, `RiskMetrics`, `RiskProfile`, `SeverityBand`, `Validation`).

Rules this module owns:

- The default progressive risk threshold (`DEFAULT_RISK_THRESHOLD`) - the run
  driver records it.
- The risk profile is computed from the threats' mirrored risk, never authored:
  the model's own total is untrusted (S2 7.3).
- The threat normalisation (S2 5.6): a stable sort by mirrored risk descending,
  ties in the modeller's write order, ids renumbered `threat-1..n`.  The store
  owns the id, so the write schema defaults `Threat.id` empty; the store also
  fills the mirror from the assessment rows, so the model cannot author it.  A
  mirror is filled only from a `threat` row of the threat's own vulnerability:
  a mismatched reference mirrors nothing and the checker rejects it.
- The completion checker (S2 5.7): the loose necessary-attribute set, the
  prior-art query requirement (one threat, one vulnerability, and one precursor
  query, each with a filter, plus the phase note), the referential integrity,
  the assumption-to-threat closure, the assessment invariants (one threat row
  per damage-bearing assessment, a precursor row with all three impact values
  `none`, the threat risk mirror equality, the enabling-precursor/capability-
  path equality, the capability-graph acyclicity), the threat order, and a
  REGRESSION check of the stored risk profile against a fresh recomputation.
  It is non-blocking: it records findings, it never rejects the model.

The checker is pure; the store (`threat_model_store`) applies it on the
`COMPLETED` write only.

Schema 5 is the ONLY model this module exposes: the retired likelihood and
impact-weight vocabulary (the enums, the weight tables, the CIA record, and the
`risk_factors`) is deleted, so no field, reader, or helper can route a score
through it.  A v4 document is still read RAW (`RawThreatModel`) and never
re-scored.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import AbstractSet, Any, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .risk_score import (
    RiskMetrics,
    RiskResult,
    SeverityBand,
    compute_risk,
    severity_band,
    validate_metrics,
)

SCHEMA_VERSION = 5

# The previous schema version. A v4 document is read RAW for prior art and
# measurement (never re-scored, never migrated), and a v4 write is refused.
PREVIOUS_SCHEMA_VERSION = 4

# The legacy schema versions the reader accepts when the caller asks for a
# legacy read. A v2/v3 document reads raw, exactly like v4: the v4 shape it was
# once lifted into no longer parses under schema 5, and no legacy model is
# re-scored.
LEGACY_SCHEMA_VERSIONS: tuple[int, ...] = (2, 3)

# Technique families are class parents in the suite tree, but they name a
# technique, not a vulnerability class. The completion checker records their
# use as a non-blocking finding; it never rejects the model.
TECHNIQUE_FAMILIES: frozenset[str] = frozenset(
    {"defence-bypass", "proxy-techniques", "two-principal-authz"}
)

# Migration note (2026-10-31): schema 5 replaces the likelihood x impact model
# with the CVSS 4.0 base score. The assessment row carries the eight factors and
# the derived `risk` / `risk_vector`; the threat mirrors the score and loses its
# likelihood block, its confidence, its risk factors, and its threat-side CIA
# vector; `RiskProfile` is the summed risk and the severity-band breakdown. The
# retired vocabulary itself is DELETED (T9 #412), not kept behind a flag. The
# `impact_assessment` section leaves `ModelSections` (the `assess_impact` tool is
# its sole writer, ticket #406). A v4 document is NOT migrated: the store reads it
# raw and refuses to write into it.
# Migration note (2026-10-26): schema 3 replaced the damage-first model with the
# impact-assessment model - the `prior_art`, `impact_assessment`, and
# `precursors` sections, the `PRIOR_ART` and `IMPACT_ASSESSED` gates,
# `Threat.impact_ref` / `Threat.enabling_precursors`, and `Impact` without
# `end_impact`. The damage text lives on the `ImpactAssessment` row. A v2 model
# is NOT migrated: this reader refuses it, and the measurement reads it raw.
# (2026-10-25, kept for history: the failure-mode contraction removed the
# `failure_modes` section and the `Threat.failure_mode_refs` link WITHOUT a
# version bump - the A/B uses fresh models and no legacy model is migrated.)

# The progressive risk budget's default halt (S2 7.4, scaled by the CVSS 4.0
# change: T7 #410, spec 7, ADR 8). The old per-threat maximum was 16, the CVSS
# 4.0 maximum is 10, so the ratio is 0.625 and the old documented default 250
# becomes 156.25. The operator raised the old default to 250 when the canary's
# first unit reached risk_total=44; the new value is that default scaled
# proportionally, never fitted to the iteration D corpus. The run records the
# effective threshold either way.
DEFAULT_RISK_THRESHOLD = 156.25


class Confidence(StrEnum):
    """The evidence-and-grounding degree every formal claim carries."""

    OBSERVED = "OBSERVED"
    INFERRED = "INFERRED"
    ASSUMED = "ASSUMED"


class UnitKind(StrEnum):
    SERVICE = "service"
    SYSTEM = "system"


class ModelState(StrEnum):
    """The seven workflow gates; the persisted state is the latest gate."""

    UNIT_TECHNICAL_SHARP = "UNIT_TECHNICAL_SHARP"
    TRUST_MODELLED = "TRUST_MODELLED"
    TRUST_ASSUMPTIONS_WRITTEN = "TRUST_ASSUMPTIONS_WRITTEN"
    VULNERABILITIES_WRITTEN = "VULNERABILITIES_WRITTEN"
    PRIOR_ART = "PRIOR_ART"
    IMPACT_ASSESSED = "IMPACT_ASSESSED"
    COMPLETED = "COMPLETED"


# The gate order (S2 5.3): a write whose gate is lower than the persisted state
# updates content but never regresses the state.
STATE_ORDER: dict[ModelState, int] = {
    state: rank for rank, state in enumerate(ModelState)
}

# The section names each gate may write (S2 5.4). The COMPLETED write does not
# carry `risk_profile`; the store computes it after the merge. The
# `IMPACT_ASSESSED` gate carries NO model-facing section: the `assess_impact`
# tool (ticket #406) is the sole writer of an assessment row, so the model can
# never bypass its contract. The gate still exists (the tool advances the state
# and the other consumers read the state); it just writes nothing through this
# surface.
GATE_SECTIONS: dict[ModelState, tuple[str, ...]] = {
    ModelState.UNIT_TECHNICAL_SHARP: ("technical_sharpening",),
    ModelState.PRIOR_ART: ("prior_art",),
    ModelState.TRUST_MODELLED: ("trust_model",),
    ModelState.TRUST_ASSUMPTIONS_WRITTEN: ("assumptions",),
    ModelState.VULNERABILITIES_WRITTEN: ("vulnerabilities",),
    ModelState.IMPACT_ASSESSED: (),
    ModelState.COMPLETED: ("threats",),
}


class EvidenceKind(StrEnum):
    REQUEST = "request"
    HTTP_HISTORY = "http_history"
    PROBE = "probe"
    NOTE = "note"
    MODEL = "model"
    FRAMEWORK_DEFAULT = "framework_default"
    DOCUMENT = "document"


class ViolationKind(StrEnum):
    TRUST_TRANSITION = "trust-transition"
    STATE_CONSISTENCY = "state-consistency"
    FORCED_TRANSITION = "forced-transition"
    OTHER = "other"


class _Record(BaseModel):
    """The shared shape rule: unknown fields are forbidden at every level."""

    model_config = ConfigDict(extra="forbid")


class Evidence(_Record):
    """One grounding entry of a claim (repeatable and indexable)."""

    kind: EvidenceKind
    ref: str
    detail: str = ""


class Agreement(_Record):
    """One technical-sharpening agreement (interface, control, or data flow)."""

    id: str
    statement: str
    confidence: Confidence
    evidences: list[Evidence]


class TrustAgreement(_Record):
    """One boundary trust agreement derived from the interface agreements."""

    id: str
    boundary: str
    interface_agreement_refs: list[str] = Field(
        default_factory=list,
        description=(
            "The ids of the technical_sharpening.interface_agreements this "
            "trust agreement rests on (IA-*), never control/data-flow ids and "
            "never prose."
        ),
    )
    statement: str
    confidence: Confidence
    evidences: list[Evidence]


class DynamicState(_Record):
    id: str
    variables: list[str]
    confidence: Confidence
    evidences: list[Evidence]


class Transition(_Record):
    id: str
    source: str
    target: str
    guard: str
    confidence: Confidence
    evidences: list[Evidence]


class Violation(_Record):
    id: str
    kind: ViolationKind
    statement: str
    maps_to_fault: str = Field(
        description=(
            "The id of the assumptions[].fault this violation maps to (F-*), "
            "never a description or prose."
        ),
    )
    # The transition the violation bounds (S2 5.1/S3 8.2): the payload's
    # dynamic-state selection reads this link. Optional because a
    # state-consistency violation need not bound a transition; when the model
    # carries transitions and this ref is absent the link is ambiguous.
    transition_ref: str | None = None
    confidence: Confidence
    evidences: list[Evidence]


class DynamicStateTrust(_Record):
    states: list[DynamicState] = Field(default_factory=list)
    transitions: list[Transition] = Field(default_factory=list)
    violations: list[Violation] = Field(default_factory=list)


class TechnicalSharpening(_Record):
    interface_agreements: list[Agreement] = Field(default_factory=list)
    control_flows: list[Agreement] = Field(default_factory=list)
    data_flows: list[Agreement] = Field(default_factory=list)


class TrustModel(_Record):
    trust_agreements: list[TrustAgreement] = Field(default_factory=list)
    dynamic_state_trust: DynamicStateTrust = Field(default_factory=DynamicStateTrust)


class Fault(_Record):
    id: str
    label: str
    description: str


class Assumption(_Record):
    id: str
    statement: str
    fault: Fault
    boundary_ref: str = ""
    confidence: Confidence
    evidences: list[Evidence]


class Vulnerability(_Record):
    id: str
    fault_ref: str
    canonical_class: str
    web_vulnerability_class: str = ""
    characterisation: str
    dropped: bool = False
    drop_reason: str = ""
    drop_probe: str = ""
    evidences: list[Evidence]


class PriorArtKind(StrEnum):
    """The record kinds the prior-art gate can query (spec section 7)."""

    THREAT = "threat"
    VULNERABILITY = "vulnerability"
    PRECURSOR = "precursor"
    ASSUMPTION = "assumption"
    IMPACT = "impact"


# The v5 factor paths of an assessment row, reused by the `threat`, `impact`,
# and `precursor` views so the catalog cannot drift from `RiskMetrics`.
_FACTOR_PATHS: tuple[str, ...] = (
    "factors",
    "factors.attack_vector",
    "factors.attack_complexity",
    "factors.attack_requirements",
    "factors.privileges_required",
    "factors.user_interaction",
    "factors.confidentiality",
    "factors.integrity",
    "factors.availability",
)

# The planned-profile amendment (2026-10-31): the v5 paths are `risk`,
# `risk_vector`, `factors.*`, `impact_description`, and
# `exploitability_description`; the v4 PROSE path (`damage`) stays accepted so a
# raw v4 document is still queryable. The retired scoring vocabulary (the
# likelihood, the risk factors, the confidence, the threat-side CIA vector, and
# the CIA weight) is not a path: a v4 document still reads raw, but its retired
# fields are not search terms. The `threat` view is the threat file merged with
# its impact row; the other views are the unit model's records. The catalog
# covers every field of the threat file and of the model records (a dict-valued
# path is matched on its JSON string); `unit_id` is accepted for EVERY kind (see
# `prior_art_paths`), because every view carries the owning model's identity and
# the query excludes the bound unit unless a filter names it.
PRIOR_ART_PATHS: dict[PriorArtKind, tuple[str, ...]] = {
    PriorArtKind.THREAT: (
        "threat_id",
        "dispatch_id",
        "unit_id",
        "unit_kind",
        "run_id",
        "risk",
        "risk_vector",
        # The assessment row's two prose blocks, flattened into the threat view
        # beside the threat file's own keys (schema-5 spec 10).
        "impact_description",
        "exploitability_description",
        *_FACTOR_PATHS,
        "created_at",
        "threat",
        "threat.id",
        "threat.fault_ref",
        "threat.vulnerability_ref",
        "threat.canonical_class",
        "threat.web_vulnerability_class",
        "threat.evidences",
        "threat.evidences.*.ref",
        "threat.impact_ref",
        "threat.enabling_precursors",
        "threat.risk",
        "impact",
        "impact.impact_ref",
        "impact.impact_description",
        "impact.exploitability_description",
        "impact.risk",
        "impact.risk_vector",
        "impact.factors",
        "impact.factors.attack_vector",
        "impact.factors.attack_complexity",
        "impact.factors.attack_requirements",
        "impact.factors.privileges_required",
        "impact.factors.user_interaction",
        "impact.factors.confidentiality",
        "impact.factors.integrity",
        "impact.factors.availability",
        "impact.damage",
        "impact.disposition",
        "impact.capability",
        "impact.capability_id",
        "impact.capability_path",
        "impact.precursor_refs",
        "impact.evidence_refs",
        "impact.evidence_refs.*",
        "impact.precursors",
        "impact.precursors.*.id",
        "impact.precursors.*.capability",
        "impact.precursors.*.procedure",
        "impact.precursors.*.evidence_refs",
    ),
    PriorArtKind.IMPACT: (
        "id",
        "vulnerability_ref",
        "disposition",
        "impact_description",
        "exploitability_description",
        "risk",
        "risk_vector",
        *_FACTOR_PATHS,
        "capability",
        "capability_id",
        "capability_path",
        "evidence_refs",
        # The v4 row's prose field stays queryable in a raw model.
        "damage",
    ),
    PriorArtKind.PRECURSOR: (
        "id",
        "capability",
        "capability_id",
        "vulnerability_ref",
        "impact_description",
        "exploitability_description",
        "risk",
        "risk_vector",
        *_FACTOR_PATHS,
        "damage",
        "disposition",
        "capability_path",
        "evidence_refs",
    ),
    PriorArtKind.VULNERABILITY: (
        "id",
        "fault_ref",
        "canonical_class",
        "web_vulnerability_class",
        "characterisation",
        "dropped",
        "drop_reason",
        "drop_probe",
        "evidences",
    ),
    PriorArtKind.ASSUMPTION: (
        "id",
        "description",
        "statement",
        "boundary_ref",
        "fault",
        "fault.id",
        "fault.label",
        "fault.description",
        "confidence",
        "evidences",
    ),
}


def prior_art_paths(kind: PriorArtKind) -> tuple[str, ...]:
    """The accepted filter paths of one query kind.

    The catalog plus the owning model's `unit_id`, which every record view
    carries: the query excludes the bound unit unless a filter path is
    `unit_id` (spec section 7). The assumption view carries both `description`
    (the catalog's name for the prose) and `statement` (the schema field), so
    either path resolves the one value.
    """
    return tuple(dict.fromkeys((*PRIOR_ART_PATHS[kind], "unit_id")))


class FieldFilter(_Record):
    """One regex field filter of a prior-art query (spec section 7)."""

    path: str
    regex: str
    flags: str = "i"


class PriorArtQuery(_Record):
    """One recorded prior-art query: the kind, its filters, its match count."""

    kind: PriorArtKind
    filters: list[FieldFilter]
    result_count: int


class PriorArtReuse(_Record):
    """One record reused from another unit's completed model."""

    unit_id: str
    record_id: str
    kind: str
    reason: str


class PriorArt(_Record):
    """The `PRIOR_ART` gate section (spec section 7).

    The queries the modeller ran and the records it reused. The completion
    check requires one query each for threats, vulnerabilities, and precursors
    (each with at least one filter) and a non-empty `notes`.
    """

    queries: list[PriorArtQuery] = Field(default_factory=list)
    reused: list[PriorArtReuse] = Field(default_factory=list)
    notes: str = ""


class ThreatQueryMatch(_Record):
    """One prior-art query match: the record summary, never the full model.

    The summary names the unit, the record, the kind, the label, the class, the
    disposition, the summary text, and the owning model's `state`, plus the
    evidence refs and the `matched` path/value pairs that made it match.
    """

    unit_id: str
    record_id: str
    kind: str
    label: str = ""
    web_vulnerability_class: str = ""
    disposition: str | None = None
    summary: str = ""
    state: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    matched: list[dict] = Field(default_factory=list)


class ThreatQueryResult(_Record):
    """The result of one prior-art query (spec section 7)."""

    matches: list[ThreatQueryMatch] = Field(default_factory=list)
    count: int = 0
    truncated: bool = False


class ImpactDisposition(StrEnum):
    """Whether a row reaches an end damage (`threat`) or only a capability."""

    THREAT = "threat"
    PRECURSOR = "precursor"


class Precursor(_Record):
    """One capability entity of a LEGACY model (schema 3 and earlier).

    Schema 4 moved the capability onto the impact row. This model is retained
    for the read-only compatibility path; no v5 gate writes it.
    """

    id: str
    capability: str
    procedure: str
    evidence_refs: list[str] = Field(default_factory=list)


class ImpactAssessment(_Record):
    """One assessed impact of one vulnerability exploitation (schema 5).

    The row is the SCORED claim: `factors` carries the eight authored CVSS 4.0
    base factors, and `risk` / `risk_vector` are derived from them at
    persistence, never authored.  `impact_description` names the victim and the
    damaged property for a `threat` row, and states why no end damage follows
    for a `precursor` row; `exploitability_description` describes the chain, its
    capabilities, and its human participation.  `capability` is the adversarial
    capability the exploitation gains, and `capability_id` keys it.
    `capability_path` lists the required capability ids in execution order.

    A `precursor` row has all three impact values `none`; a `threat` row has at
    least one above `none` (`risk_score.validate_metrics` owns the rule).
    """

    id: str = ""
    vulnerability_ref: str
    disposition: ImpactDisposition
    impact_description: str
    exploitability_description: str
    capability: str
    capability_id: str
    capability_path: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    factors: RiskMetrics
    # Derived at persistence (the `assess_impact` tool's commit), never
    # authored. The write path recomputes both from `factors`.
    risk: float = 0.0
    risk_vector: str = ""
    # Legacy schema-3 field: accepted on read, never written by a v5 gate.
    precursor_refs: list[str] = Field(default_factory=list, exclude=True)

    @field_validator("disposition", mode="before")
    @classmethod
    def _legacy_placeholder(cls, value: object) -> object:
        return "precursor" if value == "placeholder" else value


class ThreatWrite(_Record):
    """One damage-bearing row as the MODEL writes it (schema 5).

    The write shape is the canonical threat minus `risk`: the score is derived
    from the assessment row at persistence, so the model cannot author or
    iterate on it. `ModelSections.threats` is this type, which makes an authored
    `risk` a rejected field at the tool boundary.

    `id` defaults empty: the threat id is a store-owned derived symbol assigned
    at the COMPLETED write (S2 5.6 / 10.2), never authored by the modeller. The
    same reasoning keeps `impact_ref` and `enabling_precursors` defaulted empty:
    the completion checker reports them as findings, so an incomplete threat is
    feedback for the model rather than a rejected write.
    """

    id: str = ""
    fault_ref: str
    vulnerability_ref: str
    canonical_class: str
    web_vulnerability_class: str = ""
    evidences: list[Evidence]
    # The impact-assessment row this threat publishes (IA-*) and the ordered
    # (required capability, provider capability) pairs that reach its damage.
    # One threat references exactly one `threat` assessment. A `None` provider
    # is an unfilled gap; the first element mirrors the row's capability_path.
    impact_ref: str = ""
    enabling_precursors: list[tuple[str, str | None]] = Field(default_factory=list)

    @field_validator("enabling_precursors", mode="before")
    @classmethod
    def _legacy_enabling(cls, value: object) -> object:
        """A v3 list of P-* ids reads as a self-provided chain."""
        if not isinstance(value, list):
            return value
        normalized: list[object] = []
        for item in value:
            if isinstance(item, str):
                normalized.append((item, item))
            elif isinstance(item, (list, tuple)) and len(item) == 2:
                normalized.append((item[0], item[1]))
            else:
                normalized.append(item)
        return normalized


class Threat(ThreatWrite):
    """One damage-bearing row and the dispatch grain (schema 5).

    `risk` is the assessment row's derived score, mirrored here at the
    COMPLETED write for the mover and the threat file. It is never authored:
    the model writes `ThreatWrite`, and the store overwrites the mirror from
    the row the threat's `impact_ref` names.
    """

    risk: float = 0.0


class RiskProfile(_Record):
    """The unit's derived risk: the summed threat risk and the band breakdown."""

    total: float
    breakdown: dict[SeverityBand, int]


class Validation(_Record):
    checked_at: datetime
    parseable: bool
    valid: bool
    missing: list[str] = Field(default_factory=list)
    unclosed: list[str] = Field(default_factory=list)
    referential_errors: list[str] = Field(default_factory=list)
    # The class-binding signals (ADR, 2026-10-25). They never make the model
    # invalid: they are a signal to the modeller that the modelling procedure
    # went wrong, not a symbolic rejection.
    class_findings: list[str] = Field(default_factory=list)


class ModelSections(BaseModel):
    """The typed write payload for one threat-model gate.

    The tool schema exposes exactly the sections the store accepts; it is not
    an open `dict`. The store still enforces the per-gate allowed set, so a
    section from the wrong gate is a coded rejection. All fields are optional
    because a gate writes only its own section(s).

    `threats` is the WRITE shape (`ThreatWrite`), so an authored `risk` is an
    unknown field. The assessment rows are not a model-facing section at all:
    the `assess_impact` tool (ticket #406) is their sole writer."""

    technical_sharpening: TechnicalSharpening | None = None
    prior_art: PriorArt | None = None
    trust_model: TrustModel | None = None
    assumptions: list[Assumption] | None = None
    vulnerabilities: list[Vulnerability] | None = None
    threats: list[ThreatWrite] | None = None

    model_config = ConfigDict(extra="forbid")


class UnitThreatModel(_Record):
    """The complete unit threat model (S2 5.1).

    At the intermediate gates the same shape is persisted with the empty
    section defaults (`PartialThreatModel`); the completion checker runs only
    on the COMPLETED gate.
    """

    schema_version: int = SCHEMA_VERSION
    unit_id: str
    unit_kind: UnitKind
    run_id: str
    created_at: datetime
    updated_at: datetime
    state: ModelState
    technical_sharpening: TechnicalSharpening = Field(default_factory=TechnicalSharpening)
    prior_art: PriorArt = Field(default_factory=PriorArt)
    trust_model: TrustModel = Field(default_factory=TrustModel)
    assumptions: list[Assumption] = Field(default_factory=list)
    vulnerabilities: list[Vulnerability] = Field(default_factory=list)
    impact_assessment: list[ImpactAssessment] = Field(default_factory=list)
    precursors: list[Precursor] = Field(default_factory=list)
    threats: list[Threat] = Field(default_factory=list)
    risk_profile: RiskProfile | None = None
    validation: Validation | None = None


class PartialThreatModel(UnitThreatModel):
    """The persisted document shape at every write (S2 5.1).

    It is the complete schema with the empty section defaults: the store parses
    every write as this shape, and the completion checker is the only reader
    that requires the complete content.
    """


def unit_kind_from_unit_id(unit_id: str) -> UnitKind:
    """The unit kind from the kind-qualified L1 identity.

    A Service's identity is `Service:<business-function-slug>`; every other
    identity is a System's `(<kind>, <discriminator>)` form (bare for a
    singleton). This is the same derivation the hunting prompt projection uses
    (`hunting.llm`), kept here so the store never guesses an unbound identity.
    """
    return UnitKind.SERVICE if unit_id.startswith("Service:") else UnitKind.SYSTEM


class RawThreatModel(_Record):
    """A legacy document read RAW: the version and the sections, verbatim.

    The v4 shape is not migrated and never re-scored (schema-5 spec 11). The
    prior art and the measurement read its fields as they were persisted, so
    this record deliberately does not parse, normalise, or validate a single
    section. `sections` holds every key of the document except
    `schema_version`.
    """

    schema_version: int
    sections: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_document(cls, raw: Mapping[str, Any]) -> "RawThreatModel":
        """The wrapper over one loaded document mapping."""
        version = raw.get("schema_version")
        return cls(
            schema_version=version if isinstance(version, int) else 0,
            sections={
                str(key): value for key, value in raw.items()
                if key != "schema_version"
            },
        )

    def document(self) -> dict[str, Any]:
        """The document as it was persisted, `schema_version` included."""
        return {"schema_version": self.schema_version, **self.sections}


def document_of(model: UnitThreatModel | RawThreatModel) -> dict[str, Any]:
    """One loaded document as a JSON-safe mapping.

    The ONE place a typed load is rendered back to the document shape: the
    store parses and merges mappings, and a raw legacy record must round-trip
    byte-equivalent, never through the v5 schema's field set.
    """
    if isinstance(model, RawThreatModel):
        return model.document()
    return model.model_dump(mode="json")


def compute_risk_profile(threats: list[Threat]) -> RiskProfile:
    """The authoritative per-unit risk profile (S2 7.3, schema 5).

    The total sums every threat's mirrored `risk` (rounded to two decimals, as
    the score is) and the breakdown counts every threat by its `SeverityBand`.
    The profile recomputes from the threats; it never trusts an authored
    profile. The modeller never authors either value.
    """
    breakdown = {band: 0 for band in SeverityBand}
    total = 0.0
    for threat in threats:
        breakdown[severity_band(threat.risk)] += 1
        total += threat.risk
    return RiskProfile(total=round(total, 2), breakdown=breakdown)


def _risk_by_assessment(
    threats: Sequence[Threat],
    assessments: Mapping[str, float] | Sequence[ImpactAssessment] | None,
) -> dict[tuple[str, str], float]:
    """The `{(impact_ref, vulnerability_ref): risk}` map the mirror reads.

    A row is matched only when it carries the threat's OWN vulnerability and is
    a `threat` row: the assessment is the scored claim for one exploitation, so
    a reference to another vulnerability's row or to a precursor row mirrors
    nothing and the checker reports it. A caller that already holds a
    `{impact_ref: risk}` map passes it directly; it is authoritative for the
    threat that names the reference. A missing map leaves every threat's own
    `risk` in place, which the completion checker then reports as a mismatch.
    """
    if assessments is None:
        return {}
    if isinstance(assessments, Mapping):
        return {
            (threat.impact_ref, threat.vulnerability_ref):
                float(assessments[threat.impact_ref])
            for threat in threats
            if threat.impact_ref in assessments
        }
    return {
        (row.id, row.vulnerability_ref): row.risk
        for row in assessments
        if row.id and row.disposition is ImpactDisposition.THREAT
    }


def normalise_threats(
    threats: list[Threat],
    assessments: Mapping[str, float] | Sequence[ImpactAssessment] | None = None,
) -> list[Threat]:
    """The ranked order and the derived threat fields (S2 5.6, schema 5).

    The store fills the risk mirror from the assessment rows FIRST, then sorts
    stable by risk descending with the modeller's write order as the tie-break,
    and renumbers `threat-1..n` in that order. Rank 1 is the highest risk. The
    assessment is the scored claim, so a threat whose `impact_ref` names no
    matching row keeps whatever `risk` it carried (zero for a model-written
    threat) and the checker reports it.
    """
    risks = _risk_by_assessment(threats, assessments)
    ordered = sorted(
        enumerate(threats),
        key=lambda pair: (
            -risks.get(
                (pair[1].impact_ref, pair[1].vulnerability_ref), pair[1].risk),
            pair[0],
        ),
    )
    return [
        threat.model_copy(update={
            "id": f"threat-{rank}",
            "risk": risks.get(
                (threat.impact_ref, threat.vulnerability_ref), threat.risk),
        })
        for rank, (_index, threat) in enumerate(ordered, start=1)
    ]


def _check_necessary(model: UnitThreatModel) -> list[str]:
    """The fixed necessary-attribute set (S2 5.7), as dotted finding paths.

    The boundary is a pydantic-validated `UnitThreatModel`: `unit_kind` and
    the `RiskMetrics` values are already enum-checked by the schema, so no
    finding can exist for them and none is emitted (the store rejects an
    invalid shape at the write seam).
    """
    missing: list[str] = []
    sharpening = model.technical_sharpening
    if not model.unit_id:
        missing.append("unit_id")
    if not sharpening.interface_agreements:
        missing.append("technical_sharpening.interface_agreements")
    if not sharpening.control_flows:
        missing.append("technical_sharpening.control_flows")
    if not sharpening.data_flows:
        missing.append("technical_sharpening.data_flows")
    # The prior-art requirement (spec section 7): the modeller grounds the
    # trust model in at least one query for each of the three record kinds, each
    # with at least one filter, and records the phase note.
    for kind in (
        PriorArtKind.THREAT,
        PriorArtKind.VULNERABILITY,
        PriorArtKind.PRECURSOR,
    ):
        queries = [query for query in model.prior_art.queries if query.kind is kind]
        if not queries:
            missing.append(f"prior_art.queries.{kind.value}")
        elif not any(query.filters for query in queries):
            missing.append(f"prior_art.queries.{kind.value}.filters")
    if not model.prior_art.notes:
        missing.append("prior_art.notes")
    if not model.trust_model.trust_agreements:
        missing.append("trust_model.trust_agreements")
    if not model.trust_model.dynamic_state_trust.states:
        missing.append("trust_model.dynamic_state_trust.states")
    if not model.assumptions:
        missing.append("assumptions")
    for assumption in model.assumptions:
        fault = assumption.fault
        if not fault.id:
            missing.append(f"assumption:{assumption.id}.fault.id")
        if not fault.label:
            missing.append(f"assumption:{assumption.id}.fault.label")
        if not fault.description:
            missing.append(f"assumption:{assumption.id}.fault.description")
    if not model.vulnerabilities:
        missing.append("vulnerabilities")
    for vulnerability in model.vulnerabilities:
        if not vulnerability.canonical_class:
            missing.append(f"vulnerability:{vulnerability.id}.canonical_class")
    every_vulnerability_dropped = bool(model.vulnerabilities) and all(
        vulnerability.dropped for vulnerability in model.vulnerabilities
    )
    if not model.impact_assessment and not every_vulnerability_dropped:
        # A model whose vulnerabilities are all dropped has no threats and is
        # still complete; the scored claims are the impact rows.
        missing.append("impact_assessment")
    # The assessment invariants (S2 5.7, schema 5). Every row carries its two
    # prose blocks, its capability, its key, and the derived vector; the factor
    # SET is enforced by `RiskMetrics` at the write seam, so only the factor
    # VALUES need a finding. A `precursor` row must be all-none and a `threat`
    # row must carry at least one non-none value (`validate_metrics` owns both
    # rules). A row with no end damage is a `precursor` and has no threat; the
    # capability path is the ordered set of required capabilities and may be
    # empty for a direct impact.
    for assessment in model.impact_assessment:
        for name in ("impact_description", "exploitability_description"):
            if not getattr(assessment, name):
                missing.append(f"impact_assessment:{assessment.id}.{name}")
        if not assessment.capability:
            missing.append(f"impact_assessment:{assessment.id}.capability")
        if not assessment.capability_id:
            missing.append(f"impact_assessment:{assessment.id}.capability_id")
        # The score and the vector are DERIVED at the assessment write. A row
        # whose values do not recompute from its factors was hand-edited or
        # written outside the store, so the checker reports it - the same
        # REGRESSION discipline as the stored risk profile (spec 5).
        computed = compute_risk(assessment.factors)
        if assessment.risk != computed.score:
            missing.append(f"impact_assessment:{assessment.id}.risk")
        if assessment.risk_vector != computed.vector:
            missing.append(f"impact_assessment:{assessment.id}.risk_vector")
        missing.extend(
            f"impact_assessment:{assessment.id}.{finding}"
            for finding in validate_metrics(
                assessment.factors, disposition=assessment.disposition.value)
        )
    for index, assessment in enumerate(model.impact_assessment):
        if not assessment.id:
            missing.append(f"impact_assessment[{index}].id")
    assessment_ids = [
        assessment.id for assessment in model.impact_assessment if assessment.id
    ]
    if len(assessment_ids) != len(set(assessment_ids)):
        missing.append("impact_assessment.ids")
    capability_ids = [
        assessment.capability_id
        for assessment in model.impact_assessment
        if assessment.capability_id
    ]
    if len(capability_ids) != len(set(capability_ids)):
        missing.append("impact_assessment.capability_ids")
    impact_index = {
        assessment.id: assessment for assessment in model.impact_assessment
    }
    for threat in model.threats:
        if not threat.evidences:
            missing.append(f"threat:{threat.id}.evidences")
        if not threat.impact_ref:
            missing.append(f"threat:{threat.id}.impact_ref")
        # The mirror: the threat's risk IS the row's derived score. A threat
        # whose row is missing is the referential check's finding, so it is not
        # reported twice.
        assessment = impact_index.get(threat.impact_ref)
        if assessment is not None and threat.risk != assessment.risk:
            missing.append(f"threat:{threat.id}.risk")
    risks = [threat.risk for threat in model.threats]
    if any(left < right for left, right in zip(risks, risks[1:])):
        missing.append("threats.order")
    expected_ids = [f"threat-{rank}" for rank in range(1, len(model.threats) + 1)]
    if [threat.id for threat in model.threats] != expected_ids:
        missing.append("threats.ids")
    if model.risk_profile is None:
        missing.append("risk_profile")
    else:
        expected = compute_risk_profile(model.threats)
        if model.risk_profile != expected:
            if model.risk_profile.total != expected.total:
                missing.append("risk_profile.total")
            if model.risk_profile.breakdown != expected.breakdown:
                missing.append("risk_profile.breakdown")
    return missing


def _check_references(
    model: UnitThreatModel,
    capability_index: Mapping[str, Any] | None = None,
) -> list[str]:
    """The referential-integrity findings (S2 5.7), as dotted finding paths."""
    errors: list[str] = []
    sharpening = model.technical_sharpening
    dynamic = model.trust_model.dynamic_state_trust
    fault_ids = {assumption.fault.id for assumption in model.assumptions}
    vulnerability_ids = {vulnerability.id for vulnerability in model.vulnerabilities}
    vulnerability_index = {vulnerability.id: vulnerability for vulnerability in model.vulnerabilities}
    agreement_ids = {agreement.id for agreement in sharpening.interface_agreements}
    trust_agreement_ids = {
        agreement.id for agreement in model.trust_model.trust_agreements
    }
    state_ids = {state.id for state in dynamic.states}
    impact_ids = {row.id for row in model.impact_assessment if row.id}
    local_capabilities = {
        row.capability_id: row
        for row in model.impact_assessment
        if row.capability_id
    }
    foreign_capabilities = capability_index or {}

    def resolve_capability(ref: str) -> dict | None:
        if ref.startswith(f"{model.unit_id}::"):
            return local_capabilities.get(ref.split("::", 1)[1])
        if "::" in ref:
            return foreign_capabilities.get(ref)
        return local_capabilities.get(ref)

    def unresolved(owner: str, field: str, ref: str) -> None:
        errors.append(f"{owner}.{field}={ref!r}")

    for vulnerability in model.vulnerabilities:
        if vulnerability.fault_ref not in fault_ids:
            unresolved(f"vulnerability:{vulnerability.id}", "fault_ref", vulnerability.fault_ref)
    for assessment in model.impact_assessment:
        if assessment.vulnerability_ref not in vulnerability_ids:
            unresolved(
                f"impact_assessment:{assessment.id}",
                "vulnerability_ref",
                assessment.vulnerability_ref,
            )
        for ref in assessment.capability_path:
            if resolve_capability(ref) is None:
                unresolved(
                    f"impact_assessment:{assessment.id}", "capability_path", ref)
    for assumption in model.assumptions:
        if assumption.boundary_ref and assumption.boundary_ref not in trust_agreement_ids:
            unresolved(f"assumption:{assumption.id}", "boundary_ref", assumption.boundary_ref)
    for agreement in model.trust_model.trust_agreements:
        for ref in agreement.interface_agreement_refs:
            if ref not in agreement_ids:
                unresolved(f"trust_agreement:{agreement.id}", "interface_agreement_refs", ref)
    transition_ids = {transition.id for transition in dynamic.transitions}
    for transition in dynamic.transitions:
        for endpoint in (transition.source, transition.target):
            if endpoint not in state_ids:
                unresolved(f"transition:{transition.id}", "state_ref", endpoint)
    for violation in dynamic.violations:
        if violation.maps_to_fault not in fault_ids:
            unresolved(f"violation:{violation.id}", "maps_to_fault", violation.maps_to_fault)
        if violation.transition_ref and violation.transition_ref not in transition_ids:
            unresolved(f"violation:{violation.id}", "transition_ref",
                       violation.transition_ref)
    for threat in model.threats:
        if threat.fault_ref not in fault_ids:
            unresolved(f"threat:{threat.id}", "fault_ref", threat.fault_ref)
        if threat.vulnerability_ref not in vulnerability_ids:
            unresolved(f"threat:{threat.id}", "vulnerability_ref", threat.vulnerability_ref)
        if threat.impact_ref not in impact_ids:
            unresolved(f"threat:{threat.id}", "impact_ref", threat.impact_ref)
        for capability, provider in threat.enabling_precursors:
            if resolve_capability(capability) is None:
                unresolved(
                    f"threat:{threat.id}", "enabling_precursors.capability", capability)
            if provider is not None and resolve_capability(provider) is None:
                unresolved(
                    f"threat:{threat.id}", "enabling_precursors.precursor", provider)
        vulnerability = vulnerability_index.get(threat.vulnerability_ref)
        if vulnerability is not None:
            if threat.canonical_class != vulnerability.canonical_class:
                unresolved(f"threat:{threat.id}", "canonical_class", threat.canonical_class)
            if threat.web_vulnerability_class != vulnerability.web_vulnerability_class:
                unresolved(
                    f"threat:{threat.id}", "web_vulnerability_class",
                    threat.web_vulnerability_class,
                )
    return errors


def _check_closure(model: UnitThreatModel) -> list[str]:
    """The assumption-to-threat closure findings (S2 5.7), as dotted paths.

    The impact closure is the one-threat-one-assessment rule: a `threat` row
    publishes exactly one threat, a `precursor` row none, a threat references a
    `threat` row of its own vulnerability, and its enabling pairs mirror that
    row's capability path in order. An unresolved reference is the referential
    check's finding, so a threat whose row is missing is not reported twice.
    """
    unclosed: list[str] = []
    vulnerability_index = {vulnerability.id: vulnerability for vulnerability in model.vulnerabilities}
    impact_index = {row.id: row for row in model.impact_assessment}
    threats_by_impact: dict[str, list[Threat]] = {}
    for threat in model.threats:
        threats_by_impact.setdefault(threat.impact_ref, []).append(threat)
    for assessment in model.impact_assessment:
        expected = 1 if assessment.disposition is ImpactDisposition.THREAT else 0
        if len(threats_by_impact.get(assessment.id, [])) != expected:
            unclosed.append(f"impact_assessment:{assessment.id}.threat")
    for threat in model.threats:
        assessment = impact_index.get(threat.impact_ref)
        if assessment is None:
            continue
        if (
            assessment.disposition is not ImpactDisposition.THREAT
            or assessment.vulnerability_ref != threat.vulnerability_ref
        ):
            unclosed.append(f"threat:{threat.id}.impact_ref")
        elif [capability for capability, _ in threat.enabling_precursors] != list(
            assessment.capability_path
        ):
            unclosed.append(f"threat:{threat.id}.enabling_precursors")
    for assumption in model.assumptions:
        if not any(
            vulnerability.fault_ref == assumption.fault.id
            for vulnerability in model.vulnerabilities
        ):
            unclosed.append(f"assumption:{assumption.id}")
    for vulnerability in model.vulnerabilities:
        if vulnerability.dropped:
            if not vulnerability.drop_reason:
                unclosed.append(f"vulnerability:{vulnerability.id}.drop_reason")
            if not vulnerability.drop_probe:
                unclosed.append(f"vulnerability:{vulnerability.id}.drop_probe")
            continue
        if not any(
            row.vulnerability_ref == vulnerability.id
            for row in model.impact_assessment
        ):
            unclosed.append(f"vulnerability:{vulnerability.id}.impact_assessment")
    for threat in model.threats:
        vulnerability = vulnerability_index.get(threat.vulnerability_ref)
        if vulnerability is not None and vulnerability.dropped:
            unclosed.append(f"threat:{threat.id}.vulnerability_ref")
    return unclosed


def _capability_cycle(
    model: UnitThreatModel,
    capability_index: Mapping[str, Any] | None = None,
) -> str | None:
    """A cycle over the capability graph, local or across units.

    A kill chain cannot revisit a capability it needs; a cycle means the model
    has not reached an end damage.
    """
    edges: dict[str, list[str]] = {}

    def qualify(unit: str, ref: str) -> str:
        return ref if "::" in ref else f"{unit}::{ref}"

    def add(unit: str, row: Mapping[str, Any]) -> None:
        capability_id = str(row.get("capability_id") or "")
        if not capability_id:
            return
        key = f"{unit}::{capability_id}"
        edges.setdefault(key, []).extend(
            qualify(unit, str(ref)) for ref in (row.get("capability_path") or [])
        )

    for row in model.impact_assessment:
        add(model.unit_id, row.model_dump(mode="json"))
    for entry in (capability_index or {}).values():
        if isinstance(entry, Mapping):
            add(str(entry.get("unit_id") or ""), entry.get("row") or {})

    visiting: set[str] = set()
    done: set[str] = set()

    def walk(node: str) -> bool:
        if node in visiting:
            return True
        if node in done:
            return False
        visiting.add(node)
        for nxt in edges.get(node, []):
            if nxt in edges and walk(nxt):
                return True
        visiting.discard(node)
        done.add(node)
        return False

    return "capability_path.cycle" if any(walk(node) for node in list(edges)) else None


def _check_classes(
    model: UnitThreatModel, class_names: AbstractSet[str] | None,
) -> list[str]:
    """The class-binding signals (ADR, 2026-10-25).

    An empty class, a technique family, or a name outside the supplied suite
    index is a finding. A finding never makes the model invalid: the operator
    wants a signal that the modelling procedure went wrong, not a symbolic
    rejection.
    """
    findings: list[str] = []
    for vulnerability in model.vulnerabilities:
        value = vulnerability.web_vulnerability_class
        if not value:
            findings.append(
                f"vulnerability:{vulnerability.id}.web_vulnerability_class=empty")
        elif value in TECHNIQUE_FAMILIES:
            findings.append(
                f"vulnerability:{vulnerability.id}.web_vulnerability_class="
                f"{value!r} is a technique family, not a vulnerability class")
        elif class_names is not None and value not in class_names:
            findings.append(
                f"vulnerability:{vulnerability.id}.web_vulnerability_class="
                f"{value!r} is not in the suite")
    return findings


def check_completion(
    model: UnitThreatModel,
    *,
    checked_at: datetime | None = None,
    class_names: AbstractSet[str] | None = None,
    capability_index: Mapping[str, Any] | None = None,
) -> Validation:
    """The non-blocking completion check (S2 5.7).

    It records the necessary-attribute, referential-integrity, and closure
    findings; `valid` is true only when the model parsed and all three finding
    lists are empty. The stored risk profile is REGRESSION-checked against a
    fresh recomputation from the threats, never trusted.

    `class_names` is the optional suite index (class parents and variant
    leaves). Its findings ride the separate `class_findings` list and never
    affect `valid`.

    The boundary is a pydantic-validated `UnitThreatModel`, so
    `Validation.parseable` is always true here: the store rejects an
    unparseable write at the write seam (S1 6.6) before any model reaches the
    checker. The flag stays on the record so a later caller that validates a
    raw document can report a parse failure without a schema change.
    """
    missing = _check_necessary(model)
    referential_errors = _check_references(model, capability_index)
    unclosed = _check_closure(model)
    cycle = _capability_cycle(model, capability_index)
    if cycle is not None:
        unclosed.append(cycle)
    class_findings = _check_classes(model, class_names)
    return Validation(
        checked_at=checked_at or datetime.now(timezone.utc),
        parseable=True,
        valid=not missing and not unclosed and not referential_errors,
        missing=missing,
        unclosed=unclosed,
        referential_errors=referential_errors,
        class_findings=class_findings,
    )


__all__ = [
    "Agreement",
    "Assumption",
    "Confidence",
    "DEFAULT_RISK_THRESHOLD",
    "DynamicState",
    "DynamicStateTrust",
    "Evidence",
    "EvidenceKind",
    "Fault",
    "FieldFilter",
    "GATE_SECTIONS",
    "ImpactAssessment",
    "ImpactDisposition",
    "ModelSections",
    "ModelState",
    "PREVIOUS_SCHEMA_VERSION",
    "PartialThreatModel",
    "PRIOR_ART_PATHS",
    "Precursor",
    "PriorArt",
    "PriorArtKind",
    "PriorArtQuery",
    "PriorArtReuse",
    "RawThreatModel",
    "RiskMetrics",
    "RiskProfile",
    "RiskResult",
    "SCHEMA_VERSION",
    "SeverityBand",
    "TECHNIQUE_FAMILIES",
    "STATE_ORDER",
    "TechnicalSharpening",
    "Threat",
    "ThreatQueryMatch",
    "ThreatQueryResult",
    "ThreatWrite",
    "Transition",
    "TrustAgreement",
    "TrustModel",
    "UnitKind",
    "UnitThreatModel",
    "Validation",
    "Violation",
    "ViolationKind",
    "Vulnerability",
    "check_completion",
    "compute_risk",
    "compute_risk_profile",
    "document_of",
    "severity_band",
    "normalise_threats",
    "prior_art_paths",
    "unit_kind_from_unit_id",
    "validate_metrics",
]
