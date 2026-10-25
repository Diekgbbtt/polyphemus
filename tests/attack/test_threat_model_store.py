"""Unit tier: the unit threat model schema and the ThreatModelStore (T1, #374).

Pure filesystem mechanics and pure schema logic - no Neo4j, no LLM. Pins the
partial/complete document contract, the gate merge and monotonic state, the
completion checker (necessary attributes, referential integrity, the
assumption-to-loop closure, the loop order, the risk profile), the
loop-file emission and the commit protocol, the mover primitives, the
move-aware write, the collision-safe unit name, the invalid-model archive,
and the bounded notes store.

Every test drives the real store on a temporary project root and asserts the
public store API or the persisted files, never a private method.
"""
from __future__ import annotations

import pytest
import yaml

from polymerhus.attack.hunting.threat_model import (
    DEFAULT_RISK_THRESHOLD,
    GATE_SECTIONS,
    RISK_WEIGHTS,
    ModelState,
    UnitThreatModel,
    check_completion,
)
from polymerhus.attack.hunting.threat_model_store import (
    ThreatModelDirectoryError,
    ThreatModelDocumentError,
    ThreatModelIdentityError,
    ThreatModelSchemaVersionError,
    ThreatModelStore,
    collision_suffix,
)

PROJECT = "proj-1"
UNIT = "Service:catalogue-and-discovery"
RUN = "run-1"


# --- schema fixtures ---------------------------------------------------------

def _evidence(ref: str = "GET /catalogue") -> dict:
    return {"kind": "request", "ref": ref}


def _sharpening() -> dict:
    return {
        "interface_agreements": [{
            "id": "ia-1",
            "statement": "The catalogue endpoint reads the item id from the query.",
            "confidence": "OBSERVED",
            "evidences": [_evidence()],
        }],
        "control_flows": [{
            "id": "cf-1",
            "statement": "The request handler authorises before the lookup.",
            "confidence": "INFERRED",
            "evidences": [_evidence("framework default")],
        }],
        "data_flows": [{
            "id": "df-1",
            "statement": "The item body is rendered into the product page.",
            "confidence": "OBSERVED",
            "evidences": [_evidence()],
        }],
    }


def _trust_model() -> dict:
    return {
        "trust_agreements": [{
            "id": "ta-1",
            "boundary": "anonymous caller -> catalogue lookup",
            "interface_agreement_refs": ["ia-1"],
            "statement": "The lookup trusts the caller's item id.",
            "confidence": "INFERRED",
            "evidences": [_evidence()],
        }],
        "dynamic_state_trust": {
            "states": [{
                "id": "ds-1",
                "variables": ["item_id"],
                "confidence": "OBSERVED",
                "evidences": [_evidence()],
            }],
            "transitions": [{
                "id": "tr-1",
                "source": "ds-1",
                "target": "ds-1",
                "guard": "any item id",
                "confidence": "INFERRED",
                "evidences": [_evidence()],
            }],
            "violations": [{
                "id": "vi-1",
                "kind": "trust-transition",
                "statement": "A caller can force the state before the owner check.",
                "maps_to_fault": "fault-1",
                "transition_ref": "tr-1",
                "confidence": "ASSUMED",
                "evidences": [_evidence()],
            }],
        },
    }


def _fault() -> dict:
    return {
        "id": "fault-1",
        "label": "improper authorisation on the item lookup",
        "description": "The handler does not check item ownership.",
    }


def _assumptions() -> list[dict]:
    return [{
        "id": "as-1",
        "statement": "The handler omits the ownership check.",
        "fault": _fault(),
        "boundary_ref": "ta-1",
        "confidence": "ASSUMED",
        "evidences": [_evidence("note:catalogue")],
    }]


def _vulnerabilities() -> list[dict]:
    return [{
        "id": "v-1",
        "fault_ref": "fault-1",
        "canonical_class": "IDOR",
        "web_vulnerability_class": "idor",
        "characterisation": "An anonymous caller reads another user's item.",
        "confidence": "INFERRED",
        "evidences": [_evidence()],
    }]


def _legacy_failure_modes() -> list[dict]:
    """A pre-contraction section payload: the strict schema and the store must
    reject it, never merge it."""
    return [{
        "id": "fm-1",
        "vulnerability_ref": "v-1",
        "mode": "read of another tenant's item",
        "feasibility": "feasible",
        "feasibility_rationale": "The lookup takes the id straight from the query.",
        "confidence": "INFERRED",
        "evidences": [_evidence()],
    }]


def _loop(likelihood: str = "high") -> dict:
    return {
        "id": "modeller-1",
        "fault_ref": "fault-1",
        "vulnerability_ref": "v-1",
        "canonical_class": "IDOR",
        "web_vulnerability_class": "idor",
        "likelihood": likelihood,
        "likelihood_rationale": "The item id is attacker-controlled and unauthenticated.",
        "risk_factors": {
            "attack_vector": "network",
            "attack_requirements": "none",
            "privileges_required": "none",
            "complexity": "low",
        },
        "impact": {
            "confidentiality": "low",
            "integrity": "none",
            "availability": "none",
            "end_impact": "A caller reads another tenant's item.",
        },
        "confidence": "INFERRED",
        "evidences": [_evidence()],
    }


def _sections_below_completed() -> list[tuple[str, dict]]:
    return [
        ("UNIT_TECHNICAL_SHARP", {"technical_sharpening": _sharpening()}),
        ("TRUST_MODELLED", {"trust_model": _trust_model()}),
        ("TRUST_ASSUMPTIONS_WRITTEN", {"assumptions": _assumptions()}),
        ("VULNERABILITIES_WRITTEN", {"vulnerabilities": _vulnerabilities()}),
    ]


def _completed_sections(loops: list[dict] | None = None) -> dict:
    return {"loops": [_loop()] if loops is None else loops}


def _write_to_completed(store: ThreatModelStore, *, loops: list[dict] | None = None) -> None:
    for state, sections in _sections_below_completed():
        store.write_sections(PROJECT, UNIT, state, sections, run_id=RUN)
    store.write_sections(PROJECT, UNIT, "COMPLETED", _completed_sections(loops), run_id=RUN)


def _dropped_vulnerabilities() -> list[dict]:
    return [{
        **_vulnerabilities()[0],
        "dropped": True,
        "drop_reason": "The item lookup binds the id to the tenant; the mechanics are absent.",
        "drop_probe": "A request with a second tenant's item id returning that item.",
    }]


def _write_zero_loop_completed(store: ThreatModelStore) -> None:
    for state, sections in _sections_below_completed()[:-1]:
        store.write_sections(PROJECT, UNIT, state, sections, run_id=RUN)
    store.write_sections(
        PROJECT, UNIT, "VULNERABILITIES_WRITTEN",
        {"vulnerabilities": _dropped_vulnerabilities()}, run_id=RUN,
    )
    store.write_sections(
        PROJECT, UNIT, "COMPLETED", {"loops": []}, run_id=RUN,
    )


