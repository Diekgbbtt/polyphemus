# CVSS 4.0 risk scoring for the unit threat model - specification

*Status: ready-for-agent, 2026-10-31. Decision authority: `threat-model-cvss4-risk-scoring-adr.md` and `impact-assessment-atomic-write-adr.md`.*
*Impact map: `cvss4-risk-scoring-impact-map.md`.*
*Supersedes the risk-scoring and assessment-write sections of `impact-assessment-system-spec.md` and `hunting-67-threat-model-artifact-spec.md`.*

## Problem Statement

The threat modeller scores a threat with a free-form `likelihood` enum multiplied by an ordinal `impact` weight.
The four exploitability factors (`attack_vector`, `attack_requirements`, `privileges_required`, `complexity`) are stored but never feed the score.
The model also lowers the likelihood for an `ASSUMED` premise, so a severe but unverified direction is demoted before a hunter can verify it.
The impact model is a first-party CVSS-4.0-like formula with four levels, including a `medium` value that CVSS 4.0 does not define.

The iteration D run exposed three consequences:

- A stored XSS scored risk 6 because the rationale treated a reader opening the article as an attacker requirement.
- The remember-me deserialization and the client-render disclosure were explicitly demoted for an `ASSUMED` premise.
- The dispatch queue ordered units by their model sum, so the one-threat article unit never reached the twelve dispatched hunts.

The operator needs one deterministic severity score per threat.
The score must be the CVSS 4.0 base score over factors compiled from the kill chain.
The model must not author or see the score.
Confidence must leave the score and remain only on the technical and trust-model claims that a hunter can probe.
The dispatch queue must order threats by risk, not units by model sum.
The thresholds must be floats so the operator can tune them.

## Solution

Every impact assessment row carries two prose blocks and eight CVSS 4.0 base factors.
The new `assess_impact` tool writes one row atomically, validates the contract, and returns success or a coded rejection.
The persistence helper builds the CVSS 4.0 vector, computes the base score, and persists it on the row.
The threat references the assessment and mirrors the derived score for dispatch.
The modeller never authors the score and never sees it.
The `likelihood` enum, the `RiskFactors` side record, the threat-side CIA vector, the `confidence` field on threats and vulnerabilities, and the old impact weights are deleted.
The dispatch queue orders threats by risk descending, with no per-unit cap.
The promotion floor and the risk budget are floats, scaled proportionally from the old 0..16 scale.

## User Stories

