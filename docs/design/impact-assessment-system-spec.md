# Impact assessment system - design specification

*Status: spec (contract), 2026-10-26.*
*Supersedes the 2026-10-25 impact-first amendment and the five-state workflow in `hunting-67-threat-modeller-spec.md`, `unit-threat-model-workflow.md`, and `hunting-67-threat-model-artifact-spec.md`.*
*Authoritative for: the unit threat model, the threat modeller workflow, the impact assessment, the precursor, the prior art, the project scope, and the impact metric.*
*Prototype: `docs/design/impact-assessment-system-prototype.md`.*
*Open decisions: `docs/design/impact-assessment-open-questions.md`.*

## Problem Statement

The current unit threat model calls a research direction a `threat`.
That definition admits rows with no concrete end damage.
`RESTApi:api/threat-1` and `RESTApi:api/threat-3` carry an authorization capability and score `C=medium`, `I=medium`, and risk 9.
They have no data read, no state change, and no victim.
`RESTApi:api/threat-2` mixes a route-table read with a credential path in one string, and the hunter tested the route-table read.
The arithmetic cannot separate a latent capability from an account takeover: both score 9.

The operator also needs two capabilities the current model does not have.
The model cannot reuse a capability another unit already modelled, because the store has no query.
The model cannot apply a project posture, because the scope is not a project attribute.

The class-based green gate does not measure damage.
It measures whether the bound class is in a high-yield set.
It rewards latent green rows and penalises damage-bearing rows outside the set.
The metric must move to the CIA values the impact assessment produces.

## Solution

A `threat` is a row with a concrete end damage to a victim.
A `placeholder` is a row with no concrete end damage.
A `precursor` is a capability entity, not a row.
The modeller writes one `impact_assessment` section at a new `IMPACT_ASSESSED` gate.
Each assessment names the victim and the damaged property in one `damage` field, the precursors the vulnerability yields, and the capability path.
One threat references exactly one damage row.
One vulnerability may yield several threats, one per complementary exploitation manner.
Each threat carries its own damage row and its own capability path.
The threat stays broad: it names the exploitation manner and the damage, never the request, payload, or procedure.
The CIA score is authored after the assessment.
A threat row carries at least one non-none CIA value; a placeholder row carries all none.

The project gains a `threat_model_scope` string.
The hunting module appends it verbatim to the modeller prompt.
The modeller applies it at the assumptions layer: it does not model a boundary the scope excludes, so it does not make the excluded assumption or fault.

The modeller gains a `PRIOR_ART` gate before the trust model.
It queries the store for previous threats, vulnerabilities, and precursors with typed filters.
It records the queries and the reused records in the `prior_art` section.
Every precursor is queryable after the model completes.

The hunter payload carries the impact assessment and the precursors.
The spec contract and the pod contract do not change.
The hunter uses the shared end damage to choose the spec set; the verification symptoms stay variant-specific.

The measurement reports the CIA distribution and the red/green share.
A row is red when all CIA values are none.
A row is green when any CIA value is not none.
The class-binding rate remains a diagnostic.
The class-based green gate is retired.

## User Stories