def _dump_yaml(path, body) -> None:
    """The un-injected half of the atomic dump, for the injected-write tests."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(body, sort_keys=False), encoding="utf-8")


# --- the partial document contract ------------------------------------------

def test_write_sections_persists_a_partial_model_and_reads_it_back(tmp_path):
    store = ThreatModelStore(tmp_path)

    path = store.write_sections(
        PROJECT, UNIT, "UNIT_TECHNICAL_SHARP",
        {"technical_sharpening": _sharpening()}, run_id=RUN,
    )

    unit_name = "Service-catalogue-and-discovery"
    assert path == (
        tmp_path / PROJECT / "hunting" / "threat_modeller" / "produced"
        / unit_name / f"{unit_name}.yaml"
    )
    assert path.exists()
    model = store.read_model(PROJECT, UNIT)
    assert model["schema_version"] == 1
    assert model["unit_id"] == UNIT
    assert model["unit_kind"] == "service"
    assert model["run_id"] == RUN
    assert model["state"] == "UNIT_TECHNICAL_SHARP"
    assert model["technical_sharpening"]["interface_agreements"][0]["id"] == "ia-1"
    assert store.read_section(PROJECT, UNIT, "technical_sharpening") == model["technical_sharpening"]


def test_gate_writes_merge_sections_into_one_document(tmp_path):
    store = ThreatModelStore(tmp_path)

    for state, sections in _sections_below_completed():
        store.write_sections(PROJECT, UNIT, state, sections, run_id=RUN)

    model = store.read_model(PROJECT, UNIT)
    assert model["state"] == "VULNERABILITIES_WRITTEN"
    assert model["technical_sharpening"]["interface_agreements"][0]["id"] == "ia-1"
    assert model["trust_model"]["trust_agreements"][0]["id"] == "ta-1"
    assert model["assumptions"][0]["fault"]["id"] == "fault-1"
    assert model["vulnerabilities"][0]["canonical_class"] == "IDOR"
    assert "failure_modes" not in model
    assert model["loops"] == []


def test_a_lower_gate_write_never_regresses_the_state(tmp_path):
    store = ThreatModelStore(tmp_path)
    for state, sections in _sections_below_completed():
        store.write_sections(PROJECT, UNIT, state, sections, run_id=RUN)

    store.write_sections(
        PROJECT, UNIT, "UNIT_TECHNICAL_SHARP",
        {"technical_sharpening": {
            **_sharpening(),
            "data_flows": [],
        }},
        run_id=RUN,
    )

    model = store.read_model(PROJECT, UNIT)
    assert model["state"] == "VULNERABILITIES_WRITTEN"
    # the lower-gate content still merges (the trail-only backward signal)
    assert model["technical_sharpening"]["data_flows"] == []


def test_an_unknown_field_is_rejected_and_nothing_is_persisted(tmp_path):
    store = ThreatModelStore(tmp_path)
    sharpening = _sharpening()
    sharpening["interface_agreements"][0]["typo"] = "silently persisted?"

    with pytest.raises(ValueError):
        store.write_sections(
            PROJECT, UNIT, "UNIT_TECHNICAL_SHARP",
            {"technical_sharpening": sharpening}, run_id=RUN,
        )

    assert store.read_model(PROJECT, UNIT) is None
    produced = tmp_path / PROJECT / "hunting" / "threat_modeller" / "produced"
    assert list(produced.glob("*/*.yaml")) == []


def test_a_section_outside_the_gates_set_is_a_coded_rejection(tmp_path):
    store = ThreatModelStore(tmp_path)

    with pytest.raises(ThreatModelIdentityError) as raised:
        store.write_sections(
            PROJECT, UNIT, "TRUST_MODELLED",
            {"assumptions": _assumptions()}, run_id=RUN,
        )

    assert raised.value.fields == ["assumptions"]
    assert store.read_model(PROJECT, UNIT) is None


def test_the_completed_gate_accepts_only_the_loops_section(tmp_path):
    """The failure-mode contraction (ADR 2026-10-25): the COMPLETED gate carries
    the loops alone, so a `failure_modes` section is a coded rejection and
    nothing is persisted."""
    store = ThreatModelStore(tmp_path)
    for state, sections in _sections_below_completed():
        store.write_sections(PROJECT, UNIT, state, sections, run_id=RUN)

    with pytest.raises(ThreatModelIdentityError) as raised:
        store.write_sections(
            PROJECT, UNIT, "COMPLETED",
            {"failure_modes": _legacy_failure_modes(), "loops": [_loop()]}, run_id=RUN,
        )

    assert raised.value.fields == ["failure_modes"]
    assert GATE_SECTIONS[ModelState.COMPLETED] == ("loops",)
    assert store.read_model(PROJECT, UNIT)["state"] == "VULNERABILITIES_WRITTEN"


def test_the_stored_model_carries_no_failure_mode_key(tmp_path):
    """The section and the loop link are gone from the persisted document, the
    model and the loop file alike (the contract half of the expand-contract)."""
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store)

    model = store.read_model(PROJECT, UNIT)

    assert "failure_modes" not in model
    assert "failure_mode_refs" not in model["loops"][0]
    loop_file = store.read_loop_files(PROJECT, UNIT)[0]
    assert "failure_mode_refs" not in loop_file["loop"]


def test_a_model_with_a_failure_modes_key_is_rejected_by_the_strict_schema(tmp_path):
    """The contraction removes the section without a `schema_version` bump: a
    legacy document that still carries `failure_modes` no longer parses, so the
    store refuses to merge it rather than silently dropping the section (the
    migration note in `threat_model` records the decision)."""
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store)
    document = store.read_model(PROJECT, UNIT)
    document["failure_modes"] = _legacy_failure_modes()

    with pytest.raises(ValueError):
        UnitThreatModel.model_validate(document)

    # the loop link went with the section: a legacy loop carrying it is rejected
    document.pop("failure_modes")
    document["loops"][0]["failure_mode_refs"] = ["fm-1"]
    with pytest.raises(ValueError):
        UnitThreatModel.model_validate(document)


def test_an_unknown_schema_version_refuses_to_load_and_never_migrates(tmp_path):
    name = "Service-catalogue-and-discovery"
    unit_dir = tmp_path / PROJECT / "hunting" / "threat_modeller" / "produced" / name
    unit_dir.mkdir(parents=True)
    document = unit_dir / f"{name}.yaml"
    document.write_text(
        yaml.safe_dump({"schema_version": 2, "unit_id": UNIT, "state": "COMPLETED"}),
        encoding="utf-8",
    )
    before = document.read_bytes()
    store = ThreatModelStore(tmp_path)

    assert store.read_model(PROJECT, UNIT) is None
    with pytest.raises(ThreatModelSchemaVersionError):
        store.write_sections(
            PROJECT, UNIT, "UNIT_TECHNICAL_SHARP",
            {"technical_sharpening": _sharpening()}, run_id=RUN,
        )

    assert document.read_bytes() == before  # no silent migration


def test_a_persisted_document_with_an_unknown_state_is_a_coded_refusal(tmp_path):
    store = ThreatModelStore(tmp_path)
    name = "Service-catalogue-and-discovery"
    unit_dir = tmp_path / PROJECT / "hunting" / "threat_modeller" / "produced" / name
    unit_dir.mkdir(parents=True)
    (unit_dir / f"{name}.yaml").write_text(
        yaml.safe_dump({
            "schema_version": 1,
            "unit_id": UNIT,
            "unit_kind": "service",
            "run_id": RUN,
            "created_at": "2026-10-18T00:00:00Z",
            "updated_at": "2026-10-18T00:00:00Z",
            "state": "BOGUS",
        }),
        encoding="utf-8",
    )

    with pytest.raises(ThreatModelDocumentError):
        store.write_sections(
            PROJECT, UNIT, "UNIT_TECHNICAL_SHARP",
            {"technical_sharpening": _sharpening()}, run_id=RUN,
        )


# --- the COMPLETED write: loops, risk profile, validation --------------------

def test_completed_ranks_loops_emits_one_file_per_non_none_loop(tmp_path):
    store = ThreatModelStore(tmp_path)

    _write_to_completed(store, loops=[_loop("none"), _loop("high")])

    model = store.read_model(PROJECT, UNIT)
    assert model["state"] == "COMPLETED"
    assert [loop["id"] for loop in model["loops"]] == ["loop-1", "loop-2"]
    assert [loop["likelihood"] for loop in model["loops"]] == ["high", "none"]
    assert model["risk_profile"] == {
        "total": RISK_WEIGHTS["high"],
        "breakdown": {"none": 1, "low": 0, "medium": 0, "high": 1, "critical": 0},
        "impact_breakdown": {
            "none": 0, "low": 2, "medium": 0, "high": 0, "critical": 0,
        },
    }
    assert model["validation"]["valid"] is True
    assert model["validation"]["missing"] == []
    assert model["validation"]["unclosed"] == []
    assert model["validation"]["referential_errors"] == []

    unit_name = "Service-catalogue-and-discovery"
    produced = tmp_path / PROJECT / "hunting" / "threat_modeller" / "produced" / unit_name
    assert sorted(p.name for p in produced.glob("loop-*.yaml")) == ["loop-1.yaml"]
    records = store.read_loop_files(PROJECT, UNIT)
    assert [record["loop_id"] for record in records] == ["loop-1"]
    record = records[0]
    assert record["unit_id"] == UNIT
    assert record["unit_kind"] == "service"
    assert record["run_id"] == RUN
    assert record["dispatch_id"] == "Service-catalogue-and-discovery__loop-1"
    assert record["likelihood"] == "high"
    assert record["loop"]["id"] == "loop-1"
    assert record["loop"]["fault_ref"] == "fault-1"
    assert record["created_at"]


def test_a_zero_loop_model_emits_no_loop_files(tmp_path):
    store = ThreatModelStore(tmp_path)

    _write_zero_loop_completed(store)

    model = store.read_model(PROJECT, UNIT)
    assert model["loops"] == []
    assert model["risk_profile"] == {
        "total": 0,
        "breakdown": {"none": 0, "low": 0, "medium": 0, "high": 0, "critical": 0},
        "impact_breakdown": {
            "none": 0, "low": 0, "medium": 0, "high": 0, "critical": 0,
        },
    }
    assert model["validation"]["valid"] is True
    assert store.read_loop_files(PROJECT, UNIT) == []


# --- the commit protocol (S2 4.3) --------------------------------------------

def test_a_failing_model_write_after_the_loop_files_leaves_the_previous_state(
    tmp_path, monkeypatch
):
    store = ThreatModelStore(tmp_path)
    for state, sections in _sections_below_completed():
        store.write_sections(PROJECT, UNIT, state, sections, run_id=RUN)
    unit_name = "Service-catalogue-and-discovery"
    produced = tmp_path / PROJECT / "hunting" / "threat_modeller" / "produced" / unit_name

    def _fail_the_model_write(path, body):
        if path.name == f"{unit_name}.yaml":
            raise OSError("simulated crash between the loop files and the commit")
        return _dump_yaml(path, body)

    monkeypatch.setattr(store, "_dump_yaml_atomic", _fail_the_model_write)

    with pytest.raises(OSError):
        store.write_sections(PROJECT, UNIT, "COMPLETED", _completed_sections(), run_id=RUN)

    # the loop files landed (the crash window), the model did not commit
    assert (produced / "loop-1.yaml").exists()
    model = store.read_model(PROJECT, UNIT)
    assert model["state"] == "VULNERABILITIES_WRITTEN"
    assert model["loops"] == []
    assert model["risk_profile"] is None
    assert model["validation"] is None


def test_read_loop_files_is_empty_for_a_model_below_completed(tmp_path, monkeypatch):
    # S2 4.3: a loop file is never read for a model whose state is not
    # COMPLETED - the crash window leaves files on disk that must not surface
    # as dispatch work
    store = ThreatModelStore(tmp_path)
    for state, sections in _sections_below_completed():
        store.write_sections(PROJECT, UNIT, state, sections, run_id=RUN)
    unit_name = "Service-catalogue-and-discovery"
    produced = (
        tmp_path / PROJECT / "hunting" / "threat_modeller" / "produced" / unit_name
    )

    def _fail_the_model_write(path, body):
        if path.name == f"{unit_name}.yaml":
            raise OSError("simulated crash between the loop files and the commit")
        return _dump_yaml(path, body)

    monkeypatch.setattr(store, "_dump_yaml_atomic", _fail_the_model_write)
    with pytest.raises(OSError):
        store.write_sections(PROJECT, UNIT, "COMPLETED", _completed_sections(), run_id=RUN)

    assert (produced / "loop-1.yaml").exists()
    assert store.read_loop_files(PROJECT, UNIT) == []


def test_read_loop_files_is_empty_for_an_invalid_completed_model(tmp_path):
    store = ThreatModelStore(tmp_path)
    store.write_sections(
        PROJECT, UNIT, "UNIT_TECHNICAL_SHARP",
        {"technical_sharpening": _sharpening()}, run_id=RUN,
    )
    store.write_sections(
        PROJECT, UNIT, "TRUST_ASSUMPTIONS_WRITTEN",
        {"assumptions": [{**_assumptions()[0], "boundary_ref": ""}]}, run_id=RUN,
    )
    store.write_sections(
        PROJECT, UNIT, "VULNERABILITIES_WRITTEN",
        {"vulnerabilities": _vulnerabilities()}, run_id=RUN,
    )
    store.write_sections(PROJECT, UNIT, "COMPLETED", _completed_sections(), run_id=RUN)

    produced = (
        tmp_path / PROJECT / "hunting" / "threat_modeller" / "produced"
        / "Service-catalogue-and-discovery"
    )
    assert (produced / "loop-1.yaml").exists()  # emitted, but never read
    assert store.read_model(PROJECT, UNIT)["validation"]["valid"] is False
    assert store.read_loop_files(PROJECT, UNIT) == []


def test_a_lower_gate_write_deletes_the_orphan_loop_files(tmp_path, monkeypatch):
    store = ThreatModelStore(tmp_path)
    for state, sections in _sections_below_completed():
        store.write_sections(PROJECT, UNIT, state, sections, run_id=RUN)
    unit_name = "Service-catalogue-and-discovery"
    produced = tmp_path / PROJECT / "hunting" / "threat_modeller" / "produced" / unit_name

    def _fail_the_model_write(path, body):
        if path.name == f"{unit_name}.yaml":
            raise OSError("simulated crash between the loop files and the commit")
        return _dump_yaml(path, body)

    monkeypatch.setattr(store, "_dump_yaml_atomic", _fail_the_model_write)
    with pytest.raises(OSError):
        store.write_sections(PROJECT, UNIT, "COMPLETED", _completed_sections(), run_id=RUN)
    monkeypatch.undo()
    assert (produced / "loop-1.yaml").exists()

    store.write_sections(
        PROJECT, UNIT, "TRUST_MODELLED", {"trust_model": _trust_model()}, run_id=RUN,
    )

    assert list(produced.glob("loop-*.yaml")) == []
    model = store.read_model(PROJECT, UNIT)
    assert model["state"] == "VULNERABILITIES_WRITTEN"
    assert model["loops"] == []


# --- the completion checker (S2 5.7) -----------------------------------------

def test_completion_reports_missing_necessary_attributes(tmp_path):
    store = ThreatModelStore(tmp_path)
    store.write_sections(
        PROJECT, UNIT, "UNIT_TECHNICAL_SHARP",
        {"technical_sharpening": _sharpening()}, run_id=RUN,
    )
    # the TRUST_MODELLED gate is skipped: the section stays missing
    store.write_sections(
        PROJECT, UNIT, "TRUST_ASSUMPTIONS_WRITTEN",
        {"assumptions": [{**_assumptions()[0], "boundary_ref": ""}]}, run_id=RUN,
    )
    store.write_sections(
        PROJECT, UNIT, "VULNERABILITIES_WRITTEN",
        {"vulnerabilities": _vulnerabilities()}, run_id=RUN,
    )

    store.write_sections(PROJECT, UNIT, "COMPLETED", _completed_sections(), run_id=RUN)

    validation = store.read_model(PROJECT, UNIT)["validation"]
    assert validation["valid"] is False
    assert "trust_model.trust_agreements" in validation["missing"]
    assert "trust_model.dynamic_state_trust.states" in validation["missing"]
    assert validation["unclosed"] == []
    assert validation["referential_errors"] == []


def test_write_sections_accepts_typed_section_objects(tmp_path):
    # T2 may bind either plain payloads or the schema's typed section objects
    from polymerhus.attack.hunting.threat_model import (
        Loop,
        TechnicalSharpening,
        TrustModel,
    )

    store = ThreatModelStore(tmp_path)
    store.write_sections(
        PROJECT, UNIT, "UNIT_TECHNICAL_SHARP",
        {"technical_sharpening": TechnicalSharpening.model_validate(_sharpening())},
        run_id=RUN,
    )
    store.write_sections(
        PROJECT, UNIT, "TRUST_MODELLED",
        {"trust_model": TrustModel.model_validate(_trust_model())},
        run_id=RUN,
    )
    store.write_sections(
        PROJECT, UNIT, "TRUST_ASSUMPTIONS_WRITTEN",
        {"assumptions": _assumptions()}, run_id=RUN,
    )
    store.write_sections(
        PROJECT, UNIT, "VULNERABILITIES_WRITTEN",
        {"vulnerabilities": _vulnerabilities()}, run_id=RUN,
    )

    store.write_sections(
        PROJECT, UNIT, "COMPLETED",
        {"loops": [Loop.model_validate(_loop("high"))]},
        run_id=RUN,
    )

    model = store.read_model(PROJECT, UNIT)
    assert model["technical_sharpening"]["interface_agreements"][0]["id"] == "ia-1"
    assert model["trust_model"]["trust_agreements"][0]["id"] == "ta-1"
    assert model["validation"]["valid"] is True
    assert [loop["id"] for loop in model["loops"]] == ["loop-1"]


def test_completion_reports_referential_errors(tmp_path):
    store = ThreatModelStore(tmp_path)
    for state, sections in _sections_below_completed()[:-1]:
        store.write_sections(PROJECT, UNIT, state, sections, run_id=RUN)
    vulnerabilities = _vulnerabilities()
    vulnerabilities[0]["fault_ref"] = "fault-missing"
    store.write_sections(
        PROJECT, UNIT, "VULNERABILITIES_WRITTEN",
        {"vulnerabilities": vulnerabilities}, run_id=RUN,
    )

    store.write_sections(PROJECT, UNIT, "COMPLETED", _completed_sections(), run_id=RUN)

    validation = store.read_model(PROJECT, UNIT)["validation"]
    assert validation["valid"] is False
    assert "vulnerability:v-1.fault_ref='fault-missing'" in validation["referential_errors"]


def test_completion_reports_an_unresolved_violation_transition_ref(tmp_path):
    """S2 5.1/S3 8.2: a non-null `Violation.transition_ref` must resolve to a
    dynamic-state transition; the checker reports the broken link. The same
    fixture with the valid `tr-1` ref validates (asserted by the ladder test)."""
    store = ThreatModelStore(tmp_path)
    store.write_sections(
        PROJECT, UNIT, "UNIT_TECHNICAL_SHARP",
        {"technical_sharpening": _sharpening()}, run_id=RUN,
    )
    trust = _trust_model()
    trust["dynamic_state_trust"]["violations"][0]["transition_ref"] = "tr-missing"
    store.write_sections(
        PROJECT, UNIT, "TRUST_MODELLED", {"trust_model": trust}, run_id=RUN)
    store.write_sections(
        PROJECT, UNIT, "TRUST_ASSUMPTIONS_WRITTEN",
        {"assumptions": _assumptions()}, run_id=RUN)
    store.write_sections(
        PROJECT, UNIT, "VULNERABILITIES_WRITTEN",
        {"vulnerabilities": _vulnerabilities()}, run_id=RUN)
    store.write_sections(
        PROJECT, UNIT, "COMPLETED", _completed_sections(), run_id=RUN)

    validation = store.read_model(PROJECT, UNIT)["validation"]
    assert validation["valid"] is False
    assert "violation:vi-1.transition_ref='tr-missing'" in \
        validation["referential_errors"]


def test_completion_reports_an_unclosed_assumption(tmp_path):
    store = ThreatModelStore(tmp_path)
    extra_assumption = {
        **_assumptions()[0],
        "id": "as-2",
        "fault": {
            "id": "fault-2",
            "label": "an unmodelled fault",
            "description": "No vulnerability closes this fault.",
        },
    }
    for state, sections in _sections_below_completed()[:-1]:
        store.write_sections(PROJECT, UNIT, state, sections, run_id=RUN)
    store.write_sections(
        PROJECT, UNIT, "TRUST_ASSUMPTIONS_WRITTEN",
        {"assumptions": [*_assumptions(), extra_assumption]}, run_id=RUN,
    )
    store.write_sections(
        PROJECT, UNIT, "VULNERABILITIES_WRITTEN",
        {"vulnerabilities": _vulnerabilities()}, run_id=RUN,
    )

    store.write_sections(PROJECT, UNIT, "COMPLETED", _completed_sections(), run_id=RUN)

    validation = store.read_model(PROJECT, UNIT)["validation"]
    assert validation["valid"] is False
    assert "assumption:as-2" in validation["unclosed"]
    assert validation["referential_errors"] == []
    assert validation["missing"] == []


def test_check_completion_recomputes_the_risk_profile(tmp_path):
    # the stored profile is never trusted: the checker recomputes it from the
    # stored loops (the regression check against a store bug, S2 5.7)
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store)
    document = store.read_model(PROJECT, UNIT)
    document["risk_profile"]["total"] = 99
    document["risk_profile"]["breakdown"]["high"] = 0
    document["risk_profile"]["breakdown"]["low"] = 1

    validation = check_completion(UnitThreatModel.model_validate(document))

    assert validation.valid is False
    assert "risk_profile.total" in validation.missing
    assert "risk_profile.breakdown" in validation.missing


def test_the_store_records_the_non_suite_class_finding(tmp_path):
    store = ThreatModelStore(tmp_path, class_names={"idor"})
    sections = _sections_below_completed()
    for state, payload in sections:
        if state == "VULNERABILITIES_WRITTEN":
            payload = {"vulnerabilities": [{
                **_vulnerabilities()[0],
                "web_vulnerability_class": "made-up-class",
            }]}
        store.write_sections(PROJECT, UNIT, state, payload, run_id=RUN)
    loops = [{**_loop("high"), "web_vulnerability_class": "made-up-class"}]
    store.write_sections(
        PROJECT, UNIT, "COMPLETED", _completed_sections(loops), run_id=RUN)

    validation = store.read_model(PROJECT, UNIT)["validation"]

    assert validation["valid"] is True
    assert any("not in the suite" in finding
               for finding in validation["class_findings"])


def test_the_modeller_surface_wires_the_suite_class_index(tmp_path):
    from polymerhus.attack.hunting.threat_modeller_tools import (
        ModellerTools,
        build_modeller_tool_surface,
    )

    store = ThreatModelStore(tmp_path)
    tools = ModellerTools(
        threat_store=store, project_id=PROJECT, run_id=RUN,
        suite_classes=("idor",))
    build_modeller_tool_surface(PROJECT, UNIT, tools)

    for state, payload in _sections_below_completed():
        if state == "VULNERABILITIES_WRITTEN":
            payload = {"vulnerabilities": [{
                **_vulnerabilities()[0],
                "web_vulnerability_class": "made-up-class",
            }]}
        store.write_sections(PROJECT, UNIT, state, payload, run_id=RUN)
    loops = [{**_loop("high"), "web_vulnerability_class": "made-up-class"}]
    store.write_sections(
        PROJECT, UNIT, "COMPLETED", _completed_sections(loops), run_id=RUN)

    validation = store.read_model(PROJECT, UNIT)["validation"]

    assert any("not in the suite" in finding
               for finding in validation["class_findings"])


def test_the_completion_records_a_technique_family_as_a_class_finding(tmp_path):
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store)
    document = store.read_model(PROJECT, UNIT)
    for target in (document["vulnerabilities"][0], document["loops"][0]):
        target["web_vulnerability_class"] = "defence-bypass"

    validation = check_completion(
        UnitThreatModel.model_validate(document),
        class_names={"defence-bypass", "idor"},
    )

    assert validation.valid is True
    assert any("technique family" in finding
               for finding in validation.class_findings)


def test_the_completion_records_a_non_suite_class_finding(tmp_path):
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store)
    document = store.read_model(PROJECT, UNIT)
    for target in (document["vulnerabilities"][0], document["loops"][0]):
        target["web_vulnerability_class"] = "made-up-class"

    validation = check_completion(
        UnitThreatModel.model_validate(document), class_names={"idor"})

    assert validation.valid is True
    assert any("not in the suite" in finding
               for finding in validation.class_findings)


def test_the_completion_records_an_empty_class_finding(tmp_path):
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store)
    document = store.read_model(PROJECT, UNIT)
    for target in (document["vulnerabilities"][0], document["loops"][0]):
        target["web_vulnerability_class"] = ""

    validation = check_completion(UnitThreatModel.model_validate(document))

    assert validation.valid is True
    assert any("=empty" in finding for finding in validation.class_findings)


def test_check_completion_recomputes_the_impact_breakdown(tmp_path):
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store)
    document = store.read_model(PROJECT, UNIT)
    document["risk_profile"]["impact_breakdown"]["low"] = 9

    validation = check_completion(UnitThreatModel.model_validate(document))

    assert validation.valid is False
    assert "risk_profile.impact_breakdown" in validation.missing


def test_check_completion_reports_a_tampered_loop_risk(tmp_path):
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store)
    document = store.read_model(PROJECT, UNIT)
    document["loops"][0]["impact_weight"] = 0
    document["loops"][0]["risk"] = 0

    validation = check_completion(UnitThreatModel.model_validate(document))

    assert validation.valid is False
    assert "loop:loop-1.impact_weight" in validation.missing
    assert "loop:loop-1.risk" in validation.missing


def test_check_completion_reports_a_missing_end_impact(tmp_path):
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store)
    document = store.read_model(PROJECT, UNIT)
    document["loops"][0]["impact"]["end_impact"] = ""

    validation = check_completion(UnitThreatModel.model_validate(document))

    assert validation.valid is False
    assert "loop:loop-1.impact" in validation.missing


def test_a_legacy_loop_without_impact_parses_and_contributes_zero(tmp_path):
    store = ThreatModelStore(tmp_path)
    legacy = dict(_loop("high"))
    legacy.pop("impact")

    _write_to_completed(store, loops=[legacy])

    model = store.read_model(PROJECT, UNIT)
    assert model["risk_profile"]["total"] == 0
    assert model["risk_profile"]["impact_breakdown"]["none"] == 1
    assert "loop:loop-1.impact" in model["validation"]["missing"]


def test_a_zero_risk_loop_is_stored_but_emits_no_loop_file(tmp_path):
    """The impact axis can zero a high-likelihood direction. The loop stays in
    the model and the risk profile, but it is never dispatched."""
    store = ThreatModelStore(tmp_path)
    zero = {**_loop("high"), "impact": {
        "confidentiality": "none", "integrity": "none", "availability": "none",
        "end_impact": "no end impact",
    }}

    _write_to_completed(store, loops=[zero])

    model = store.read_model(PROJECT, UNIT)
    assert model["loops"][0]["risk"] == 0
    assert model["risk_profile"]["total"] == 0
    assert store.read_loop_files(PROJECT, UNIT) == []


def test_the_loop_file_carries_the_impact_and_the_risk(tmp_path):
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store, loops=[_loop("high")])

    record = store.read_loop_files(PROJECT, UNIT)[0]

    assert record["loop"]["impact"] == {
        "confidentiality": "low",
        "integrity": "none",
        "availability": "none",
        "end_impact": "A caller reads another tenant's item.",
    }
    assert record["loop"]["impact_weight"] == 1
    assert record["loop"]["risk"] == 3


def test_check_completion_reports_a_broken_loop_order_and_ids(tmp_path):
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store, loops=[_loop("high"), _loop("medium")])
    document = store.read_model(PROJECT, UNIT)

    document["loops"].reverse()
    document["loops"][0]["id"] = "loop-1"
    document["loops"][1]["id"] = "loop-2"
    validation = check_completion(UnitThreatModel.model_validate(document))
    assert "loops.order" in validation.missing

    document["loops"][1]["id"] = "loop-7"
    validation = check_completion(UnitThreatModel.model_validate(document))
    assert "loops.ids" in validation.missing


def test_completion_reports_the_trust_model_referential_rules(tmp_path):
    store = ThreatModelStore(tmp_path)
    for state, sections in _sections_below_completed()[:-1]:
        store.write_sections(PROJECT, UNIT, state, sections, run_id=RUN)
    trust_model = _trust_model()
    trust_model["trust_agreements"][0]["interface_agreement_refs"] = ["ia-missing"]
    trust_model["dynamic_state_trust"]["transitions"][0]["target"] = "ds-missing"
    trust_model["dynamic_state_trust"]["violations"][0]["maps_to_fault"] = "fault-missing"
    store.write_sections(
        PROJECT, UNIT, "TRUST_MODELLED", {"trust_model": trust_model}, run_id=RUN,
    )
    store.write_sections(
        PROJECT, UNIT, "TRUST_ASSUMPTIONS_WRITTEN",
        {"assumptions": [{**_assumptions()[0], "boundary_ref": "ta-missing"}]}, run_id=RUN,
    )
    store.write_sections(
        PROJECT, UNIT, "VULNERABILITIES_WRITTEN",
        {"vulnerabilities": _vulnerabilities()}, run_id=RUN,
    )

    store.write_sections(PROJECT, UNIT, "COMPLETED", _completed_sections(), run_id=RUN)

    errors = store.read_model(PROJECT, UNIT)["validation"]["referential_errors"]
    assert "trust_agreement:ta-1.interface_agreement_refs='ia-missing'" in errors
    assert "transition:tr-1.state_ref='ds-missing'" in errors
    assert "violation:vi-1.maps_to_fault='fault-missing'" in errors
    assert "assumption:as-1.boundary_ref='ta-missing'" in errors


def test_completed_keeps_the_write_order_on_a_likelihood_tie(tmp_path):
    store = ThreatModelStore(tmp_path)
    loops = [
        {**_loop("medium"), "likelihood_rationale": "first medium"},
        {**_loop("critical"), "likelihood_rationale": "the critical one"},
        {**_loop("medium"), "likelihood_rationale": "second medium"},
    ]

    _write_to_completed(store, loops=loops)

    model = store.read_model(PROJECT, UNIT)
    assert [(loop["id"], loop["likelihood"]) for loop in model["loops"]] == [
        ("loop-1", "critical"), ("loop-2", "medium"), ("loop-3", "medium"),
    ]
    assert [loop["likelihood_rationale"] for loop in model["loops"]] == [
        "the critical one", "first medium", "second medium",
    ]
    assert model["risk_profile"]["total"] == (
        RISK_WEIGHTS["critical"] + RISK_WEIGHTS["medium"] * 2
    )
    assert [record["loop_id"] for record in store.read_loop_files(PROJECT, UNIT)] == [
        "loop-1", "loop-2", "loop-3",
    ]


# --- consumption (the mover primitives, S2 8.4) ------------------------------

def _threat_modeller_root(tmp_path):
    return tmp_path / PROJECT / "hunting" / "threat_modeller"


def test_the_model_document_moves_with_its_last_loop_file(tmp_path):
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store, loops=[_loop("high"), _loop("medium")])
    unit_name = "Service-catalogue-and-discovery"

    assert store.consume_model_if_done(PROJECT, UNIT) is False  # loops remain
    assert store.consume_loop(PROJECT, UNIT, "loop-1") is True
    assert store.read_model(PROJECT, UNIT)["state"] == "COMPLETED"
    assert store.consume_loop(PROJECT, UNIT, "loop-1") is True  # at-least-once no-op
    assert store.consume_loop(PROJECT, UNIT, "loop-2") is True

    root = _threat_modeller_root(tmp_path)
    assert not (root / "produced" / unit_name).exists()
    assert (root / "consumed" / unit_name / f"{unit_name}.yaml").exists()
    assert store.read_completed_units(PROJECT) == [UNIT]
    assert store.read_model(PROJECT, UNIT)["state"] == "COMPLETED"


def test_a_zero_loop_completed_model_is_consumed_without_a_dispatch(tmp_path):
    store = ThreatModelStore(tmp_path)
    _write_zero_loop_completed(store)

    assert store.consume_model_if_done(PROJECT, UNIT) is True
    assert store.consume_model_if_done(PROJECT, UNIT) is True  # at-least-once

    assert store.read_completed_units(PROJECT) == [UNIT]
    assert store.read_loop_files(PROJECT, UNIT) == []
    unit_name = "Service-catalogue-and-discovery"
    root = _threat_modeller_root(tmp_path)
    assert not (root / "produced" / unit_name).exists()
    assert (root / "consumed" / unit_name / f"{unit_name}.yaml").exists()


def test_read_produced_loops_returns_the_unit_and_its_produced_loop_files(tmp_path):
    """S2 8.1/8.4 (T4, #377): the mover's dispatch inbox read - one entry per
    produced, consumable unit carrying the derived on-disk identity and the
    loop file records VERBATIM (an unreadable record is the mover's to refuse,
    never the store's to hide)."""
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store, loops=[_loop("high"), _loop("low")])
    unit_name = "Service-catalogue-and-discovery"

    entries = store.read_produced_loops(PROJECT)

    assert [(e["unit_id"], e["unit_name"], e["run_id"]) for e in entries] == [
        (UNIT, unit_name, RUN),
    ]
    assert [loop["loop_id"] for loop in entries[0]["loops"]] == ["loop-1", "loop-2"]
    record = entries[0]["loops"][0]["record"]
    assert record["dispatch_id"] == f"{unit_name}__loop-1"
    assert record["likelihood"] == "high"
    assert record["loop"]["id"] == "loop-1"


def test_read_produced_loops_is_empty_for_a_consumed_or_unconsumable_model(tmp_path):
    """The mover's inbox is the PRODUCED family only: a consumed (decided) unit
    is not dispatched again, and a model below COMPLETED (or invalid) is never
    dispatch input (S2 4.3, 5.7)."""
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store)
    store.consume_loop(PROJECT, UNIT, "loop-1")
    assert store.read_produced_loops(PROJECT) == []

    other = ThreatModelStore(tmp_path)
    other.write_sections(
        PROJECT, "Service:other", "UNIT_TECHNICAL_SHARP",
        {"technical_sharpening": _sharpening()}, run_id=RUN,
    )
    assert other.read_produced_loops(PROJECT) == []


