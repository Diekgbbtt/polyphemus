# Threat Modeller Impact Refinement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the adversarial capability a first-class field of every impact assessment, replace the `placeholder` disposition with `precursor`, move prior art after the vulnerability phase, and loosen the sharpening's fact-restriction so a mapped fault is not closed on negative evidence.

**Architecture:** One schema change in `threat_model.py`, one store view change in `threat_model_store.py`, one payload change in `hunter_payload.py`, one workflow reorder in the prompt and the state enum, and one metric change in `eval/measure_utm.py`. Every row carries `capability` and `capability_id`; every threat maps its row's `capability_path` to providers as ordered `(capability_id, precursor_id | null)` tuples. The `precursors[]` section becomes legacy read-only.

**Tech Stack:** Python 3.13, pydantic v2, pytest, YAML file store, Markdown prompt assets.

## Seams under test

Confirm these seams before writing any test. They are the public boundaries of the change.

1. `check_completion(model, capability_index=...)` in `src/polymerhus/attack/hunting/threat_model.py` - the domain validator.
2. `ThreatModelStore.write_model` / `query_prior_art` / `read_threat_files` in `src/polymerhus/attack/hunting/threat_model_store.py` - the store contract.
3. `materialise_hunter_payload` in `src/polymerhus/attack/hunting/hunter_payload.py` - the hunter payload.
4. The static text of `src/polymerhus/attack/hunting/prompts/threat-modeller.md` - the workflow contract.
5. `impact_metric` in `eval/measure_utm.py` - the metric.
6. The assessor's `impact_review.yaml` schema in `eval/prompts/assessment.md`.

## Locked design

| Item | Decision |
|---|---|
| Schema version | `SCHEMA_VERSION = 4`; the reader accepts 2 and 3 |
| Disposition | `threat` or `precursor`; a v3 `placeholder` reads as `precursor` |
| Threat definition | a named victim and end damage; severity is only a score |
| Precursor definition | no end damage; still yields a capability |
| Capability | every row carries `capability` (text) and `capability_id` (`P-*`) |
| Path | `capability_path` is the ordered required capability ids |
| Threat mapping | `enabling_precursors: list[tuple[str, str | None]]`, ordered, mirrors the path; a `null` provider is a gap |
| Qualified ids | `Unit::P-1` in paths and tuples; a bare `P-1` resolves inside the owning unit |
| `precursors[]` | legacy read-only; removed from the gate sections and the tool schema |
| `precursor_refs` | legacy read-only; never written |
| Gate order | `UNIT_TECHNICAL_SHARP -> TRUST_MODELLED -> TRUST_ASSUMPTIONS_WRITTEN -> VULNERABILITIES_WRITTEN -> PRIOR_ART -> IMPACT_ASSESSED -> COMPLETED` |
| Well-formedness | prompt-only, between `VULNERABILITIES_WRITTEN` and `PRIOR_ART` |
| Prior-art query | `kind=precursor` returns `impact_assessment` rows with `disposition=precursor` |
| Payload | the threat file carries the row's capability fields plus the resolved chain |
| Metric | `green_share = green / (green + red)`; red is assessor-labelled |
| Assessor output | `verdicts.yaml` plus `impact_review.yaml` |
| Sharpening | prompt-only; no new validator |

## Non-goals

- No role-permission matrix ingestion. The prompt carries a stub; another agent owns the mining.
- No new validator for the sharpening change. It is prompt-only by explicit decision.
- No rewrite of existing v3 evidence. Compatibility is read-side.

---

## Workstream 1: Domain model and validator

### Task 1: The row carries a first-class capability and the disposition is `precursor`

**Files:**
- Modify: `src/polymerhus/attack/hunting/threat_model.py:52` (schema version), `:334` (Vulnerability, unchanged), `:553-580` (ImpactDisposition, Precursor, ImpactAssessment)
- Test: `tests/attack/test_threat_model_impact.py`

- [ ] **Step 1: Write the failing test.** Replace `test_the_model_carries_the_assessment_the_precursors_and_the_prior_art` with the new contract:

```python
def test_the_row_carries_a_first_class_capability_and_the_disposition_is_precursor():
    assert SCHEMA_VERSION == 4
    assert set(ImpactAssessment.model_fields) == {
        "id",
        "vulnerability_ref",
        "disposition",
        "damage",
        "capability",
        "capability_id",
        "capability_path",
        "evidence_refs",
        "precursor_refs",  # legacy read-only
    }
    assert ImpactDisposition.THREAT.value == "threat"
    assert ImpactDisposition.PRECURSOR.value == "precursor"
    assert "PLACEHOLDER" not in ImpactDisposition.__members__
    row = ImpactAssessment(
        id="IA-1",
        vulnerability_ref="V-1",
        disposition="placeholder",
        damage="no end damage",
        capability="read the upload directory",
        capability_id="P-1",
    )
    assert row.disposition is ImpactDisposition.PRECURSOR
    assert row.capability == "read the upload directory"
```

- [ ] **Step 2: Run the test and watch it fail.**

Run: `/Users/diekgbbtt/polymerhus/.venv/bin/python -m pytest tests/attack/test_threat_model_impact.py::test_the_row_carries_a_first_class_capability_and_the_disposition_is_precursor -q`
Expected: FAIL with `ImportError`/`ValidationError` for the missing fields.

- [ ] **Step 3: Implement.**

