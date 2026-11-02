"""Unit tier: the unit threat model schema and the ThreatModelStore (T1, #374).

Pure filesystem mechanics and pure schema logic - no Neo4j, no LLM. Pins the
partial/complete document contract, the gate merge and monotonic state, the
seven-gate ladder, the completion checker (necessary attributes, referential
integrity, the assumption-to-threat closure, the impact-assessment invariants,
the threat order, the risk profile), the threat-file emission with its
denormalised impact block, the commit protocol, the mover primitives, the
move-aware write, the collision-safe unit name, the invalid-model archive, and
the bounded notes store.

Every test drives the real store on a temporary project root and asserts the
public store API or the persisted files, never a private method.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from polymerhus.attack.hunting.threat_model import (
    DEFAULT_RISK_THRESHOLD,
    GATE_SECTIONS,
    ModelState,
    UnitThreatModel,
    check_completion,
)
from polymerhus.attack.hunting.threat_model_store import (
    ImpactAssessmentError,
    ThreatModelDirectoryError,
    ThreatModelIdentityError,
    ThreatModelSchemaVersionError,
    ThreatModelStore,
    collision_suffix,
    sanitise_unit_name,
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
        "evidences": [_evidence()],
    }]


def _prior_art() -> dict:
    """The known-good prior-art section: one query for each kind the completion
    check requires (threat, vulnerability, precursor), each with a filter, and
    the phase note."""
    return {
        "queries": [
            {
                "kind": "precursor",
                "filters": [{
                    "path": "capability",
                    "regex": "session|item",
                    "flags": "i",
                }],
                "result_count": 3,
            },
            {
                "kind": "threat",
                "filters": [{
                    "path": "threat.web_vulnerability_class",
                    "regex": "session-management",
                    "flags": "i",
                }],
                "result_count": 0,
            },
            {
                "kind": "vulnerability",
                "filters": [{
                    "path": "canonical_class",
                    "regex": "credential",
                    "flags": "i",
                }],
                "result_count": 0,
            },
        ],
        "reused": [{
            "unit_id": "Service:sign-in",
            "record_id": "p-2",
            "kind": "precursor",
            "reason": "The item-read capability applies to this unit's lookup surface.",
        }],
        "notes": "No prior threat matched the item read; the precursor is reused.",
    }


# The known-good CVSS 4.0 scores of the two literal factor sets (`cvss==3.6`,
# `AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:N/VA:N` = 9.2, `VC:L` = 6.9).
TOP_RISK = 9.2
LOWER_RISK = 6.9
TOP_VECTOR = "CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:N/VA:N/SC:H/SI:N/SA:N"
LOWER_VECTOR = "CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:L/VI:N/VA:N/SC:L/SI:N/SA:N"
ZERO_VECTOR = "CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:N/VI:N/VA:N/SC:N/SI:N/SA:N"
ITEM_DESCRIPTION = (
    "An anonymous caller reads another tenant's item from the catalogue "
    "database."
)
ITEM_EXPLOITABILITY = (
    "One unauthenticated request names the item id; no defence stands between "
    "the caller and the lookup."
)

# The score tier of one fixture threat, for the tests that only care that two
# threats sort (or do not sort) against each other.
_TIER_RISK: dict[str, float] = {
    "critical": TOP_RISK,
    "high": TOP_RISK,
    "medium": LOWER_RISK,
    "low": LOWER_RISK,
    "none": 0.0,
}


def _factors(confidentiality: str = "high") -> dict:
    return {
        "attack_vector": "network",
        "attack_complexity": "low",
        "attack_requirements": "none",
        "privileges_required": "none",
        "user_interaction": "none",
        "confidentiality": confidentiality,
        "integrity": "none",
        "availability": "none",
    }


def _scored_factors(risk: float) -> tuple[dict, str]:
    """The factor set and vector that carry one known-good score."""
    if risk <= 0:
        return _factors("none"), ZERO_VECTOR
    if risk >= TOP_RISK:
        return _factors("high"), TOP_VECTOR
    return _factors("low"), LOWER_VECTOR


def _impact_assessment(
    index: int = 1, *, risk: float = TOP_RISK,
    confidentiality: str = "high",
) -> list[dict]:
    """One scored assessment row: a direct disclosure, no prerequisite."""
    factors, vector = _scored_factors(risk)
    if confidentiality != "high":
        factors = _factors(confidentiality)
    return [{
        "id": f"ia-{index}",
        "vulnerability_ref": "v-1",
        "disposition": "threat",
        "impact_description": ITEM_DESCRIPTION,
        "exploitability_description": ITEM_EXPLOITABILITY,
        "capability": "read another tenant's item",
        "capability_id": f"p-{index}",
        "capability_path": [],
        "evidence_refs": ["GET /catalogue?id=2"],
        "factors": factors,
        "risk": risk,
        "risk_vector": vector,
    }]


def _impact_row_for(threat: dict, index: int = 1) -> dict:
    """The row a supplied threat declares: one threat, one row, one path."""
    ref = threat.get("impact_ref") or f"ia-{index}"
    pairs = list(threat.get("enabling_precursors") or [])
    path = [pair[0] if isinstance(pair, (list, tuple)) else pair for pair in pairs]
    risk = float(threat.get("risk", TOP_RISK))
    row = _impact_assessment(index, risk=risk)[0]
    return {
        **row,
        "id": ref,
        "vulnerability_ref": threat["vulnerability_ref"],
        "capability_id": ref.replace("ia-", "p-"),
        "capability_path": path,
    }


def _placeholder_assessment() -> list[dict]:
    """One precursor row: a capability with no end damage (all impacts none)."""
    return [{
        "id": "ia-1",
        "vulnerability_ref": "v-1",
        "disposition": "precursor",
        "impact_description": (
            "No user, application, or infrastructure property is affected; the "
            "handler returns a generic envelope."),
        "exploitability_description": (
            "One unauthenticated request distinguishes an unmapped handler "
            "from an unmapped route."),
        "capability": "distinguish an unmapped handler from an unmapped route",
        "capability_id": "p-1",
        "capability_path": [],
        "evidence_refs": ["GET /catalogue?id=2"],
        "factors": _factors("none"),
        "risk": 0.0,
        "risk_vector": (
            "CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:N/VI:N/VA:N/SC:N/SI:N/SA:N"),
    }]


def _precursor_row(
    capability_id: str = "p-1",
    capability: str = "distinguish an unmapped handler from an unmapped route",
) -> dict:
    return {
        **_placeholder_assessment()[0],
        "capability_id": capability_id,
        "capability": capability,
    }


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


def _threat(tier: str = "high", *, index: int = 1, risk: float | None = None) -> dict:
    """One model-written threat row (schema 5): no authored score.

    `tier` keeps the fixture's old call sites readable (a higher tier is a
    higher score); the store fills the mirror from the threat's own row in
    `_impact_row_for`, so `risk` is only the fixture's tier marker.
    """
    return {
        "id": "modeller-1",
        "fault_ref": "fault-1",
        "vulnerability_ref": "v-1",
        "canonical_class": "IDOR",
        "web_vulnerability_class": "idor",
        "impact_ref": f"ia-{index}",
        "enabling_precursors": [],
        "evidences": [_evidence()],
        "risk": _TIER_RISK.get(tier, TOP_RISK) if risk is None else risk,
    }


def _write_shape(threat: dict) -> dict:
    """One threat as the MODEL writes it: `ThreatWrite` carries no `risk`."""
    return {key: value for key, value in threat.items() if key != "risk"}


def _sections_below_completed() -> list[tuple[str, dict]]:
    """The MODEL-facing gates below COMPLETED.

    The `IMPACT_ASSESSED` gate carries no model section (the `assess_impact`
    tool owns it, ticket #406), so the ladder stops at `PRIOR_ART`; the
    assessment rows are seeded by `_seed_assessments`.
    """
    return [
        ("UNIT_TECHNICAL_SHARP", {"technical_sharpening": _sharpening()}),
        ("TRUST_MODELLED", {"trust_model": _trust_model()}),
        ("TRUST_ASSUMPTIONS_WRITTEN", {"assumptions": _assumptions()}),
        ("VULNERABILITIES_WRITTEN", {"vulnerabilities": _vulnerabilities()}),
        ("PRIOR_ART", {"prior_art": _prior_art()}),
    ]


def _write_gates(
    store: ThreatModelStore,
    *,
    unit_id: str = UNIT,
    run_id: str = RUN,
    sections: list[tuple[str, dict]] | None = None,
) -> Path:
    """Drive the model-facing gates in order; return the produced model path."""
    path = None
    for state, payload in sections if sections is not None else _sections_below_completed():
        path = store.write_sections(PROJECT, unit_id, state, payload, run_id=run_id)
    return path


def _seed_assessments(path: Path, rows: list[dict]) -> None:
    """Seed the assessment rows the `assess_impact` tool writes (ticket #406).

    A schema-5 assessment row has no model-facing gate write; its sole writer
    is `ThreatModelStore.write_impact_assessment`. These tests seed the document
    the tool writes (state `IMPACT_ASSESSED`, the scored rows) so a fixture can
    also drive a row set the write would reject (a tampered score, a duplicate
    capability id), and then drive every OTHER write through the real store, so
    the merge, the COMPLETED commit, the ranking, and the completion checker all
    run for real.
    """
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["state"] = "IMPACT_ASSESSED"
    document["impact_assessment"] = rows
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def _completed_sections(threats: list[dict] | None = None) -> dict:
    rows = [_threat()] if threats is None else threats
    return {"threats": [_write_shape(row) for row in rows]}


def _write_to_completed(
    store: ThreatModelStore,
    *,
    threats: list[dict] | None = None,
    impact_assessment: list[dict] | None = None,
    unit_id: str = UNIT,
    run_id: str = RUN,
) -> None:
    rows = [_threat()] if threats is None else list(threats)
    if impact_assessment is None:
        impact_assessment = [
            _impact_row_for(row, index) for index, row in enumerate(rows, start=1)
        ]
    path = _write_gates(
        store,
        unit_id=unit_id,
        run_id=run_id,
        sections=_sections_below_completed(),
    )
    _seed_assessments(path, impact_assessment)
    store.write_sections(
        PROJECT, unit_id, "COMPLETED", _completed_sections(rows), run_id=run_id)


def _dropped_vulnerabilities() -> list[dict]:
    return [{
        **_vulnerabilities()[0],
        "dropped": True,
        "drop_reason": "The item lookup binds the id to the tenant; the mechanics are absent.",
        "drop_probe": "A request with a second tenant's item id returning that item.",
    }]


def _write_zero_threat_completed(store: ThreatModelStore) -> None:
    for state, sections in _sections_below_completed():
        store.write_sections(PROJECT, UNIT, state, sections, run_id=RUN)
    store.write_sections(
        PROJECT, UNIT, "VULNERABILITIES_WRITTEN",
        {"vulnerabilities": _dropped_vulnerabilities()}, run_id=RUN,
    )
    store.write_sections(
        PROJECT, UNIT, "COMPLETED", {"threats": []}, run_id=RUN,
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
    assert model["schema_version"] == 5
    assert model["unit_id"] == UNIT
    assert model["unit_kind"] == "service"
    assert model["run_id"] == RUN
    assert model["state"] == "UNIT_TECHNICAL_SHARP"
    assert model["technical_sharpening"]["interface_agreements"][0]["id"] == "ia-1"
    assert store.read_section(PROJECT, UNIT, "technical_sharpening") == model["technical_sharpening"]


def test_gate_writes_merge_sections_into_one_document(tmp_path):
    store = ThreatModelStore(tmp_path)

    path = _write_gates(store)
    _seed_assessments(path, _impact_assessment())

    model = store.read_model(PROJECT, UNIT)
    assert model["state"] == "IMPACT_ASSESSED"
    assert model["technical_sharpening"]["interface_agreements"][0]["id"] == "ia-1"
    assert model["trust_model"]["trust_agreements"][0]["id"] == "ta-1"
    assert model["assumptions"][0]["fault"]["id"] == "fault-1"
    assert model["vulnerabilities"][0]["canonical_class"] == "IDOR"
    assert model["impact_assessment"][0]["id"] == "ia-1"
    assert model["impact_assessment"][0]["capability_id"] == "p-1"
    assert model["prior_art"]["queries"][0]["kind"] == "precursor"
    assert "failure_modes" not in model
    assert model["threats"] == []


def test_a_lower_gate_write_never_regresses_the_state(tmp_path):
    store = ThreatModelStore(tmp_path)
    path = _write_gates(store)
    _seed_assessments(path, _impact_assessment())

    store.write_sections(
        PROJECT, UNIT, "UNIT_TECHNICAL_SHARP",
        {"technical_sharpening": {
            **_sharpening(),
            "data_flows": [],
        }},
        run_id=RUN,
    )

    model = store.read_model(PROJECT, UNIT)
    assert model["state"] == "IMPACT_ASSESSED"
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


def test_the_completed_gate_accepts_only_the_threats_section(tmp_path):
    """The failure-mode contraction (ADR 2026-10-25): the COMPLETED gate carries
    the threats alone, so a `failure_modes` section is a coded rejection and
    nothing is persisted."""
    store = ThreatModelStore(tmp_path)
    path = _write_gates(store)
    _seed_assessments(path, _impact_assessment())

    with pytest.raises(ThreatModelIdentityError) as raised:
        store.write_sections(
            PROJECT, UNIT, "COMPLETED",
            {"failure_modes": _legacy_failure_modes(), "threats": [_threat()]}, run_id=RUN,
        )

    assert raised.value.fields == ["failure_modes"]
    assert GATE_SECTIONS[ModelState.COMPLETED] == ("threats",)
    assert store.read_model(PROJECT, UNIT)["state"] == "IMPACT_ASSESSED"


def test_the_stored_model_carries_no_failure_mode_key(tmp_path):
    """The section and the threat link are gone from the persisted document, the
    model and the threat file alike (the contract half of the expand-contract)."""
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store)

    model = store.read_model(PROJECT, UNIT)

    assert "failure_modes" not in model
    assert "failure_mode_refs" not in model["threats"][0]
    threat_file = store.read_threat_files(PROJECT, UNIT)[0]
    assert "failure_mode_refs" not in threat_file["threat"]


def test_a_model_with_a_failure_modes_key_is_rejected_by_the_strict_schema(tmp_path):
    """The contraction removed the section, and the later loop->threat rename
    bumped the schema: a legacy document that still carries `failure_modes` (or
    the old `loops` key) no longer parses, so the store refuses to merge it
    rather than silently dropping the section (the migration note in
    `threat_model` records both decisions)."""
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store)
    document = store.read_model(PROJECT, UNIT)
    document["failure_modes"] = _legacy_failure_modes()

    with pytest.raises(ValueError):
        UnitThreatModel.model_validate(document)

    # the threat link went with the section: a legacy threat carrying it is rejected
    document.pop("failure_modes")
    document["threats"][0]["failure_mode_refs"] = ["fm-1"]
    with pytest.raises(ValueError):
        UnitThreatModel.model_validate(document)


def test_an_unknown_schema_version_refuses_to_load_and_never_migrates(tmp_path):
    name = "Service-catalogue-and-discovery"
    unit_dir = tmp_path / PROJECT / "hunting" / "threat_modeller" / "produced" / name
    unit_dir.mkdir(parents=True)
    document = unit_dir / f"{name}.yaml"
    document.write_text(
        yaml.safe_dump({"schema_version": 6, "unit_id": UNIT, "state": "COMPLETED"}),
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


def test_a_v4_document_reads_raw_and_is_never_re_scored(tmp_path):
    """Schema 5 spec 11: a v4 model is read for the prior art and the
    measurement, exactly as it was written. Its likelihood and its old risk stay
    untouched and no profile is computed."""
    store = ThreatModelStore(tmp_path)
    name = "Service-catalogue-and-discovery"
    unit_dir = tmp_path / PROJECT / "hunting" / "threat_modeller" / "produced" / name
    unit_dir.mkdir(parents=True)
    (unit_dir / f"{name}.yaml").write_text(
        yaml.safe_dump({
            "schema_version": 4,
            "unit_id": UNIT,
            "unit_kind": "service",
            "run_id": RUN,
            "state": "COMPLETED",
            "validation": {"valid": True},
            "impact_assessment": [{
                "id": "ia-1",
                "vulnerability_ref": "v-1",
                "disposition": "threat",
                "damage": "An anonymous caller reads another tenant's item.",
                "capability": "read another tenant's item",
                "capability_id": "p-1",
                "capability_path": [],
                "evidence_refs": ["GET /catalogue?id=2"],
            }],
            "threats": [{
                "id": "threat-1",
                "fault_ref": "fault-1",
                "vulnerability_ref": "v-1",
                "canonical_class": "IDOR",
                "web_vulnerability_class": "idor",
                "likelihood": "medium",
                "likelihood_rationale": "the id is caller-controlled",
                "impact_ref": "ia-1",
                "enabling_precursors": [],
                "impact": {
                    "confidentiality": "low",
                    "integrity": "none",
                    "availability": "none",
                },
                "impact_weight": 1,
                "risk": 2,
            }],
        }, sort_keys=False),
        encoding="utf-8",
    )

    model = store.read_model(PROJECT, UNIT)

    assert model["schema_version"] == 4
    assert model["state"] == "COMPLETED"
    assert "risk_profile" not in model
    assert model["impact_assessment"][0]["damage"].startswith("An anonymous")
    assert model["threats"][0]["likelihood"] == "medium"
    assert model["threats"][0]["risk"] == 2  # the stored v4 score, never re-scored

    # the prior art reads the raw v4 PROSE through the v5 catalog
    result = store.query_prior_art(
        PROJECT,
        kind="impact",
        filters=[{"path": "damage", "regex": "anonymous caller"}],
    )

    assert result["count"] == 1
    assert result["matches"][0]["record_id"] == "ia-1"

    # a v4 threat file is queryable too, through the v5 threat paths; its
    # retired likelihood is NOT a path (T9 #412)
    (unit_dir / "threat-1.yaml").write_text(
        yaml.safe_dump({
            "threat_id": "threat-1",
            "unit_id": UNIT,
            "unit_kind": "service",
            "run_id": RUN,
            "dispatch_id": "Service-catalogue-and-discovery__threat-1",
            "risk": 2,
            "threat": {
                "id": "threat-1",
                "canonical_class": "IDOR",
                "web_vulnerability_class": "idor",
                "impact_ref": "ia-1",
                "risk": 2,
            },
            "impact": {"impact_ref": "ia-1"},
        }, sort_keys=False),
        encoding="utf-8",
    )
    threats = store.query_prior_art(
        PROJECT,
        kind="threat",
        filters=[{"path": "threat.canonical_class", "regex": "^IDOR$"}],
    )

    assert threats["count"] == 1
    assert threats["matches"][0]["summary"].startswith("An anonymous caller")


def test_a_v4_document_and_a_v5_document_coexist_in_one_store(tmp_path):
    """Schema 5 spec 11: the schema version is a per-document property, so one
    project root can hold archived v4 evidence and a live v5 model. The v5
    document is normalised; the v4 document is raw; neither leaks into the
    other."""
    store = ThreatModelStore(tmp_path)
    v4_name = "Service-v4-archive"
    v4_dir = (
        tmp_path / PROJECT / "hunting" / "threat_modeller" / "produced" / v4_name)
    v4_dir.mkdir(parents=True)
    (v4_dir / f"{v4_name}.yaml").write_text(
        yaml.safe_dump({
            "schema_version": 4,
            "unit_id": "Service:v4-archive",
            "unit_kind": "service",
            "run_id": RUN,
            "state": "COMPLETED",
            "impact_assessment": [],
            "threats": [],
        }, sort_keys=False),
        encoding="utf-8",
    )
    _write_gates(store, unit_id="Service:v5-live")

    v4 = store.read_model(PROJECT, "Service:v4-archive")
    v5 = store.read_model(PROJECT, "Service:v5-live")

    assert v4["schema_version"] == 4
    assert "risk_profile" not in v4
    assert v5["schema_version"] == 5
    assert v5["unit_id"] == "Service:v5-live"
    assert v5["threats"] == []
    assert v4["unit_id"] == "Service:v4-archive"


def test_a_v4_write_is_refused(tmp_path):
    """Schema 5 spec 11: a stale model is never mixed into a v5 run."""
    store = ThreatModelStore(tmp_path)
    name = "Service-catalogue-and-discovery"
    unit_dir = tmp_path / PROJECT / "hunting" / "threat_modeller" / "produced" / name
    unit_dir.mkdir(parents=True)
    document = unit_dir / f"{name}.yaml"
    document.write_text(
        yaml.safe_dump({
            "schema_version": 4,
            "unit_id": UNIT,
            "state": "IMPACT_ASSESSED",
        }, sort_keys=False),
        encoding="utf-8",
    )
    before = document.read_bytes()

    with pytest.raises(ThreatModelSchemaVersionError) as raised:
        store.write_sections(
            PROJECT, UNIT, "UNIT_TECHNICAL_SHARP",
            {"technical_sharpening": _sharpening()}, run_id=RUN,
        )

    assert raised.value.version == 4
    assert document.read_bytes() == before


def test_a_persisted_document_with_an_unknown_state_is_a_coded_refusal(tmp_path):
    """A document the v5 schema cannot parse is never merged into: the store
    refuses it instead of raising a raw pydantic/enum error."""
    store = ThreatModelStore(tmp_path)
    name = "Service-catalogue-and-discovery"
    unit_dir = tmp_path / PROJECT / "hunting" / "threat_modeller" / "produced" / name
    unit_dir.mkdir(parents=True)
    (unit_dir / f"{name}.yaml").write_text(
        yaml.safe_dump({
            "schema_version": 5,
            "unit_id": UNIT,
            "unit_kind": "service",
            "run_id": RUN,
            "created_at": "2026-10-18T00:00:00Z",
            "updated_at": "2026-10-18T00:00:00Z",
            "state": "BOGUS",
        }),
        encoding="utf-8",
    )

    with pytest.raises(ThreatModelSchemaVersionError):
        store.write_sections(
            PROJECT, UNIT, "UNIT_TECHNICAL_SHARP",
            {"technical_sharpening": _sharpening()}, run_id=RUN,
        )


# --- the COMPLETED write: threats, risk profile, validation --------------------

def test_completed_ranks_threats_by_risk_and_emits_a_file_per_threat(tmp_path):
    store = ThreatModelStore(tmp_path)

    _write_to_completed(store, threats=[_threat("low"), _threat("high", index=2)])

    model = store.read_model(PROJECT, UNIT)
    assert model["state"] == "COMPLETED"
    assert [threat["id"] for threat in model["threats"]] == ["threat-1", "threat-2"]
    # the mirror is the row's score, and the higher row ranks first
    assert [threat["risk"] for threat in model["threats"]] == [TOP_RISK, LOWER_RISK]
    assert model["risk_profile"] == {
        "total": round(TOP_RISK + LOWER_RISK, 2),
        "breakdown": {
            "none": 0, "low": 0, "medium": 1, "high": 0, "critical": 1,
        },
    }
    assert model["validation"]["valid"] is True
    assert model["validation"]["missing"] == []
    assert model["validation"]["unclosed"] == []
    assert model["validation"]["referential_errors"] == []

    unit_name = "Service-catalogue-and-discovery"
    produced = tmp_path / PROJECT / "hunting" / "threat_modeller" / "produced" / unit_name
    assert sorted(p.name for p in produced.glob("threat-*.yaml")) == [
        "threat-1.yaml", "threat-2.yaml",
    ]
    records = store.read_threat_files(PROJECT, UNIT)
    assert [record["threat_id"] for record in records] == ["threat-1", "threat-2"]
    record = records[0]
    assert record["unit_id"] == UNIT
    assert record["unit_kind"] == "service"
    assert record["run_id"] == RUN
    assert record["dispatch_id"] == "Service-catalogue-and-discovery__threat-1"
    assert record["risk"] == TOP_RISK
    assert record["threat"]["id"] == "threat-1"
    assert record["threat"]["fault_ref"] == "fault-1"
    assert record["created_at"]


def test_a_zero_threat_model_emits_no_threat_files(tmp_path):
    store = ThreatModelStore(tmp_path)

    _write_zero_threat_completed(store)

    model = store.read_model(PROJECT, UNIT)
    assert model["threats"] == []
    assert model["risk_profile"] == {
        "total": 0.0,
        "breakdown": {"none": 0, "low": 0, "medium": 0, "high": 0, "critical": 0},
    }
    assert model["validation"]["valid"] is True
    assert store.read_threat_files(PROJECT, UNIT) == []


# --- the commit protocol (S2 4.3) --------------------------------------------

def test_a_failing_model_write_after_the_threat_files_leaves_the_previous_state(
    tmp_path, monkeypatch
):
    store = ThreatModelStore(tmp_path)
    path = _write_gates(store)
    _seed_assessments(path, _impact_assessment())
    unit_name = "Service-catalogue-and-discovery"
    produced = tmp_path / PROJECT / "hunting" / "threat_modeller" / "produced" / unit_name

    def _fail_the_model_write(path, body):
        if path.name == f"{unit_name}.yaml":
            raise OSError("simulated crash between the threat files and the commit")
        return _dump_yaml(path, body)

    monkeypatch.setattr(store, "_dump_yaml_atomic", _fail_the_model_write)

    with pytest.raises(OSError):
        store.write_sections(PROJECT, UNIT, "COMPLETED", _completed_sections(), run_id=RUN)

    # the threat files landed (the crash window), the model did not commit
    assert (produced / "threat-1.yaml").exists()
    model = store.read_model(PROJECT, UNIT)
    assert model["state"] == "IMPACT_ASSESSED"
    assert model["threats"] == []
    assert model["risk_profile"] is None
    assert model["validation"] is None


def test_read_threat_files_is_empty_for_a_model_below_completed(tmp_path, monkeypatch):
    # S2 4.3: a threat file is never read for a model whose state is not
    # COMPLETED - the crash window leaves files on disk that must not surface
    # as dispatch work
    store = ThreatModelStore(tmp_path)
    path = _write_gates(store)
    _seed_assessments(path, _impact_assessment())
    unit_name = "Service-catalogue-and-discovery"
    produced = (
        tmp_path / PROJECT / "hunting" / "threat_modeller" / "produced" / unit_name
    )

    def _fail_the_model_write(path, body):
        if path.name == f"{unit_name}.yaml":
            raise OSError("simulated crash between the threat files and the commit")
        return _dump_yaml(path, body)

    monkeypatch.setattr(store, "_dump_yaml_atomic", _fail_the_model_write)
    with pytest.raises(OSError):
        store.write_sections(PROJECT, UNIT, "COMPLETED", _completed_sections(), run_id=RUN)

    assert (produced / "threat-1.yaml").exists()
    assert store.read_threat_files(PROJECT, UNIT) == []


def test_read_threat_files_is_empty_for_an_invalid_completed_model(tmp_path):
    store = ThreatModelStore(tmp_path)
    store.write_sections(
        PROJECT, UNIT, "UNIT_TECHNICAL_SHARP",
        {"technical_sharpening": _sharpening()}, run_id=RUN,
    )
    store.write_sections(
        PROJECT, UNIT, "TRUST_ASSUMPTIONS_WRITTEN",
        {"assumptions": [{**_assumptions()[0], "boundary_ref": ""}]}, run_id=RUN,
    )
    path = store.write_sections(
        PROJECT, UNIT, "VULNERABILITIES_WRITTEN",
        {"vulnerabilities": _vulnerabilities()}, run_id=RUN,
    )
    _seed_assessments(path, _impact_assessment())
    store.write_sections(PROJECT, UNIT, "COMPLETED", _completed_sections(), run_id=RUN)

    produced = (
        tmp_path / PROJECT / "hunting" / "threat_modeller" / "produced"
        / "Service-catalogue-and-discovery"
    )
    assert (produced / "threat-1.yaml").exists()  # emitted, but never read
    assert store.read_model(PROJECT, UNIT)["validation"]["valid"] is False
    assert store.read_threat_files(PROJECT, UNIT) == []


def test_a_lower_gate_write_deletes_the_orphan_threat_files(tmp_path, monkeypatch):
    store = ThreatModelStore(tmp_path)
    path = _write_gates(store)
    _seed_assessments(path, _impact_assessment())
    unit_name = "Service-catalogue-and-discovery"
    produced = tmp_path / PROJECT / "hunting" / "threat_modeller" / "produced" / unit_name

    def _fail_the_model_write(path, body):
        if path.name == f"{unit_name}.yaml":
            raise OSError("simulated crash between the threat files and the commit")
        return _dump_yaml(path, body)

    monkeypatch.setattr(store, "_dump_yaml_atomic", _fail_the_model_write)
    with pytest.raises(OSError):
        store.write_sections(PROJECT, UNIT, "COMPLETED", _completed_sections(), run_id=RUN)
    monkeypatch.undo()
    assert (produced / "threat-1.yaml").exists()

    store.write_sections(
        PROJECT, UNIT, "TRUST_MODELLED", {"trust_model": _trust_model()}, run_id=RUN,
    )

    assert list(produced.glob("threat-*.yaml")) == []
    model = store.read_model(PROJECT, UNIT)
    assert model["state"] == "IMPACT_ASSESSED"
    assert model["threats"] == []


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
    path = store.write_sections(
        PROJECT, UNIT, "VULNERABILITIES_WRITTEN",
        {"vulnerabilities": _vulnerabilities()}, run_id=RUN,
    )
    _seed_assessments(path, _impact_assessment())

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
        PriorArt,
        TechnicalSharpening,
        ThreatWrite,
        TrustModel,
    )

    store = ThreatModelStore(tmp_path)
    store.write_sections(
        PROJECT, UNIT, "UNIT_TECHNICAL_SHARP",
        {"technical_sharpening": TechnicalSharpening.model_validate(_sharpening())},
        run_id=RUN,
    )
    store.write_sections(
        PROJECT, UNIT, "PRIOR_ART",
        {"prior_art": PriorArt.model_validate(_prior_art())},
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
    path = store.write_sections(
        PROJECT, UNIT, "VULNERABILITIES_WRITTEN",
        {"vulnerabilities": _vulnerabilities()}, run_id=RUN,
    )
    _seed_assessments(path, _impact_assessment())

    store.write_sections(
        PROJECT, UNIT, "COMPLETED",
        {"threats": [ThreatWrite.model_validate(
            _write_shape(_threat("high")))]},
        run_id=RUN,
    )

    model = store.read_model(PROJECT, UNIT)
    assert model["technical_sharpening"]["interface_agreements"][0]["id"] == "ia-1"
    assert model["trust_model"]["trust_agreements"][0]["id"] == "ta-1"
    assert model["impact_assessment"][0]["id"] == "ia-1"
    assert model["validation"]["valid"] is True
    assert [threat["id"] for threat in model["threats"]] == ["threat-1"]


def test_completion_reports_referential_errors(tmp_path):
    store = ThreatModelStore(tmp_path)
    for state, sections in _sections_below_completed()[:-1]:
        store.write_sections(PROJECT, UNIT, state, sections, run_id=RUN)
    vulnerabilities = _vulnerabilities()
    vulnerabilities[0]["fault_ref"] = "fault-missing"
    path = store.write_sections(
        PROJECT, UNIT, "VULNERABILITIES_WRITTEN",
        {"vulnerabilities": vulnerabilities}, run_id=RUN,
    )

    _write_completed_document(store, path, _completed_sections())

    validation = check_completion(
        UnitThreatModel.model_validate(store.read_model(PROJECT, UNIT)))
    assert validation.valid is False
    assert "vulnerability:v-1.fault_ref='fault-missing'" in validation.referential_errors


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
    path = store.write_sections(
        PROJECT, UNIT, "VULNERABILITIES_WRITTEN",
        {"vulnerabilities": _vulnerabilities()}, run_id=RUN)
    _write_completed_document(store, path, _completed_sections())

    validation = check_completion(
        UnitThreatModel.model_validate(store.read_model(PROJECT, UNIT)))
    assert validation.valid is False
    assert "violation:vi-1.transition_ref='tr-missing'" in \
        validation.referential_errors


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
    path = _write_gates(store)
    store.write_sections(
        PROJECT, UNIT, "TRUST_ASSUMPTIONS_WRITTEN",
        {"assumptions": [*_assumptions(), extra_assumption]}, run_id=RUN,
    )
    store.write_sections(
        PROJECT, UNIT, "VULNERABILITIES_WRITTEN",
        {"vulnerabilities": _vulnerabilities()}, run_id=RUN,
    )
    _seed_assessments(path, _impact_assessment())

    store.write_sections(PROJECT, UNIT, "COMPLETED", _completed_sections(), run_id=RUN)

    validation = store.read_model(PROJECT, UNIT)["validation"]
    assert validation["valid"] is False
    assert "assumption:as-2" in validation["unclosed"]
    assert validation["referential_errors"] == []
    assert validation["missing"] == []


def test_check_completion_recomputes_the_risk_profile(tmp_path):
    # the stored profile is never trusted: the checker recomputes it from the
    # stored threats (the regression check against a store bug, S2 5.7)
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store)
    document = store.read_model(PROJECT, UNIT)
    document["risk_profile"]["total"] = 99
    document["risk_profile"]["breakdown"]["critical"] = 0
    document["risk_profile"]["breakdown"]["low"] = 1

    validation = check_completion(UnitThreatModel.model_validate(document))

    assert validation.valid is False
    assert "risk_profile.total" in validation.missing
    assert "risk_profile.breakdown" in validation.missing


def test_the_store_records_the_non_suite_class_finding(tmp_path):
    store = ThreatModelStore(tmp_path, class_names={"idor"})
    path = _write_gates(store)
    _seed_assessments(path, _impact_assessment())
    store.write_sections(
        PROJECT, UNIT, "VULNERABILITIES_WRITTEN",
        {"vulnerabilities": [{
            **_vulnerabilities()[0],
            "web_vulnerability_class": "made-up-class",
        }]}, run_id=RUN)
    threats = [{**_threat("high"), "web_vulnerability_class": "made-up-class"}]
    store.write_sections(
        PROJECT, UNIT, "COMPLETED", _completed_sections(threats), run_id=RUN)

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

    path = _write_gates(store)
    _seed_assessments(path, _impact_assessment())
    store.write_sections(
        PROJECT, UNIT, "VULNERABILITIES_WRITTEN",
        {"vulnerabilities": [{
            **_vulnerabilities()[0],
            "web_vulnerability_class": "made-up-class",
        }]}, run_id=RUN)
    threats = [{**_threat("high"), "web_vulnerability_class": "made-up-class"}]
    store.write_sections(
        PROJECT, UNIT, "COMPLETED", _completed_sections(threats), run_id=RUN)

    validation = store.read_model(PROJECT, UNIT)["validation"]

    assert any("not in the suite" in finding
               for finding in validation["class_findings"])


def test_the_completion_records_a_technique_family_as_a_class_finding(tmp_path):
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store)
    document = store.read_model(PROJECT, UNIT)
    for target in (document["vulnerabilities"][0], document["threats"][0]):
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
    for target in (document["vulnerabilities"][0], document["threats"][0]):
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
    for target in (document["vulnerabilities"][0], document["threats"][0]):
        target["web_vulnerability_class"] = ""

    validation = check_completion(UnitThreatModel.model_validate(document))

    assert validation.valid is True
    assert any("=empty" in finding for finding in validation.class_findings)


def test_check_completion_recomputes_the_risk_total(tmp_path):
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store)
    document = store.read_model(PROJECT, UNIT)
    document["risk_profile"]["total"] = 99

    validation = check_completion(UnitThreatModel.model_validate(document))

    assert validation.valid is False
    assert "risk_profile.total" in validation.missing


def test_check_completion_reports_a_tampered_threat_risk(tmp_path):
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store)
    document = store.read_model(PROJECT, UNIT)
    document["threats"][0]["risk"] = 0

    validation = check_completion(UnitThreatModel.model_validate(document))

    assert validation.valid is False
    assert "threat:threat-1.risk" in validation.missing


def test_check_completion_reports_a_threat_row_with_no_impact_value(tmp_path):
    """A `threat` row is damage-bearing: at least one of its three impact
    factors must be above `none`, so an all-none factor set is a finding."""
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store)
    document = store.read_model(PROJECT, UNIT)
    document["impact_assessment"][0]["factors"] = _factors("none")

    validation = check_completion(UnitThreatModel.model_validate(document))

    assert validation.valid is False
    assert any(
        finding.startswith("impact_assessment:ia-1.factors.confidentiality")
        for finding in validation.missing
    )


def test_check_completion_recomputes_the_assessment_score_and_vector(tmp_path):
    """The row's `risk` and `risk_vector` are DERIVED: a row whose values do not
    recompute from its factors was hand-edited, so the checker reports it (the
    completion check's regression rule, spec 5)."""
    store = ThreatModelStore(tmp_path)
    document = _completed_document(store)
    document["impact_assessment"][0]["risk"] = 0.0
    document["impact_assessment"][0]["risk_vector"] = ""

    validation = check_completion(UnitThreatModel.model_validate(document))

    assert validation.valid is False
    assert "impact_assessment:ia-1.risk" in validation.missing
    assert "impact_assessment:ia-1.risk_vector" in validation.missing


def test_completion_reports_a_vulnerability_without_an_assessment_row(tmp_path):
    """Spec 5: every non-dropped vulnerability carries at least one scored row."""
    store = ThreatModelStore(tmp_path)
    path = _write_gates(store)
    second = {
        **_vulnerabilities()[0],
        "id": "v-2",
        "canonical_class": "Path Traversal",
        "characterisation": "An anonymous caller reads a file outside the root.",
    }
    store.write_sections(
        PROJECT, UNIT, "VULNERABILITIES_WRITTEN",
        {"vulnerabilities": [_vulnerabilities()[0], second]}, run_id=RUN)
    _seed_assessments(path, _impact_assessment())
    _write_completed_document(store, path, {"threats": []})

    validation = check_completion(
        UnitThreatModel.model_validate(store.read_model(PROJECT, UNIT)))

    assert "vulnerability:v-2.impact_assessment" in validation.unclosed


def _completed_document(store) -> dict:
    """The valid completed model, written by the ladder fixture."""
    _write_to_completed(store)
    return store.read_model(PROJECT, UNIT)


def test_completion_reports_a_missing_prose_and_a_missing_capability(tmp_path):
    """Every row names its impact, its exploitability, and its capability."""
    store = ThreatModelStore(tmp_path)
    document = _completed_document(store)
    document["impact_assessment"][0]["impact_description"] = ""
    document["impact_assessment"][0]["exploitability_description"] = ""
    document["impact_assessment"][0]["capability"] = ""
    document["impact_assessment"][0]["capability_id"] = ""

    validation = check_completion(UnitThreatModel.model_validate(document))

    assert validation.valid is False
    assert "impact_assessment:ia-1.impact_description" in validation.missing
    assert "impact_assessment:ia-1.exploitability_description" in validation.missing
    assert "impact_assessment:ia-1.capability" in validation.missing
    assert "impact_assessment:ia-1.capability_id" in validation.missing


def test_completion_accepts_a_precursor_row_with_a_capability_path(tmp_path):
    """A precursor may name the capabilities it leveraged to gain its own."""
    store = ThreatModelStore(tmp_path)
    first = {**_precursor_row(), "capability_id": "p-1"}
    second = {
        **_precursor_row(),
        "id": "ia-2",
        "capability_id": "p-2",
        "capability_path": ["p-1"],
    }
    _write_to_completed(store, impact_assessment=[first, second], threats=[])

    validation = check_completion(
        UnitThreatModel.model_validate(store.read_model(PROJECT, UNIT)))

    assert validation.valid is True


def test_completion_reports_a_threat_without_its_assessment_link(tmp_path):
    """The impact_ref is a necessary attribute; an empty enabling list is valid."""
    store = ThreatModelStore(tmp_path)
    document = _completed_document(store)
    document["threats"][0]["impact_ref"] = ""

    validation = check_completion(UnitThreatModel.model_validate(document))

    assert validation.valid is False
    assert "threat:threat-1.impact_ref" in validation.missing
    assert "threat:threat-1.enabling_precursors" not in validation.missing


# --- the one-threat-one-damage closure (ticket 436) --------------------------

def test_completion_reports_a_threat_row_without_its_threat(tmp_path):
    """A `threat` row publishes exactly one threat; none is unclosed."""
    store = ThreatModelStore(tmp_path)
    _write_to_completed(
        store, impact_assessment=_impact_assessment(), threats=[])

    validation = check_completion(
        UnitThreatModel.model_validate(store.read_model(PROJECT, UNIT)))

    assert validation.valid is False
    assert "impact_assessment:ia-1.threat" in validation.unclosed


def test_completion_reports_a_placeholder_that_a_threat_references(tmp_path):
    """A placeholder has no threat, and a threat cannot stand on a placeholder."""
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store, impact_assessment=_placeholder_assessment())

    validation = check_completion(
        UnitThreatModel.model_validate(store.read_model(PROJECT, UNIT)))

    assert validation.valid is False
    assert "impact_assessment:ia-1.threat" in validation.unclosed
    assert "threat:threat-1.impact_ref" in validation.unclosed


def test_completion_reports_two_threats_on_one_row(tmp_path):
    """One threat references exactly one row, and a row publishes one threat."""
    store = ThreatModelStore(tmp_path)
    _write_to_completed(
        store,
        impact_assessment=_impact_assessment(),
        threats=[
            _threat("high"),
            {**_threat("high"), "canonical_class": "IDOR"},
        ],
    )

    validation = check_completion(
        UnitThreatModel.model_validate(store.read_model(PROJECT, UNIT)))

    assert validation.valid is False
    assert "impact_assessment:ia-1.threat" in validation.unclosed
    assert "threat:threat-2.impact_ref" not in validation.unclosed


def test_completion_reports_a_threat_on_a_row_of_another_vulnerability(tmp_path):
    """The row a threat references must carry the threat's vulnerability."""
    store = ThreatModelStore(tmp_path)
    second_vulnerability = {
        **_vulnerabilities()[0],
        "id": "v-2",
        "canonical_class": "Path Traversal",
        "characterisation": "An anonymous caller reads a file outside the root.",
    }
    second_row = {
        **_impact_assessment()[0],
        "id": "ia-2",
        "vulnerability_ref": "v-2",
    }
    second_threat = {
        **_threat("high"),
        "vulnerability_ref": "v-2",
        "canonical_class": "Path Traversal",
        "impact_ref": "ia-2",
    }
    _write_to_completed(
        store,
        impact_assessment=[_impact_assessment()[0], second_row],
        threats=[
            {**_threat("high"), "impact_ref": "ia-2"},
            {**second_threat, "impact_ref": "ia-1"},
        ],
    )
    document = store.read_model(PROJECT, UNIT)
    document["vulnerabilities"].append(second_vulnerability)

    validation = check_completion(UnitThreatModel.model_validate(document))

    assert validation.valid is False
    assert "threat:threat-1.impact_ref" in validation.unclosed
    assert "threat:threat-2.impact_ref" in validation.unclosed
    assert "impact_assessment:ia-1.threat" not in validation.unclosed
    assert "impact_assessment:ia-2.threat" not in validation.unclosed


def test_completion_reports_a_capability_path_mismatch(tmp_path):
    """The threat's enabling set equals the row's capability-path set."""
    store = ThreatModelStore(tmp_path)
    document = _completed_document(store)
    document["precursors"].append({
        "id": "p-2",
        "capability": "enumerate the item ids",
        "procedure": "walk the item identifier space",
        "evidence_refs": ["GET /catalogue?id=3"],
    })
    document["threats"][0]["enabling_precursors"] = ["p-2"]

    validation = check_completion(UnitThreatModel.model_validate(document))

    assert validation.valid is False
    assert "threat:threat-1.enabling_precursors" in validation.unclosed


def test_completion_reports_duplicate_assessment_and_capability_ids(tmp_path):
    """The assessment and capability ids are unique in the unit."""
    store = ThreatModelStore(tmp_path)
    document = _completed_document(store)
    document["impact_assessment"].append(
        {**document["impact_assessment"][0]})

    validation = check_completion(UnitThreatModel.model_validate(document))

    assert validation.valid is False
    assert "impact_assessment.ids" in validation.missing
    assert "impact_assessment.capability_ids" in validation.missing


def test_completion_accepts_a_capability_from_another_row(tmp_path):
    """A path may chain a capability yielded by another row."""
    store = ThreatModelStore(tmp_path)
    precursor = {**_precursor_row("p-2"), "id": "ia-2"}
    row = {
        **_impact_assessment()[0],
        "capability_path": ["p-2"],
    }
    _write_to_completed(
        store,
        impact_assessment=[row, precursor],
        threats=[{
            **_threat(),
            "enabling_precursors": [["p-2", "p-2"]],
        }],
    )

    validation = check_completion(
        UnitThreatModel.model_validate(store.read_model(PROJECT, UNIT)))

    assert validation.valid is True


def test_completion_reports_unresolved_capability_references(tmp_path):
    """Every capability reference resolves inside the project."""
    store = ThreatModelStore(tmp_path)
    document = _completed_document(store)
    document["impact_assessment"][0]["capability_path"] = ["p-missing"]
    document["threats"][0]["enabling_precursors"] = [["p-missing", None]]
    document["threats"][0]["impact_ref"] = "ia-missing"

    validation = check_completion(UnitThreatModel.model_validate(document))

    assert validation.valid is False
    assert "impact_assessment:ia-1.capability_path='p-missing'" in \
        validation.referential_errors
    assert "threat:threat-1.enabling_precursors.capability='p-missing'" in \
        validation.referential_errors
    assert "threat:threat-1.impact_ref='ia-missing'" in \
        validation.referential_errors


def test_a_vulnerability_may_yield_several_threats_one_per_manner(tmp_path):
    """The positive closure case: two exploitation manners of ONE vulnerability,
    each with its own damage row, its own capability path, and its own threat."""
    store = ThreatModelStore(tmp_path)
    second_row = {
        **_impact_assessment()[0],
        "id": "ia-2",
        "capability_id": "p-2",
        "capability": "change another tenant's item through the enumeration path",
        "impact_description": (
            "An anonymous caller changes another tenant's item through the "
            "enumeration path."),
        "capability_path": ["p-1"],
    }
    _write_to_completed(
        store,
        impact_assessment=[_impact_assessment()[0], second_row],
        threats=[
            _threat("high"),
            {
                **_threat("high"),
                "impact_ref": "ia-2",
                "enabling_precursors": [["p-1", "p-1"]],
            },
        ],
    )

    model = store.read_model(PROJECT, UNIT)

    assert model["validation"]["valid"] is True
    assert model["validation"]["missing"] == []
    assert model["validation"]["unclosed"] == []
    assert model["validation"]["referential_errors"] == []
    assert [row["id"] for row in model["impact_assessment"]] == ["ia-1", "ia-2"]
    assert [record["threat_id"] for record in store.read_threat_files(PROJECT, UNIT)] == [
        "threat-1", "threat-2",
    ]


def test_the_store_overwrites_an_authored_threat_risk(tmp_path):
    """The mirror is derived: a threat written with a score is overwritten from
    its assessment row (the tool schema forbids the field; the store enforces
    the value)."""
    store = ThreatModelStore(tmp_path)
    path = _write_gates(store)
    _seed_assessments(path, _impact_assessment())
    store.write_sections(
        PROJECT, UNIT, "COMPLETED",
        {"threats": [{**_threat("high"), "risk": 99.0}]}, run_id=RUN)

    model = store.read_model(PROJECT, UNIT)

    assert model["threats"][0]["risk"] == TOP_RISK
    assert model["risk_profile"]["total"] == TOP_RISK


def test_a_zero_score_threat_is_stored_but_emits_no_threat_file(tmp_path):
    """A zero score is no work: the threat stays in the model and the profile,
    and it is never dispatched. (A valid `threat` row scores above zero, so this
    state is also a completion finding.)"""
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store, threats=[_threat("none")])

    model = store.read_model(PROJECT, UNIT)
    assert model["threats"][0]["risk"] == 0.0
    assert model["risk_profile"]["total"] == 0.0
    assert store.read_threat_files(PROJECT, UNIT) == []
    assert any(
        finding.startswith("impact_assessment:ia-1.factors.confidentiality")
        for finding in model["validation"]["missing"]
    )


def test_the_threat_file_carries_the_assessment_and_the_risk(tmp_path):
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store, threats=[_threat("high")])

    record = store.read_threat_files(PROJECT, UNIT)[0]

    assert record["risk"] == TOP_RISK
    assert record["threat"]["risk"] == TOP_RISK
    assert record["impact"]["risk"] == TOP_RISK
    assert record["impact"]["risk_vector"] == TOP_VECTOR
    assert record["impact"]["impact_description"] == ITEM_DESCRIPTION
    assert record["impact"]["exploitability_description"] == ITEM_EXPLOITABILITY
    assert record["impact"]["factors"] == _factors("high")