def test_read_consumed_loops_reports_the_consumed_unit_and_its_model(tmp_path):
    """F-022: the recovery read is the SAME entry shape as the produced read,
    over the consumed family. The model document is the consumed one - the
    model moved with its last loop file - so a recovery dispatch never needs a
    re-model."""
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store, loops=[_loop("high")])
    assert store.consume_loop(PROJECT, UNIT, "loop-1") is True

    entries = store.read_consumed_loops(PROJECT)

    assert [(e["unit_id"], e["unit_name"], e["run_id"]) for e in entries] == [
        (UNIT, "Service-catalogue-and-discovery", RUN),
    ]
    assert [loop["loop_id"] for loop in entries[0]["loops"]] == ["loop-1"]
    assert entries[0]["loops"][0]["record"]["loop_id"] == "loop-1"
    assert entries[0]["model"]["unit_id"] == UNIT
    assert store.read_produced_loops(PROJECT) == []


def test_read_consumed_loops_falls_back_to_the_produced_model_for_a_multi_loop_unit(
        tmp_path):
    """F-022 model dependency: the model moves with the unit's LAST loop file.
    A consumed loop from a multi-loop unit therefore finds its original model
    still in produced/; the recovery read falls back to it and never re-models.
    Consuming the last loop moves the model, and both reads still agree."""
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store, loops=[_loop("high"), _loop("low")])
    assert store.consume_loop(PROJECT, UNIT, "loop-1") is True

    entries = store.read_consumed_loops(PROJECT)

    assert [loop["loop_id"] for loop in entries[0]["loops"]] == ["loop-1"]
    assert entries[0]["model"]["unit_id"] == UNIT
    assert [loop["loop_id"] for loop in
            store.read_produced_loops(PROJECT)[0]["loops"]] == ["loop-2"]

    assert store.consume_loop(PROJECT, UNIT, "loop-2") is True
    assert store.read_produced_loops(PROJECT) == []
    entries = store.read_consumed_loops(PROJECT)
    assert [loop["loop_id"] for loop in entries[0]["loops"]] == [
        "loop-1", "loop-2"]
    assert entries[0]["model"]["unit_id"] == UNIT