```python
SCHEMA_VERSION = 4

class ImpactDisposition(StrEnum):
    """Whether a row reaches an end damage (`threat`) or only a capability."""
    THREAT = "threat"
    PRECURSOR = "precursor"

class ImpactAssessment(_Record):
    """One assessed impact of one vulnerability exploitation.

    `damage` names the victim and the damaged property for a `threat` row and
    states why no end damage follows for a `precursor` row. `capability` is the
    adversarial capability the exploitation gains, and `capability_id` keys it.
    `capability_path` lists the required capability ids in execution order.
    """
    id: str = ""
    vulnerability_ref: str
    disposition: ImpactDisposition
    damage: str
    capability: str = ""
    capability_id: str = ""
    capability_path: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    precursor_refs: list[str] = Field(default_factory=list, exclude=True)

    @field_validator("disposition", mode="before")
    @classmethod
    def _legacy_placeholder(cls, value: object) -> object:
        return "precursor" if value == "placeholder" else value
```

Keep `Precursor` as a legacy model. Add `from pydantic import field_validator` if absent.

- [ ] **Step 4: Run the test and the module suite.**

Run: `/Users/diekgbbtt/polymerhus/.venv/bin/python -m pytest tests/attack/test_threat_model_impact.py -q`
Expected: PASS for the new test, failures in the old schema tests that you will rewrite in Tasks 2 and 3.

- [ ] **Step 5: Commit.**

```bash
git add src/polymerhus/attack/hunting/threat_model.py tests/attack/test_threat_model_impact.py
git commit -m "feat: give the impact row a first-class capability and replace placeholder with precursor"
```

### Task 2: The threat maps required capabilities to providers as ordered tuples

**Files:**
- Modify: `src/polymerhus/attack/hunting/threat_model.py:640-700` (Threat)
- Test: `tests/attack/test_threat_model_impact.py`

- [ ] **Step 1: Write the failing test.**

```python
def test_the_threat_maps_each_required_capability_to_its_precursor():
    threat = Threat(
        fault_ref="F-1",
        vulnerability_ref="V-1",
        canonical_class="fixation",
        web_vulnerability_class="session-management",
        likelihood=Likelihood.HIGH,
        likelihood_rationale="proven write",
        risk_factors=RiskFactors(
            attack_vector=AttackVector.NETWORK,
            attack_requirements=AttackRequirements.NONE,
            privileges_required=PrivilegesRequired.NONE,
            complexity=Complexity.LOW,
        ),
        confidence=Confidence.OBSERVED,
        evidences=[Evidence(kind=EvidenceKind.PROBE, ref="probe:1", detail="")],
        impact_ref="IA-1",
        enabling_precursors=[
            ("ReverseProxy::P-5", "ReverseProxy::P-5"),
            ("Service:sign-in::P-8", None),
        ],
        impact=impact(ImpactLevel.HIGH, ImpactLevel.HIGH),
    )
    assert threat.enabling_precursors == [
        ("ReverseProxy::P-5", "ReverseProxy::P-5"),
        ("Service:sign-in::P-8", None),
    ]
```

- [ ] **Step 2: Run it and watch it fail.**

Run: `/Users/diekgbbtt/polymerhus/.venv/bin/python -m pytest tests/attack/test_threat_model_impact.py::test_the_threat_maps_each_required_capability_to_its_precursor -q`
Expected: FAIL, the list items are strings today.

- [ ] **Step 3: Implement.**

```python
class Threat(_Record):
    ...
    impact_ref: str = ""
    enabling_precursors: list[tuple[str, str | None]] = Field(default_factory=list)
    impact: Impact = Field(default_factory=Impact)

    @field_validator("enabling_precursors", mode="before")
    @classmethod
    def _legacy_enabling(cls, value: object) -> object:
        """A v3 list of P-* ids reads as a self-provided chain."""
        if not isinstance(value, list):
            return value
        normalized = []
        for item in value:
            if isinstance(item, str):
                normalized.append((item, item))
            elif isinstance(item, (list, tuple)) and len(item) == 2:
                normalized.append((item[0], item[1]))
            else:
                normalized.append(item)
        return normalized
```

- [ ] **Step 4: Run the test.**

Run: `/Users/diekgbbtt/polymerhus/.venv/bin/python -m pytest tests/attack/test_threat_model_impact.py::test_the_threat_maps_each_required_capability_to_its_precursor -q`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add src/polymerhus/attack/hunting/threat_model.py tests/attack/test_threat_model_impact.py
git commit -m "feat: map required capabilities to precursors as ordered tuples"
```

### Task 3: The validator enforces the new row and chain invariants

**Files:**
- Modify: `src/polymerhus/attack/hunting/threat_model.py:839-1085` (`_check_necessary`, `_check_references`, `_check_closure`, `check_completion`)
- Test: `tests/attack/test_threat_model_impact.py`

- [ ] **Step 1: Write the failing tests.** Add a helper `model_with(...)` that builds a `UnitThreatModel` with one assumption, one vulnerability, one row, and one threat; then test each rule.

```python
def _chain_model(*, disposition="threat", capability_path=("P-1",),
                 enabling=(("P-1", "P-1"),), capability="cap", damage="dmg"):
    return UnitThreatModel(
        unit_id="Service:register",
        unit_kind="service",
        run_id="run-1",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        state=ModelState.COMPLETED,
        technical_sharpening=TechnicalSharpening(
            interface_agreements=[Agreement(id="IA-1", statement="s", confidence=Confidence.OBSERVED, evidences=[])],
            control_flows=[Agreement(id="CF-1", statement="s", confidence=Confidence.OBSERVED, evidences=[])],
            data_flows=[Agreement(id="DF-1", statement="s", confidence=Confidence.OBSERVED, evidences=[])],
        ),
        prior_art=PriorArt(notes="n", queries=[
            PriorArtQuery(kind=PriorArtKind.THREAT, filters=[FieldFilter(path="unit_id", regex=".")], result_count=1),
            PriorArtQuery(kind=PriorArtKind.VULNERABILITY, filters=[FieldFilter(path="unit_id", regex=".")], result_count=1),
            PriorArtQuery(kind=PriorArtKind.PRECURSOR, filters=[FieldFilter(path="unit_id", regex=".")], result_count=1),
        ]),
        trust_model=TrustModel(
            trust_agreements=[TrustAgreement(id="TA-1", statement="s", confidence=Confidence.OBSERVED, evidences=[])],
            dynamic_state_trust=DynamicStateTrust(states=[State(id="S1", statement="s", confidence=Confidence.OBSERVED, evidences=[])]),
        ),
        assumptions=[Assumption(id="A-1", statement="s", fault=Fault(id="F-1", label="l", description="d"), confidence=Confidence.INFERRED, evidences=[])],
        vulnerabilities=[Vulnerability(id="V-1", fault_ref="F-1", canonical_class="c", web_vulnerability_class="w", characterisation="x", confidence=Confidence.OBSERVED, evidences=[])],
        impact_assessment=[ImpactAssessment(id="IA-1", vulnerability_ref="V-1", disposition=disposition, damage=damage, capability=capability, capability_id="P-1", capability_path=list(capability_path))],
        threats=[Threat(... impact_ref="IA-1", enabling_precursors=list(enabling), impact=impact(ImpactLevel.HIGH))],
    )

