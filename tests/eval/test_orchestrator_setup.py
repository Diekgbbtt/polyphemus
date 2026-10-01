"""EvalSetup parsing and validation (ticket #269, D1/D4).

The `EvalSetup` shape follows the design's extended system description
(`docs/design/eval-harness-multi-instance-solution.md` section 5): one setup
carries instances, each with a serial target pipeline, plus the eval-wide
artifact store and work items (D14). Every missing or unknown field fails loud
and names itself, so an operator never debugs a silently empty run.
"""
from __future__ import annotations

from pathlib import Path

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


# --- pre-mined hunting artifacts (#270 AC4) -----------------------------------


def _target(sample_setup) -> dict:
    return sample_setup["instances"][0]["targets"][0]


def test_preloaded_artifacts_legacy_string_parses_as_configs(sample_setup) -> None:
    # Backward compatibility: the former single-path form pre-mines configs only.
    _target(sample_setup)["preloaded_hunting_artifacts"] = "/mnt/premined-configs"

    parsed = setup_mod.parse_eval_setup(sample_setup)

    pre = parsed.instances[0].targets[0].preloaded_hunting_artifacts
    assert pre.configs == "/mnt/premined-configs"
    assert pre.test_specs == ()


def test_preloaded_artifacts_parses_configs_and_test_specs(sample_setup) -> None:
    _target(sample_setup)["preloaded_hunting_artifacts"] = {
        "configs": "/mnt/configs",
        "test_specs": [
            {"path": "/mnt/specs/a.yaml", "fault_key": "unit_CWE-89_sqli"},
            {"path": "/mnt/specs/b.yaml", "fault_key": "svc_CWE-79_xss"},
        ],
    }

    parsed = setup_mod.parse_eval_setup(sample_setup)

    pre = parsed.instances[0].targets[0].preloaded_hunting_artifacts
    assert pre.configs == "/mnt/configs"
    assert [(s.path, s.fault_key) for s in pre.test_specs] == [
        ("/mnt/specs/a.yaml", "unit_CWE-89_sqli"),
        ("/mnt/specs/b.yaml", "svc_CWE-79_xss"),
    ]


def test_preloaded_artifacts_accepts_specs_without_configs(sample_setup) -> None:
    _target(sample_setup)["preloaded_hunting_artifacts"] = {
        "test_specs": [{"path": "/mnt/specs/a.yaml", "fault_key": "fault-a"}]
    }

    parsed = setup_mod.parse_eval_setup(sample_setup)

    pre = parsed.instances[0].targets[0].preloaded_hunting_artifacts
    assert pre.configs is None
    assert [s.fault_key for s in pre.test_specs] == ["fault-a"]


def test_preloaded_test_spec_without_fault_key_is_named(sample_setup) -> None:
    _target(sample_setup)["preloaded_hunting_artifacts"] = {
        "test_specs": [{"path": "/mnt/specs/a.yaml"}]
    }

    with pytest.raises(setup_mod.SetupError, match="fault_key"):
        setup_mod.parse_eval_setup(sample_setup)


def test_preloaded_test_spec_without_path_is_named(sample_setup) -> None:
    _target(sample_setup)["preloaded_hunting_artifacts"] = {
        "test_specs": [{"fault_key": "fault-a"}]
    }

    with pytest.raises(setup_mod.SetupError, match="path"):
        setup_mod.parse_eval_setup(sample_setup)


def test_preloaded_test_spec_unknown_key_is_named(sample_setup) -> None:
    _target(sample_setup)["preloaded_hunting_artifacts"] = {
        "test_specs": [{"path": "/mnt/specs/a.yaml", "fault_key": "f", "extra": 1}]
    }

    with pytest.raises(setup_mod.SetupError, match="extra"):
        setup_mod.parse_eval_setup(sample_setup)


def test_preloaded_artifacts_unknown_shape_is_named(sample_setup) -> None:
    _target(sample_setup)["preloaded_hunting_artifacts"] = 42

    with pytest.raises(setup_mod.SetupError, match="preloaded_hunting_artifacts"):
        setup_mod.parse_eval_setup(sample_setup)