1. As an operator, I want a threat to require a concrete victim and damaged property, so that a latent capability is not dispatched as a damage claim.
2. As an operator, I want a placeholder for a direction with no concrete end damage, so that the modelling work is kept without inflating the threat set.
3. As an operator, I want a precursor entity for a capability that another threat can leverage, so that the capability is not lost when it does not reach damage by itself.
4. As an operator, I want the impact assessment to be a first-class model section, so that the damage reasoning is auditable apart from the CIA score.
5. As an operator, I want the CIA score authored after the damage assessment, so that the score reflects the victim and the property.
6. As an operator, I want a threat row to carry at least one non-none CIA value, so that a threat is damage-bearing by construction.
7. As an operator, I want a placeholder row to carry all-none CIA values, so that the impact metric can separate placeholders from threats.
8. As an operator, I want the damage field to name the victim and the property in one concise sentence, so that the assessment is readable without a taxonomy lookup.
9. As an operator, I want the victim and property catalog in the prompt, so that the model reasons over users, the application, and the infrastructure.
10. As an operator, I want the capability path to list the precursors that reach the damage, so that the hunter sees the attacker's position.
11. As an operator, I want every precursor to live in the store after completion, so that a later unit can query it.
12. As an operator, I want a prior-art phase before the trust model, so that the modeller reuses existing threats, vulnerabilities, and precursors.
13. As an operator, I want at least one prior-art query for threats, one for vulnerabilities, and one for precursors, so that the reuse is deliberate.
14. As an operator, I want the prior-art queries recorded in the model, so that the reuse is auditable.
15. As an operator, I want a typed query contract with field filters, so that the modeller does not dump the store.
16. As an operator, I want the query to exclude the current unit by default, so that an unfinished model is not prior art.
17. As an operator, I want the query result to name the unit, the record, the kind, the class, the disposition, the summary, and the state, so that the modeller can choose what to read.
18. As an operator, I want a project-level posture string, so that the exclusion is a project assumption, not a hidden prompt rule.
19. As an operator, I want the posture string configurable through the REST API, so that the operator can change it without a deploy.
20. As an operator, I want the posture string appended verbatim to the modeller prompt, so that the model sees the operator's exact words.
21. As an operator, I want the posture applied at the assumptions layer, so that the excluded boundary never becomes an assumption or a fault.
22. As an operator, I want the run record to stay lean, so that it does not duplicate data that lives in the project settings or the files.
23. As an operator, I want the impact metric based on CIA values, so that it measures damage rather than class membership.
24. As an operator, I want the red/green share over all impact rows, so that placeholders count as red.
25. As an operator, I want the class-binding rate kept as a diagnostic, so that the class guard remains visible.
26. As an operator, I want the old class-based green gate retired, so that a green class cannot mask a damage-less row.
27. As the threat modeller, I want a `PRIOR_ART` gate, so that I query the store before I commit to a trust model.
28. As the threat modeller, I want the query filters, so that I can narrow by unit, kind, class, disposition, and text.
29. As the threat modeller, I want to read a full model after a query, so that a summary that looks relevant can be inspected.
30. As the threat modeller, I want a precursor to name the capability and the abstract procedure, so that I can reuse it without copying a payload.
31. As the threat modeller, I want the impact assessment to name the victim and the property, so that the CIA score is grounded.
32. As the threat modeller, I want the CIA score after the assessment, so that the score acknowledges the damage.
33. As the threat modeller, I want the project posture verbatim, so that I know which boundaries not to model.
34. As the threat modeller, I want the prior-art results as evidence, so that a reused capability is not a guess.
35. As the hunter, I want the impact assessment in the payload, so that I know the shared end damage.
36. As the hunter, I want the precursors in the payload, so that I know the attacker's position.
37. As the hunter, I want the spec contract unchanged, so that the variant-specific verification symptoms stay the pod's ground truth.
38. As the hunter, I want the shared damage stated once, so that I do not duplicate it into every spec.
39. As the pod, I want the spec contract unchanged, so that the verdict remains the variant-specific symptom.
40. As the measurement, I want the CIA values per row, so that I can report the distribution and the red/green share.
41. As the measurement, I want the disposition per row, so that I can separate threats from placeholders.
42. As the measurement, I want the precursor count and the prior-art reuse, so that I can report the capability reuse.
43. As a reviewer, I want the old class-based green figure beside the new impact figure, so that the change is visible.
44. As a reviewer, I want the new spec to supersede the old amendment, so that the docs do not describe two models.
45. As a reviewer, I want the workflow to stay passive, so that a forward gate jump is recorded and never blocked.
46. As the threat modeller, I want my probes to stay light and falsification-only, so that the impact assessment does not turn into an exploitation budget.

## Implementation Decisions

### 1. Domain terms and dispositions

- `threat`: a unit-model row with a concrete end damage to a victim.
  It carries the fault, the web-vulnerability class, the impact reference, the enabling precursors, the CIA vector, the likelihood, and the risk.
- `placeholder`: a unit-model row with no concrete end damage.
  It is stored in the model, has no threat file, and is never dispatched.
  It is red in the impact metric.