1. As a threat modeller, I want to reflect on the impact and the exploitability in two prose blocks, so the reasoning is explicit before I compile it to metric values.
2. As a threat modeller, I want the assessment write to carry both prose blocks and all eight factors atomically, so the prose and the metrics cannot drift.
3. As a threat modeller, I want the tool to return success or a coded rejection, so I can fix a malformed row without guessing at a score.
4. As a threat modeller, I want the score computed by the system, so I cannot bias it with a narrative.
5. As a threat modeller, I want `UI` to be passive for a routine flow and active for a specific victim action, so a stored XSS is not downgraded for a reader opening the article.
6. As a threat modeller, I want `UI` to stay a loose expression in the prose, so a normal operational flow is left implicit and an active interaction is stated briefly.
7. As a threat modeller, I want `AT` to mean an attacker capability that adds a phase, so a multi-request chain is not penalised as an environmental precondition.
8. As a threat modeller, I want `PR` to mean the role and permissions needed for the chain's application primitives, so the factor is derived from the capability path.
9. As a threat modeller, I want `AC` to mean the defence that must be circumnavigated, so a sanitizer or a rate limiter is scored as a defence, not as a step count.
10. As a threat modeller, I want the impact values to be `high`, `low`, and `none`, so the score uses the standard CVSS 4.0 value set.
11. As a threat modeller, I want one-line examples for every factor value, so I can choose consistently.
12. As a threat modeller, I want to record an `ASSUMED` premise on the trust assumption, so the hunter knows what to probe.
13. As a threat modeller, I want the exploitability factors to describe the attack as it would run if the fault is present, so an unverified premise never lowers the score.
14. As a threat modeller, I want the assessment row to be the scored claim, so the threat is a dispatch grain and not a second scoring record.
15. As a threat modeller, I want the first successful assessment to advance the `IMPACT_ASSESSED` state, so I do not need a second gate write.
16. As a threat modeller, I want the `hunts_store` surface to reject an `impact_assessment` section, so I cannot bypass the tool.
17. As a threat modeller, I want the completion check to name a missing assessment, so I can close the model.
18. As a hunter, I want the threat payload to show the risk score, the severity band, the factors, and the vector, so I know why the threat was prioritised.
19. As a hunter, I want the payload to show the impact description and the exploitability description, so I understand the intended damage and the chain.
20. As a hunter, I want the payload to show the assumption confidences, so I can plan the verification probes and avoid duplicating an unverified premise.
21. As a hunter, I want the payload not to show a likelihood rationale, so the retired vocabulary does not return.
22. As an operator, I want the promotion floor to be a float, so I can tune it below one CVSS point.
23. As an operator, I want the risk budget to be a float, so I can tune the modelling halt precisely.
24. As an operator, I want the dispatch queue to order threats by risk descending, so a high-severity one-threat unit is not crowded out by a four-threat unit.
25. As an operator, I want no per-unit cap, so the queue is a pure risk order.
26. As an operator, I want the run record to show the risk total and the band breakdown, so I can audit the halt.
27. As an operator, I want the old v4 models to stay readable, so the iteration D evidence is not lost.
28. As an operator, I want the new defaults to be the old defaults scaled by the maximum ratio, so the change is proportional and not fitted to one run.
29. As an API client, I want the hunting config to accept float thresholds, so the settings round-trip without truncation.
30. As an API client, I want a malformed threshold to be rejected with the field name, so the configuration fails fast.
31. As an eval assessor, I want the impact review to judge the new assessment rows, so the review follows the scored claim.
32. As an eval assessor, I want the measurement to read the v5 score and band, so the metric reports the new model.
33. As an eval assessor, I want the v4 artifacts to stay raw, so the iteration D numbers remain reproducible.
34. As a security reviewer, I want the CVSS vector persisted, so I can audit the mapping from factors to score.
35. As a security reviewer, I want the score presented as CVSS 4.0 over domain-mapped factors with attribution, so it is not mistaken for a certified CVSS assessment.
36. As a maintainer, I want one thin risk module wrapped around the `cvss` library, so the rest of the code depends on a local interface.
37. As a maintainer, I want the factor descriptions defined once, so the tool contract and the system prompt cannot drift.
38. As a maintainer, I want the old likelihood and impact code deleted after the migration, so no caller can keep the retired model alive.
39. As a maintainer, I want a v4 write to be refused by the v5 store, so a stale model cannot be mixed into a new run.
40. As a maintainer, I want the dispatch queue change tested on ties and on a one-threat unit, so the queue order is deterministic.

## Implementation Decisions

### 1. The risk module

A new pure module owns the local risk interface.
It wraps `cvss==3.6` and no other module imports the library directly.

The public surface:

```python
class AttackVector(StrEnum):
    NETWORK = "network"
    ADJACENT = "adjacent"
    LOCAL = "local"
    PHYSICAL = "physical"

class AttackComplexity(StrEnum):
    LOW = "low"
    HIGH = "high"

class AttackRequirements(StrEnum):
    NONE = "none"
    PRESENT = "present"

class PrivilegesRequired(StrEnum):
    NONE = "none"
    LOW = "low"
    HIGH = "high"

class UserInteraction(StrEnum):
    NONE = "none"
    PASSIVE = "passive"
    ACTIVE = "active"

class ImpactLevel(StrEnum):
    NONE = "none"
    LOW = "low"
    HIGH = "high"

class SeverityBand(StrEnum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class RiskMetrics(_Record):
    attack_vector: AttackVector
    attack_complexity: AttackComplexity
    attack_requirements: AttackRequirements
    privileges_required: PrivilegesRequired
    user_interaction: UserInteraction
    confidentiality: ImpactLevel
    integrity: ImpactLevel
    availability: ImpactLevel

class RiskResult(_Record):
    vector: str
    score: float
    band: SeverityBand

def build_vector(metrics: RiskMetrics) -> str
def compute_risk(metrics: RiskMetrics) -> RiskResult
def severity_band(score: float) -> SeverityBand
def validate_metrics(metrics: RiskMetrics, *, disposition: ImpactDisposition) -> list[str]
```