# --- the impact assessment and the precursors (ticket 436) -------------------

def test_the_prior_art_gate_persists_the_section_and_refuses_it_elsewhere(tmp_path):
    """`PRIOR_ART` is the only gate that writes `prior_art`; the section round-
    trips as the typed section (three query kinds, the reused records, the note)."""
    store = ThreatModelStore(tmp_path)
    store.write_sections(
        PROJECT, UNIT, "PRIOR_ART", {"prior_art": _prior_art()}, run_id=RUN)

    model = store.read_model(PROJECT, UNIT)
    assert model["state"] == "PRIOR_ART"
    assert model["prior_art"]["queries"][0]["kind"] == "precursor"
    assert model["prior_art"]["reused"][0]["record_id"] == "p-2"
    assert model["prior_art"]["notes"]

    with pytest.raises(ThreatModelIdentityError) as raised:
        store.write_sections(
            PROJECT, UNIT, "TRUST_MODELLED",
            {"prior_art": _prior_art()}, run_id=RUN)
    assert raised.value.fields == ["prior_art"]


def test_completion_requires_the_three_prior_art_query_kinds_and_the_note(
        tmp_path):
    """S2 section 7: at least one query for threats, one for vulnerabilities,
    and one for precursors - each with a filter - plus a non-empty note. A
    missing kind and a missing note are completion findings."""
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store)
    document = store.read_model(PROJECT, UNIT)
    document["prior_art"]["queries"] = [
        query for query in document["prior_art"]["queries"]
        if query["kind"] == "precursor"
    ]
    document["prior_art"]["notes"] = ""

    validation = check_completion(UnitThreatModel.model_validate(document))

    assert validation.valid is False
    assert "prior_art.queries.threat" in validation.missing
    assert "prior_art.queries.vulnerability" in validation.missing
    assert "prior_art.queries.precursor" not in validation.missing
    assert "prior_art.notes" in validation.missing


