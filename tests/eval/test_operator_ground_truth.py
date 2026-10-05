"""The operator-only ground-truth source (operator dashboard, Task 2).

`GroundTruthSource` is the one place the operator API reads a benchmark
checkout. It resolves a Trial's `target_id` through operator-approved setup
files (never by stripping an ID suffix), reads only bounded, symlink-free files
under the mounted benchmark root, and projects each vulnerability to the small
path-free JSON shape the operator UI consumes. Every failure carries a stable
code and no host path.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from operator_api import ground_truth


def _setup_file(setup_root: Path, name: str, targets: list[tuple[str, str]]) -> None:
    """Write one valid EvalSetup mapping `target_id -> target_key`."""
    payload = {
        "schema_version": 1,
        "artifact_store": "/srv/eval-artifacts",
        "instances": [
            {
                "instance_id": "inst-1",
                "targets": [
                    {"target_key": key, "target_id": target_id}
                    for target_id, key in targets
                ],
            }
        ],
    }
    setup_root.mkdir(parents=True, exist_ok=True)
    (setup_root / name).write_text(yaml.safe_dump(payload), encoding="utf-8")


def _challenge(
    benchmark_root: Path,
    target: str,
    vulnerabilities: list[object],
    *,
    metadata: dict[str, object | None] | None = None,
) -> Path:
    """Write one benchmark target: `challenge.json` plus per-vuln metadata."""
    challenge_dir = benchmark_root / target
    challenge_dir.mkdir(parents=True, exist_ok=True)
    (challenge_dir / "challenge.json").write_text(
        json.dumps({"id": f"challenge-{target}", "vulnerabilities": vulnerabilities}),
        encoding="utf-8",
    )
    for vuln_id, meta in (metadata or {}).items():
        if meta is None:
            continue
        vuln_dir = challenge_dir / "vulnerability" / vuln_id
        vuln_dir.mkdir(parents=True, exist_ok=True)
        (vuln_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    return challenge_dir


def _metadata(location: str, vuln_type: str = "Arbitrary File Read") -> dict[str, str]:
    return {"Location": location, "Vulnerability Type": vuln_type}


def _source(
    benchmark_root: Path,
    setup_root: Path,
    setup_files: tuple[str, ...] = ("first.yaml",),
) -> ground_truth.GroundTruthSource:
    return ground_truth.GroundTruthSource(
        benchmark_root=benchmark_root,
        setup_root=setup_root,
        setup_files=setup_files,
    )


def _error_code(callable_) -> tuple[str, int]:
    with pytest.raises(ground_truth.GroundTruthError) as excinfo:
        callable_()
    error = excinfo.value
    return error.code, error.status_code


# --- mapping and projection ----------------------------------------------------


def test_reads_the_mapped_target_reference(tmp_path: Path) -> None:
    benchmark_root, setup_root = tmp_path / "bench", tmp_path / "setups"
    _setup_file(setup_root, "first.yaml", [("comfyui-1", "webexploitbench/comfyui")])
    _challenge(
        benchmark_root,
        "comfyui",
        [
            {"vuln_id": "comfyui-001", "scoring": ["LLM_judge"]},
            {"vuln_id": "comfyui-002", "scoring": ["route_probe", "dir_list"]},
        ],
        metadata={
            "comfyui-001": _metadata("http://comfyui-manager:8288/"),
            "comfyui-002": _metadata("/api/v1/items", "Path Traversal"),
        },
    )

    result = _source(benchmark_root, setup_root).read("comfyui-1")

    assert result == {
        "target_id": "comfyui-1",
        "provenance": "current_benchmark_checkout",
        "vulnerabilities": [
            {
                "vuln_id": "comfyui-001",
                "location": "http://comfyui-manager:8288/",
                "type": "Arbitrary File Read",
                "scoring": ["LLM_judge"],
            },
            {
                "vuln_id": "comfyui-002",
                "location": "/api/v1/items",
                "type": "Path Traversal",
                "scoring": ["route_probe", "dir_list"],
            },
        ],
    }


def test_mapping_resolves_target_ids_that_do_not_match_their_segment(tmp_path: Path) -> None:
    benchmark_root, setup_root = tmp_path / "bench", tmp_path / "setups"
    # `machine-a` is not a suffix of `webexploitbench/prestashop`: only the
    # explicit setup mapping may connect them.
    _setup_file(setup_root, "first.yaml", [("machine-a", "webexploitbench/prestashop")])
    _challenge(
        benchmark_root,
        "prestashop",
        [{"vuln_id": "presta-001", "scoring": []}],
        metadata={"presta-001": _metadata("http://prestashop:8080/")},
    )

    result = _source(benchmark_root, setup_root).read("machine-a")

    assert result["target_id"] == "machine-a"
    assert [v["vuln_id"] for v in result["vulnerabilities"]] == ["presta-001"]


def test_identical_duplicate_mappings_are_allowed(tmp_path: Path) -> None:
    benchmark_root, setup_root = tmp_path / "bench", tmp_path / "setups"
    _setup_file(setup_root, "first.yaml", [("comfyui-1", "webexploitbench/comfyui")])
    _setup_file(setup_root, "second.yaml", [("comfyui-1", "webexploitbench/comfyui")])
    _challenge(
        benchmark_root,
        "comfyui",
        [{"vuln_id": "comfyui-001", "scoring": ["LLM_judge"]}],
        metadata={"comfyui-001": _metadata("http://comfyui-manager:8288/")},
    )

    source = _source(benchmark_root, setup_root, ("first.yaml", "second.yaml"))

    assert len(source.read("comfyui-1")["vulnerabilities"]) == 1


def test_conflicting_mappings_fail_closed_for_that_target(tmp_path: Path) -> None:
    benchmark_root, setup_root = tmp_path / "bench", tmp_path / "setups"
    _setup_file(
        setup_root,
        "first.yaml",
        [
            ("comfyui-1", "webexploitbench/comfyui"),
            ("jetlinks-1", "webexploitbench/jetlinks"),
        ],
    )
    _setup_file(
        setup_root,
        "second.yaml",
        [
            ("comfyui-1", "webexploitbench/jetlinks"),
            ("jetlinks-1", "webexploitbench/jetlinks"),
        ],
    )
    _challenge(
        benchmark_root,
        "comfyui",
        [{"vuln_id": "comfyui-001", "scoring": ["LLM_judge"]}],
        metadata={"comfyui-001": _metadata("http://comfyui-manager:8288/")},
    )
    _challenge(
        benchmark_root,
        "jetlinks",
        [{"vuln_id": "jetlinks-001", "scoring": ["LLM_judge"]}],
        metadata={"jetlinks-001": _metadata("http://jetlinks:8848/")},
    )

    source = _source(benchmark_root, setup_root, ("first.yaml", "second.yaml"))

    code, status = _error_code(lambda: source.read("comfyui-1"))
    assert (code, status) == ("ground_truth_mapping_ambiguous", 409)
    # An unaffected target still resolves.
    assert source.read("jetlinks-1")["target_id"] == "jetlinks-1"


def test_unknown_target_is_a_path_free_404(tmp_path: Path) -> None:
    benchmark_root, setup_root = tmp_path / "bench", tmp_path / "setups"
    _setup_file(setup_root, "first.yaml", [("comfyui-1", "webexploitbench/comfyui")])

    code, status = _error_code(lambda: _source(benchmark_root, setup_root).read("nope-1"))

    assert (code, status) == ("ground_truth_target_unknown", 404)


@pytest.mark.parametrize("target_id", ["../etc", "a/b", "..", "", "a\\b", "."])
def test_unsafe_request_ids_are_rejected(target_id: str, tmp_path: Path) -> None:
    benchmark_root, setup_root = tmp_path / "bench", tmp_path / "setups"
    _setup_file(setup_root, "first.yaml", [("comfyui-1", "webexploitbench/comfyui")])

    code, status = _error_code(lambda: _source(benchmark_root, setup_root).read(target_id))

    assert (code, status) == ("ground_truth_invalid_target_id", 400)


# --- guarded source reads ------------------------------------------------------


def test_unsafe_setup_basenames_are_rejected(tmp_path: Path) -> None:
    benchmark_root, setup_root = tmp_path / "bench", tmp_path / "setups"
    _setup_file(setup_root, "first.yaml", [("comfyui-1", "webexploitbench/comfyui")])
    (tmp_path / "outside.yaml").write_text("schema_version: 1", encoding="utf-8")

    source = _source(benchmark_root, setup_root, ("../outside.yaml", "first.yaml"))

    code, status = _error_code(lambda: source.read("comfyui-1"))
    assert (code, status) == ("ground_truth_source_invalid", 503)


def test_symlinked_setup_file_is_rejected(tmp_path: Path) -> None:
    benchmark_root, setup_root = tmp_path / "bench", tmp_path / "setups"
    setup_root.mkdir(parents=True)
    outside = tmp_path / "real-first.yaml"
    outside.write_text("schema_version: 1", encoding="utf-8")
    (setup_root / "first.yaml").symlink_to(outside)

    code, status = _error_code(
        lambda: _source(benchmark_root, setup_root).read("comfyui-1")
    )
    assert (code, status) == ("ground_truth_source_invalid", 503)


def test_symlinked_benchmark_member_is_rejected(tmp_path: Path) -> None:
    benchmark_root, setup_root = tmp_path / "bench", tmp_path / "setups"
    _setup_file(setup_root, "first.yaml", [("comfyui-1", "webexploitbench/comfyui")])
    elsewhere = tmp_path / "elsewhere"
    _challenge(
        elsewhere,
        "comfyui",
        [{"vuln_id": "comfyui-001", "scoring": ["LLM_judge"]}],
        metadata={"comfyui-001": _metadata("http://comfyui-manager:8288/")},
    )
    benchmark_root.mkdir(parents=True, exist_ok=True)
    (benchmark_root / "comfyui").symlink_to(elsewhere / "comfyui", target_is_directory=True)

    code, status = _error_code(
        lambda: _source(benchmark_root, setup_root).read("comfyui-1")
    )
    assert (code, status) == ("ground_truth_source_invalid", 503)


def test_symlinked_challenge_file_is_rejected(tmp_path: Path) -> None:
    benchmark_root, setup_root = tmp_path / "bench", tmp_path / "setups"
    _setup_file(setup_root, "first.yaml", [("comfyui-1", "webexploitbench/comfyui")])
    target_dir = benchmark_root / "comfyui"
    target_dir.mkdir(parents=True)
    outside = tmp_path / "challenge.json"
    outside.write_text(json.dumps({"vulnerabilities": []}), encoding="utf-8")
    (target_dir / "challenge.json").symlink_to(outside)

    code, status = _error_code(
        lambda: _source(benchmark_root, setup_root).read("comfyui-1")
    )
    assert (code, status) == ("ground_truth_source_invalid", 503)


def test_malformed_challenge_json_is_unavailable(tmp_path: Path) -> None:
    benchmark_root, setup_root = tmp_path / "bench", tmp_path / "setups"
    _setup_file(setup_root, "first.yaml", [("comfyui-1", "webexploitbench/comfyui")])
    target_dir = benchmark_root / "comfyui"
    target_dir.mkdir(parents=True)
    (target_dir / "challenge.json").write_text("{ not json", encoding="utf-8")

    code, status = _error_code(
        lambda: _source(benchmark_root, setup_root).read("comfyui-1")
    )
    assert (code, status) == ("ground_truth_source_invalid", 503)


def test_missing_challenge_is_unavailable(tmp_path: Path) -> None:
    benchmark_root, setup_root = tmp_path / "bench", tmp_path / "setups"
    _setup_file(setup_root, "first.yaml", [("comfyui-1", "webexploitbench/comfyui")])
    benchmark_root.mkdir(parents=True)

    code, status = _error_code(
        lambda: _source(benchmark_root, setup_root).read("comfyui-1")
    )
    assert (code, status) == ("ground_truth_source_invalid", 503)


def test_absent_metadata_omits_only_that_entry(tmp_path: Path) -> None:
    benchmark_root, setup_root = tmp_path / "bench", tmp_path / "setups"
    _setup_file(setup_root, "first.yaml", [("comfyui-1", "webexploitbench/comfyui")])
    _challenge(
        benchmark_root,
        "comfyui",
        [
            {"vuln_id": "comfyui-001", "scoring": ["LLM_judge"]},
            {"vuln_id": "comfyui-002", "scoring": ["LLM_judge"]},
        ],
        metadata={"comfyui-002": _metadata("http://comfyui-manager:8288/")},
    )

    result = _source(benchmark_root, setup_root).read("comfyui-1")

    assert [v["vuln_id"] for v in result["vulnerabilities"]] == ["comfyui-002"]


def test_conflicting_duplicate_vulnerability_entries_choose_neither(tmp_path: Path) -> None:
    benchmark_root, setup_root = tmp_path / "bench", tmp_path / "setups"
    _setup_file(setup_root, "first.yaml", [("comfyui-1", "webexploitbench/comfyui")])
    _challenge(
        benchmark_root,
        "comfyui",
        [
            {"vuln_id": "comfyui-001", "scoring": ["LLM_judge"]},
            {"vuln_id": "comfyui-001", "scoring": ["route_probe"]},
            {"vuln_id": "comfyui-002", "scoring": ["LLM_judge"]},
        ],
        metadata={
            "comfyui-001": _metadata("http://comfyui-manager:8288/"),
            "comfyui-002": _metadata("http://comfyui-manager:8288/other"),
        },
    )

    result = _source(benchmark_root, setup_root).read("comfyui-1")

    assert [v["vuln_id"] for v in result["vulnerabilities"]] == ["comfyui-002"]


def test_unsafe_benchmark_vulnerability_ids_are_omitted(tmp_path: Path) -> None:
    benchmark_root, setup_root = tmp_path / "bench", tmp_path / "setups"
    _setup_file(setup_root, "first.yaml", [("comfyui-1", "webexploitbench/comfyui")])
    # `../evil` would escape `vulnerability/`; it must never be read.
    escaped = benchmark_root / "comfyui" / "evil"
    escaped.mkdir(parents=True)
    (escaped / "metadata.json").write_text(
        json.dumps(_metadata("http://evil.invalid/")), encoding="utf-8"
    )
    _challenge(
        benchmark_root,
        "comfyui",
        [
            {"vuln_id": "../evil", "scoring": ["LLM_judge"]},
            {"vuln_id": "comfyui-002", "scoring": ["LLM_judge"]},
        ],
        metadata={"comfyui-002": _metadata("http://comfyui-manager:8288/")},
    )

    result = _source(benchmark_root, setup_root).read("comfyui-1")

    assert [v["vuln_id"] for v in result["vulnerabilities"]] == ["comfyui-002"]


def test_preserves_http_locations_without_host_paths(tmp_path: Path) -> None:
    benchmark_root, setup_root = tmp_path / "bench", tmp_path / "setups"
    _setup_file(setup_root, "first.yaml", [("comfyui-1", "webexploitbench/comfyui")])
    _challenge(
        benchmark_root,
        "comfyui",
        [
            {"vuln_id": "comfyui-001", "scoring": ["LLM_judge"]},
            {"vuln_id": "comfyui-002", "scoring": ["LLM_judge"]},
            {"vuln_id": "comfyui-003", "scoring": ["LLM_judge"]},
            {"vuln_id": "comfyui-004", "scoring": ["LLM_judge"]},
            {"vuln_id": "comfyui-005", "scoring": ["LLM_judge"]},
        ],
        metadata={
            "comfyui-001": _metadata("http://comfyui-manager:8288/view"),
            "comfyui-002": _metadata("/etc/passwd"),
            "comfyui-003": _metadata("/root/secret.yaml"),
            "comfyui-004": _metadata("\\\\fileserver\\share\\secret.yaml"),
            "comfyui-005": _metadata("../../etc/passwd"),
        },
    )

    result = _source(benchmark_root, setup_root).read("comfyui-1")

    assert [v["location"] for v in result["vulnerabilities"]] == [
        "http://comfyui-manager:8288/view"
    ]
    serialized = json.dumps(result)
    assert str(tmp_path) not in serialized
    assert "fileserver" not in serialized
    assert "/etc/passwd" not in serialized


# --- bounds --------------------------------------------------------------------


def test_files_over_the_size_bound_are_rejected(tmp_path: Path) -> None:
    benchmark_root, setup_root = tmp_path / "bench", tmp_path / "setups"
    _setup_file(setup_root, "first.yaml", [("comfyui-1", "webexploitbench/comfyui")])
    target_dir = benchmark_root / "comfyui"
    target_dir.mkdir(parents=True)
    (target_dir / "challenge.json").write_text(
        "x" * (ground_truth.MAX_SOURCE_BYTES + 1), encoding="utf-8"
    )

    code, status = _error_code(
        lambda: _source(benchmark_root, setup_root).read("comfyui-1")
    )
    assert (code, status) == ("ground_truth_source_invalid", 503)


def test_too_many_vulnerabilities_is_rejected(tmp_path: Path) -> None:
    benchmark_root, setup_root = tmp_path / "bench", tmp_path / "setups"
    _setup_file(setup_root, "first.yaml", [("comfyui-1", "webexploitbench/comfyui")])
    _challenge(
        benchmark_root,
        "comfyui",
        [
            {"vuln_id": f"v-{index}", "scoring": []}
            for index in range(ground_truth.MAX_VULNERABILITIES + 1)
        ],
    )

    code, status = _error_code(
        lambda: _source(benchmark_root, setup_root).read("comfyui-1")
    )
    assert (code, status) == ("ground_truth_source_invalid", 503)


def test_overlong_display_strings_are_omitted(tmp_path: Path) -> None:
    benchmark_root, setup_root = tmp_path / "bench", tmp_path / "setups"
    _setup_file(setup_root, "first.yaml", [("comfyui-1", "webexploitbench/comfyui")])
    _challenge(
        benchmark_root,
        "comfyui",
        [
            {"vuln_id": "comfyui-001", "scoring": ["LLM_judge"]},
            {"vuln_id": "comfyui-002", "scoring": ["LLM_judge"]},
        ],
        metadata={
            "comfyui-001": _metadata("/" + "a" * (ground_truth.MAX_TEXT_CHARS + 1)),
            "comfyui-002": _metadata("/view"),
        },
    )

    result = _source(benchmark_root, setup_root).read("comfyui-1")

    assert [v["vuln_id"] for v in result["vulnerabilities"]] == ["comfyui-002"]


def test_serialized_output_over_the_bound_is_rejected(tmp_path: Path) -> None:
    benchmark_root, setup_root = tmp_path / "bench", tmp_path / "setups"
    _setup_file(setup_root, "first.yaml", [("comfyui-1", "webexploitbench/comfyui")])
    long_location = "/view?" + "a" * (ground_truth.MAX_TEXT_CHARS - 20)
    # The per-entry bounds are all respected; only the serialized total is over.
    vuln_ids = [f"v-{index:03d}" for index in range(ground_truth.MAX_VULNERABILITIES)]
    _challenge(
        benchmark_root,
        "comfyui",
        [{"vuln_id": vuln_id, "scoring": ["LLM_judge"]} for vuln_id in vuln_ids],
        metadata={vuln_id: _metadata(long_location) for vuln_id in vuln_ids},
    )

    code, status = _error_code(
        lambda: _source(benchmark_root, setup_root).read("comfyui-1")
    )
    assert (code, status) == ("ground_truth_source_invalid", 503)


# --- dataset scope and health --------------------------------------------------


def test_a_non_webexploitbench_dataset_is_unavailable(tmp_path: Path) -> None:
    benchmark_root, setup_root = tmp_path / "bench", tmp_path / "setups"
    _setup_file(setup_root, "first.yaml", [("app-1", "mock/app")])

    code, status = _error_code(
        lambda: _source(benchmark_root, setup_root).read("app-1")
    )
    assert (code, status) == ("ground_truth_source_unavailable", 503)


def test_health_reports_state_without_ground_truth(tmp_path: Path) -> None:
    benchmark_root, setup_root = tmp_path / "bench", tmp_path / "setups"
    _setup_file(setup_root, "first.yaml", [("comfyui-1", "webexploitbench/comfyui")])
    _challenge(
        benchmark_root,
        "comfyui",
        [{"vuln_id": "comfyui-001", "scoring": ["LLM_judge"]}],
        metadata={"comfyui-001": _metadata("http://comfyui-manager:8288/")},
    )

    healthy = _source(benchmark_root, setup_root).health()
    assert healthy == {"status": "ok"}
    assert "comfyui-001" not in json.dumps(healthy)

    missing = _source(tmp_path / "absent", setup_root).health()
    assert missing == {"status": "degraded"}

    unreadable = _source(benchmark_root, setup_root, ("missing.yaml",)).health()
    assert unreadable == {"status": "degraded"}


def test_errors_never_carry_the_source_root(tmp_path: Path) -> None:
    benchmark_root, setup_root = tmp_path / "bench", tmp_path / "setups"
    _setup_file(setup_root, "first.yaml", [("comfyui-1", "webexploitbench/comfyui")])

    with pytest.raises(ground_truth.GroundTruthError) as excinfo:
        _source(benchmark_root, setup_root).read("comfyui-1")

    assert str(tmp_path) not in str(excinfo.value)