def test_a_threat_row_without_a_capability_is_unclosed():
    model = _chain_model(capability="")
    findings = check_completion(model)
    assert "impact_assessment:IA-1.capability" in findings.missing

def test_a_threat_chain_must_mirror_the_path_order():
    model = _chain_model(capability_path=("P-1", "P-2"),
                         enabling=(("P-2", "P-2"), ("P-1", "P-1")))
    findings = check_completion(model)
    assert "threat:threat-1.enabling_precursors" in findings.unclosed

def test_a_null_provider_is_a_valid_gap():
    model = _chain_model(enabling=(("P-1", None),))
    assert check_completion(model).valid

def test_a_precursor_row_must_not_have_a_threat():
    model = _chain_model(disposition="precursor")
    assert "impact_assessment:IA-1.threat" in check_completion(model).unclosed
```

- [ ] **Step 2: Run and watch them fail.**

Run: `/Users/diekgbbtt/polymerhus/.venv/bin/python -m pytest tests/attack/test_threat_model_impact.py -q -k "capability or chain or gap or precursor_row"`
Expected: FAIL.

- [ ] **Step 3: Implement `_check_necessary`.**

Replace the impact and precursor blocks with:

```python
    for assessment in model.impact_assessment:
        if not assessment.damage:
            missing.append(f"impact_assessment:{assessment.id}.damage")
        if not assessment.capability:
            missing.append(f"impact_assessment:{assessment.id}.capability")
        if not assessment.capability_id:
            missing.append(f"impact_assessment:{assessment.id}.capability_id")
    capability_ids = [
        row.capability_id for row in model.impact_assessment if row.capability_id
    ]
    if len(capability_ids) != len(set(capability_ids)):
        missing.append("impact_assessment.capability_ids")
```

Delete the `precursors` field checks. Keep the assessment id checks. In the threat block, replace `if not threat.enabling_precursors` with nothing: an empty chain is valid.

- [ ] **Step 4: Implement `_check_references`.**

Add `capability_index: Mapping[str, Any] | None = None` to the signature. Replace the precursor reference block with:

```python
    local_capabilities = {
        row.capability_id: row for row in model.impact_assessment if row.capability_id
    }

    def resolve_capability(ref: str) -> dict | None:
        if "::" in ref:
            return (capability_index or {}).get(ref)
        return local_capabilities.get(ref)

    for assessment in model.impact_assessment:
        if assessment.vulnerability_ref not in vulnerability_ids:
            ...
        for ref in assessment.capability_path:
            if resolve_capability(ref) is None:
                unresolved(f"impact_assessment:{assessment.id}", "capability_path", ref)
    for threat in model.threats:
        ...
        row = impact_ids.get(threat.impact_ref)
        for capability, provider in threat.enabling_precursors:
            if resolve_capability(capability) is None:
                unresolved(f"threat:{threat.id}", "enabling_precursors.capability", capability)
            if provider is not None and resolve_capability(provider) is None:
                unresolved(f"threat:{threat.id}", "enabling_precursors.precursor", provider)
```

- [ ] **Step 5: Implement `_check_closure`.**

```python
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
        elif [capability for capability, _ in threat.enabling_precursors] != assessment.capability_path:
            unclosed.append(f"threat:{threat.id}.enabling_precursors")
```

- [ ] **Step 6: Add the cycle check.**

```python
def _capability_cycle(model: UnitThreatModel, index: Mapping[str, Any]) -> str | None:
    edges: dict[str, list[str]] = {}
    for row in model.impact_assessment:
        if row.capability_id:
            edges[row.capability_id] = list(row.capability_path)
    visiting, done = set(), set()

    def walk(node: str) -> bool:
        if node in visiting:
            return True
        if node in done:
            return False
        visiting.add(node)
        for nxt in edges.get(node, []):
            if walk(nxt):
                return True
        visiting.discard(node)
        done.add(node)
        return False

    return "capability_path.cycle" if any(walk(node) for node in list(edges)) else None