def test_completion_requires_a_filter_on_each_prior_art_query(tmp_path):
    """A recorded query with no filter is the empty-filter dump the query tool
    refuses; the completion check reports it on that kind."""
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store)
    document = store.read_model(PROJECT, UNIT)
    for query in document["prior_art"]["queries"]:
        if query["kind"] == "precursor":
            query["filters"] = []

    validation = check_completion(UnitThreatModel.model_validate(document))

    assert validation.valid is False
    assert "prior_art.queries.precursor.filters" in validation.missing
    assert "prior_art.queries.threat" not in validation.missing
    assert "prior_art.queries.vulnerability" not in validation.missing


def test_the_three_prior_art_queries_and_the_note_close_the_check(tmp_path):
    store = ThreatModelStore(tmp_path)

    _write_to_completed(store)

    model = store.read_model(PROJECT, UNIT)
    assert model["validation"]["valid"] is True
    assert [query["kind"] for query in model["prior_art"]["queries"]] == [
        "precursor", "threat", "vulnerability",
    ]
    assert model["prior_art"]["notes"]


def test_the_impact_assessed_gate_accepts_no_model_section(tmp_path):
    """Schema 5: the `assess_impact` tool (ticket #406) is the sole writer of an
    assessment row, so the model-facing gate refuses the section outright."""
    store = ThreatModelStore(tmp_path)
    _write_gates(store)

    assert GATE_SECTIONS[ModelState.IMPACT_ASSESSED] == ()
    with pytest.raises(ThreatModelIdentityError) as raised:
        store.write_sections(
            PROJECT, UNIT, "IMPACT_ASSESSED",
            {"impact_assessment": _impact_assessment()}, run_id=RUN)

    assert raised.value.fields == ["impact_assessment"]
    assert store.read_model(PROJECT, UNIT)["state"] == "PRIOR_ART"
    assert store.read_model(PROJECT, UNIT)["impact_assessment"] == []