def test_read_produced_loops_reports_a_zero_loop_produced_model(tmp_path):
    """S2 8.4: a zero-loop produced COMPLETED valid model IS the mover's input -
    it carries no loop file, so the entry proves the model is consumable, and
    the mover consumes it without a dispatch."""
    store = ThreatModelStore(tmp_path)
    _write_zero_loop_completed(store)

    entries = store.read_produced_loops(PROJECT)

    assert len(entries) == 1
    assert entries[0]["unit_id"] == UNIT
    assert entries[0]["loops"] == []


def test_read_produced_loops_does_not_read_an_abandoned_unit(tmp_path):
    """S2 4.2/8.4: the mover ignores abandoned/ - a degraded unit's loop files
    are never dispatched (the archive moved them out of produced/)."""
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store)
    store.archive_unit(PROJECT, UNIT, "degraded (fixture)")

    assert store.read_produced_loops(PROJECT) == []


def test_read_produced_loops_reports_a_malformed_loop_file_instead_of_dropping_it(
        tmp_path):
    """S2 10.5 (T4a review F1): an unreadable or non-mapping loop file is
    REPORTED, never silently dropped - a dropped file would read as "the unit has
    no loops", the mover would try to consume the model, and the store would
    refuse because a `loop-*.yaml` remains: the run then never quiesces."""
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store, loops=[_loop("high")])
    unit_name = "Service-catalogue-and-discovery"
    produced = (_threat_modeller_root(tmp_path) / "produced" / unit_name)
    (produced / "loop-2.yaml").write_text("{[ unparseable", encoding="utf-8")
    (produced / "loop-3.yaml").write_text("- just\n- a\n- list\n", encoding="utf-8")

    entry = store.read_produced_loops(PROJECT)[0]

    assert [loop["loop_id"] for loop in entry["loops"]] == ["loop-1"]
    assert [broken["loop_id"] for broken in entry["malformed_loops"]] \
        == ["loop-2", "loop-3"]
    assert all(broken["reason"] for broken in entry["malformed_loops"])