```

Call it in `check_completion` and append to `unclosed` when present.

- [ ] **Step 7: Run the tests and the module suite.**

Run: `/Users/diekgbbtt/polymerhus/.venv/bin/python -m pytest tests/attack/test_threat_model_impact.py -q`
Expected: PASS.

- [ ] **Step 8: Commit.**

```bash
git add src/polymerhus/attack/hunting/threat_model.py tests/attack/test_threat_model_impact.py
git commit -m "feat: enforce capability, chain order, gap, and cycle invariants"
```

### Task 4: The v3 document reads through the v4 schema

**Files:**
- Modify: `src/polymerhus/attack/hunting/threat_model_store.py:106` (`LEGACY_SCHEMA_VERSION`), `:660-690` (`_load_document`)
- Test: `tests/attack/test_threat_model_store.py`

- [ ] **Step 1: Write the failing test.**

```python
def test_a_v3_placeholder_row_reads_as_a_precursor_without_synthesis(tmp_path):
    store = ThreatModelStore(root_dir=tmp_path)
    raw = {
        "schema_version": 3,
        "unit_id": "IdentificationSystem",
        "unit_kind": "system",
        "run_id": "run-1",
        "state": "COMPLETED",
        "impact_assessment": [{
            "id": "IA-1",
            "vulnerability_ref": "V-1",
            "disposition": "placeholder",
            "damage": "no end damage",
            "precursor_refs": ["P-1"],
            "capability_path": [],
        }],
        "precursors": [{"id": "P-1", "capability": "assert identity", "procedure": "p"}],
        "threats": [],
    }
    path = store._model_path(PROJECT, "IdentificationSystem", "produced")
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(raw))
    doc = store.read_model(PROJECT, "IdentificationSystem")
    assert doc["schema_version"] == 4
    row = doc["impact_assessment"][0]
    assert row["disposition"] == "precursor"
    assert row["capability"] == ""
    assert row["capability_id"] == ""
    assert doc["precursors"] == raw["precursors"]
```

- [ ] **Step 2: Run and watch it fail.**

Run: `/Users/diekgbbtt/polymerhus/.venv/bin/python -m pytest tests/attack/test_threat_model_store.py::test_a_v3_placeholder_row_reads_as_a_precursor_without_synthesis -q`
Expected: FAIL, the reader refuses version 3.

- [ ] **Step 3: Implement the normaliser.**

Add `from .threat_model import LEGACY_SCHEMA_VERSIONS` and:

```python
def _normalise_v3(raw: dict) -> dict:
    """Lift a v3 document into the v4 shape without inventing capabilities."""
    doc = json.loads(json.dumps(raw))
    doc["schema_version"] = SCHEMA_VERSION
    for row in doc.get("impact_assessment") or []:
        if row.get("disposition") == "placeholder":
            row["disposition"] = "precursor"
        row.setdefault("capability", "")
        row.setdefault("capability_id", "")
    for threat in doc.get("threats") or []:
        enabling = threat.get("enabling_precursors") or []
        threat["enabling_precursors"] = [
            (item, item) if isinstance(item, str) else item for item in enabling
        ]
    return doc
```

In `_load_document`, accept `version == 3` and return `_normalise_v3(raw)`. Keep `allow_legacy` for v2. In `threat_model.py`, export `LEGACY_SCHEMA_VERSIONS = (2, 3)`.

- [ ] **Step 4: Run the store test and the impact test.**

Run: `/Users/diekgbbtt/polymerhus/.venv/bin/python -m pytest tests/attack/test_threat_model_store.py::test_a_v3_placeholder_row_reads_as_a_precursor_without_synthesis tests/attack/test_threat_model_impact.py -q`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add src/polymerhus/attack/hunting/threat_model.py src/polymerhus/attack/hunting/threat_model_store.py tests/attack/test_threat_model_store.py
git commit -m "feat: read v3 placeholders as precursors without synthesising capabilities"
```

---

## Workstream 2: Store, query, and payload

### Task 5: The impact gate writes rows only, and `precursors[]` becomes legacy

**Files:**
- Modify: `src/polymerhus/attack/hunting/threat_model.py:163-178` (`GATE_SECTIONS`), `:700-720` (`ModelSections`)
- Test: `tests/attack/test_threat_model_impact.py`

- [ ] **Step 1: Write the failing test.**

```python
def test_the_impact_gate_writes_rows_only():
    assert GATE_SECTIONS[ModelState.IMPACT_ASSESSED] == ("impact_assessment",)
    assert "precursors" not in ModelSections.model_fields
```

- [ ] **Step 2: Run and watch it fail.**

Run: `/Users/diekgbbtt/polymerhus/.venv/bin/python -m pytest tests/attack/test_threat_model_impact.py::test_the_impact_gate_writes_rows_only -q`
Expected: FAIL.

- [ ] **Step 3: Implement.** Set the gate tuple to `("impact_assessment",)`. Remove the `precursors` field from `ModelSections`. Keep `UnitThreatModel.precursors` as a legacy field.

- [ ] **Step 4: Run and commit.**

Run: `/Users/diekgbbtt/polymerhus/.venv/bin/python -m pytest tests/attack/test_threat_model_impact.py -q`

```bash
git add src/polymerhus/attack/hunting/threat_model.py tests/attack/test_threat_model_impact.py
git commit -m "feat: retire the precursor section from the impact gate"
```

### Task 6: `kind=precursor` returns impact rows with `disposition=precursor`

**Files:**
- Modify: `src/polymerhus/attack/hunting/threat_model_store.py:286-300` (`_QUERY_SECTION_BY_KIND`), `:521-590` (`_section_query_views`, `_query_match`), `src/polymerhus/attack/hunting/threat_model.py:365-445` (`PRIOR_ART_PATHS`)
- Test: `tests/attack/test_threat_model_store.py`