def test_the_impact_assessed_gate_refuses_an_empty_hunts_store_write(tmp_path):
    """The `assess_impact` tool owns the transition, so `hunts_store` cannot
    advance the gate with an empty payload either."""
    store = ThreatModelStore(tmp_path)
    _write_gates(store)

    with pytest.raises(ThreatModelIdentityError) as raised:
        store.write_sections(
            PROJECT, UNIT, "IMPACT_ASSESSED", {}, run_id=RUN)

    assert raised.value.fields == ["state"]
    assert store.read_model(PROJECT, UNIT)["state"] == "PRIOR_ART"


def _write_completed_document(store, path: Path, sections: dict) -> Path:
    """Write a COMPLETED document out of band.

    The store now refuses a COMPLETED write that skips a non-dropped
    vulnerability's assessment. The checker tests need an invalid document, so
    they write it directly; the checker remains the unit under test."""
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document.update(sections)
    document["state"] = "COMPLETED"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


def test_a_completed_write_without_an_assessment_is_rejected(tmp_path):
    """The pass cannot skip the impact assessment: a COMPLETED write that
    leaves a non-dropped vulnerability without a scored row is a coded
    rejection, so the model re-enters with the assess_impact feedback instead
    of the run archiving the unit as degraded."""
    store = ThreatModelStore(tmp_path)
    _write_gates(store)

    with pytest.raises(ThreatModelIdentityError) as raised:
        store.write_sections(
            PROJECT, UNIT, "COMPLETED", {"threats": [_threat()]}, run_id=RUN)

    assert raised.value.fields == ["impact_assessment"]
    assert "assess_impact" in str(raised.value)
    assert store.read_model(PROJECT, UNIT)["state"] == "PRIOR_ART"


