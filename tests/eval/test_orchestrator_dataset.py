"""The BenchmarkDataset loader, keying, and path resolution (spec #301)."""
from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.dataset import (
    BenchmarkDataset,
    DatasetError,
    load_benchmark_dataset,
    make_target_key,
    parse_benchmark_dataset,
    resolve_target_key,
)


def _payload(**overrides):
    base = {
        "id": "webexploitbench",
        "repo": "https://github.com/AgentCyberRange/WebExploitBench.git",
        "registry": "",
        "platform_root": "~/WebExploitBench",
        "targets": ["comfyui", "jetlinks"],
    }
    base.update(overrides)
    return base


def test_parse_reads_shared_attributes():
    dataset = parse_benchmark_dataset(_payload())
    assert dataset.id == "webexploitbench"
    assert dataset.repo.endswith("WebExploitBench.git")
    assert dataset.registry == ""
    assert dataset.platform_root == "~/WebExploitBench"
    assert dataset.targets == ("comfyui", "jetlinks")


def test_registry_defaults_to_empty():
    payload = _payload()
    del payload["registry"]
    assert parse_benchmark_dataset(payload).registry == ""


def test_exclude_services_parses_and_defaults_empty():
    assert parse_benchmark_dataset(_payload()).exclude_services == ()
    dataset = parse_benchmark_dataset(_payload(exclude_services=["evaluator"]))
    assert dataset.exclude_services == ("evaluator",)


def test_exclude_services_rejects_a_non_list():
    with pytest.raises(DatasetError, match="exclude_services"):
        parse_benchmark_dataset(_payload(exclude_services="evaluator"))


def test_native_services_parses_and_defaults_empty():
    assert parse_benchmark_dataset(_payload()).native_services == ()
    dataset = parse_benchmark_dataset(_payload(native_services=["redis"]))
    assert dataset.native_services == ("redis",)


def test_native_services_rejects_a_non_list():
    with pytest.raises(DatasetError, match="native_services"):
        parse_benchmark_dataset(_payload(native_services="redis"))


@pytest.mark.parametrize("missing", ["id", "repo"])
def test_missing_required_field_fails_loud(missing):
    payload = _payload()
    del payload[missing]
    with pytest.raises(DatasetError, match=missing):
        parse_benchmark_dataset(payload)


def test_unknown_field_fails_loud():
    with pytest.raises(DatasetError, match="unknown field"):
        parse_benchmark_dataset(_payload(extra="nope"))


def test_duplicate_targets_fail_loud():
    with pytest.raises(DatasetError, match="duplicate"):
        parse_benchmark_dataset(_payload(targets=["comfyui", "comfyui"]))


@pytest.mark.parametrize("bad", ["../escape", "a/b", ".."])
def test_non_path_safe_id_fails_loud(bad):
    with pytest.raises(DatasetError, match="path-safe"):
        parse_benchmark_dataset(_payload(id=bad))


def test_empty_id_fails_loud():
    with pytest.raises(DatasetError, match="non-empty"):
        parse_benchmark_dataset(_payload(id=""))


def test_non_path_safe_target_fails_loud():
    with pytest.raises(DatasetError, match="path-safe"):
        parse_benchmark_dataset(_payload(targets=["ok", "../bad"]))


def test_resolve_target_key():
    assert resolve_target_key("webexploitbench/comfyui") == ("webexploitbench", "comfyui")


@pytest.mark.parametrize("bad", ["comfyui", "a/b/c", "", "a/../b"])
def test_resolve_target_key_rejects_bad_keys(bad):
    with pytest.raises(DatasetError):
        resolve_target_key(bad)


def test_make_target_key_roundtrips():
    assert make_target_key("ds", "t") == "ds/t"
    assert resolve_target_key(make_target_key("ds", "t")) == ("ds", "t")


def test_absolute_platform_root_is_used_in_place(tmp_path):
    dataset = BenchmarkDataset(
        id="webexploitbench",
        repo="r",
        platform_root="~/WebExploitBench",
        targets=("comfyui",),
        eval_root=tmp_path,
    )
    assert dataset.bank_root() == Path.home() / "WebExploitBench"
    assert dataset.bank_entry("comfyui") == Path.home() / "WebExploitBench" / "comfyui"


def test_relative_platform_root_resolves_against_eval_root(tmp_path):
    dataset = BenchmarkDataset(
        id="mock", repo="r", platform_root="platform/mock", targets=("webmock",),
        eval_root=tmp_path,
    )
    assert dataset.bank_root() == tmp_path / "platform" / "mock"
    assert dataset.bank_entry("webmock") == tmp_path / "platform" / "mock" / "webmock"


def test_default_platform_root_is_the_repo_local_bank(tmp_path):
    dataset = BenchmarkDataset(id="mock", repo="r", targets=("webmock",), eval_root=tmp_path)
    assert dataset.bank_root() == tmp_path / "platform" / "mock"


def test_target_paths_are_keyed(tmp_path):
    dataset = BenchmarkDataset(
        id="webexploitbench", repo="r", targets=("comfyui",), eval_root=tmp_path
    )
    assert dataset.target_config_path("comfyui") == (
        tmp_path / "targets" / "webexploitbench" / "comfyui.yaml"
    )
    assert dataset.data_dir("comfyui") == (
        tmp_path / "data" / "webexploitbench" / "comfyui"
    )


def test_require_target_names_an_unknown_target(tmp_path):
    dataset = BenchmarkDataset(id="ds", repo="r", targets=("a",), eval_root=tmp_path)
    with pytest.raises(DatasetError, match="no target"):
        dataset.require_target("b")


def test_load_derives_eval_root_from_the_datasets_dir(tmp_path):
    datasets = tmp_path / "datasets"
    datasets.mkdir()
    path = datasets / "webexploitbench.yaml"
    path.write_text(
        "id: webexploitbench\nrepo: r\ntargets: [comfyui]\n", encoding="utf-8"
    )
    dataset = load_benchmark_dataset(path)
    assert dataset.eval_root == tmp_path
    assert dataset.target_config_path("comfyui") == (
        tmp_path / "targets" / "webexploitbench" / "comfyui.yaml"
    )


def test_load_reports_invalid_yaml(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("id: [unclosed\n", encoding="utf-8")
    with pytest.raises(DatasetError, match="invalid YAML"):
        load_benchmark_dataset(path)