- [ ] **Step 1: Write the failing test.**

```python
def test_the_precursor_query_returns_precursor_rows_with_the_capability(tmp_path):
    store = ThreatModelStore(root_dir=tmp_path)
    _write_model(store, rows=[precursor_row(capability="read uploads")], threats=[])
    result = store.query_prior_art(
        PROJECT, kind="precursor",
        filters=[{"path": "capability", "regex": "upload"}],
    )
    assert result["matches"][0]["record_id"] == "IA-1"
    assert result["matches"][0]["label"] == "read uploads"
    assert result["matches"][0]["disposition"] == "precursor"
```

- [ ] **Step 2: Run and watch it fail.**

Run: `/Users/diekgbbtt/polymerhus/.venv/bin/python -m pytest tests/attack/test_threat_model_store.py::test_the_precursor_query_returns_precursor_rows_with_the_capability -q`
Expected: FAIL, the query reads `precursors[]`.

- [ ] **Step 3: Implement.** Map `PriorArtKind.PRECURSOR` to `"impact_assessment"` in `_QUERY_SECTION_BY_KIND`. In `_section_query_views`, when `kind is PriorArtKind.PRECURSOR`, skip rows whose `disposition != "precursor"`. In `_query_match`, for `PRECURSOR`, set `label=capability`, `summary=damage`, and `disposition=disposition`. Add `capability`, `capability_id` to both `PRIOR_ART_PATHS[PRECURSOR]` and `[IMPACT]`.

- [ ] **Step 4: Run and commit.**

Run: `/Users/diekgbbtt/polymerhus/.venv/bin/python -m pytest tests/attack/test_threat_model_store.py -q -k "query or precursor"`

```bash
git add src/polymerhus/attack/hunting/threat_model_store.py src/polymerhus/attack/hunting/threat_model.py tests/attack/test_threat_model_store.py
git commit -m "feat: resolve precursor queries from impact rows"
```

### Task 7: Qualified capability ids resolve across the project

**Files:**
- Modify: `src/polymerhus/attack/hunting/threat_model_store.py` (new `capability_index`, pass it to `check_completion` at `:1470-1485`)
- Test: `tests/attack/test_threat_model_store.py`

- [ ] **Step 1: Write the failing test.** Write two models, the second referencing `First::P-1`; assert the completed write is valid and the threat file's qualified path is preserved.

```python
def test_a_capability_from_another_unit_resolves(tmp_path):
    store = ThreatModelStore(root_dir=tmp_path)
    _write_completed(store, "First", rows=[threat_row(capability_id="P-1")], threats=[])
    result = _write_completed(store, "Second",
        rows=[threat_row(id="IA-2", capability_id="P-2", capability_path=["First::P-1"])],
        threats=[threat(impact_ref="IA-2", enabling=[("First::P-1", None)])],
    )
    assert result["validation"]["valid"] is True
```

- [ ] **Step 2: Run and watch it fail.**

Run: `/Users/diekgbbtt/polymerhus/.venv/bin/python -m pytest tests/attack/test_threat_model_store.py::test_a_capability_from_another_unit_resolves -q`
Expected: FAIL with a referential error.

- [ ] **Step 3: Implement.**

```python
def _capability_index(self, project_id: str) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for family in _READ_FAMILIES:
        for _directory, document in self._query_documents(project_id, family):
            unit = str(document.get("unit_id") or "")
            for row in document.get("impact_assessment") or []:
                capability_id = str(row.get("capability_id") or "")
                if unit and capability_id:
                    index[f"{unit}::{capability_id}"] = {
                        "unit_id": unit, "row": row,
                    }
    return index
```

Call `self._capability_index(project_id)` in `_merged_document` before `check_completion`, and pass it as `capability_index=`.

- [ ] **Step 4: Run and commit.**

Run: `/Users/diekgbbtt/polymerhus/.venv/bin/python -m pytest tests/attack/test_threat_model_store.py -q -k "capability or resolve"`

```bash
git add src/polymerhus/attack/hunting/threat_model_store.py tests/attack/test_threat_model_store.py
git commit -m "feat: resolve qualified capability ids across the project"
```

### Task 8: The threat file and the hunter payload carry the resolved chain

**Files:**
- Modify: `src/polymerhus/attack/hunting/threat_model_store.py:1491-1555` (`_write_threat_files`), `src/polymerhus/attack/hunting/hunter_payload.py:123-220`
- Test: `tests/attack/test_threat_model_store.py`, `tests/attack/test_hunter_payload.py` (create if absent)

- [ ] **Step 1: Write the failing test.**

```python
def test_the_threat_file_carries_the_capability_and_the_resolved_chain(tmp_path):
    ...
    record = yaml.safe_load((produced / "threat-1.yaml").read_text())
    assert record["impact"]["capability"] == "read the roster"
    assert record["impact"]["capability_id"] == "Second::P-2"
    assert record["impact"]["capability_path"] == ["First::P-1"]
    assert record["impact"]["chain"] == [
        {"capability": "First::P-1", "precursor": None,
         "resolved": {"unit_id": "First", "capability": "reach admin", "damage": "..."}},
    ]
```

- [ ] **Step 2: Run and watch it fail.**

Run: `/Users/diekgbbtt/polymerhus/.venv/bin/python -m pytest tests/attack/test_threat_model_store.py::test_the_threat_file_carries_the_capability_and_the_resolved_chain -q`
Expected: FAIL, the file has `precursors` and `precursor_refs`.

- [ ] **Step 3: Implement.** In `_write_threat_files`:

```python
index = self._capability_index(project_id)

def qualify(ref: str, unit: str) -> str:
    return ref if "::" in ref else f"{unit}::{ref}"

"impact": {
    "impact_ref": assessment.id,
    "damage": assessment.damage,
    "disposition": assessment.disposition.value,
    "capability": assessment.capability,
    "capability_id": qualify(assessment.capability_id, model.unit_id),
    "capability_path": [qualify(ref, model.unit_id) for ref in assessment.capability_path],
    "chain": [
        {
            "capability": qualify(capability, model.unit_id),
            "precursor": qualify(provider, model.unit_id) if provider else None,
            "resolved": (index.get(qualify(capability, model.unit_id)) or {}).get("row"),
        }
        for capability, provider in threat.enabling_precursors
    ],
},
```

Keep the raw `threat` block unchanged. In `materialise_hunter_payload`, copy `impact` as-is; add a `capability_chain` key that is the `impact["chain"]` with each `resolved` row reduced to `{unit_id, capability, damage}`.

- [ ] **Step 4: Run and commit.**

Run: `/Users/diekgbbtt/polymerhus/.venv/bin/python -m pytest tests/attack/test_threat_model_store.py tests/attack/test_hunter_payload.py -q`

```bash
git add src/polymerhus/attack/hunting/threat_model_store.py src/polymerhus/attack/hunting/hunter_payload.py tests/attack
git commit -m "feat: denormalise the capability chain into the threat file and payload"
```

---

## Workstream 3: Workflow and prompt

### Task 9: Prior art moves after the vulnerability phase

**Files:**
- Modify: `src/polymerhus/attack/hunting/threat_model.py:147-160` (`ModelState`), `src/polymerhus/attack/hunting/threat_modeller.py:97-235` (hints/instructions), `src/polymerhus/attack/hunting/prompts/threat-modeller.md:19-32`, `:87-91`
- Test: `tests/attack/test_threat_model_impact.py`, `tests/attack/test_threat_modeller_prompt.py`

- [ ] **Step 1: Write the failing test.**

```python
def test_the_gate_order_puts_prior_art_after_the_vulnerability_phase():
    assert [state.value for state in ModelState] == [
        "UNIT_TECHNICAL_SHARP",
        "TRUST_MODELLED",
        "TRUST_ASSUMPTIONS_WRITTEN",
        "VULNERABILITIES_WRITTEN",
        "PRIOR_ART",
        "IMPACT_ASSESSED",
        "COMPLETED",
    ]
```

- [ ] **Step 2: Run and watch it fail.**

Run: `/Users/diekgbbtt/polymerhus/.venv/bin/python -m pytest tests/attack/test_threat_model_impact.py::test_the_gate_order_puts_prior_art_after_the_vulnerability_phase -q`
Expected: FAIL.

- [ ] **Step 3: Implement.** Move the `PRIOR_ART` member. Update `STATE_INSTRUCTIONS` and the gate hints: after `VULNERABILITIES_WRITTEN` the hint is the well-formedness pass, then `PRIOR_ART`; after `PRIOR_ART` the hint is `IMPACT_ASSESSED`. Update the prompt's numbered table and the "After VULNERABILITIES_WRITTEN" sentence to "run well-formedness, then the PRIOR_ART gate".

- [ ] **Step 4: Run the prompt and impact suites.**

Run: `/Users/diekgbbtt/polymerhus/.venv/bin/python -m pytest tests/attack/test_threat_model_impact.py tests/attack/test_threat_modeller_prompt.py -q`

- [ ] **Step 5: Commit.**

```bash
git add src/polymerhus/attack/hunting/threat_model.py src/polymerhus/attack/hunting/threat_modeller.py src/polymerhus/attack/hunting/prompts/threat-modeller.md tests/attack
git commit -m "feat: move prior art after the vulnerability phase"
```

### Task 10: The impact prompt teaches the one-pass, gap-filling chain

**Files:**
- Modify: `src/polymerhus/attack/hunting/prompts/threat-modeller.md:200-226`, `:287-341`, `:353-369`
- Test: `tests/attack/test_threat_modeller_prompt.py`

- [ ] **Step 1: Write the failing assertions.**

```python
def test_the_impact_prompt_teaches_the_capability_and_the_chain():
    prompt = _prompt()
    assert "capability_id" in prompt
    assert "enabling_precursors" in prompt
    assert "(capability_id, precursor_id)" in prompt
    assert "null" in prompt and "gap" in prompt
    assert "one pass" in prompt
    assert "queries the prior art" in prompt
    assert "disposition=precursor" in prompt
```

- [ ] **Step 2: Run and watch it fail.**

Run: `/Users/diekgbbtt/polymerhus/.venv/bin/python -m pytest tests/attack/test_threat_modeller_prompt.py::test_the_impact_prompt_teaches_the_capability_and_the_chain -q`
Expected: FAIL.

- [ ] **Step 3: Implement the prompt section.** Replace the "Impact assessment and the precursors" section with:

```markdown
## Impact assessment and the capability chain (IMPACT_ASSESSED)

Assess the damage BEFORE you score it.
One row per exploitation manner goes in `impact_assessment`.
Every row carries the adverse capability the exploitation gains.

1. First pass: assess the impact of exploiting the vulnerability alone.
   If it reaches a concrete end damage, write a `threat` row.
2. If it does not, name the end damages close to the impact reached, and list the
   capabilities the attacker still needs.
3. Query the prior art for the threats, vulnerabilities, and precursors affine to
   the exploitation, and look for a chain that fills the gaps.
4. If you can illustrate the chain, write the `threat` row with an
   `enabling_precursors` list that covers the full path.
   If the chain is partial, keep every required capability in the list and set the
   unresolved provider to `null`.
5. If you cannot illustrate a chain to an end damage, the row is a `precursor`.

The victim and property catalog:

| Victim | Property |
|---|---|
| An end user (PII, account, access) | confidentiality, integrity, availability |
| The application (persisted data, configuration, audit or telemetry data, availability) | confidentiality, integrity, availability |
| The infrastructure (host, runtime, network, cloud account) | confidentiality, integrity, availability, privileged code execution |

Row fields:

- `capability` (text): the adversarial capability gained when this impact is realised.
- `capability_id` (`P-*`): the key that other units reference.
- `capability_path` (`P-*` or `Unit::P-*`, ordered): the capabilities required to exploit the vulnerability.
- `damage`: the victim and the damaged property for a `threat` row; for a `precursor` row, why no end damage follows.
- `evidence_refs`: the probes and records behind the assessment.

A `threat` row names a concrete victim and property and closes to exactly one threat.
A `precursor` row has no end damage, is never dispatched, and still yields its capability.
The capability is first class in both dispositions: a later unit may reference a
`precursor` capability or a `threat` capability with the same `Unit::P-*` id.

The threat maps every required capability to its provider:

```yaml
enabling_precursors:
  - [ReverseProxy::P-5, ReverseProxy::P-5]
  - [Service:sign-in::P-8, null]
```

The first element is the capability required, the second is the precursor that
provides it, and `null` is an unfilled gap. The order is the execution order and
mirrors the row's `capability_path`.
```

Update the worked example to the tuple shape:

```yaml
IA-1: disposition=threat, damage="...", capability="read the cloud instance
credentials", capability_id=P-1, capability_path=[P-1]
threat-1: enabling_precursors=[[P-1, P-1]]
```

Replace the "Low-yield contrast" paragraph with a precursor contrast: a soft-404
contract divergence yields `disposition=precursor`, `capability="detect the
difference between an unmapped route and an unmapped handler"`, `capability_id=P-2`,
`capability_path=[]`; it is not dispatched but remains queryable.

- [ ] **Step 4: Run the prompt suite.**

Run: `/Users/diekgbbtt/polymerhus/.venv/bin/python -m pytest tests/attack/test_threat_modeller_prompt.py -q`

- [ ] **Step 5: Commit.**

```bash
git add src/polymerhus/attack/hunting/prompts/threat-modeller.md tests/attack/test_threat_modeller_prompt.py
git commit -m "feat: teach the capability chain in the modeller prompt"
```

### Task 11: The sharpening stops closing faults on negative evidence

**Files:**
- Modify: `src/polymerhus/attack/hunting/prompts/threat-modeller.md:56-85`, `:269-285`, `:343-351`
- Test: `tests/attack/test_threat_modeller_prompt.py`

- [ ] **Step 1: Write the failing assertions.**

```python
def test_the_sharpening_keeps_a_fault_open_on_negative_evidence():
    prompt = _prompt()
    assert "A negative probe never closes a fault" in prompt
    assert "IT DOES NOT EXIST ON THE PUBLIC LISTENER" in prompt
    assert "at least two independent falsifying observations" in prompt
    assert "reduce the probing budget" in prompt
```

- [ ] **Step 2: Run and watch it fail.**

Run: `/Users/diekgbbtt/polymerhus/.venv/bin/python -m pytest tests/attack/test_threat_modeller_prompt.py::test_the_sharpening_keeps_a_fault_open_on_negative_evidence -q`
Expected: FAIL.

- [ ] **Step 3: Implement.** Insert into the grounding section:

```markdown
**Probe the interface, not the exploit.** Probe only the fundamental mechanical
properties the interface agreements depend on. A negative probe never closes a
fault: a 404 on a route proves one spelling does not resolve, not that the route
or its handler is absent.

Keep a modelled endpoint even when you hold no objective evidence of its fault:
carry the fault at `ASSUMED` or `INFERRED`. Close a fault only on at least two
independent falsifying observations, one of them a control from inside the served
root. Six shapes of one payload are one observation, not six.

**Worked failure: white-jotter-006.** The file-read route answered 404 for six
single-encoded shapes. The model wrote "IT DOES NOT EXIST ON THE PUBLIC LISTENER"
and closed the whole upload-to-served-executable chain. The ground truth used a
double-encoded separator (`..%252f..%252f..%252fetc%252fpasswd`) and read
`/etc/passwd`. The route existed; the candidate was wrong. The model should have
kept the endpoint and the fault at `ASSUMED`, and left the concrete technique to
the hunter.

Keep the probing budget small: verify the primitive and the shape, record the
evidence, and stop. The hunter owns exploitation.
```

Also add to the Identity trust section:

```markdown
When the unit enforces authorization, model the permissions of every observed
object and function for each role you can name. A role-permission matrix is the
expected evidence; until the mining agent supplies it, infer the cells from the
observed interface and mark them `INFERRED` or `ASSUMED`.
```

- [ ] **Step 4: Run and commit.**

Run: `/Users/diekgbbtt/polymerhus/.venv/bin/python -m pytest tests/attack/test_threat_modeller_prompt.py -q`

```bash
git add src/polymerhus/attack/hunting/prompts/threat-modeller.md tests/attack/test_threat_modeller_prompt.py
git commit -m "feat: keep faults open on negative evidence and reduce probing"
```

---

## Workstream 4: Metric and assessment

### Task 12: The impact metric counts capabilities and reads the review labels

**Files:**
- Modify: `eval/measure_utm.py:730-890`, `eval/prompts/measure.md`
- Test: `tests/eval/test_measure_utm.py`