def test_the_threat_file_carries_the_denormalised_impact_block(tmp_path):
    """The threat file carries the damage context (the row, its precursors, and
    the capability path), so a consumer needs no model document for it."""
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store)

    record = store.read_threat_files(PROJECT, UNIT)[0]

    assert record["impact"] == {
        "impact_ref": "ia-1",
        "impact_description": ITEM_DESCRIPTION,
        "exploitability_description": ITEM_EXPLOITABILITY,
        "disposition": "threat",
        "capability": "read another tenant's item",
        "capability_id": f"{UNIT}::p-1",
        "capability_path": [],
        "factors": _factors("high"),
        "risk": TOP_RISK,
        "risk_vector": TOP_VECTOR,
        "chain": [],
    }
    assert record["threat"]["impact_ref"] == "ia-1"
    assert record["threat"]["enabling_precursors"] == []


def test_a_precursor_produces_no_threat_file(tmp_path):
    """A precursor row stays in the model; only a `threat` row is dispatched."""
    store = ThreatModelStore(tmp_path)
    _write_to_completed(
        store, impact_assessment=_placeholder_assessment(), threats=[])

    model = store.read_model(PROJECT, UNIT)
    assert model["state"] == "COMPLETED"
    assert model["validation"]["valid"] is True
    assert model["validation"]["missing"] == []
    assert model["impact_assessment"][0]["disposition"] == "precursor"
    assert store.read_threat_files(PROJECT, UNIT) == []

    unit_name = "Service-catalogue-and-discovery"
    produced = (
        tmp_path / PROJECT / "hunting" / "threat_modeller" / "produced" / unit_name
    )
    assert list(produced.glob("threat-*.yaml")) == []