def test_consume_model_if_done_ignores_the_refused_loop_files(tmp_path):
    """S2 10.5/8.4: the model-consume gate counts only PENDING loop files - a
    loop file the mover refused (a malformed body) can never dispatch or be
    consumed as a loop record, so it must not hold the model document."""
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store, loops=[_loop("high")])
    unit_name = "Service-catalogue-and-discovery"
    produced = (_threat_modeller_root(tmp_path) / "produced" / unit_name)
    (produced / "loop-2.yaml").write_text("{[ unparseable", encoding="utf-8")

    # a pending loop file still holds the model; a refused one does not
    assert store.consume_model_if_done(PROJECT, UNIT) is False
    assert store.consume_model_if_done(
        PROJECT, UNIT, refused_loops=("loop-1", "loop-2")) is True
    assert store.read_completed_units(PROJECT) == [UNIT]


def test_read_produced_units_reports_each_produced_model_and_its_run(tmp_path):
    """S2 9.3: the intake freeze reads the produced family itself - the unit id,
    the producing run, and the persisted state - so it can tell an in-flight
    model from a stale one."""
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store, loops=[_loop("high")])
    store.write_sections(
        PROJECT, "Service:other", "UNIT_TECHNICAL_SHARP",
        {"technical_sharpening": _sharpening()}, run_id="run-2",
    )

    assert store.read_produced_units(PROJECT) == [
        {"unit_id": UNIT, "run_id": RUN, "state": "COMPLETED"},
        {"unit_id": "Service:other", "run_id": "run-2",
         "state": "UNIT_TECHNICAL_SHARP"},
    ]