def test_preloaded_artifacts_unknown_field_is_named(sample_setup) -> None:
    _target(sample_setup)["preloaded_hunting_artifacts"] = {"configs": "/mnt", "oops": 1}

    with pytest.raises(setup_mod.SetupError, match="oops"):
        setup_mod.parse_eval_setup(sample_setup)


def test_preloaded_test_spec_path_unsafe_fault_key_is_named(sample_setup) -> None:
    _target(sample_setup)["preloaded_hunting_artifacts"] = {
        "test_specs": [{"path": "/mnt/specs/a.yaml", "fault_key": "../escape"}]
    }

    with pytest.raises(setup_mod.SetupError, match="fault_key"):
        setup_mod.parse_eval_setup(sample_setup)


# --- target-run identity (#273) ------------------------------------------------


def test_target_run_id_is_optional(sample_setup) -> None:
    parsed = setup_mod.parse_eval_setup(sample_setup)

    assert parsed.instances[0].targets[0].target_run_id is None


def test_parses_an_explicit_target_run_id(sample_setup) -> None:
    _target(sample_setup)["target_run_id"] = "jetlinks-1-run1"

    parsed = setup_mod.parse_eval_setup(sample_setup)

    assert parsed.instances[0].targets[0].target_run_id == "jetlinks-1-run1"


def test_duplicate_target_run_id_is_named(sample_setup) -> None:
    targets = sample_setup["instances"][0]["targets"]
    targets[0]["target_run_id"] = "run-1"
    targets.append({**targets[0], "target_id": "other-1"})

    with pytest.raises(setup_mod.SetupError, match="target_run_id"):
        setup_mod.parse_eval_setup(sample_setup)


def test_path_unsafe_target_run_id_is_named(sample_setup) -> None:
    _target(sample_setup)["target_run_id"] = "../escape"

    with pytest.raises(setup_mod.SetupError, match="target_run_id"):
        setup_mod.parse_eval_setup(sample_setup)


# --- alignment declarations (#274) --------------------------------------------


def test_alignment_declarations_are_optional(sample_setup) -> None:
    parsed = setup_mod.parse_eval_setup(sample_setup)

    assert parsed.alignment is None


def test_parses_declared_migration_and_rebuild(sample_setup) -> None:
    sample_setup["alignment"] = {
        "migrations": [
            {
                "artifact_class": "schema_data_layout",
                "command": ["python3", "eval/migrations/0001.py"],
                "reason": "db layout",
            }
        ],
        "rebuilds": [
            {
                "artifact_class": "image_definition",
                "image": "agent",
                "command": ["docker", "build", "-t", "ph-agent", "."],
            }
        ],
    }

    parsed = setup_mod.parse_eval_setup(sample_setup)

    assert parsed.alignment is not None
    assert parsed.alignment.migrations[0].artifact_class == "schema_data_layout"
    assert parsed.alignment.migrations[0].command == ("python3", "eval/migrations/0001.py")
    assert parsed.alignment.rebuilds[0].image == "agent"


def test_alignment_unknown_field_is_named(sample_setup) -> None:
    sample_setup["alignment"] = {"migrations": [], "oops": 1}

    with pytest.raises(setup_mod.SetupError, match="oops"):
        setup_mod.parse_eval_setup(sample_setup)


def test_alignment_empty_is_refused(sample_setup) -> None:
    sample_setup["alignment"] = {"migrations": [], "rebuilds": []}

    with pytest.raises(setup_mod.SetupError, match="alignment"):
        setup_mod.parse_eval_setup(sample_setup)


def test_declared_migration_without_a_command_is_named(sample_setup) -> None:
    sample_setup["alignment"] = {
        "migrations": [{"artifact_class": "schema_data_layout"}]
    }

    with pytest.raises(setup_mod.SetupError, match="command"):
        setup_mod.parse_eval_setup(sample_setup)