def test_check_completion_reports_a_broken_threat_order_and_ids(tmp_path):
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store, threats=[_threat("high"), _threat("medium", index=2)])
    document = store.read_model(PROJECT, UNIT)

    document["threats"].reverse()
    document["threats"][0]["id"] = "threat-1"
    document["threats"][1]["id"] = "threat-2"
    validation = check_completion(UnitThreatModel.model_validate(document))
    assert "threats.order" in validation.missing

    document["threats"][1]["id"] = "threat-7"
    validation = check_completion(UnitThreatModel.model_validate(document))
    assert "threats.ids" in validation.missing


def test_completion_reports_the_trust_model_referential_rules(tmp_path):
    store = ThreatModelStore(tmp_path)
    path = _write_gates(store)
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
    path = store.write_sections(
        PROJECT, UNIT, "VULNERABILITIES_WRITTEN",
        {"vulnerabilities": _vulnerabilities()}, run_id=RUN,
    )
    _seed_assessments(path, _impact_assessment())

    store.write_sections(PROJECT, UNIT, "COMPLETED", _completed_sections(), run_id=RUN)

    errors = store.read_model(PROJECT, UNIT)["validation"]["referential_errors"]
    assert "trust_agreement:ta-1.interface_agreement_refs='ia-missing'" in errors
    assert "transition:tr-1.state_ref='ds-missing'" in errors
    assert "violation:vi-1.maps_to_fault='fault-missing'" in errors
    assert "assumption:as-1.boundary_ref='ta-missing'" in errors


def test_completed_keeps_the_write_order_on_a_risk_tie(tmp_path):
    store = ThreatModelStore(tmp_path)
    threats = [
        _threat("low"),
        _threat("high", index=2),
        {**_threat("low", index=3), "canonical_class": "IDOR"},
    ]

    _write_to_completed(store, threats=threats)

    model = store.read_model(PROJECT, UNIT)
    assert [threat["id"] for threat in model["threats"]] == [
        "threat-1", "threat-2", "threat-3",
    ]
    # the higher row moved to rank 1; the two ties keep the write order
    assert [threat["impact_ref"] for threat in model["threats"]] == [
        "ia-2", "ia-1", "ia-3",
    ]
    assert [threat["risk"] for threat in model["threats"]] == [
        TOP_RISK, LOWER_RISK, LOWER_RISK,
    ]
    assert model["risk_profile"]["total"] == round(TOP_RISK + 2 * LOWER_RISK, 2)
    assert [record["threat_id"] for record in store.read_threat_files(PROJECT, UNIT)] == [
        "threat-1", "threat-2", "threat-3",
    ]


# --- consumption (the mover primitives, S2 8.4) ------------------------------

def _threat_modeller_root(tmp_path):
    return tmp_path / PROJECT / "hunting" / "threat_modeller"


def test_the_model_document_moves_with_its_last_threat_file(tmp_path):
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store, threats=[_threat("high"), _threat("medium", index=2)])
    unit_name = "Service-catalogue-and-discovery"

    assert store.consume_model_if_done(PROJECT, UNIT) is False  # threats remain
    assert store.consume_threat(PROJECT, UNIT, "threat-1") is True
    assert store.read_model(PROJECT, UNIT)["state"] == "COMPLETED"
    assert store.consume_threat(PROJECT, UNIT, "threat-1") is True  # at-least-once no-op
    assert store.consume_threat(PROJECT, UNIT, "threat-2") is True

    root = _threat_modeller_root(tmp_path)
    assert not (root / "produced" / unit_name).exists()
    assert (root / "consumed" / unit_name / f"{unit_name}.yaml").exists()
    assert store.read_completed_units(PROJECT) == [UNIT]
    assert store.read_model(PROJECT, UNIT)["state"] == "COMPLETED"


def test_a_zero_threat_completed_model_is_consumed_without_a_dispatch(tmp_path):
    store = ThreatModelStore(tmp_path)
    _write_zero_threat_completed(store)

    assert store.consume_model_if_done(PROJECT, UNIT) is True
    assert store.consume_model_if_done(PROJECT, UNIT) is True  # at-least-once

    assert store.read_completed_units(PROJECT) == [UNIT]
    assert store.read_threat_files(PROJECT, UNIT) == []
    unit_name = "Service-catalogue-and-discovery"
    root = _threat_modeller_root(tmp_path)
    assert not (root / "produced" / unit_name).exists()
    assert (root / "consumed" / unit_name / f"{unit_name}.yaml").exists()


def test_read_produced_threats_returns_the_unit_and_its_produced_threat_files(tmp_path):
    """S2 8.1/8.4 (T4, #377): the mover's dispatch inbox read - one entry per
    produced, consumable unit carrying the derived on-disk identity and the
    threat file records VERBATIM (an unreadable record is the mover's to refuse,
    never the store's to hide)."""
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store, threats=[_threat("high"), _threat("low", index=2)])
    unit_name = "Service-catalogue-and-discovery"

    entries = store.read_produced_threats(PROJECT)

    assert [(e["unit_id"], e["unit_name"], e["run_id"]) for e in entries] == [
        (UNIT, unit_name, RUN),
    ]
    assert [threat["threat_id"] for threat in entries[0]["threats"]] == ["threat-1", "threat-2"]
    record = entries[0]["threats"][0]["record"]
    assert record["dispatch_id"] == f"{unit_name}__threat-1"
    assert record["risk"] == TOP_RISK
    assert record["threat"]["id"] == "threat-1"


def test_read_produced_threats_is_empty_for_a_consumed_or_unconsumable_model(tmp_path):
    """The mover's inbox is the PRODUCED family only: a consumed (decided) unit
    is not dispatched again, and a model below COMPLETED (or invalid) is never
    dispatch input (S2 4.3, 5.7)."""
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store)
    store.consume_threat(PROJECT, UNIT, "threat-1")
    assert store.read_produced_threats(PROJECT) == []

    other = ThreatModelStore(tmp_path)
    other.write_sections(
        PROJECT, "Service:other", "UNIT_TECHNICAL_SHARP",
        {"technical_sharpening": _sharpening()}, run_id=RUN,
    )
    assert other.read_produced_threats(PROJECT) == []


def test_read_consumed_threats_reports_the_consumed_unit_and_its_model(tmp_path):
    """F-022: the recovery read is the SAME entry shape as the produced read,
    over the consumed family. The model document is the consumed one - the
    model moved with its last threat file - so a recovery dispatch never needs a
    re-model."""
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store, threats=[_threat("high")])
    assert store.consume_threat(PROJECT, UNIT, "threat-1") is True

    entries = store.read_consumed_threats(PROJECT)

    assert [(e["unit_id"], e["unit_name"], e["run_id"]) for e in entries] == [
        (UNIT, "Service-catalogue-and-discovery", RUN),
    ]
    assert [threat["threat_id"] for threat in entries[0]["threats"]] == ["threat-1"]
    assert entries[0]["threats"][0]["record"]["threat_id"] == "threat-1"
    assert entries[0]["model"]["unit_id"] == UNIT
    assert store.read_produced_threats(PROJECT) == []


def test_read_consumed_threats_falls_back_to_the_produced_model_for_a_multi_threat_unit(
        tmp_path):
    """F-022 model dependency: the model moves with the unit's LAST threat file.
    A consumed threat from a multi-threat unit therefore finds its original model
    still in produced/; the recovery read falls back to it and never re-models.
    Consuming the last threat moves the model, and both reads still agree."""
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store, threats=[_threat("high"), _threat("low", index=2)])
    assert store.consume_threat(PROJECT, UNIT, "threat-1") is True

    entries = store.read_consumed_threats(PROJECT)

    assert [threat["threat_id"] for threat in entries[0]["threats"]] == ["threat-1"]
    assert entries[0]["model"]["unit_id"] == UNIT
    assert [threat["threat_id"] for threat in
            store.read_produced_threats(PROJECT)[0]["threats"]] == ["threat-2"]

    assert store.consume_threat(PROJECT, UNIT, "threat-2") is True
    assert store.read_produced_threats(PROJECT) == []
    entries = store.read_consumed_threats(PROJECT)
    assert [threat["threat_id"] for threat in entries[0]["threats"]] == [
        "threat-1", "threat-2"]
    assert entries[0]["model"]["unit_id"] == UNIT


def test_read_produced_threats_reports_a_zero_threat_produced_model(tmp_path):
    """S2 8.4: a zero-threat produced COMPLETED valid model IS the mover's input -
    it carries no threat file, so the entry proves the model is consumable, and
    the mover consumes it without a dispatch."""
    store = ThreatModelStore(tmp_path)
    _write_zero_threat_completed(store)

    entries = store.read_produced_threats(PROJECT)

    assert len(entries) == 1
    assert entries[0]["unit_id"] == UNIT
    assert entries[0]["threats"] == []


def test_read_produced_threats_does_not_read_an_abandoned_unit(tmp_path):
    """S2 4.2/8.4: the mover ignores abandoned/ - a degraded unit's threat files
    are never dispatched (the archive moved them out of produced/)."""
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store)
    store.archive_unit(PROJECT, UNIT, "degraded (fixture)")

    assert store.read_produced_threats(PROJECT) == []


def test_read_produced_threats_reports_a_malformed_threat_file_instead_of_dropping_it(
        tmp_path):
    """S2 10.5 (T4a review F1): an unreadable or non-mapping threat file is
    REPORTED, never silently dropped - a dropped file would read as "the unit has
    no threats", the mover would try to consume the model, and the store would
    refuse because a `threat-*.yaml` remains: the run then never quiesces."""
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store, threats=[_threat("high")])
    unit_name = "Service-catalogue-and-discovery"
    produced = (_threat_modeller_root(tmp_path) / "produced" / unit_name)
    (produced / "threat-2.yaml").write_text("{[ unparseable", encoding="utf-8")
    (produced / "threat-3.yaml").write_text("- just\n- a\n- list\n", encoding="utf-8")

    entry = store.read_produced_threats(PROJECT)[0]

    assert [threat["threat_id"] for threat in entry["threats"]] == ["threat-1"]
    assert [broken["threat_id"] for broken in entry["malformed_threats"]] \
        == ["threat-2", "threat-3"]
    assert all(broken["reason"] for broken in entry["malformed_threats"])


def test_consume_model_if_done_ignores_the_refused_threat_files(tmp_path):
    """S2 10.5/8.4: the model-consume gate counts only PENDING threat files - a
    threat file the mover refused (a malformed body) can never dispatch or be
    consumed as a threat record, so it must not hold the model document."""
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store, threats=[_threat("high")])
    unit_name = "Service-catalogue-and-discovery"
    produced = (_threat_modeller_root(tmp_path) / "produced" / unit_name)
    (produced / "threat-2.yaml").write_text("{[ unparseable", encoding="utf-8")

    # a pending threat file still holds the model; a refused one does not
    assert store.consume_model_if_done(PROJECT, UNIT) is False
    assert store.consume_model_if_done(
        PROJECT, UNIT, refused_threats=("threat-1", "threat-2")) is True
    assert store.read_completed_units(PROJECT) == [UNIT]