def test_a_write_after_the_move_is_a_noop_returning_the_consumed_path(tmp_path):
    store = ThreatModelStore(tmp_path)
    _write_zero_loop_completed(store)
    assert store.consume_model_if_done(PROJECT, UNIT) is True
    unit_name = "Service-catalogue-and-discovery"
    root = _threat_modeller_root(tmp_path)
    consumed = root / "consumed" / unit_name / f"{unit_name}.yaml"
    before = consumed.read_bytes()

    returned = store.write_sections(
        PROJECT, UNIT, "TRUST_MODELLED", {"trust_model": _trust_model()}, run_id=RUN,
    )

    assert returned == consumed
    assert not (root / "produced" / unit_name).exists()
    assert consumed.read_bytes() == before


# --- the invalid / degraded archive (S2 5.7, 7.7) -----------------------------

def test_an_invalid_completed_model_is_not_consumable_and_is_archived(tmp_path):
    store = ThreatModelStore(tmp_path)
    # the TRUST_MODELLED gate is skipped: the checker marks the model invalid
    store.write_sections(
        PROJECT, UNIT, "UNIT_TECHNICAL_SHARP",
        {"technical_sharpening": _sharpening()}, run_id=RUN,
    )
    store.write_sections(
        PROJECT, UNIT, "TRUST_ASSUMPTIONS_WRITTEN",
        {"assumptions": [{**_assumptions()[0], "boundary_ref": ""}]}, run_id=RUN,
    )
    store.write_sections(
        PROJECT, UNIT, "VULNERABILITIES_WRITTEN",
        {"vulnerabilities": _vulnerabilities()}, run_id=RUN,
    )
    store.write_sections(PROJECT, UNIT, "COMPLETED", _completed_sections(), run_id=RUN)

    assert store.consume_model_if_done(PROJECT, UNIT) is False
    assert store.read_completed_units(PROJECT) == []

    archived = store.archive_unit(PROJECT, UNIT, "completion validation failed")

    unit_name = "Service-catalogue-and-discovery"
    root = _threat_modeller_root(tmp_path)
    assert archived == root / "abandoned" / unit_name
    assert not (root / "produced" / unit_name).exists()
    assert (archived / f"{unit_name}.yaml").exists()
    assert (archived / "loop-1.yaml").exists()  # the emitted loops move with it
    assert store.read_abandoned_units(PROJECT) == [UNIT]
    document = yaml.safe_load((archived / f"{unit_name}.yaml").read_text(encoding="utf-8"))
    assert document["validation"]["valid"] is False
    assert "trust_model.trust_agreements" in document["validation"]["missing"]


