"""EvalSetup parsing and validation (ticket #269, D1/D4; spec #301).

The `EvalSetup` shape follows the design's extended system description
(`docs/design/eval-harness-multi-instance-solution.md` section 5): one setup
carries instances, each with a serial target pipeline, plus the eval-wide
artifact store and work items (D14). Under spec #301 a target is addressed by its
`<dataset>/<target>` key and the per-trial data configuration only; the
bring-up configuration lives in the target's own YAML. Every missing or unknown
field fails loud and names itself, so an operator never debugs a silently empty
run.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator import setup as setup_mod
from orchestrator.dataset import DatasetError, load_benchmark_dataset
from orchestrator.target_config import load_target_configuration


def test_parses_a_valid_setup(sample_setup) -> None:
    parsed = setup_mod.parse_eval_setup(sample_setup)

    assert parsed.schema_version == 1
    assert parsed.artifact_store == "/srv/eval-artifacts"
    assert parsed.datasets == ("webexploitbench",)
    assert [w.name for w in parsed.work_items] == ["auth-bootstrap", "l1-surface"]
    (instance,) = parsed.instances
    assert instance.instance_id == "arm-a"
    assert instance.env_file == "arm-a/.env"
    (run,) = instance.targets
    assert run.target_key == "webexploitbench/jetlinks"
    assert run.dataset_id == "webexploitbench"
    assert run.target == "jetlinks"
    assert run.target_id == "jetlinks-1"
    assert run.start_phase == "recon"
    assert run.hunt_config_budget == 10
    assert run.token_budget == 10
    assert run.target_config.operator_kb == (
        "eval/data/webexploitbench/jetlinks/operator_kb.md"
    )


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


# --- the keyed dataset/target model (spec #301) -------------------------------


def _target(sample_setup) -> dict:
    return sample_setup["instances"][0]["targets"][0]


def test_datasets_are_optional_and_default_empty(sample_setup) -> None:
    sample_setup.pop("datasets")

    assert setup_mod.parse_eval_setup(sample_setup).datasets == ()


def test_datasets_are_parsed(sample_setup) -> None:
    sample_setup["datasets"] = ["webexploitbench", "mock"]

    assert setup_mod.parse_eval_setup(sample_setup).datasets == (
        "webexploitbench",
        "mock",
    )


def test_path_unsafe_dataset_key_is_named(sample_setup) -> None:
    sample_setup["datasets"] = ["../escape"]

    with pytest.raises(setup_mod.SetupError, match="datasets"):
        setup_mod.parse_eval_setup(sample_setup)


def test_missing_target_key_is_named(sample_setup) -> None:
    _target(sample_setup).pop("target_key")

    with pytest.raises(setup_mod.SetupError, match="target_key"):
        setup_mod.parse_eval_setup(sample_setup)


def test_target_key_without_a_separator_is_named(sample_setup) -> None:
    _target(sample_setup)["target_key"] = "jetlinks"

    # The key splitter owns this failure and names the expected shape.
    with pytest.raises(DatasetError, match="target key"):
        setup_mod.parse_eval_setup(sample_setup)


def test_target_id_defaults_to_the_target_segment(sample_setup) -> None:
    _target(sample_setup).pop("target_id")

    (run,) = setup_mod.parse_eval_setup(sample_setup).instances[0].targets

    assert run.target_id == "jetlinks"


def test_explicit_target_id_is_parsed(sample_setup) -> None:
    _target(sample_setup)["target_id"] = "jetlinks-run1"

    (run,) = setup_mod.parse_eval_setup(sample_setup).instances[0].targets

    assert run.target_id == "jetlinks-run1"


def test_duplicate_target_id_is_named(sample_setup) -> None:
    targets = sample_setup["instances"][0]["targets"]
    targets.append(dict(targets[0]))

    with pytest.raises(setup_mod.SetupError, match="jetlinks-1"):
        setup_mod.parse_eval_setup(sample_setup)


def test_path_unsafe_target_id_is_named(sample_setup) -> None:
    _target(sample_setup)["target_id"] = "../escape"

    with pytest.raises(setup_mod.SetupError, match="target_id"):
        setup_mod.parse_eval_setup(sample_setup)


def test_target_config_is_optional(sample_setup) -> None:
    _target(sample_setup).pop("target_config")

    (run,) = setup_mod.parse_eval_setup(sample_setup).instances[0].targets

    assert run.target_config.operator_kb is None
    assert run.target_config.target_seed is None


def test_target_config_unknown_key_is_named(sample_setup) -> None:
    _target(sample_setup)["target_config"] = {"lifecycle": "targetctl"}

    with pytest.raises(setup_mod.SetupError, match="lifecycle"):
        setup_mod.parse_eval_setup(sample_setup)


def test_bad_start_phase_is_named(sample_setup) -> None:
    _target(sample_setup)["start_phase"] = "exploit"

    with pytest.raises(setup_mod.SetupError, match="start_phase"):
        setup_mod.parse_eval_setup(sample_setup)


def test_parses_a_valid_token_budget(sample_setup) -> None:
    _target(sample_setup)["token_budget"] = 5000

    (run,) = setup_mod.parse_eval_setup(sample_setup).instances[0].targets

    assert run.token_budget == 5000


def test_token_budget_defaults_to_none(sample_setup) -> None:
    _target(sample_setup).pop("token_budget")

    (run,) = setup_mod.parse_eval_setup(sample_setup).instances[0].targets

    assert run.token_budget is None


def test_token_budget_non_int_is_named(sample_setup) -> None:
    _target(sample_setup)["token_budget"] = "lots"

    with pytest.raises(setup_mod.SetupError, match="token_budget"):
        setup_mod.parse_eval_setup(sample_setup)


def test_token_budget_bool_is_named(sample_setup) -> None:
    _target(sample_setup)["token_budget"] = True

    with pytest.raises(setup_mod.SetupError, match="token_budget"):
        setup_mod.parse_eval_setup(sample_setup)


# --- pre-mined hunting artifacts (#270 AC4) -----------------------------------


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


# --- the WebExploitBench chain setup (spec #301) ------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
CHAIN_SETUP = REPO_ROOT / "eval" / "setups" / "webexploitbench-chain.yaml"

CHAIN_TARGETS = [
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
# The 5 targets bundled with the repo carry a committed operator KB; the 10
# Hugging Face-only targets carry none yet.
BUNDLED = ("comfyui", "jetlinks", "prestashop", "siyucms", "white-jotter")


def test_webexploitbench_chain_setup_parses() -> None:
    setup = setup_mod.load_eval_setup(CHAIN_SETUP)

    assert setup.datasets == ("webexploitbench",)
    (instance,) = setup.instances
    assert [run.target for run in instance.targets] == CHAIN_TARGETS
    # Every target keeps its per-trial identity for the artifact store.
    assert [run.target_id for run in instance.targets] == [
        f"{name}-1" for name in CHAIN_TARGETS
    ]
    by_target = {run.target: run for run in instance.targets}
    for name in BUNDLED:
        assert by_target[name].target_config.operator_kb == (
            f"eval/data/webexploitbench/{name}/operator_kb.md"
        )
    for name in CHAIN_TARGETS:
        if name not in BUNDLED:
            assert by_target[name].target_config.operator_kb is None


def test_webexploitbench_target_configs_exist_and_parse() -> None:
    setup = setup_mod.load_eval_setup(CHAIN_SETUP)
    dataset = load_benchmark_dataset(REPO_ROOT / "eval" / "datasets" / "webexploitbench.yaml")

    assert dataset.targets == tuple(CHAIN_TARGETS)
    for run in setup.instances[0].targets:
        path = dataset.target_config_search(run.target)
        assert path.is_file(), path
        config = load_target_configuration(path)
        assert config.target == run.target
        assert config.runner == "targetctl"
        assert config.compose == "docker-compose.cage.yml"


def test_mock_dataset_and_target_config_exist() -> None:
    dataset = load_benchmark_dataset(REPO_ROOT / "eval" / "datasets" / "mock.yaml")

    assert dataset.targets == ("webmock",)
    config = load_target_configuration(dataset.target_config_search("webmock"))
    assert config.target == "webmock"
    assert dataset.bank_entry("webmock").is_dir()