def test_read_produced_units_reports_each_produced_model_and_its_run(tmp_path):
    """S2 9.3: the intake freeze reads the produced family itself - the unit id,
    the producing run, and the persisted state - so it can tell an in-flight
    model from a stale one."""
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store, threats=[_threat("high")])
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
    _write_zero_threat_completed(store)
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
    path = store.write_sections(
        PROJECT, UNIT, "VULNERABILITIES_WRITTEN",
        {"vulnerabilities": _vulnerabilities()}, run_id=RUN,
    )
    _seed_assessments(path, _impact_assessment())
    store.write_sections(PROJECT, UNIT, "COMPLETED", _completed_sections(), run_id=RUN)

    assert store.consume_model_if_done(PROJECT, UNIT) is False
    assert store.read_completed_units(PROJECT) == []

    archived = store.archive_unit(PROJECT, UNIT, "completion validation failed")

    unit_name = "Service-catalogue-and-discovery"
    root = _threat_modeller_root(tmp_path)
    assert archived == root / "abandoned" / unit_name
    assert not (root / "produced" / unit_name).exists()
    assert (archived / f"{unit_name}.yaml").exists()
    assert (archived / "threat-1.yaml").exists()  # the emitted threats move with it
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
    assert store.consume_threat(PROJECT, UNIT, "threat-1") is True
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

def test_the_default_threshold_is_exported(tmp_path):
    # The old per-threat maximum was 16, the new one 10: 250 * 0.625 (ADR 8).
    assert DEFAULT_RISK_THRESHOLD == 156.25


def test_reads_of_an_unknown_unit_are_empty(tmp_path):
    store = ThreatModelStore(tmp_path)

    assert store.read_model(PROJECT, "Service:absent") is None
    assert store.read_section(PROJECT, "Service:absent", "threats") is None
    assert store.read_threat_files(PROJECT, "Service:absent") == []
    assert store.read_completed_units(PROJECT) == []
    assert store.read_abandoned_units(PROJECT) == []
    assert store.read_notes(PROJECT) == []
    assert store.consume_model_if_done(PROJECT, "Service:absent") is False
    assert store.consume_threat(PROJECT, "Service:absent", "threat-1") is False


def test_a_retried_completed_write_repairs_the_threat_set(tmp_path, monkeypatch):
    store = ThreatModelStore(tmp_path)
    path = _write_gates(store)
    _seed_assessments(path, _impact_assessment())
    unit_name = "Service-catalogue-and-discovery"

    def _fail_the_model_write(path, body):
        if path.name == f"{unit_name}.yaml":
            raise OSError("simulated crash between the threat files and the commit")
        return _dump_yaml(path, body)

    monkeypatch.setattr(store, "_dump_yaml_atomic", _fail_the_model_write)
    with pytest.raises(OSError):
        store.write_sections(PROJECT, UNIT, "COMPLETED", _completed_sections(), run_id=RUN)
    monkeypatch.undo()

    store.write_sections(PROJECT, UNIT, "COMPLETED", _completed_sections(), run_id=RUN)

    model = store.read_model(PROJECT, UNIT)
    assert model["state"] == "COMPLETED"
    assert model["validation"]["valid"] is True
    assert [threat["id"] for threat in model["threats"]] == ["threat-1"]
    assert [record["threat_id"] for record in store.read_threat_files(PROJECT, UNIT)] == ["threat-1"]


def test_a_late_lower_gate_write_on_a_completed_model_keeps_the_threat_files(tmp_path):
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store)
    unit_name = "Service-catalogue-and-discovery"
    root = _threat_modeller_root(tmp_path)
    threat_file = root / "produced" / unit_name / "threat-1.yaml"
    before = threat_file.read_bytes()

    store.write_sections(
        PROJECT, UNIT, "UNIT_TECHNICAL_SHARP",
        {"technical_sharpening": {**_sharpening(), "data_flows": []}}, run_id=RUN,
    )

    model = store.read_model(PROJECT, UNIT)
    assert model["state"] == "COMPLETED"  # the state never regresses
    assert model["technical_sharpening"]["data_flows"] == []  # content still merges
    assert threat_file.read_bytes() == before  # the committed threat set is untouched


def test_consume_model_if_done_ignores_promotion_demoted_threat_files(tmp_path):
    """The model consume treats a promotion-demoted file as non-pending: the
    evidence stays in produced/, the model moves, and the run can quiesce."""
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store, threats=[_threat("high")])
    unit_name = "Service-catalogue-and-discovery"
    produced = (_threat_modeller_root(tmp_path) / "produced" / unit_name)
    (produced / "threat-2.yaml").write_text(
        "threat_id: threat-2\n", encoding="utf-8")

    assert store.consume_model_if_done(PROJECT, UNIT) is False
    assert store.consume_threat(PROJECT, UNIT, "threat-1") is True
    assert store.consume_model_if_done(
        PROJECT, UNIT, non_pending_threats=("threat-2",)) is True
    assert store.read_completed_units(PROJECT) == [UNIT]
    assert (produced / "threat-2.yaml").exists()