- `precursor`: a capability entity.
  It carries an id, the capability gained, the abstract procedure that gains it, and the evidence.
  It is not a threat and it is not a placeholder.
- `impact_assessment`: the model section that holds the rows and the precursors.
  It is written at the `IMPACT_ASSESSED` gate.
- `capability_path`: the ordered precursor ids that reach the damage.
  It lives on the impact assessment.
- `prior_art`: the model section that records the store queries and the reused records.
  It is written at the `PRIOR_ART` gate.

The `disposition` is the first-class typed field on the impact assessment row.
It is `threat` or `placeholder`.
There is no damage-family enum and no victim-class enum.
The `damage` field carries the semantic.

### 2. The damage field

`damage` is one concise sentence or short paragraph.
It names the victim and the damaged property.
The prompt defines the catalog:

- Victim: an end user (PII, account, access), the application (persisted data, configuration, audit or telemetry data, availability), or the infrastructure (host, runtime, network, cloud account).
- Property: confidentiality, integrity, availability, or privileged code execution.

Examples:

- `A tenant user reads another tenant's PII from the application database.`
- `An anonymous caller changes another user's persisted content.`
- `An unauthenticated caller runs commands on the application host.`
- `A user loses access to the application for the duration of the resource exhaustion.`

A `threat` row must name a concrete victim and property.
A `placeholder` row says that no concrete victim or property is affected.
The CIA score is authored after the damage field.
The score must reflect the damage.

### 3. The typed model

```python
class Project(BaseModel):
    project_id: str
    name: str
    created_at: datetime
    threat_model_scope: str = ""


class FieldFilter(BaseModel):
    path: str
    regex: str
    flags: str = "i"          # "i" case-insensitive, "" case-sensitive


class ThreatQuery(BaseModel):
    kind: Literal["threat", "vulnerability", "precursor", "assumption", "impact"]
    filters: list[FieldFilter]
    limit: int = 20


class ThreatQueryMatch(BaseModel):
    unit_id: str
    record_id: str
    kind: str
    label: str
    web_vulnerability_class: str
    disposition: str | None = None
    summary: str
    state: str
    evidence_refs: list[str]
    matched: list[dict] = Field(default_factory=list)


class ThreatQueryResult(BaseModel):
    matches: list[ThreatQueryMatch]
    count: int
    truncated: bool


class PriorArtQuery(BaseModel):
    kind: Literal["threat", "vulnerability", "precursor", "assumption", "impact"]
    filters: list[FieldFilter]
    result_count: int


class PriorArtReuse(BaseModel):
    unit_id: str
    record_id: str
    kind: str
    reason: str


class PriorArt(BaseModel):
    queries: list[PriorArtQuery]
    reused: list[PriorArtReuse] = Field(default_factory=list)
    notes: str


class Precursor(BaseModel):
    id: str                      # P-*
    capability: str
    procedure: str               # abstract, never a request or a payload
    evidence_refs: list[str]


class ImpactDisposition(StrEnum):
    THREAT = "threat"
    PLACEHOLDER = "placeholder"


class ImpactAssessment(BaseModel):
    id: str                      # IA-*
    vulnerability_ref: str       # V-*
    disposition: ImpactDisposition
    damage: str
    precursor_refs: list[str]    # P-* yielded by this vulnerability
    capability_path: list[str]   # P-* in order; empty for a placeholder
    evidence_refs: list[str]


class Threat(BaseModel):
    id: str
    fault_ref: str
    vulnerability_ref: str
    canonical_class: str
    web_vulnerability_class: str
    likelihood: Likelihood
    likelihood_rationale: str
    risk_factors: RiskFactors
    confidence: Confidence
    evidences: list[Evidence]
    impact_ref: str              # IA-*
    enabling_precursors: list[str]
    impact: Impact               # C, I, A only
    impact_weight: int = 0
    risk: int = 0


class Impact(BaseModel):
    confidentiality: ImpactLevel = ImpactLevel.NONE
    integrity: ImpactLevel = ImpactLevel.NONE
    availability: ImpactLevel = ImpactLevel.NONE
```

