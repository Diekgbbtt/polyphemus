"""Unit tier: the measurement substrate for threat breadth and spec discrimination.

The operator's next-trial question has two deterministic halves:

- Is the bound vulnerability class a parent class (a broad class with variants)?
- Is the discriminated spec set substantial (at least three specs) and
  well-formed (the primary discrimination axes do not overlap)?

The impact metric is the third half: the red/green share over the impact rows,
the CIA distribution, the placeholder share, and the v2 legacy recomputation.

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


def test_a_dispatch_id_provenance_value_normalises_to_the_threat_id():
    assert measure_utm.threat_id_of(
        {"threat_id": "Service-sign-in__threat-1"}
    ) == "threat-1"
    assert measure_utm.threat_id_of({"threat_id": "threat-1"}) == "threat-1"
    assert measure_utm.threat_id_of({}) == ""


def test_spec_metrics_normalises_the_dispatch_id_provenance():
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

    assert row["threat_id"] == "threat-1"


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
    assert metrics["narrowing"]["threats_total"] == 0
    assert metrics["rates"]["identification_rate"] is None