def test_archive_unit_moves_a_degraded_partial_model(tmp_path):
    store = ThreatModelStore(tmp_path)
    store.write_sections(
        PROJECT, UNIT, "UNIT_TECHNICAL_SHARP",
        {"technical_sharpening": _sharpening()}, run_id=RUN,
    )

    archived = store.archive_unit(PROJECT, UNIT, "live target unreachable")

    unit_name = "Service-catalogue-and-discovery"
    assert (archived / f"{unit_name}.yaml").exists()
    assert store.read_model(PROJECT, UNIT) is None
    assert store.read_abandoned_units(PROJECT) == [UNIT]


def test_archive_returns_none_when_there_is_nothing_to_archive(tmp_path):
    store = ThreatModelStore(tmp_path)

    assert store.archive_unit(PROJECT, UNIT, "no model was ever written") is None

    _write_to_completed(store)
    assert store.consume_loop(PROJECT, UNIT, "loop-1") is True
    assert store.read_completed_units(PROJECT) == [UNIT]
    assert store.archive_unit(PROJECT, UNIT, "already decided") is None


# --- the collision-safe unit name (S2 4.2) ------------------------------------

def test_an_empty_produced_unit_directory_is_reused(tmp_path):
    # a crash between the atomic write's parent mkdir and its os.replace
    # leaves an empty unit directory; the identity is unknown, so the store
    # must reuse the plain name rather than invent a suffixed sibling
    store = ThreatModelStore(tmp_path)
    root = _threat_modeller_root(tmp_path)
    unit_dir = root / "produced" / "Service-catalogue-and-discovery"
    unit_dir.mkdir(parents=True)

    store.write_sections(
        PROJECT, UNIT, "UNIT_TECHNICAL_SHARP",
        {"technical_sharpening": _sharpening()}, run_id=RUN,
    )

    assert sorted(directory.name for directory in (root / "produced").iterdir()) == [
        "Service-catalogue-and-discovery",
    ]
    assert (unit_dir / "Service-catalogue-and-discovery.yaml").exists()
    assert store.read_model(PROJECT, UNIT)["unit_id"] == UNIT