`build_vector` maps `AV` to `N/A/L/P`, `AC` to `L/H`, `AT` to `N/P`, `PR` to `N/L/H`, `UI` to `N/P/A`, and each impact level to `N/L/H`.
It sets `SC = VC`, `SI = VI`, and `SA = VA`.
`compute_risk` calls `CVSS4(vector).base_score`, rounds to two decimals, and derives the band.
`severity_band` uses the standard CVSS bands: `0.0` none, `0.1..3.9` low, `4.0..6.9` medium, `7.0..8.9` high, `9.0..10.0` critical.

`validate_metrics` returns coded findings:
- a `precursor` row must have all three impact values `none`;
- a `threat` row must have at least one impact value above `none`;
- every factor must be present (the typed model enforces it).

The module also exports the single source of truth for the factor descriptions:

```python
FACTOR_DESCRIPTIONS: dict[str, dict[str, str]]
```

Each entry carries the value, a one-line semantic, and one brief example.
The `assess_impact` tool description and the modeller prompt render the same entries.

### 2. The assessment row

`ImpactAssessment` becomes:

```python
class ImpactAssessment(_Record):
    id: str                      # IA-*
    vulnerability_ref: str       # V-*
    disposition: ImpactDisposition
    impact_description: str      # victim and damaged property, or why no end damage follows
    exploitability_description: str  # the chain, its capabilities, its human participation
    capability: str
    capability_id: str           # P-*
    capability_path: list[str]   # ordered P-* or Unit::P-*
    evidence_refs: list[str]
    factors: RiskMetrics
    risk: float = 0.0            # derived, never authored
    risk_vector: str = ""        # derived, never authored
```

`damage` is renamed `impact_description`.
The legacy `precursor_refs` field stays read-only.

### 3. The threat row

`Threat` becomes:

```python
class Threat(_Record):
    id: str = ""
    fault_ref: str
    vulnerability_ref: str
    canonical_class: str
    web_vulnerability_class: str = ""
    evidences: list[Evidence]
    impact_ref: str = ""
    enabling_precursors: list[tuple[str, str | None]] = Field(default_factory=list)
    risk: float = 0.0            # derived at COMPLETED from the assessment
```

The threat loses `likelihood`, `likelihood_rationale`, `risk_factors`, `confidence`, `impact`, and `impact_weight`.
The model writes a `ThreatWrite` shape that excludes `risk`.
The store fills `risk` from the assessment at the `COMPLETED` write.
The threat file carries `risk` for the mover and the payload.

### 4. The `assess_impact` tool

The tool is a typed `BaseTool` bound to the threat-model store, the project, the unit, and the run.

Args:

```python
class AssessImpactArgs(BaseModel):
    id: str
    vulnerability_ref: str
    disposition: Literal["threat", "precursor"]
    impact_description: str
    exploitability_description: str
    capability: str
    capability_id: str
    capability_path: list[str]
    evidence_refs: list[str]
    factors: RiskMetrics
    model_config = ConfigDict(extra="forbid")
```

The tool:
1. validates the field presence and the referential links;
2. calls `store.write_impact_assessment(...)`;
3. returns `{"ok": True}` or a coded teaching rejection naming the field and the fix.

The tool never returns `risk`, `risk_vector`, or a factor echo.

The store method:
- loads the current document;
- accepts a write at `PRIOR_ART` or `IMPACT_ASSESSED`;
- validates the row (id uniqueness, vulnerability ref, disposition, capability id uniqueness, capability path resolution);
- calls `compute_risk(factors)`;
- merges the row by id, replacing a prior row with the same id;
- sets `state = IMPACT_ASSESSED`;
- commits the document;
- returns the row read model.

The first successful call advances the state.
The `hunts_store` `ModelSections` no longer carries `impact_assessment`.
`GATE_SECTIONS[IMPACT_ASSESSED]` becomes an empty tuple for the model-facing gate.
The `COMPLETED` write remains the only model-facing threat write.

### 5. The completion check

The completion check reports findings, not a hard rejection, as today:

- every non-dropped vulnerability has at least one assessment row;
- every row has a non-empty `impact_description`, `exploitability_description`, `capability`, and `capability_id`;
- every row has a computed `risk` and `risk_vector`;
- a `precursor` row has all impact values `none`;
- a `threat` row has at least one impact value above `none`;
- every threat's `impact_ref` resolves to a `threat` row with the same `vulnerability_ref`;
- every threat's `risk` equals the row's `risk`;
- the `enabling_precursors` first element mirrors the row's `capability_path`;
- the capability graph is acyclic.

The dispatch gate remains `validation.valid`.