`Threat.impact.end_impact` is removed.
The damage text lives in the `ImpactAssessment`.
The store computes the impact sub-score, the ordinal weight, and the threat risk from the CIA vector, as it does today.

### 4. The impact invariants

- A `threat` row has at least one non-none CIA value.
- A `placeholder` row has all-none CIA values.
- A `threat` row has a non-empty `damage`, a non-empty `capability_path`, and at least one `enabling_precursor`.
- A `placeholder` row has a non-empty `damage` that states no concrete victim or property, and an empty `capability_path`.
- Every `precursor_refs` and `capability_path` entry resolves to a `Precursor` in the same model.
- Every `Threat.impact_ref` resolves to a `threat` assessment with the same `vulnerability_ref`.
- Every `Threat.enabling_precursors` entry resolves to a `Precursor` in the same model.
- The `Threat.enabling_precursors` set equals the assessment's `capability_path` set.
- One threat references exactly one assessment.
- A `threat` assessment has exactly one threat.
- A vulnerability may have several `threat` assessments, one per exploitation manner.
- A `placeholder` assessment has no threat.
- Every non-dropped vulnerability has at least one assessment.

These invariants are deterministic.
The semantic quality of the `damage` sentence is judged by the model, the measurement review, and the assessment.

### 5. The workflow

The modeller has seven states.

| # | State | Gate section | Necessary content |
|---|---|---|---|
| 1 | `UNIT_TECHNICAL_SHARP` | `technical_sharpening` | Interface agreements, control flows, data flows |
| 2 | `PRIOR_ART` | `prior_art` | The store queries and the reused records |
| 3 | `TRUST_MODELLED` | `trust_model` | Trust agreements and dynamic-state trust |
| 4 | `TRUST_ASSUMPTIONS_WRITTEN` | `assumptions` | Assumptions, each naming a fault |
| 5 | `VULNERABILITIES_WRITTEN` | `vulnerabilities` | Web-vulnerability classes |
| 6 | `IMPACT_ASSESSED` | `impact_assessment`, `precursors` | The impact rows and the precursors |
| 7 | `COMPLETED` | `threats` | The damage-bearing threats |

The well-formedness loop runs after `VULNERABILITIES_WRITTEN` and before `IMPACT_ASSESSED`.
The harness stays passive.
The state is monotonic.
The trajectory records the gates.
The completion check reports the findings.
The existing `validation.valid` contract is the dispatch gate.

The `PRIOR_ART` phase runs after the technical sharpening and before the trust model.
The modeller runs at least one query for threats, one for vulnerabilities, and one for precursors.
It records the queries and the reused records in `prior_art`.
It writes a `prior_art` note as the phase exit.

The `IMPACT_ASSESSED` phase runs after the well-formedness loop.
The modeller writes one assessment row per damage claim.
It writes the precursor entities.
It scores the CIA vector in the `COMPLETED` threats, after the assessment.

### 6. The project scope

`Project.threat_model_scope` is a free-text posture statement.
The persistence is `settings.hunting.threat_model_scope`.
The REST surface is the existing hunting config pair:

```http
GET /projects/{project_id}/hunting/config
PUT /projects/{project_id}/hunting/config
{"threat_model_scope": "The target is assumed to have ..."}
```

`HuntingConfigUpdate` gains `threat_model_scope: str | None` with `extra="forbid"`.
The PUT is a partial deep merge.
The run reads the string at start and appends it verbatim to the per-turn modeller prompt under `## Project scope (verbatim)`.
The static system prompt carries the assumptions binding, never the per-project text.
The run record does not duplicate it.
The repository has no separate `Project` entity class; the project domain model is the settings projection behind the hunting config pair.
The string is applied at the assumptions layer.
The modeller does not model a trust boundary the scope excludes, so it does not make the excluded assumption or fault.

### 7. The `hunts_store` query contract

The modeller tool gains `cmd='query'`.
It is the one grounding tool for previous threats, vulnerabilities, and precursors.

```yaml
cmd: query
kind: precursor
filters:
  - path: capability
    regex: "session|credential"
    flags: i
  - path: evidence_refs
    regex: "^exec:"
limit: 20
```