def test_a_v2_model_is_readable_for_intake_but_not_dispatched(tmp_path):
    """The spec keeps a v2 model readable for the intake and the measurement.
    The mover and the prior-art query stay on the current schema, so a v2
    threat file is never dispatched into the v3 hunter contract."""
    store = ThreatModelStore(root_dir=tmp_path)
    name = sanitise_unit_name(UNIT)
    directory = (
        tmp_path / PROJECT / "hunting" / "threat_modeller" / "consumed" / name
    )
    directory.mkdir(parents=True)
    document = {
        "schema_version": 2,
        "unit_id": UNIT,
        "state": "COMPLETED",
        "validation": {"valid": True},
        "threats": [{"id": "threat-1", "web_vulnerability_class": "idor"}],
    }
    (directory / f"{name}.yaml").write_text(
        yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    (directory / "threat-1.yaml").write_text(
        yaml.safe_dump(
            {"threat_id": "threat-1", "threat": {"id": "threat-1"}},
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    assert store.read_model(PROJECT, UNIT)["schema_version"] == 2
    assert store.read_completed_units(PROJECT) == [UNIT]
    assert store.read_threat_files(PROJECT, UNIT) == []
    assert store.read_consumed_threats(PROJECT) == []
    assert store.read_produced_threats(PROJECT) == []


# --- the capability-first query and cross-unit chain (schema 4) ---------------

def test_the_precursor_query_returns_precursor_rows_with_the_capability(tmp_path):
    store = ThreatModelStore(tmp_path)
    _write_to_completed(
        store, impact_assessment=_placeholder_assessment(), threats=[])

    result = store.query_prior_art(
        PROJECT,
        kind="precursor",
        filters=[{"path": "capability", "regex": "unmapped"}],
    )

    assert len(result["matches"]) == 1
    match = result["matches"][0]
    assert match["record_id"] == "ia-1"
    assert match["label"].startswith("distinguish an unmapped")
    assert match["disposition"] == "precursor"


def test_the_impact_query_returns_threat_rows_too(tmp_path):
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store)

    result = store.query_prior_art(
        PROJECT,
        kind="impact",
        filters=[{"path": "capability", "regex": "read another"}],
    )

    assert len(result["matches"]) == 1
    assert result["matches"][0]["disposition"] == "threat"


def test_the_v5_score_the_factors_and_the_vector_are_queryable(tmp_path):
    """The v5 paths are in the catalog beside the v4 ones (schema-5 spec 10)."""
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store)

    result = store.query_prior_art(
        PROJECT,
        kind="impact",
        filters=[
            {"path": "risk", "regex": "^9.2$"},
            {"path": "factors.confidentiality", "regex": "high"},
            {"path": "risk_vector", "regex": "^CVSS:4.0/"},
            {"path": "impact_description", "regex": "tenant"},
        ],
    )

    assert result["count"] == 1
    assert result["matches"][0]["record_id"] == "ia-1"


def _write_unit(store, unit_id, rows, threats):
    path = _write_gates(store, unit_id=unit_id)
    _seed_assessments(path, rows)
    store.write_sections(
        PROJECT, unit_id, "COMPLETED",
        {"threats": [_write_shape(row) for row in threats]}, run_id=RUN)


def test_a_capability_from_another_unit_resolves_and_lands_in_the_chain(tmp_path):
    store = ThreatModelStore(tmp_path)
    _write_unit(
        store,
        "First",
        rows=[_precursor_row("p-1")],
        threats=[],
    )
    second_row = {
        **_impact_assessment()[0],
        "capability_path": ["First::p-1"],
    }
    _write_unit(
        store,
        "Second",
        rows=[second_row],
        threats=[{
            **_threat(),
            "enabling_precursors": [["First::p-1", "First::p-1"]],
        }],
    )

    model = store.read_model(PROJECT, "Second")
    assert model["validation"]["valid"] is True
    record = store.read_threat_files(PROJECT, "Second")[0]
    assert record["impact"]["capability_path"] == ["First::p-1"]
    chain = record["impact"]["chain"]
    assert chain[0]["capability"] == "First::p-1"
    assert chain[0]["precursor"] == "First::p-1"
    assert chain[0]["resolved"]["row"]["capability_id"] == "p-1"


def test_a_self_qualified_capability_resolves_locally(tmp_path):
    """A model may qualify its own capability; resolution stays local."""
    store = ThreatModelStore(tmp_path)
    precursor = {**_precursor_row("p-1"), "id": "ia-1"}
    threat_row = {
        **_impact_assessment()[0],
        "id": "ia-2",
        "capability_id": "p-2",
        "capability_path": [f"{UNIT}::p-1"],
    }
    _write_to_completed(
        store,
        impact_assessment=[precursor, threat_row],
        threats=[{
            **_threat(),
            "impact_ref": "ia-2",
            "enabling_precursors": [[f"{UNIT}::p-1", f"{UNIT}::p-1"]],
        }],
    )

    model = store.read_model(PROJECT, UNIT)
    assert model["validation"]["valid"] is True
    assert model["validation"]["referential_errors"] == []


# --- the assessment write (the `assess_impact` seam, ticket #406) -------------

def _assessment_args(**overrides) -> dict:
    """The v5 row fields one `write_impact_assessment` call carries.

    The fixture row's derived `risk` and `risk_vector` are deliberately dropped:
    the store is the only authority that computes them.
    """
    row = _impact_assessment()[0]
    return {
        "id": row["id"],
        "vulnerability_ref": row["vulnerability_ref"],
        "disposition": row["disposition"],
        "impact_description": row["impact_description"],
        "exploitability_description": row["exploitability_description"],
        "capability": row["capability"],
        "capability_id": row["capability_id"],
        "capability_path": row["capability_path"],
        "evidence_refs": row["evidence_refs"],
        "factors": row["factors"],
        **overrides,
    }


def test_write_impact_assessment_computes_the_score_and_persists_the_row(tmp_path):
    """The row's `risk` and `risk_vector` are DERIVED at the write: the caller
    authors the eight factors only, and the persisted document carries the
    score the CVSS 4.0 library gives the factor set."""
    store = ThreatModelStore(tmp_path)
    _write_gates(store)

    row = store.write_impact_assessment(PROJECT, UNIT, RUN, **_assessment_args())

    assert row.id == "ia-1"
    assert row.risk == TOP_RISK
    assert row.risk_vector == TOP_VECTOR
    model = store.read_model(PROJECT, UNIT)
    assert model["state"] == "IMPACT_ASSESSED"
    assert model["impact_assessment"][0]["risk"] == TOP_RISK
    assert model["impact_assessment"][0]["risk_vector"] == TOP_VECTOR
    assert model["impact_assessment"][0]["factors"] == _factors("high")


def test_the_first_assessment_advances_the_state_and_a_later_call_appends(tmp_path):
    """The first successful call owns the `IMPACT_ASSESSED` transition; a second
    row for the same vulnerability is admitted with its own capability id."""
    store = ThreatModelStore(tmp_path)
    _write_gates(store)
    assert store.read_model(PROJECT, UNIT)["state"] == "PRIOR_ART"

    store.write_impact_assessment(PROJECT, UNIT, RUN, **_assessment_args())
    assert store.read_model(PROJECT, UNIT)["state"] == "IMPACT_ASSESSED"

    store.write_impact_assessment(PROJECT, UNIT, RUN, **{
        **_assessment_args(),
        "id": "ia-2",
        "capability_id": "p-2",
        "capability": "change another tenant's item",
        "impact_description": (
            "An anonymous caller changes another tenant's item."),
    })

    model = store.read_model(PROJECT, UNIT)
    assert model["state"] == "IMPACT_ASSESSED"
    assert [row["id"] for row in model["impact_assessment"]] == ["ia-1", "ia-2"]


def test_a_duplicate_row_id_replaces_the_row(tmp_path):
    store = ThreatModelStore(tmp_path)
    _write_gates(store)
    store.write_impact_assessment(PROJECT, UNIT, RUN, **_assessment_args())

    row = store.write_impact_assessment(PROJECT, UNIT, RUN, **{
        **_assessment_args(),
        "impact_description": "An amended claim.",
        "factors": _factors("low"),
    })

    rows = store.read_model(PROJECT, UNIT)["impact_assessment"]
    assert len(rows) == 1
    assert rows[0]["impact_description"] == "An amended claim."
    assert row.risk == LOWER_RISK
    assert rows[0]["risk"] == LOWER_RISK
    assert rows[0]["risk_vector"] == LOWER_VECTOR


def test_a_duplicate_capability_id_on_the_same_vulnerability_is_rejected(tmp_path):
    store = ThreatModelStore(tmp_path)
    _write_gates(store)
    store.write_impact_assessment(PROJECT, UNIT, RUN, **_assessment_args())

    with pytest.raises(ImpactAssessmentError) as raised:
        store.write_impact_assessment(
            PROJECT, UNIT, RUN, **{**_assessment_args(), "id": "ia-2"})

    assert raised.value.fields == ["capability_id"]
    assert [
        row["id"] for row in store.read_model(PROJECT, UNIT)["impact_assessment"]
    ] == ["ia-1"]


def test_an_unknown_vulnerability_ref_is_rejected(tmp_path):
    store = ThreatModelStore(tmp_path)
    _write_gates(store)

    with pytest.raises(ImpactAssessmentError) as raised:
        store.write_impact_assessment(
            PROJECT, UNIT, RUN,
            **{**_assessment_args(), "vulnerability_ref": "v-missing"})

    assert raised.value.fields == ["vulnerability_ref"]
    assert store.read_model(PROJECT, UNIT)["impact_assessment"] == []


def test_a_precursor_row_with_a_non_none_impact_is_rejected(tmp_path):
    store = ThreatModelStore(tmp_path)
    _write_gates(store)

    with pytest.raises(ImpactAssessmentError) as raised:
        store.write_impact_assessment(
            PROJECT, UNIT, RUN,
            **{**_assessment_args(), "disposition": "precursor"})

    assert raised.value.fields == ["factors"]
    assert store.read_model(PROJECT, UNIT)["impact_assessment"] == []


def test_a_malformed_assessment_id_is_rejected(tmp_path):
    store = ThreatModelStore(tmp_path)
    _write_gates(store)

    with pytest.raises(ImpactAssessmentError) as raised:
        store.write_impact_assessment(
            PROJECT, UNIT, RUN, **{**_assessment_args(), "id": "row-1"})

    assert raised.value.fields == ["id"]


def test_the_assessment_write_is_accepted_only_at_prior_art_or_impact_assessed(
        tmp_path):
    """The `IMPACT_ASSESSED` gate is tool-only, so the write needs the gate
    below it: a model still writing vulnerabilities has nothing to assess."""
    store = ThreatModelStore(tmp_path)
    store.write_sections(
        PROJECT, UNIT, "VULNERABILITIES_WRITTEN",
        {"vulnerabilities": _vulnerabilities()}, run_id=RUN)

    with pytest.raises(ImpactAssessmentError) as raised:
        store.write_impact_assessment(PROJECT, UNIT, RUN, **_assessment_args())

    assert raised.value.fields == ["state"]
    assert store.read_model(PROJECT, UNIT)["impact_assessment"] == []


def test_the_assessment_write_resolves_a_capability_path(tmp_path):
    """A path element resolves to a local capability row and to another unit's
    qualified capability; an unresolved element is a coded rejection."""
    store = ThreatModelStore(tmp_path)
    _write_gates(store)
    store.write_impact_assessment(PROJECT, UNIT, RUN, **_assessment_args())

    row = store.write_impact_assessment(PROJECT, UNIT, RUN, **{
        **_assessment_args(),
        "id": "ia-2",
        "capability_id": "p-2",
        "capability": "change another tenant's item",
        "capability_path": ["p-1"],
    })
    assert row.capability_path == ["p-1"]

    with pytest.raises(ImpactAssessmentError) as raised:
        store.write_impact_assessment(PROJECT, UNIT, RUN, **{
            **_assessment_args(),
            "id": "ia-3",
            "capability_id": "p-3",
            "capability_path": ["p-missing"],
        })
    assert raised.value.fields == ["capability_path"]


def test_the_assessment_write_resolves_a_capability_of_another_unit(tmp_path):
    store = ThreatModelStore(tmp_path)
    first = "First"
    second = "Second"
    _write_gates(store, unit_id=first)
    store.write_impact_assessment(PROJECT, first, RUN, **_assessment_args(
        id="ia-1",
        disposition="precursor",
        capability="enumerate the item ids",
        factors=_factors("none"),
    ))
    _write_gates(store, unit_id=second)

    row = store.write_impact_assessment(
        PROJECT, second, RUN,
        **_assessment_args(capability_path=[f"{first}::p-1"]))

    assert row.capability_path == [f"{first}::p-1"]


def test_a_v4_document_is_refused_for_the_assessment_write(tmp_path):
    """Schema 5 spec 11: the v5 assessment writer refuses a v4 document and
    leaves it untouched; the v4 read stays raw."""
    store = ThreatModelStore(tmp_path)
    name = "Service-catalogue-and-discovery"
    unit_dir = tmp_path / PROJECT / "hunting" / "threat_modeller" / "produced" / name
    unit_dir.mkdir(parents=True)
    document = unit_dir / f"{name}.yaml"
    document.write_text(
        yaml.safe_dump({
            "schema_version": 4,
            "unit_id": UNIT,
            "state": "IMPACT_ASSESSED",
        }, sort_keys=False),
        encoding="utf-8",
    )
    before = document.read_bytes()

    with pytest.raises(ThreatModelSchemaVersionError) as raised:
        store.write_impact_assessment(PROJECT, UNIT, RUN, **_assessment_args())

    assert raised.value.version == 4
    assert document.read_bytes() == before
    assert store.read_model(PROJECT, UNIT)["schema_version"] == 4


# --- the COMPLETED risk mirror (schema-5 spec 3) -----------------------------

def test_the_completed_write_mirrors_the_row_risk_and_rejects_a_mismatch(tmp_path):
    """The threat file's score is the assessment row's derived score; a threat
    whose mirror disagrees is a completion finding, so the model is never
    consumable."""
    store = ThreatModelStore(tmp_path)
    _write_gates(store)
    store.write_impact_assessment(PROJECT, UNIT, RUN, **_assessment_args())
    store.write_sections(
        PROJECT, UNIT, "COMPLETED", _completed_sections(), run_id=RUN)

    model = store.read_model(PROJECT, UNIT)
    assert model["threats"][0]["risk"] == TOP_RISK
    assert model["validation"]["valid"] is True
    assert store.read_threat_files(PROJECT, UNIT)[0]["risk"] == TOP_RISK

    model["threats"][0]["risk"] = 0.0
    validation = check_completion(UnitThreatModel.model_validate(model))

    assert validation.valid is False
    assert "threat:threat-1.risk" in validation.missing


def test_the_completed_mirror_never_takes_another_vulnerability_row(tmp_path):
    """The assessment is the scored claim for THAT exploitation: a threat of
    v-2 that names v-1's row is not scored from it, so the mismatch is rejected
    (no threat file, the checker's finding) instead of silently dispatched."""
    store = ThreatModelStore(tmp_path)
    _write_gates(store)
    second_vulnerability = {
        **_vulnerabilities()[0],
        "id": "v-2",
        "canonical_class": "Path Traversal",
        "characterisation": "An anonymous caller reads a file outside the root.",
    }
    path = store.write_sections(
        PROJECT, UNIT, "VULNERABILITIES_WRITTEN",
        {"vulnerabilities": [_vulnerabilities()[0], second_vulnerability]},
        run_id=RUN,
    )
    _seed_assessments(path, _impact_assessment())
    _write_completed_document(store, path, {"threats": [{
        **_write_shape(_threat("high")),
        "vulnerability_ref": "v-2",
        "canonical_class": "Path Traversal",
    }]})

    model = UnitThreatModel.model_validate(store.read_model(PROJECT, UNIT))
    validation = check_completion(model)
    assert validation.valid is False
    assert any(
        finding.startswith("threat:") and finding.endswith(".impact_ref")
        for finding in validation.unclosed)
    assert store.read_threat_files(PROJECT, UNIT) == []


def test_the_v5_threat_file_carries_no_retired_risk_key(tmp_path):
    """The threat file carries the float score and the v5 assessment block; the
    retired likelihood, confidence, risk-factor, and CIA vocabulary is gone."""
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store)

    record = store.read_threat_files(PROJECT, UNIT)[0]

    assert record["risk"] == TOP_RISK
    assert isinstance(record["risk"], float)
    assert record["threat"]["risk"] == TOP_RISK
    for key in (
        "likelihood", "likelihood_rationale", "risk_factors", "confidence",
        "impact_weight",
    ):
        assert key not in record["threat"]
        assert key not in record
    assert "impact" not in record["threat"]
    assert set(record["impact"]) == {
        "impact_ref",
        "impact_description",
        "exploitability_description",
        "disposition",
        "capability",
        "capability_id",
        "capability_path",
        "factors",
        "risk",
        "risk_vector",
        "chain",
    }


def test_the_v5_threat_view_paths_resolve(tmp_path):
    """The `threat` view merges the threat file with its assessment row, so the
    v5 paths resolve at the view level (schema-5 spec 10)."""
    store = ThreatModelStore(tmp_path)
    _write_to_completed(store)

    result = store.query_prior_art(
        PROJECT,
        kind="threat",
        filters=[
            {"path": "risk", "regex": f"^{TOP_RISK}$"},
            {"path": "risk_vector", "regex": "^CVSS:4.0/"},
            {"path": "impact_description", "regex": "tenant"},
            {"path": "exploitability_description", "regex": "unauthenticated"},
            {"path": "factors.confidentiality", "regex": "^high$"},
        ],
    )

    assert result["count"] == 1
    assert result["matches"][0]["record_id"] == "threat-1"
