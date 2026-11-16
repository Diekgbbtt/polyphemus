"""Unit tier: the measurement substrate for threat breadth and spec discrimination.

The operator's next-trial question has two deterministic halves:

- Is the bound vulnerability class a parent class (a broad class with variants)?
- Is the discriminated spec set substantial (at least three specs) and
  well-formed (the primary discrimination axes do not overlap)?

The impact metric is the third half: the red/green share over the impact rows,
the CIA distribution, the placeholder share, the v2 legacy recomputation, and
the v5 scored rows (the derived risk, the band, and the two prose blocks).

The semantic judgement stays with the measurement subagent; these functions
produce the substrate it reads.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

import measure_utm


def _skill(root: Path, name: str, *, parent: bool = False, variants: tuple[str, ...] = ()) -> None:
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
    if parent:
        for variant in variants:
            child = directory / variant
            child.mkdir()
            (child / "SKILL.md").write_text(f"# {variant}\n", encoding="utf-8")


def test_is_bound_class_counts_a_leaf_and_a_parent_but_not_an_absent_name():
    index = {"ssrf": 2, "xss": 0}

    assert measure_utm.is_bound_class("ssrf", index) is True
    assert measure_utm.is_bound_class("xss", index) is True
    assert measure_utm.is_bound_class("not-in-suite", index) is False
    assert measure_utm.is_bound_class("", index) is False


def test_the_suite_index_marks_a_class_with_variants_as_a_parent(tmp_path):
    _skill(tmp_path, "ssrf", parent=True, variants=("metadata-read", "egress"))
    _skill(tmp_path, "xss")

    index = measure_utm.suite_index(tmp_path)

    assert index["ssrf"] == 2
    assert index["xss"] == 0
    assert index["metadata-read"] == 0
    assert measure_utm.is_broad_class("ssrf", index) is True
    assert measure_utm.is_broad_class("xss", index) is False
    assert measure_utm.is_broad_class("metadata-read", index) is False
    assert measure_utm.is_broad_class("not-in-the-suite", index) is None


def _spec(*axes: str) -> dict:
    return {
        "discriminators": [
            {"axis": axis, "value": f"value-{number}"}
            for number, axis in enumerate(axes)
        ],
    }


def test_three_specs_on_distinct_primary_axes_are_substantial_and_well_formed():
    summary = measure_utm.discrimination_summary([
        _spec("technique", "state"),
        _spec("actor", "surface"),
        _spec("data-flow", "technology"),
    ])

    assert summary["spec_count"] == 3
    assert summary["substantial"] is True
    assert summary["primary_axes"] == ["technique", "actor", "data-flow"]
    assert summary["axes_overlap"] is False
    assert summary["well_formed"] is True


def test_three_specs_sharing_a_primary_axis_overlap():
    summary = measure_utm.discrimination_summary([
        _spec("payload-vector", "state"),
        _spec("payload-vector", "actor"),
        _spec("payload-vector", "surface"),
    ])

    assert summary["substantial"] is True
    assert summary["axes_overlap"] is True
    assert summary["well_formed"] is False


def test_a_two_spec_set_is_not_substantial():
    summary = measure_utm.discrimination_summary([
        _spec("technique", "state"),
        _spec("actor", "surface"),
    ])

    assert summary["substantial"] is False
    assert summary["well_formed"] is False


def test_a_spec_without_discriminators_is_malformed():
    summary = measure_utm.discrimination_summary([
        _spec("technique", "state"),
        _spec("actor", "surface"),
        {"discriminators": []},
    ])

    assert summary["missing_discriminators"] == 1
    assert summary["well_formed"] is False


def test_load_models_reads_the_threat_files(tmp_path):
    unit = tmp_path / "produced" / "Service-catalogue"
    unit.mkdir(parents=True)
    (unit / "Service-catalogue.yaml").write_text(
        yaml.safe_dump({"unit_id": "Service:catalogue", "threats": [{"id": "threat-1"}]}),
        encoding="utf-8",
    )
    (unit / "threat-1.yaml").write_text(
        yaml.safe_dump({"threat_id": "threat-1", "threat": {"id": "threat-1"}}),
        encoding="utf-8",
    )

    models, threats = measure_utm.load_models(tmp_path)

    assert [model["unit_id"] for model in models] == ["Service:catalogue"]
    assert [threat["threat_id"] for threat in threats] == ["threat-1"]


def test_load_models_reads_the_legacy_loop_files_under_the_threat_names(tmp_path):
    unit = tmp_path / "produced" / "Service-billing"
    unit.mkdir(parents=True)
    (unit / "Service-billing.yaml").write_text(
        yaml.safe_dump({"schema_version": 2, "unit_id": "Service:billing"}),
        encoding="utf-8",
    )
    (unit / "loop-1.yaml").write_text(
        yaml.safe_dump({
            "loop_id": "loop-1",
            "unit_id": "Service:billing",
            "loop": {
                "id": "loop-1",
                "web_vulnerability_class": "idor",
                "impact": {
                    "confidentiality": "high",
                    "integrity": "none",
                    "availability": "none",
                },
            },
        }),
        encoding="utf-8",
    )

    models, threats = measure_utm.load_models(tmp_path)

    assert [model["unit_id"] for model in models] == ["Service:billing"]
    assert [row["threat_id"] for row in threats] == ["loop-1"]
    assert threats[0]["_legacy"] is True
    assert threats[0]["threat"]["web_vulnerability_class"] == "idor"


def test_threat_downstream_links_specs_by_provenance_threat_id():
    threat = {"threat_id": "threat-1"}
    specs = [
        {"threat_id": "threat-1", **_spec("technique", "state")},
        {"threat_id": "threat-1", **_spec("actor", "surface")},
        {"threat_id": "threat-1", **_spec("data-flow", "technology")},
        {"threat_id": "threat-2", **_spec("technique", "state")},
    ]

    downstream = measure_utm.threat_downstream(threat, specs)

    assert downstream["spec_count"] == 3
    assert downstream["well_formed"] is True


def test_the_measurement_prompt_carries_the_narrowing_rubric():
    prompt = (
        Path(__file__).resolve().parents[2] / "eval" / "prompts" / "measure.md"
    ).read_text(encoding="utf-8")
    for clause in (
        "bound_class_is_parent",
        "breadth: broad | narrow | unknown",
        "spec_count",
        "axes_overlap",
        "well_formed",
        "narrowing:",
        "substantial_and_well_formed",
    ):
        assert clause in prompt, clause


def test_a_dispatch_id_provenance_value_keeps_the_full_identity():
    assert measure_utm.threat_id_of(
        {"threat_id": "Service-sign-in__threat-1"}
    ) == "Service-sign-in__threat-1"
    assert measure_utm.threat_id_of({"threat_id": "threat-1"}) == "threat-1"
    assert measure_utm.threat_id_of({}) == ""


def test_spec_metrics_keeps_the_full_dispatch_id_and_its_suffix():
    spec = {
        "target_identity": {"unit_id": "Service:sign-in"},
        "verification_symptoms": "a symptom",
        "assumptions": [],
        "rationale": "a rationale",
        "provenance": {"threat_id": "Service-sign-in__threat-1"},
        "discriminators": [{"axis": "technique", "value": "burst"}],
    }

    identity = {
        "expected_id": "Service:sign-in",
        "names": ["Service:sign-in"],
        "fault_class": "",
        "location": "",
    }
    row = measure_utm.spec_metrics(spec, {"type": ""}, identity)

    assert row["threat_id"] == "Service-sign-in__threat-1"
    assert row["threat_id_suffix"] == "threat-1"


# --- the impact metric (spec section 9) --------------------------------------

def _v3_model(root: Path, *, threat_file: bool = True) -> None:
    """The prototype's worked example: one placeholder, one damage-bearing row.

    IA-2 is the threat `H/M/N`; IA-1 is the placeholder `N/N/N`. The precursors
    are P-1..P-4, and one prior-art record is reused.
    """
    unit = root / "produced" / "Service-catalogue"
    unit.mkdir(parents=True)
    (unit / "Service-catalogue.yaml").write_text(
        yaml.safe_dump({
            "schema_version": 3,
            "unit_id": "Service:catalogue",
            "state": "COMPLETED",
            "prior_art": {
                "queries": [
                    {
                        "kind": "threat",
                        "filters": [{"path": "threat.canonical_class", "regex": "idor"}],
                        "result_count": 1,
                    },
                    {
                        "kind": "vulnerability",
                        "filters": [{"path": "web_vulnerability_class", "regex": "idor"}],
                        "result_count": 1,
                    },
                    {
                        "kind": "precursor",
                        "filters": [{"path": "capability", "regex": "read"}],
                        "result_count": 1,
                    },
                ],
                "reused": [{
                    "unit_id": "Service:sign-in",
                    "record_id": "P-9",
                    "kind": "precursor",
                    "reason": "same item read",
                }],
                "notes": "the item read precursor is reused",
            },
            "impact_assessment": [
                {
                    "id": "IA-1",
                    "vulnerability_ref": "V-1",
                    "disposition": "placeholder",
                    "damage": "No user or application property is affected; the handler returns a generic envelope.",
                    "precursor_refs": ["P-1"],
                    "capability_path": [],
                    "evidence_refs": [],
                },
                {
                    "id": "IA-2",
                    "vulnerability_ref": "V-2",
                    "disposition": "threat",
                    "damage": "An unauthenticated caller reads live session material from the process dump.",
                    "precursor_refs": ["P-2", "P-3", "P-4"],
                    "capability_path": ["P-2", "P-3", "P-4"],
                    "evidence_refs": [],
                },
            ],
            "precursors": [
                {
                    "id": f"P-{number}",
                    "capability": f"capability {number}",
                    "procedure": f"abstract procedure {number}",
                    "evidence_refs": [],
                }
                for number in range(1, 5)
            ],
            "threats": [{
                "id": "threat-1",
                "impact_ref": "IA-2",
                "canonical_class": "IDOR",
                "web_vulnerability_class": "idor",
                "impact": {
                    "confidentiality": "high",
                    "integrity": "medium",
                    "availability": "none",
                },
            }],
        }),
        encoding="utf-8",
    )
    if not threat_file:
        # A zero-risk threat is stored in the model but emits no threat file.
        return
    (unit / "threat-1.yaml").write_text(
        yaml.safe_dump({
            "threat_id": "threat-1",
            "unit_id": "Service:catalogue",
            "likelihood": "high",
            "threat": {
                "id": "threat-1",
                "impact_ref": "IA-2",
                "web_vulnerability_class": "idor",
                "impact": {
                    "confidentiality": "high",
                    "integrity": "medium",
                    "availability": "none",
                },
            },
            "impact": {
                "impact_ref": "IA-2",
                "disposition": "threat",
                "damage": "An unauthenticated caller reads live session material from the process dump.",
                "capability_path": ["P-2", "P-3", "P-4"],
            },
        }),
        encoding="utf-8",
    )


def test_the_impact_metric_counts_a_v3_threat_and_a_placeholder(tmp_path):
    _v3_model(tmp_path)
    models, threats = measure_utm.load_models(tmp_path)

    metric = measure_utm.impact_metric(models, threats)

    assert metric["schema"] == "v3"
    assert metric["legacy_recomputation"] is False
    assert metric["impact_rows"] == 2
    assert metric["threats"] == 1
    assert metric["placeholders"] == 1
    assert metric["red"] == 1
    assert metric["green"] == 1
    assert metric["green_share"] == 0.5
    assert metric["threat_share"] == 0.5
    assert metric["placeholder_share"] == 0.5


def test_the_impact_metric_ignores_an_abandoned_copy(tmp_path):
    """An abandoned copy is a degraded retry, not a second damage claim. The
    loader reads it; the primary metric does not count its rows twice."""
    _v3_model(tmp_path)
    produced = (
        tmp_path / "produced" / "Service-catalogue" / "Service-catalogue.yaml")
    abandoned = tmp_path / "abandoned" / "Service-catalogue"
    abandoned.mkdir(parents=True)
    (abandoned / "Service-catalogue.yaml").write_text(
        produced.read_text(encoding="utf-8"), encoding="utf-8")
    models, threats = measure_utm.load_models(tmp_path)
    assert any(model.get("_family") == "abandoned" for model in models)

    metric = measure_utm.impact_metric(models, threats)

    assert metric["impact_rows"] == 2
    assert metric["green"] == 1
    assert metric["red"] == 1


def test_the_impact_metric_reports_a_mixed_store_in_two_blocks(tmp_path):
    """A v2 unit and a v3 unit in one project: the v3 block is primary, the v2
    rows ride a legacy sub-block instead of vanishing."""
    _v3_model(tmp_path)
    legacy = tmp_path / "consumed" / "Service-legacy"
    legacy.mkdir(parents=True)
    (legacy / "Service-legacy.yaml").write_text(
        yaml.safe_dump({
            "schema_version": 2,
            "unit_id": "Service:legacy",
            "state": "COMPLETED",
            "validation": {"valid": True},
        }),
        encoding="utf-8",
    )
    (legacy / "loop-1.yaml").write_text(
        yaml.safe_dump({
            "loop": {
                "impact": {
                    "confidentiality": "high",
                    "integrity": "none",
                    "availability": "none",
                },
            },
        }),
        encoding="utf-8",
    )
    models, threats = measure_utm.load_models(tmp_path)

    metric = measure_utm.impact_metric(models, threats)

    assert metric["schema"] == "mixed"
    assert metric["impact_rows"] == 2
    assert metric["legacy_v2"]["schema"] == "v2"
    assert metric["legacy_v2"]["impact_rows"] == 1
    assert metric["legacy_v2"]["green"] == 1


def test_the_impact_metric_reports_the_cia_distribution_and_the_counts(tmp_path):
    _v3_model(tmp_path)
    models, threats = measure_utm.load_models(tmp_path)

    metric = measure_utm.impact_metric(models, threats, {"idor": 0})

    assert metric["cia"] == {
        "confidentiality": {"none": 1, "low": 0, "medium": 0, "high": 1},
        "integrity": {"none": 1, "low": 0, "medium": 1, "high": 0},
        "availability": {"none": 2, "low": 0, "medium": 0, "high": 0},
    }
    assert metric["precursors"] == 4
    assert metric["prior_art_reused"] == 1
    assert metric["class_binding_rate"] == 1.0


def test_a_green_row_reads_its_cia_vector_from_the_model_threat(tmp_path):
    """A zero-risk threat is stored in the model and emits no threat file."""
    _v3_model(tmp_path, threat_file=False)
    models, threats = measure_utm.load_models(tmp_path)

    metric = measure_utm.impact_metric(models, threats)

    assert metric["green"] == 1
    assert metric["green_share"] == 0.5


def test_the_impact_metric_degrades_when_no_model_is_readable():
    metric = measure_utm.impact_metric([], [])

    assert metric["schema"] is None
    assert metric["impact_rows"] == 0
    assert metric["green"] == 0
    assert metric["green_share"] is None
    assert metric["precursors"] == 0
    assert metric["prior_art_reused"] == 0
    assert metric["class_binding_rate"] is None


def _v2_model(root: Path) -> None:
    """A v2 model: two `loop-*.yaml` artifacts, one green and one red."""
    unit = root / "produced" / "Service-billing"
    unit.mkdir(parents=True)
    (unit / "Service-billing.yaml").write_text(
        yaml.safe_dump({
            "schema_version": 2,
            "unit_id": "Service:billing",
            "state": "COMPLETED",
            "loops": [{"id": "loop-1"}, {"id": "loop-2"}],
        }),
        encoding="utf-8",
    )
    for rank, (suite_class, impact) in enumerate((
        ("idor", {
            "confidentiality": "high", "integrity": "none", "availability": "none",
        }),
        ("xss", {
            "confidentiality": "none", "integrity": "none", "availability": "none",
        }),
    ), start=1):
        (unit / f"loop-{rank}.yaml").write_text(
            yaml.safe_dump({
                "loop_id": f"loop-{rank}",
                "unit_id": "Service:billing",
                "loop": {
                    "id": f"loop-{rank}",
                    "web_vulnerability_class": suite_class,
                    "impact": impact,
                },
            }),
            encoding="utf-8",
        )


def test_a_v2_model_is_reported_as_a_legacy_recomputation(tmp_path):
    _v2_model(tmp_path)
    models, threats = measure_utm.load_models(tmp_path)

    metric = measure_utm.impact_metric(models, threats, {"idor": 0})

    assert metric["schema"] == "v2"
    assert metric["legacy_recomputation"] is True
    assert metric["impact_rows"] == 2
    assert metric["green"] == 1
    assert metric["red"] == 1
    assert metric["green_share"] == 0.5
    assert metric["threats"] is None
    assert metric["placeholders"] is None
    assert metric["threat_share"] is None
    assert metric["placeholder_share"] is None
    assert metric["cia"]["confidentiality"] == {
        "none": 1, "low": 0, "medium": 0, "high": 1,
    }
    assert metric["precursors"] is None
    assert metric["prior_art_reused"] is None
    assert metric["class_binding_rate"] == 0.5


def test_a_schema_two_threat_file_is_a_legacy_row(tmp_path):
    """The iteration B artifacts are schema-2 `threat-*.yaml`, not `loop-*`."""
    unit = tmp_path / "produced" / "Service-catalogue"
    unit.mkdir(parents=True)
    (unit / "Service-catalogue.yaml").write_text(
        yaml.safe_dump({"schema_version": 2, "unit_id": "Service:catalogue"}),
        encoding="utf-8",
    )
    (unit / "threat-1.yaml").write_text(
        yaml.safe_dump({
            "threat_id": "threat-1",
            "unit_id": "Service:catalogue",
            "threat": {
                "id": "threat-1",
                "web_vulnerability_class": "information-disclosure",
                "impact": {
                    "confidentiality": "medium",
                    "integrity": "none",
                    "availability": "none",
                },
            },
        }),
        encoding="utf-8",
    )

    models, threats = measure_utm.load_models(tmp_path)
    metric = measure_utm.impact_metric(models, threats)

    assert metric["schema"] == "v2"
    assert metric["impact_rows"] == 1
    assert metric["green"] == 1
    assert metric["green_share"] == 1.0


def test_the_measurement_writes_the_impact_block_beside_the_existing_fields(
    tmp_path, monkeypatch,
):
    trial = tmp_path / "trial"
    trial.mkdir()
    (trial / "trial.yaml").write_text(
        yaml.safe_dump({"project_id": "p-1", "trial_id": "t-1", "terminal": "complete"}),
        encoding="utf-8",
    )
    (trial / "verdicts.yaml").write_text("[]", encoding="utf-8")
    (trial / "diagnoses.yaml").write_text("[]", encoding="utf-8")
    _v3_model(tmp_path / "data" / "p-1" / "hunting" / "threat_modeller")
    ground_truth = tmp_path / "gt"
    ground_truth.mkdir()
    (ground_truth / "challenge.json").write_text(
        yaml.safe_dump({"vulnerabilities": []}), encoding="utf-8")
    skills = tmp_path / "skills"
    skills.mkdir()
    graph = tmp_path / "graph.json"
    graph.write_text(yaml.safe_dump({"nodes": [], "links": []}), encoding="utf-8")

    monkeypatch.setattr(sys, "argv", [
        "measure_utm",
        "--trial", str(trial),
        "--data-root", str(tmp_path / "data"),
        "--corpus", str(tmp_path / "corpus"),
        "--target", "white-jotter-1",
        "--ground-truth", str(ground_truth),
        "--graph", str(graph),
        "--skills-root", str(skills),
    ])
    assert measure_utm.main() == 0

    metrics = yaml.safe_load((trial / "metrics.yaml").read_text(encoding="utf-8"))
    assert metrics["impact"]["impact_rows"] == 2
    assert metrics["impact"]["green_share"] == 0.5
    assert metrics["counts"]["gt_total"] == 0
    assert metrics["counts"]["threats_total"] == 1
    assert metrics["narrowing"]["threats_total"] == 1
    assert metrics["narrowing"]["broad"] == 0
    assert metrics["rates"]["identification_rate"] is None


def test_the_v4_impact_block_counts_capabilities_and_applies_the_review():
    models = [{
        "schema_version": 4,
        "unit_id": "Service:test",
        "impact_assessment": [
            {
                "id": "IA-1",
                "disposition": "threat",
                "capability": "read the roster",
                "capability_id": "P-1",
            },
            {
                "id": "IA-2",
                "disposition": "precursor",
                "capability": "probe the handler",
                "capability_id": "P-2",
            },
        ],
        "threats": [{
            "impact_ref": "IA-1",
            "impact": {
                "confidentiality": "high",
                "integrity": "none",
                "availability": "none",
            },
        }],
    }]
    review = {
        "scope": {"Service:test::IA-1": "in", "Service:test::IA-2": "in"},
        "rows": {
            "Service:test::IA-1": "sufficient",
            "Service:test::IA-2": "under_mined",
        },
    }

    metric = measure_utm.impact_metric(models, [], impact_review=review)

    assert metric["schema"] == "v4"
    assert metric["reviewed"] is True
    assert metric["green"] == 1
    assert metric["red"] == 1
    assert metric["capability_rows"] == 2
    assert metric["green_share"] == 0.5


# --- the v5 scored rows --------------------------------------------------------

# The worked example's known-good factor set: the `cvss==3.6` score for
# `AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:N/VA:N/SC:H/SI:N/SA:N` is 9.2, and the
# all-none set scores 0.0. Literals, never recomputed by the tests.
V5_FACTORS = {
    "attack_vector": "network",
    "attack_complexity": "low",
    "attack_requirements": "none",
    "privileges_required": "none",
    "user_interaction": "none",
    "confidentiality": "high",
    "integrity": "none",
    "availability": "none",
}
V5_NONE_FACTORS = {**V5_FACTORS, "confidentiality": "none"}
V5_RISK = 9.2
V5_VECTOR = "CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:N/VA:N/SC:H/SI:N/SA:N"
V5_NONE_VECTOR = "CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:N/VI:N/VA:N/SC:N/SI:N/SA:N"


def _assessed_model(
    root: Path,
    *,
    schema_version: int = 5,
    threat_impact: dict | None = None,
) -> None:
    """A scored unit: one `threat` row at 9.2 and one all-none `precursor` row.

    `schema_version=4` writes the same rows under the raw v4 shape, where the
    green signal is the threat's retired CIA vector: the v4 path must ignore
    the v5 `factors` / `risk` fields and never re-score the document.
    """
    unit = root / "produced" / "Service-catalogue"
    unit.mkdir(parents=True)
    threat = {
        "id": "threat-1",
        "fault_ref": "fault-1",
        "vulnerability_ref": "V-1",
        "canonical_class": "XSS",
        "web_vulnerability_class": "xss",
        "evidences": [],
        "impact_ref": "IA-1",
    }
    threat_file = {
        "threat_id": "threat-1",
        "unit_id": "Service:catalogue",
        "unit_kind": "service",
        "run_id": "run-1",
        "dispatch_id": "Service-catalogue__threat-1",
        "threat": threat,
        "impact": {
            "impact_ref": "IA-1",
            "disposition": "threat",
            "impact_description": (
                "An unauthenticated caller reads live session material from "
                "the process dump."
            ),
            "exploitability_description": (
                "A crafted remember-me cookie reaches the deserializer "
                "without a login."
            ),
            "capability_path": ["P-1"],
        },
    }
    if schema_version >= 5:
        threat["risk"] = V5_RISK
        threat_file["risk"] = V5_RISK
    else:
        threat["impact"] = dict(threat_impact or {
            "confidentiality": "none",
            "integrity": "none",
            "availability": "none",
        })
        threat_file["likelihood"] = "high"
    (unit / "Service-catalogue.yaml").write_text(
        yaml.safe_dump({
            "schema_version": schema_version,
            "unit_id": "Service:catalogue",
            "unit_kind": "service",
            "run_id": "run-1",
            "created_at": "2026-10-31T00:00:00Z",
            "updated_at": "2026-10-31T00:00:00Z",
            "state": "COMPLETED",
            "prior_art": {
                "queries": [],
                "reused": [{
                    "unit_id": "Service:sign-in",
                    "record_id": "P-9",
                    "kind": "precursor",
                    "reason": "same item read",
                }],
            },
            "impact_assessment": [
                {
                    "id": "IA-1",
                    "vulnerability_ref": "V-1",
                    "disposition": "threat",
                    "impact_description": (
                        "An unauthenticated caller reads live session material "
                        "from the process dump."
                    ),
                    "exploitability_description": (
                        "A crafted remember-me cookie reaches the deserializer "
                        "without a login."
                    ),
                    "capability": "read the session store",
                    "capability_id": "P-1",
                    "capability_path": ["P-1"],
                    "factors": dict(V5_FACTORS),
                    "risk": V5_RISK,
                    "risk_vector": V5_VECTOR,
                },
                {
                    "id": "IA-2",
                    "vulnerability_ref": "V-2",
                    "disposition": "precursor",
                    "impact_description": (
                        "No user or application property is affected; the "
                        "handler returns a generic envelope."
                    ),
                    "exploitability_description": (
                        "A crafted identifier reaches the handler with no "
                        "privilege of its own."
                    ),
                    "capability": "probe the session handler",
                    "capability_id": "P-2",
                    "factors": dict(V5_NONE_FACTORS),
                    "risk": 0.0,
                    "risk_vector": V5_NONE_VECTOR,
                },
            ],
            "precursors": [
                {
                    "id": f"P-{number}",
                    "capability": f"capability {number}",
                    "procedure": f"abstract procedure {number}",
                    "evidence_refs": [],
                }
                for number in (1, 2)
            ],
            "threats": [threat],
        }, sort_keys=False),
        encoding="utf-8",
    )
    (unit / "threat-1.yaml").write_text(
        yaml.safe_dump(threat_file, sort_keys=False), encoding="utf-8")


def test_the_severity_band_follows_the_cvss_table():
    assert measure_utm.severity_band(0.0) == "none"
    assert measure_utm.severity_band(0.1) == "low"
    assert measure_utm.severity_band(3.9) == "low"
    assert measure_utm.severity_band(4.0) == "medium"
    assert measure_utm.severity_band(6.9) == "medium"
    assert measure_utm.severity_band(7.0) == "high"
    assert measure_utm.severity_band(8.9) == "high"
    assert measure_utm.severity_band(9.0) == "critical"
    assert measure_utm.severity_band(10.0) == "critical"


def test_a_v5_model_reports_its_scored_rows_and_the_review_labels(tmp_path):
    _assessed_model(tmp_path)
    models, threats = measure_utm.load_models(tmp_path)
    review = {
        "scope": {"Service:catalogue::IA-1": "in", "Service:catalogue::IA-2": "in"},
        "rows": {
            "Service:catalogue::IA-1": "sufficient",
            "Service:catalogue::IA-2": "under_mined",
        },
    }

    metric = measure_utm.impact_metric(models, threats, impact_review=review)

    assert metric["schema"] == "v5"
    assert metric["legacy_recomputation"] is False
    assert metric["reviewed"] is True
    assert metric["impact_rows"] == 2
    assert metric["threats"] == 1
    assert metric["precursor_rows"] == 1
    assert metric["capability_rows"] == 2
    assert metric["green"] == 1
    assert metric["red"] == 1
    assert metric["green_share"] == 0.5
    # The dispatchable threat file's float risk and its band, not a re-score.
    assert metric["risk_total"] == V5_RISK
    assert metric["risk_breakdown"] == {
        "none": 0, "low": 0, "medium": 0, "high": 0, "critical": 1,
    }
    (row,) = [row for row in metric["rows"] if row["id"] == "IA-1"]
    assert row["impact_description"].startswith("An unauthenticated caller")
    assert row["exploitability_description"].startswith("A crafted remember-me")
    assert row["factors"] == V5_FACTORS
    assert row["risk"] == V5_RISK
    assert row["risk_vector"] == V5_VECTOR
    assert row["band"] == "critical"
    assert row["mining"] == "sufficient"
    assert row["scope"] == "in"


def test_the_measurement_reads_the_v5_risk_and_band_from_the_threat_file(
    tmp_path, monkeypatch,
):
    trial = tmp_path / "trial"
    trial.mkdir()
    (trial / "trial.yaml").write_text(
        yaml.safe_dump({"project_id": "p-1", "trial_id": "t-1", "terminal": "complete"}),
        encoding="utf-8",
    )
    (trial / "verdicts.yaml").write_text("[]", encoding="utf-8")
    (trial / "diagnoses.yaml").write_text("[]", encoding="utf-8")
    (trial / "impact_review.yaml").write_text(
        yaml.safe_dump({
            "units": [{
                "unit": "Service:catalogue",
                "scope": "in",
                "scope_reason": "the unit is in the project scope",
                "rows": [
                    {"id": "IA-1", "mining": "sufficient", "rationale": "scored"},
                    {"id": "IA-2", "mining": "under_mined", "rationale": "a capability only"},
                ],
            }],
        }, sort_keys=False),
        encoding="utf-8",
    )
    _assessed_model(tmp_path / "data" / "p-1" / "hunting" / "threat_modeller")
    ground_truth = tmp_path / "gt"
    ground_truth.mkdir()
    (ground_truth / "challenge.json").write_text(
        yaml.safe_dump({"vulnerabilities": [{"vuln_id": "v-1"}]}), encoding="utf-8")
    (ground_truth / "vulnerability" / "v-1").mkdir(parents=True)
    (ground_truth / "vulnerability" / "v-1" / "metadata.json").write_text(
        yaml.safe_dump({
            "Vulnerability Type": "Cross-site scripting",
            "Location": "/",
        }), encoding="utf-8")
    skills = tmp_path / "skills"
    skills.mkdir()
    graph = tmp_path / "graph.json"
    graph.write_text(yaml.safe_dump({"nodes": [], "links": []}), encoding="utf-8")

    monkeypatch.setattr(sys, "argv", [
        "measure_utm",
        "--trial", str(trial),
        "--data-root", str(tmp_path / "data"),
        "--corpus", str(tmp_path / "corpus"),
        "--target", "white-jotter-1",
        "--ground-truth", str(ground_truth),
        "--graph", str(graph),
        "--skills-root", str(skills),
    ])
    assert measure_utm.main() == 0

    metrics = yaml.safe_load((trial / "metrics.yaml").read_text(encoding="utf-8"))
    impact = metrics["impact"]
    assert impact["schema"] == "v5"
    assert impact["risk_total"] == V5_RISK
    assert impact["risk_breakdown"]["critical"] == 1
    assert impact["green_share"] == 0.5
    threat = metrics["per_vuln"][0]["threats"][0]
    assert threat["risk"] == V5_RISK
    assert threat["band"] == "critical"


def test_a_v4_document_is_reported_raw_and_never_re_scored(tmp_path):
    """The v4 read keeps its persisted CIA vector: the v5 row fields are inert,
    so a 9.2 assessment row cannot turn a no-impact v4 threat green."""
    _assessed_model(tmp_path, schema_version=4)
    models, threats = measure_utm.load_models(tmp_path)

    metric = measure_utm.impact_metric(models, threats)

    assert metric["schema"] == "v4"
    assert metric["legacy_recomputation"] is False
    assert metric["impact_rows"] == 2
    assert metric["green"] == 0
    assert metric["green_share"] == 0.0
    assert metric["cia"]["confidentiality"] == {
        "none": 2, "low": 0, "medium": 0, "high": 0,
    }
    assert "risk_total" not in metric
    assert "risk_breakdown" not in metric
    assert "rows" not in metric


def test_the_review_labels_do_not_collide_across_units():
    """Two units both name a row IA-1; the label must resolve by unit."""
    def unit(name, label):
        return {
            "schema_version": 4,
            "unit_id": name,
            "impact_assessment": [{
                "id": "IA-1",
                "disposition": "threat",
                "capability": "read",
                "capability_id": "P-1",
            }],
            "threats": [{
                "impact_ref": "IA-1",
                "impact": {
                    "confidentiality": "high",
                    "integrity": "none",
                    "availability": "none",
                },
            }],
        }

    review = {
        "scope": {"Service:a::IA-1": "in", "Service:b::IA-1": "out"},
        "rows": {"Service:a::IA-1": "sufficient", "Service:b::IA-1": "sufficient"},
    }

    metric = measure_utm.impact_metric(
        [unit("Service:a", "in"), unit("Service:b", "out")], [],
        impact_review=review,
    )

    assert metric["green"] == 2
    assert metric["red"] == 1
    assert abs(metric["green_share"] - 2 / 3) < 1e-4


def test_load_corpus_unit_reads_the_l1_profile_markdown(tmp_path):
    target = tmp_path / "corpus" / "siyucms"
    unit = target / "siyucms-001"
    unit.mkdir(parents=True)
    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "siyucms-001-l1-profile.md"
    )
    (unit / "l1-profile.md").write_text(
        fixture.read_text(encoding="utf-8"), encoding="utf-8"
    )
    spec = measure_utm.load_corpus_unit(target, "siyucms-001")
    assert spec["unit"]["match"]["business_function_slug"] == "admin-authentication"
    assert spec["fault_class"] == "Weak Credentials"
    assert spec["edges_to_l0"]["endpoints"][0]["path"] == "/admin/index/index.html"
    assert spec["typed_backbone"]["required"][0]["field"] == "api_paradigm"
    assert spec["service_to_system_edges"]["required"][0]["target_kind"] == (
        "AuthenticationMechanism"
    )
    assert len(spec["edges_to_l0"]["endpoints"]) == 3


def test_a_profile_without_a_unit_line_is_not_a_present_spec():
    assert measure_utm.unit_spec_from_profile("# L1 profile\n\nno unit") == {}


def test_a_profile_parses_a_bare_system_unit():
    spec = measure_utm.unit_spec_from_profile(
        "The target unit is `ReverseProxy`.\n"
    )
    assert spec["unit"]["kind"] == "ReverseProxy"
    assert spec["unit"]["match"] == {"kind": "ReverseProxy", "discriminator": ""}


def test_a_profile_parses_a_discriminated_system_unit():
    spec = measure_utm.unit_spec_from_profile(
        "The target unit is `WebPresentation:admin::login`.\n"
    )
    assert spec["unit"]["kind"] == "WebPresentation"
    assert spec["unit"]["match"] == {
        "kind": "WebPresentation",
        "discriminator": "admin::login",
    }


def test_spec_metrics_counts_all_nine_concretised_procedure_fields():
    spec = {
        "target_identity": {"unit_id": "Service:sign-in"},
        "verification_symptoms": ["a symptom"],
        "assumptions": [],
        "rationale": "a rationale",
        "provenance": {"threat_id": "Service-sign-in__threat-1"},
        "skill_concretised_procedure": {
            "recon_action": "a",
            "bypass_technique": "b",
            "advanced_technique": "c",
            "preliminary_chaining": "d",
            "payload_vector": "e",
            "technology_misconfiguration": "f",
            "technology_grounding": "g",
            "pro_tips": "h",
            "interpretation_pitfalls": "i",
        },
        "discriminators": [{"axis": "technique", "value": "burst"}],
    }
    identity = {
        "expected_id": "Service:sign-in",
        "names": ["Service:sign-in"],
        "fault_class": "",
        "location": "",
    }
    row = measure_utm.spec_metrics(spec, {"type": ""}, identity)
    assert row["procedure_fields"] == 9
    assert row["procedure_total"] == 9


def test_threat_downstream_matches_the_unit_and_the_threat_id():
    threat = {"threat_id": "threat-1", "unit_id": "Service:console-dashboard"}
    specs = [
        {
            "threat_id": "Service-console-dashboard__threat-1",
            "unit_id": "Service:console-dashboard",
            **_spec("technique"),
        },
        {
            "threat_id": "Service-console-dashboard__threat-1",
            "unit_id": "Service:content-browsing",
            **_spec("actor"),
        },
    ]
    downstream = measure_utm.threat_downstream(threat, specs)
    assert downstream["spec_count"] == 1


def test_a_bare_threat_id_does_not_cross_units():
    threat = {"threat_id": "threat-1", "unit_id": "Service:a"}
    specs = [
        {"threat_id": "threat-1", "unit_id": "Service:a", **_spec("technique")},
        {"threat_id": "threat-1", "unit_id": "Service:b", **_spec("actor")},
    ]
    assert measure_utm.threat_downstream(threat, specs)["spec_count"] == 1


def test_the_narrowing_block_counts_distinct_threat_files():
    threats = [
        {"threat_id": "threat-1", "unit_id": "Service:a", "risk": 5.0},
        {"threat_id": "threat-1", "unit_id": "Service:b", "risk": 5.0},
    ]
    block = measure_utm.narrowing_block(threats, [], {})
    assert block["threats_total"] == 2
    assert block["breadth_unknown"] == 2


def test_a_threat_file_without_a_model_file_still_carries_its_risk(tmp_path):
    unit = tmp_path / "consumed" / "Service-console-dashboard"
    unit.mkdir(parents=True)
    (unit / "threat-1.yaml").write_text(
        yaml.safe_dump({"risk": 9.9, "threat_id": "threat-1"}), encoding="utf-8"
    )
    models, threats = measure_utm.load_models(tmp_path)
    metric = measure_utm.impact_metric(models, threats)
    assert metric["risk_total"] == 9.9