### 6. The risk profile and the run record

`RiskProfile` becomes:

```python
class RiskProfile(_Record):
    total: float
    breakdown: dict[SeverityBand, int]
```

The total sums the threat risks and rounds to two decimals.
The breakdown counts the threats by band.
`compute_risk_profile(threats)` reads the threat's derived risk.

The run record:
- `risk_threshold` is a float;
- `risk_total` is a float;
- `risk_breakdown` is keyed by `SeverityBand`;
- `model_sums` entries carry `total` and `breakdown`;
- `risk_weights`, `impact_weights`, and `impact_breakdown` are removed.

The `RiskAccumulator` adds the profile total and uses the inclusive `>=` comparison.
The `threshold_config` returns a float.
`HUNT_RISK_THRESHOLD` parses a float.
`DEFAULT_RISK_THRESHOLD` becomes `156.25`.

### 7. The thresholds

The old per-threat maximum was 16; the new maximum is 10.
The proportional factor is `0.625`.
The defaults are:

| setting | old | new |
|---|---|---|
| `DEFAULT_RISK_THRESHOLD` | 250 | 156.25 |
| iteration D `risk_threshold` | 180 | 112.5 |
| iteration D `promotion_risk_threshold` | 4 | 2.5 |

The settings API accepts a float at least 0 for `risk_threshold` and a float at least 0 or `null` for `promotion_risk_threshold`.
A malformed value is a coded rejection naming the field.
The comparison is inclusive.
`None` or `0` on the promotion floor means no filter.

The thresholds are not calibrated on the iteration D corpus.
The corpus is recorded as evidence of the scoring change, not as a fitting set.

### 8. The dispatch queue

The dispatch queue is a global list of promoted threat items, ordered by:
1. `risk` descending;
2. the unit intake position ascending;
3. the threat rank ascending;
4. the dispatch id ascending.

The queue does not order units by model sum and applies no per-unit cap.
The unit model sum remains in the run record for the budget and the audit.

`order_threats` replaces `order_units` for the dispatch decision.
`decide` works the global threat frontier:
- `parallel` admits every item;
- `batched` admits the current threat's hunter, then its pods once the hunter is terminal, in fixed blocks of `pod_batch_size` hunts by risk order;
- `serial` admits one threat at a time.

The modeller phase stays whole-budget first.
The intake order still governs the modelling halt and the tie-break.

### 9. The payload and the hunter prompt

The threat payload renders:
- the risk score and the severity band;
- the CVSS vector;
- the eight factors with their values;
- the impact description;
- the exploitability description;
- the capability and the capability path;
- the enabling precursors;
- the assumption confidences and the evidence refs.

The payload does not render a likelihood, a likelihood rationale, or a threat confidence.
The hunter prompt's ontology is updated to the same vocabulary.
The payload reads the assessment through the threat's `impact_ref`.

### 10. The prior-art query

The v5 paths are added:
`risk`, `risk_vector`, `factors.*`, `impact_description`, `exploitability_description`.

The v4 paths stay available for raw reads.
The `threat` view merges the threat file with the assessment row.
The `precursor` view returns the impact rows disposed as `precursor`.

### 11. Schema v5 and the v4 read

`SCHEMA_VERSION` becomes 5.

A v5 document is parsed and normalised.
A v4 document is read raw for prior art and measurement.
A v4 write is refused with a coded rejection.
A v4 threat file is read by the mover through the tolerant `threat_risk` reader, which accepts an int or a float.
The v4 artifacts are never re-scored.

### 12. The settings surface

The hunting config endpoints keep their shape.
`HuntingConfigUpdate` gains float fields for the two thresholds.
The repository reads and writes the same JSONB blob.
The context documentation for the project management module is updated.

### 13. The eval metric

`measure_utm.py` gains a v5 path:
- reads `risk` and the band from the threat file;
- reads the assessment rows for the impact review;
- keeps the v4 raw path for the archived iteration D artifacts;
- reports the reviewed green share as today.

The assessment prompt and the impact review schema are updated to the new factor vocabulary.
The setup files use the new float thresholds.

### 14. Documentation convergence