- [ ] **Step 1: Write the failing test.**

```python
def test_the_v4_impact_block_counts_capabilities_and_applies_the_review(tmp_path):
    models = [{
        "schema_version": 4,
        "impact_assessment": [
            {"id": "IA-1", "disposition": "threat", "capability": "read", "capability_id": "P-1"},
            {"id": "IA-2", "disposition": "precursor", "capability": "probe", "capability_id": "P-2"},
        ],
        "threats": [{"impact_ref": "IA-1", "impact": {"confidentiality": "high", "integrity": "none", "availability": "none"}}],
    }]
    review = {"rows": {"IA-1": "sufficient", "IA-2": "under_mined"}, "scope": {"IA-1": "in", "IA-2": "in"}}
    block = impact_metric(models, [], impact_review=review)
    assert block["green"] == 1
    assert block["red"] == 1
    assert block["capability_rows"] == 1
    assert block["green_share"] == 0.5
```

- [ ] **Step 2: Run and watch it fail.**

Run: `/Users/diekgbbtt/polymerhus/.venv/bin/python -m pytest tests/eval/test_measure_utm.py::test_the_v4_impact_block_counts_capabilities_and_applies_the_review -q`
Expected: FAIL.

- [ ] **Step 3: Implement.** Add a `impact_review` parameter to `impact_metric` and `impact_block`. In `v3_impact`, recognise `schema_version == 4` and `disposition in ("threat", "precursor", "placeholder")`, counting:
  - `green` = `threat` rows;
  - `capability_rows` = rows with a non-empty `capability` and `disposition == "precursor"`;
  - `red` = rows the review marks `scope=out` or `mining=under_mined`;
  - `green_share = green / (green + red)` when a review exists, else `green / total` with `reviewed: false`.
  Keep `placeholders` as an alias for legacy counts and add `precursors`.

- [ ] **Step 4: Run and commit.**

Run: `/Users/diekgbbtt/polymerhus/.venv/bin/python -m pytest tests/eval/test_measure_utm.py -q`

```bash
git add eval/measure_utm.py eval/prompts/measure.md tests/eval/test_measure_utm.py
git commit -m "feat: count capabilities and apply the impact review in the metric"
```

### Task 13: The assessor writes `impact_review.yaml`

**Files:**
- Modify: `eval/prompts/assessment.md`, `eval/orchestrator/monitor.py` (verify the sibling file)
- Test: `tests/eval/test_orchestrator_monitor.py` (or the existing monitor test)

- [ ] **Step 1: Write the failing test.** Assert the monitor's assessment node accepts a trial with both `verdicts.yaml` and `impact_review.yaml` and rejects a review with an unknown `mining` value.

- [ ] **Step 2: Run and watch it fail.**

- [ ] **Step 3: Implement.** Add to `assessment.md`:

```markdown
## Second output: impact_review.yaml

Write a sibling `impact_review.yaml` beside `verdicts.yaml`:

```yaml
units:
  - unit: Service:article-management
    scope: in | out
    scope_reason: string
    rows:
      - id: IA-1
        mining: sufficient | under_mined
        rationale: string
```

`scope` labels the unit against the injected `threat_model_scope`.
`mining` labels one row: `sufficient` when the row's capability is the honest end
of that exploitation, `under_mined` when a concrete end damage was achievable and
the row stopped at a capability. A `threat` row is always `sufficient`.
```

Update the monitor to verify the file exists and its enums are valid.

- [ ] **Step 4: Run and commit.**

```bash
git add eval/prompts/assessment.md eval/orchestrator/monitor.py tests/eval
git commit -m "feat: require the impact review beside the verdicts"
```

---

## Workstream 5: Design documents

### Task 14: Update the impact specification and the module context

**Files:**
- Modify: `docs/design/impact-assessment-system-spec.md`
- Modify: `src/polymerhus/attack/hunting/CONTEXT.md`
- Modify: `docs/design/unit-threat-model-spec-impact-map.md`
- Test: docs lint if present; otherwise a grep assertion

- [ ] **Step 1: Update the spec.** Replace every `placeholder` definition with `precursor`; add the capability fields; change the gate order; change the metric definitions; add stories for capability persistence and cross-unit composition; update the worked example.

- [ ] **Step 2: Update `CONTEXT.md`.** Change the gate order, the impact assessment term, the precursor term, the query kinds, and the payload description.

- [ ] **Step 3: Update the impact map.** List the changed entities and the changed tests.

- [ ] **Step 4: Commit.**

```bash
git add docs/design/impact-assessment-system-spec.md src/polymerhus/attack/hunting/CONTEXT.md docs/design/unit-threat-model-spec-impact-map.md
git commit -m "docs: describe the capability-first impact model"
```

---

## Workstream 6: Verification

### Task 15: Full regression and lint

- [ ] **Step 1: Run the four focused suites.**

```bash
/Users/diekgbbtt/polymerhus/.venv/bin/python -m pytest \
  tests/attack/test_threat_model_impact.py \
  tests/attack/test_threat_model_store.py \
  tests/attack/test_threat_modeller_prompt.py \
  tests/eval/test_measure_utm.py -q
```

- [ ] **Step 2: Run the full attack and eval suites.**

```bash
/Users/diekgbbtt/polymerhus/.venv/bin/python -m pytest tests/attack tests/eval -q
```

- [ ] **Step 3: Run lint and type checks if configured.**

```bash
/Users/diekgbbtt/polymerhus/.venv/bin/python -m ruff check src tests eval
```

- [ ] **Step 4: Commit the final fixes.**

```bash
git add -A
git commit -m "test: verify the capability-first impact model"
```