def test_missing_file_names_the_path(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="nope.yaml"):
        setup_mod.load_eval_setup(tmp_path / "nope.yaml")


def test_invalid_yaml_names_the_path(tmp_path) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text("instances: [ : :\n", encoding="utf-8")

    with pytest.raises(setup_mod.SetupError, match="broken.yaml"):
        setup_mod.load_eval_setup(path)


def test_dataset_absent_is_none(sample_setup) -> None:
    assert setup_mod.parse_eval_setup(sample_setup).dataset is None


def test_dataset_is_parsed(sample_setup) -> None:
    sample_setup["dataset"] = {
        "name": "webexploitbench",
        "repo": "https://github.com/AgentCyberRange/WebExploitBench.git",
        "registry": "ghcr.io/agentcyberrange/webench",
        "ground_truth": "/srv/eval-harness/gt",
    }

    dataset = setup_mod.parse_eval_setup(sample_setup).dataset

    assert dataset.name == "webexploitbench"
    assert dataset.repo == "https://github.com/AgentCyberRange/WebExploitBench.git"
    assert dataset.registry == "ghcr.io/agentcyberrange/webench"
    assert dataset.ground_truth == "/srv/eval-harness/gt"


def test_dataset_registry_defaults_empty(sample_setup) -> None:
    sample_setup["dataset"] = {
        "name": "webexploitbench",
        "repo": "https://github.com/AgentCyberRange/WebExploitBench.git",
    }

    assert setup_mod.parse_eval_setup(sample_setup).dataset.registry == ""


def test_target_run_images_are_parsed(sample_setup) -> None:
    sample_setup["instances"][0]["targets"][0]["images"] = [
        "pentestbench-comfyui-web:latest"
    ]

    (run,) = setup_mod.parse_eval_setup(sample_setup).instances[0].targets

    assert run.images == ("pentestbench-comfyui-web:latest",)


def test_target_run_images_default_empty(sample_setup) -> None:
    (run,) = setup_mod.parse_eval_setup(sample_setup).instances[0].targets

    assert run.images == ()


def test_target_config_dockerfile_is_parsed(sample_setup) -> None:
    target_config = sample_setup["instances"][0]["targets"][0]["target_config"]
    target_config["dockerfile"] = "setup_files/environment/Dockerfile"
    target_config["dockerfile_context"] = "setup_files"

    (run,) = setup_mod.parse_eval_setup(sample_setup).instances[0].targets

    assert run.target_config.dockerfile == "setup_files/environment/Dockerfile"
    assert run.target_config.dockerfile_context == "setup_files"


def test_target_config_dockerfile_defaults_none(sample_setup) -> None:
    (run,) = setup_mod.parse_eval_setup(sample_setup).instances[0].targets

    assert run.target_config.dockerfile is None
    assert run.target_config.dockerfile_context is None


def test_target_run_images_must_be_strings(sample_setup) -> None:
    sample_setup["instances"][0]["targets"][0]["images"] = [1]

    with pytest.raises(setup_mod.SetupError, match="images"):
        setup_mod.parse_eval_setup(sample_setup)


def test_webexploitbench_chain_setup_parses() -> None:
    root = Path(__file__).resolve().parents[2]
    setup = setup_mod.load_eval_setup(
        root / "eval" / "setups" / "webexploitbench-chain.yaml"
    )

    assert setup.dataset is not None
    assert setup.dataset.name == "webexploitbench"
    assert setup.dataset.registry == ""
    (instance,) = setup.instances
    names = [run.target_config.params["target"] for run in instance.targets]
    assert names == [
        "comfyui",
        "jetlinks",
        "prestashop",
        "siyucms",
        "white-jotter",
        "dataease",
        "dify",
        "geoserver",
        "mogu-blog-v2",
        "ofbiz",
        "openmetadata",
        "openremote",
        "phpbb",
        "wordpress",
        "youlai-mall",
    ]
    assert all(run.images for run in instance.targets)