The following documents are amended in the same change:
- `impact-assessment-system-spec.md`: the typed model, the invariants, the workflow, the payload, the metric, the run record, and the migration sections point to this spec.
- `hunting-67-threat-model-artifact-spec.md`: the schema, the threat entity, the risk scoring, the payload, and the run-record sections point to this spec.
- `hunting-pipeline-sync-spec.md`: the promotion filter and the queue order.
- `unit-threat-model-tools-adr.md`: the `assess_impact` binding and the `hunts_store` section removal.
- `unit-threat-model-workbench.md`: the risk-scoring recommendation is superseded.
- `unit-threat-model-risk-scoring-research.md`: the recommendation is superseded.
- `threat-model-impact-elicitation-adr.md`: the risk formula is superseded.
- `unit-threat-model-spec-impact-map.md`: the new amendment and the impact map link.
- `src/polymerhus/attack/hunting/CONTEXT.md`: the vocabulary block is the canonical glossary.
- `src/polymerhus/project_management/CONTEXT.md`: the float thresholds.
- `docs/design/domain-model.md`: the hunting entities.

## Testing Decisions

### What makes a good test

Test external behavior, not implementation details.
A test reads like a specification and survives a refactor.
Expected values come from an independent source: a FIRST or Red Hat worked example, a known CVSS vector, or the spec.
Do not recompute the expected score with the same code path.
The store tests use a temporary directory and the real store.
The tool tests invoke the tool through its typed args and assert the returned envelope and the persisted row.
The queue tests call the pure `order_threats` and `decide` functions with explicit facts.

### Seams

1. The risk module: `compute_risk`, `build_vector`, `severity_band`, `validate_metrics`. Known vectors from the CVSS 4.0 reference set.
2. The `assess_impact` tool: the typed args, the store call, the response envelope, and the persisted row.
3. The threat-model store: the v5 write, the v4 raw read, the completion findings, the threat risk mirror, and the profile.
4. The modeller pass: the tool surface and the gate sequence, through the existing pass seam.
5. The pure queue: `order_threats`, `decide`, and `batch_state`.
6. The run lifecycle: `RiskAccumulator` and the run-record projection.
7. The settings API: the FastAPI test client.
8. The eval metric: a fixture store with a v5 model and a v4 model.

These seams already exist or are the natural public boundaries of the changed modules.
No new private seam is introduced.

### Prior art

- `tests/attack/test_threat_model_impact.py` for the assessment invariants.
- `tests/attack/test_threat_model_store.py` for the store merge, the completion check, and the threat files.
- `tests/attack/test_threat_modeller.py` and `tests/attack/test_threat_modeller_prompt.py` for the pass and the prompt.
- `tests/attack/test_hunting_mover.py` and `tests/attack/test_hunting_pipeline_sync.py` for the queue and the promotion filter.
- `tests/attack/test_hunting_run_lifecycle.py` for the risk accumulator.
- `tests/project_management/test_hunting_config_api.py` for the settings.
- `tests/eval/test_measure_utm.py` for the metric.

### Coverage shape

- Unit: the risk module, the store, the queue, the accumulator, the settings validation.
- Integration: the tool over the real store, the pass over a fake actor and the real store, one `decide` walk with a one-threat unit and a four-threat unit.
- E2E: one scripted modeller walk that writes one assessment and one threat, reads the score back, and dispatches the threat through the queue. The live LLM edge is replaced by a scripted actor; the store and the queue are real.

## Out of Scope

- The pod and triager verdict, persistence, and export-flush workstream. It starts with its own diagnosis.
- The recon and Steel crawl changes.
- The CVSS threat, environmental, and supplemental metric groups.
- A certified CVSS assessment or a FIRST validation pass.
- Re-scoring the archived v4 models.
- The frontend.
- The `threat_model_scope` fence.

## Further Notes

The CVSS 4.0 impact values are `high`, `low`, and `none`.
The 2026-10-31 grilling accepted `high/none` after I stated that the standard has no `medium`.
The standard also has `low`; this spec uses the full set.
The `low` value is not a smaller `medium`; it is a bounded or partial loss.
The decision prose must force `VC:H/VI:H` for a stored XSS that executes in another user's session.

The CVSS 4.0 base score is a severity score, not a likelihood.
The reconstructed iteration D corpus shows saturation: under the `medium -> high` reading, 15 of 27 threats score at least 9.2.
The score is a filter and a rank key, not a probability.
The dispatch cap remains a separate policy.

FIRST requires attribution and the vector beside a published score.
The persisted `risk_vector` satisfies the second requirement.
Any report that prints the score must print the vector and state that the factors are domain-mapped.