def test_a_corrupt_model_document_refuses_instead_of_suffixing(tmp_path):
    # a truncated model file leaves an unknown identity at the derived name;
    # the suffix is only for a readable DIFFERENT unit id, so the write must
    # refuse with a coded error, never create a second directory
    store = ThreatModelStore(tmp_path)
    root = _threat_modeller_root(tmp_path)
    unit_dir = root / "produced" / "Service-catalogue-and-discovery"
    unit_dir.mkdir(parents=True)
    (unit_dir / "Service-catalogue-and-discovery.yaml").write_text(
        "unit_id: [not: a mapping", encoding="utf-8",
    )

    with pytest.raises(ThreatModelDirectoryError):
        store.write_sections(
            PROJECT, UNIT, "UNIT_TECHNICAL_SHARP",
            {"technical_sharpening": _sharpening()}, run_id=RUN,
        )

    assert sorted(directory.name for directory in (root / "produced").iterdir()) == [
        "Service-catalogue-and-discovery",
    ]


def test_two_unit_ids_that_sanitise_alike_get_distinct_unit_directories(tmp_path):
    colliding_a = "Service:alpha/beta"
    colliding_b = "Service:alpha:beta"
    store = ThreatModelStore(tmp_path)

    store.write_sections(
        PROJECT, colliding_a, "UNIT_TECHNICAL_SHARP",
        {"technical_sharpening": _sharpening()}, run_id=RUN,
    )
    store.write_sections(
        PROJECT, colliding_b, "UNIT_TECHNICAL_SHARP",
        {"technical_sharpening": _sharpening()}, run_id=RUN,
    )

    root = _threat_modeller_root(tmp_path)
    plain = root / "produced" / "Service-alpha-beta"
    suffixed = root / "produced" / f"Service-alpha-beta-{collision_suffix(colliding_b)}"
    assert (plain / "Service-alpha-beta.yaml").exists()
    assert (suffixed / f"{suffixed.name}.yaml").exists()
    assert store.read_model(PROJECT, colliding_a)["unit_id"] == colliding_a
    assert store.read_model(PROJECT, colliding_b)["unit_id"] == colliding_b

    # a repeat write for the collided unit reuses its resolved directory
    store.write_sections(
        PROJECT, colliding_b, "TRUST_MODELLED", {"trust_model": _trust_model()}, run_id=RUN,
    )

    assert store.read_model(PROJECT, colliding_b)["trust_model"]["trust_agreements"][0]["id"] == "ta-1"
    assert sorted(directory.name for directory in (root / "produced").iterdir()) == [
        plain.name, suffixed.name,
    ]


# --- the bounded notes store (#341) ------------------------------------------

def test_notes_append_update_delete_round_trip(tmp_path):
    store = ThreatModelStore(tmp_path)

    key = store.write_note(
        PROJECT, UNIT, note_name="phase-1", kind="freeform",
        body="decision node: the lookup trusts the query id",
        evidence="GET /catalogue",
    )

    assert key == "Service-catalogue-and-discovery:phase-1"
    notes = store.read_notes(PROJECT, "Service-catalogue-and-discovery")
    assert [note["body"] for note in notes] == [
        "decision node: the lookup trusts the query id",
    ]
    assert notes[0]["kind"] == "freeform"

    assert store.write_note(
        PROJECT, UNIT, action="update", note_name="phase-1",
        kind="freeform", body="amended",
    ) == key
    assert store.read_notes(PROJECT, "Service-catalogue-and-discovery")[0]["body"] == "amended"

    assert store.write_note(
        PROJECT, UNIT, action="delete", note_name="phase-1",
        kind="freeform", body="",
    ) == key
    assert store.read_notes(PROJECT, "Service-catalogue-and-discovery") == []


def test_notes_are_bounded(tmp_path, monkeypatch):
    import polymerhus.attack.hunting.threat_model_store as store_module

    monkeypatch.setattr(store_module, "NOTES_MAX_RECORDS", 3)
    store = ThreatModelStore(tmp_path)
    for index in range(4):
        store.write_note(
            PROJECT, UNIT, note_name=f"phase-{index}", kind="freeform",
            body=f"body {index}",
        )

    notes = store.read_notes(PROJECT)

    assert [note["body"] for note in notes] == ["body 3", "body 2", "body 1"]


def test_the_note_kinds_match_the_patterns_single_source():
    # The store keeps its own copy of the note-kinds vocabulary (S2 10.1: a
    # store does not import another store's namespace), guarded against drift
    # from the pattern's single source. `phase_summary` is the hunter's kind
    # and is reserved for the hunter (S1 5.2), so it is never admitted here.
    from polymerhus.attack.hunting.hunt_store import ProjectMemoryStore
    from polymerhus.attack.hunting.threat_model_store import NOTE_KINDS

    assert NOTE_KINDS == ProjectMemoryStore.NOTE_KINDS
    assert "phase_summary" not in NOTE_KINDS


# --- the exported risk contract (for T3) and the read defaults ----------------

def test_the_risk_weights_and_default_threshold_are_exported(tmp_path):
    assert RISK_WEIGHTS == {
        "none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4,
    }
    assert DEFAULT_RISK_THRESHOLD == 250
    weights = [RISK_WEIGHTS[level] for level in ("none", "low", "medium", "high", "critical")]
    assert weights == sorted(weights)
    assert len(set(weights)) == len(weights)


def test_reads_of_an_unknown_unit_are_empty(tmp_path):
    store = ThreatModelStore(tmp_path)

    assert store.read_model(PROJECT, "Service:absent") is None
    assert store.read_section(PROJECT, "Service:absent", "loops") is None
    assert store.read_loop_files(PROJECT, "Service:absent") == []
    assert store.read_completed_units(PROJECT) == []
    assert store.read_abandoned_units(PROJECT) == []
    assert store.read_notes(PROJECT) == []
    assert store.consume_model_if_done(PROJECT, "Service:absent") is False
    assert store.consume_loop(PROJECT, "Service:absent", "loop-1") is False


def test_a_retried_completed_write_repairs_the_loop_set(tmp_path, monkeypatch):
    store = ThreatModelStore(tmp_path)
    for state, sections in _sections_below_completed():
        store.write_sections(PROJECT, UNIT, state, sections, run_id=RUN)
    unit_name = "Service-catalogue-and-discovery"

    def _fail_the_model_write(path, body):
        if path.name == f"{unit_name}.yaml":
            raise OSError("simulated crash between the loop files and the commit")
        return _dump_yaml(path, body)

    monkeypatch.setattr(store, "_dump_yaml_atomic", _fail_the_model_write)
    with pytest.raises(OSError):
        store.write_sections(PROJECT, UNIT, "COMPLETED", _completed_sections(), run_id=RUN)
    monkeypatch.undo()

    store.write_sections(PROJECT, UNIT, "COMPLETED", _completed_sections(), run_id=RUN)

    model = store.read_model(PROJECT, UNIT)
    assert model["state"] == "COMPLETED"
    assert model["validation"]["valid"] is True
    assert [loop["id"] for loop in model["loops"]] == ["loop-1"]
    assert [record["loop_id"] for record in store.read_loop_files(PROJECT, UNIT)] == ["loop-1"]


def test_a_late_lower_gate_write_on_a_completed_model_keeps_the_loop_files(tmp_path):
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store)
    unit_name = "Service-catalogue-and-discovery"
    root = _threat_modeller_root(tmp_path)
    loop_file = root / "produced" / unit_name / "loop-1.yaml"
    before = loop_file.read_bytes()

    store.write_sections(
        PROJECT, UNIT, "UNIT_TECHNICAL_SHARP",
        {"technical_sharpening": {**_sharpening(), "data_flows": []}}, run_id=RUN,
    )

    model = store.read_model(PROJECT, UNIT)
    assert model["state"] == "COMPLETED"  # the state never regresses
    assert model["technical_sharpening"]["data_flows"] == []  # content still merges
    assert loop_file.read_bytes() == before  # the committed loop set is untouched
