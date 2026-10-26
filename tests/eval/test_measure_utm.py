"""Unit tier: the measurement substrate for threat breadth and spec discrimination.

The operator's next-trial question has two deterministic halves:

- Is the bound vulnerability class a parent class (a broad class with variants)?
- Is the discriminated spec set substantial (at least three specs) and
  well-formed (the primary discrimination axes do not overlap)?

The semantic judgement stays with the measurement subagent; these functions
produce the substrate it reads.
"""
from __future__ import annotations

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