The query is a regex field filter over one record type.

- `kind` is required: `threat`, `vulnerability`, `precursor`, `assumption`, or `impact`.
- `filters` is a non-empty list.
  A query with no filter is a coded teaching rejection.
- The filters are AND.
  A record matches when every filter matches at least one value at its path.
- A filter matches when `re.search(regex, value, flags)` returns a match.
  `flags` is `i` for case-insensitive or `""` for case-sensitive.
  The regex is capped at 200 characters.
  An invalid regex is a coded teaching rejection.
- `path` is a dot path into the selected record view.
  `*` iterates a list.
  A path that resolves to a dict is matched on its JSON string.
  A missing path is no match.
  An unknown path is a coded teaching rejection.
  The path is capped at 120 characters.
- `limit` is 1..50, default 20.
- The query is project-scoped.
  It never crosses projects.
- The query reads the `produced` and `consumed` models.
  The result carries the model `state`.
  A `consumed` model is complete.
  A `produced` model may be partial.
- The query excludes the bound unit unless a filter path is `unit_id`.
- The query returns summaries, never a full model.
  The modeller uses `cmd='read'` with `unit_id` for the full model.
- The query result carries the `matched` path/value pairs that made the record match.

Path catalog:

| Kind | Paths |
|---|---|
| `threat` | `threat_id`, `dispatch_id`, `unit_id`, `run_id`, `likelihood`, `threat.canonical_class`, `threat.web_vulnerability_class`, `threat.fault_ref`, `threat.vulnerability_ref`, `threat.impact_ref`, `threat.enabling_precursors`, `threat.impact.confidentiality`, `threat.impact.integrity`, `threat.impact.availability`, `impact.damage`, `impact.disposition`, `impact.capability_path`, `impact.precursor_refs`, `impact.precursors.*.id`, `impact.precursors.*.capability`, `impact.precursors.*.procedure`, `impact.precursors.*.evidence_refs` |
| `impact` | `id`, `vulnerability_ref`, `disposition`, `damage`, `capability_path`, `precursor_refs`, `evidence_refs` |
| `precursor` | `id`, `capability`, `procedure`, `evidence_refs` |
| `vulnerability` | `id`, `canonical_class`, `web_vulnerability_class`, `fault_ref`, `dropped`, `drop_reason` |
| `assumption` | `id`, `description`, `boundary_ref`, `fault.id`, `fault.label`, `fault.description` |

The `threat` view merges the threat file with its impact row and its precursor entities.
The `impact`, `precursor`, `vulnerability`, and `assumption` views read the unit model.

Result:

```yaml
matches:
  - unit_id: "Service:sign-in"
    record_id: "P-2"
    kind: precursor
    label: "recover a live session from the dump"
    web_vulnerability_class: information-disclosure
    disposition: null
    summary: "read live session material from the process dump"
    state: COMPLETED
    evidence_refs: ["exec:api-35"]
    matched:
      - path: capability
        value: "recover a live session from the dump"
count: 1
truncated: false
```

The `prior_art` section records the queries:

```yaml
prior_art:
  queries:
    - kind: threat
      filters:
        - path: threat.web_vulnerability_class
          regex: "session-management"
          flags: i
      result_count: 4
    - kind: vulnerability
      filters:
        - path: canonical_class
          regex: "credential"
          flags: i
      result_count: 2
    - kind: precursor
      filters:
        - path: capability
          regex: "session|credential"
          flags: i
      result_count: 3
  reused:
    - unit_id: "Service:sign-in"
      record_id: "P-2"
      kind: precursor
      reason: "the session-recovery capability applies to this unit's dump surface"
  notes: "No prior threat matched the dump damage; the precursor path is reused."
```

The completion check requires at least one query for each of `threat`, `vulnerability`, and `precursor`, each with at least one filter, and a non-empty `notes`.
The `PRIOR_ART` gate is passive.
A missing prior-art section is a completion finding.

### 8. The threat file and the hunter payload

