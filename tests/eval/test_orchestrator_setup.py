"""EvalSetup parsing and validation (ticket #269, D1/D4).

The `EvalSetup` shape follows the design's extended system description
(`docs/design/eval-harness-multi-instance-solution.md` section 5): one setup
carries instances, each with a serial target pipeline, plus the eval-wide
artifact store and work items (D14). Every missing or unknown field fails loud
and names itself, so an operator never debugs a silently empty run.
"""
from __future__ import annotations

import pytest

from orchestrator import setup as setup_mod


def test_parses_a_valid_setup(sample_setup) -> None:
    parsed = setup_mod.parse_eval_setup(sample_setup)

    assert parsed.schema_version == 1
    assert parsed.artifact_store == "/srv/eval-artifacts"
    assert [w.name for w in parsed.work_items] == ["auth-bootstrap", "l1-surface"]
    (instance,) = parsed.instances
    assert instance.instance_id == "arm-a"
    assert instance.env_file == "arm-a/.env"
    (run,) = instance.targets
    assert run.target_id == "jetlinks-1"
    assert run.start_phase == "recon"
    assert run.hunt_config_budget == 10
    assert run.target_config.lifecycle == "targetctl"
    assert run.target_config.params["target"] == "jetlinks"
    assert run.target_config.operator_kb == "eval/kbs/jetlinks/operator_kb.md"


def test_loads_from_yaml_file(tmp_path, sample_setup) -> None:
    import yaml

    path = tmp_path / "setup.yaml"
    path.write_text(yaml.safe_dump(sample_setup), encoding="utf-8")

    parsed = setup_mod.load_eval_setup(path)

    assert parsed.instances[0].instance_id == "arm-a"


def _mutated(sample_setup, mutator) -> dict:
    mutator(sample_setup)
    return sample_setup


def test_missing_schema_version_is_named(sample_setup) -> None:
    payload = _mutated(sample_setup, lambda p: p.pop("schema_version"))

    with pytest.raises(setup_mod.SetupError, match="schema_version"):
        setup_mod.parse_eval_setup(payload)


def test_unsupported_schema_version_is_named(sample_setup) -> None:
    sample_setup["schema_version"] = 99

    with pytest.raises(setup_mod.SetupError, match="schema_version"):
        setup_mod.parse_eval_setup(sample_setup)


def test_missing_artifact_store_is_named(sample_setup) -> None:
    payload = _mutated(sample_setup, lambda p: p.pop("artifact_store"))

    with pytest.raises(setup_mod.SetupError, match="artifact_store"):
        setup_mod.parse_eval_setup(payload)


def test_empty_instances_is_named(sample_setup) -> None:
    sample_setup["instances"] = []

    with pytest.raises(setup_mod.SetupError, match="instances"):
        setup_mod.parse_eval_setup(sample_setup)


def test_missing_instance_id_is_named(sample_setup) -> None:
    sample_setup["instances"][0].pop("instance_id")

    with pytest.raises(setup_mod.SetupError, match="instance_id"):
        setup_mod.parse_eval_setup(sample_setup)


def test_duplicate_instance_id_is_named(sample_setup) -> None:
    sample_setup["instances"].append(dict(sample_setup["instances"][0]))

    with pytest.raises(setup_mod.SetupError, match="arm-a"):
        setup_mod.parse_eval_setup(sample_setup)


def test_missing_target_config_is_named(sample_setup) -> None:
    sample_setup["instances"][0]["targets"][0].pop("target_config")

    with pytest.raises(setup_mod.SetupError, match="target_config"):
        setup_mod.parse_eval_setup(sample_setup)


def test_unknown_lifecycle_is_named(sample_setup) -> None:
    sample_setup["instances"][0]["targets"][0]["target_config"]["lifecycle"] = "magic"

    with pytest.raises(setup_mod.SetupError, match="lifecycle"):
        setup_mod.parse_eval_setup(sample_setup)


def test_missing_lifecycle_is_named(sample_setup) -> None:
    sample_setup["instances"][0]["targets"][0]["target_config"].pop("lifecycle")

    with pytest.raises(setup_mod.SetupError, match="lifecycle"):
        setup_mod.parse_eval_setup(sample_setup)


def test_targetctl_missing_required_param_is_named(sample_setup) -> None:
    sample_setup["instances"][0]["targets"][0]["target_config"]["params"] = {}

    with pytest.raises(setup_mod.SetupError, match="target"):
        setup_mod.parse_eval_setup(sample_setup)


def test_image_missing_required_params_is_named(sample_setup) -> None:
    cfg = sample_setup["instances"][0]["targets"][0]["target_config"]
    cfg["lifecycle"] = "image"
    cfg["params"] = {}

    with pytest.raises(setup_mod.SetupError, match="image"):
        setup_mod.parse_eval_setup(sample_setup)


def test_bad_start_phase_is_named(sample_setup) -> None:
    sample_setup["instances"][0]["targets"][0]["start_phase"] = "exploit"

    with pytest.raises(setup_mod.SetupError, match="start_phase"):
        setup_mod.parse_eval_setup(sample_setup)


def test_duplicate_target_id_is_named(sample_setup) -> None:
    targets = sample_setup["instances"][0]["targets"]
    targets.append(dict(targets[0]))

    with pytest.raises(setup_mod.SetupError, match="jetlinks-1"):
        setup_mod.parse_eval_setup(sample_setup)


def test_unknown_top_level_key_is_named(sample_setup) -> None:
    sample_setup["extra_sauce"] = True

    with pytest.raises(setup_mod.SetupError, match="extra_sauce"):
        setup_mod.parse_eval_setup(sample_setup)


def test_unknown_work_item_status_is_named(sample_setup) -> None:
    sample_setup["work_items"][0]["status"] = "maybe"

    with pytest.raises(setup_mod.SetupError, match="status"):
        setup_mod.parse_eval_setup(sample_setup)


def test_work_items_are_optional(sample_setup) -> None:
    sample_setup.pop("work_items")

    parsed = setup_mod.parse_eval_setup(sample_setup)

    assert parsed.work_items == ()


def test_parse_error_for_non_mapping_payload() -> None:
    with pytest.raises(setup_mod.SetupError, match="mapping"):
        setup_mod.parse_eval_setup(["not", "a", "mapping"])


def test_missing_file_names_the_path(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="nope.yaml"):
        setup_mod.load_eval_setup(tmp_path / "nope.yaml")


def test_invalid_yaml_names_the_path(tmp_path) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text("instances: [ : :\n", encoding="utf-8")

    with pytest.raises(setup_mod.SetupError, match="broken.yaml"):
        setup_mod.load_eval_setup(path)