The threat file stays in `produced/<unit>/threat-*.yaml` and `consumed/<unit>/threat-*.yaml`.
It gains a denormalised `impact` block, so the hunter does not need the model document for the damage context.

```yaml
threat_id: threat-2
dispatch_id: RESTApi-api__threat-2
impact:
  impact_ref: IA-2
  damage: "The attacker reads live credential material from the process dump."
  disposition: threat
  precursors:
    - id: P-1
      capability: "read the management route table"
      procedure: "resolve the management base path outside the API filter"
      evidence_refs: ["exec:api-36"]
    - id: P-2
      capability: "read live session material"
      procedure: "fetch a heap dump from the exposed management handle"
      evidence_refs: ["exec:api-35"]
  capability_path: [P-1, P-2]
threat:
  impact_ref: IA-2
  enabling_precursors: [P-1, P-2]
  impact:
    confidentiality: high
    integrity: medium
    availability: none
```

`materialise_hunter_payload` adds the `impact` block to the payload.
`_compose_grounding` renders `## Impact assessment` and `## Attacker position`.
The payload carries no request, payload, or procedure that belongs to the hunter.
The `procedure` on a precursor is the abstract trust-boundary mechanism, not the hunter's technique.

The spec contract is unchanged.
The pod contract is unchanged.
The hunter uses the impact block as context.
The verification symptoms remain variant-specific.
The hunter acknowledges that the confirmation symptoms differ per variant while the end damage is shared.
No `damage_claim`, `damage_symptom`, or `damage_verdict` field is added.

### 9. The metric

The measurement reads the unit model and the threat files.

- `impact_rows` = every `impact_assessment` row.
- `threats` = rows with `disposition=threat`.
- `placeholders` = rows with `disposition=placeholder`.
- `red` = rows with all CIA values `none`.
- `green` = rows with any CIA value not `none`.
- `green_share` = green / impact_rows.
- `threat_share` = threats / impact_rows.
- `placeholder_share` = placeholders / impact_rows.
- The CIA distribution per metric and level.
- The precursor count and the prior-art reuse count.

A threat row is green by the invariant.
A placeholder row is red by the invariant.
The green share therefore measures the share of modelled rows that are damage-bearing.
The class-binding rate remains a diagnostic.
The class-based green gate is retired.
The old class-based figure may be reported beside the new figure for continuity, marked superseded.

### 10. The modelling probe discipline

The modeller stays at the modelling layer.
Its probes are light, cheap, and falsification-only.
It probes to falsify a claim about the unit's mechanics, not to execute an exploit or to prove a damage.
The impact assessment may leave the terminal capability `ASSUMED`.
That assumption does not lower the likelihood to invite a deeper probe.
The likelihood is scored from the attack factors.
The hunter and the pod own the effective attempt.
A probe that would require a destructive or data-exfiltrating step is out of scope for the modeller.

The probe discipline is part of the prompt and the honour clauses.
It is not a new gate.
It prevents the impact assessment from becoming a probe budget.

### 11. The run record

The run record keeps its existing keys.
It gains no damage counts, no precursor counts, no scope field, and no leads list.
The damage data lives in the unit model and the threat files.
The trajectory records the `PRIOR_ART` and `IMPACT_ASSESSED` gates through the existing trajectory entry.
The `model_sums` and `risk_total` stay as they are.
The measurement reads the files, not the run record.

### 12. The directory layout

One `produced` and one `consumed` directory per store.
The impact assessment and the precursors live inside `<unit>.yaml`.
The threat files stay inside the same `produced/<unit>/` and `consumed/<unit>/` directories.
No new directory and no new artifact family are added.

```text
data/<project_id>/hunting/
├── threat_modeller/
│   ├── produced/<unit>/<unit>.yaml
│   ├── produced/<unit>/threat-*.yaml
│   ├── consumed/<unit>/<unit>.yaml
│   ├── consumed/<unit>/threat-*.yaml
│   └── abandoned/<unit>/...
├── hunter/test-specs/<unit>__<threat>/
│   ├── produced/<class>__<value>__<value>.yaml
│   ├── consumed/<class>__<value>__<value>.yaml
│   └── terminal.yaml
└── test-executor-pod/<spec_id>/<run_id>.yaml
```

### 13. Migration

- `SCHEMA_VERSION` becomes 3.
- The new sections are `prior_art`, `impact_assessment`, and `precursors`.
- The new states are `PRIOR_ART` and `IMPACT_ASSESSED`.
- A v2 model remains readable and consumable under its stored `validation.valid`.
- A v2 model is not migrated.
- A new run uses a fresh project.
- The measurement reads v2 and v3.
  The v2 read maps `loop-*.yaml` to the legacy row and reads the CIA vector.
  The v2 model has no impact assessment, so its impact metric is reported as a legacy recomputation, not as a v3 result.

### 14. Supersession ledger

The following documents are amended by this spec:

- `hunting-67-threat-modeller-spec.md`
- `hunting-67-threat-model-artifact-spec.md`
- `unit-threat-model-workflow.md`
- `threat-model-impact-elicitation-adr.md`
- `hunting-67-hunting-agent-spec.md`
- `hunting-67-test-executor-pod-spec.md`
- `domain-model.md`
- `src/polymerhus/attack/hunting/CONTEXT.md`

The old 2026-10-25 amendment and the five-state tables remain as history.
The amendment at the top of each document states that this spec wins.

## Testing Decisions

### What makes a good test

Test external behavior at the store, the tool, the prompt, and the measurement boundaries.
Drive the real store on a temporary project root.
Drive the real passive state machine with injected gate observations.
Use the existing note and probe fakes at their contract boundaries.
Assert the persisted model, the threat file, the tool result, and the measurement, not private calls.
Expected values come from the spec, not from a recomputation of the implementation.

### Seams

1. The project hunting config REST pair: the scope string round-trips and a partial PUT preserves its siblings.
2. The `hunts_store` query: typed filters, the current-unit exclusion, the project boundary, the result shape, the empty-filter rejection.
3. The completion checker: the impact invariants, the precursor references, the prior-art requirement, the placeholder closure.
4. The store: the `PRIOR_ART` and `IMPACT_ASSESSED` merges, the threat-file emission, the placeholder not emitted, the model consumption.
5. The hunter payload: the impact block and the precursor rendering, no request or payload leakage.
6. The prompt contract: the seven states, the damage semantic, the prior-art phase, the project scope verbatim append.
7. The measurement: the CIA distribution, the red/green share, the placeholder share, the v2 legacy read.

The seams should be confirmed by the operator before the tickets are cut.

### Prior art

- The threat model store tests for the atomic write, the merge, and the consumption.
- The workflow tracker tests for the passive gate detection and the trajectory.
- The hunter payload tests for the field projection.
- The measurement tests for the deterministic metrics.
- The project settings tests for the partial deep merge.

### Coverage shape

- A damage-bearing row, a placeholder, and a precursor in one model.
- A threat with a multi-hop capability path.
- A placeholder with a precursor and no threat file.
- A prior-art query with each filter and the empty-filter rejection.
- A prior-art query that excludes the bound unit and includes a named unit.
- A completion failure for a missing prior-art kind, a missing damage, a CIA/disposition mismatch, and an unresolved precursor.
- A partial REST PUT that preserves `pipeline_sync` and `risk_threshold`.
- A hunter payload with the impact block and the precursor list.
- A measurement with red and green rows, and a v2 legacy read.

## Out of Scope

- Cross-project queries.
- Automatic promotion of a precursor into a threat.
- A second dispatch type for precursors.
- A pod damage verdict.
- A damage symptom field on the spec.
- The class-based green gate as a primary metric.
- Full CVSS base metrics.
- Model evolution or re-modelling.
- Cross-unit chain dispatch.
- A first-class `projects` column for the scope.
  The domain attribute is fixed; the persistence is the hunting settings blob.

## Further Notes

The open decisions are in `docs/design/impact-assessment-open-questions.md`.
The provisional ticket breakdown is in that document.
The prototype is `docs/design/impact-assessment-system-prototype.md`.
The old change note `docs/design/threat-damage-bearing-change-requirement.md` is superseded by this spec.
