"""The synthetic *storage-compatibility* corpus for the eval read API.

These tests pin the generator to the *production* contract of the four sources
the read API now reads - the materialized store, the persistent raw project
root, the primary runs root and the optional legacy runs root - so the dashboard
can be exercised end-to-end without a real evaluation:

- ids, digests, counts and graph hashes come from the production helpers, never
  hand-authored;
- the resolved inventory equals the allowlisted files really on disk, and every
  detail/content round-trip re-verifies the same bytes;
- the evidence chain only resolves inside its own Trial;
- spend distinguishes zero from absent, and reads primary *and* legacy roots;
- `refresh` adds new data that a later request (or the frontend poll) sees
  without an API restart, and stays deterministic and non-destructive.

The corpus is FAKE; nothing here touches a real store, raw data, Neo4j or the
benchmark checkout.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from collections import Counter
from pathlib import Path

import pytest
import yaml

from orchestrator import verdicts as orchestrator_verdicts
from orchestrator.files import FileStore
from read_api import source as source_module
from read_api import storage_compat_corpus as corpus

REPO_ROOT = Path(__file__).resolve().parents[2]

COMPLETE = ("demo-complete-1", "demo-run-a", "demo-complete-trial-1")
INTERRUPTED = ("demo-interrupted-1", "demo-run-a", "demo-interrupted-trial-1")
HISTORICAL = ("demo-historical-1", "demo-run-legacy", "demo-historical-trial-1")
DELTA = ("demo-complete-1", "demo-run-a", "demo-delta-trial-1")

FOUR_KINDS = {
    "hunt_config",
    "test_spec",
    "pod_variant",
    "experiment_log",
    "pod_export",
    "skill_procedure",
}


def _adapter(roots: "corpus.Roots") -> source_module.ArtifactStoreSnapshotSource:
    """The read API source wired exactly as the environment configures it."""
    env = roots.environment()
    return source_module.ArtifactStoreSnapshotSource(
        store=env["EVAL_ARTIFACT_STORE"],
        project_data_root=env["EVAL_PROJECT_DATA_ROOT"],
        runs_root=env["EVAL_RUNS_ROOT"],
        legacy_runs_root=env["EVAL_RUNS_LEGACY_ROOT"],
        instance_id=env["EVAL_INSTANCE_ID"],
        dataset_id=env["EVAL_DATASET_ID"],
        dataset_name=env["EVAL_DATASET_NAME"],
    )


def _fingerprint(root: Path) -> dict[str, str]:
    """Every file's posix-relative path -> sha256 of its bytes."""
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            out[path.relative_to(root).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return out


def _flatten(groups: list[dict]) -> list[dict]:
    """Every entry of a (possibly nested) resolved inventory, in order."""
    entries: list[dict] = []
    for group in groups:
        entries.extend(group["entries"])
        entries.extend(_flatten(group["children"]))
    return entries


def _inventory(
    adapter: source_module.ArtifactStoreSnapshotSource, trial: tuple[str, str, str]
) -> list[dict]:
    body = adapter.list_resolved_artifacts(*trial)
    return _flatten(body["groups"])


def _trial(snapshot: dict, trial_id: str) -> dict:
    for trial in snapshot["trials"]:
        if trial["trial_id"] == trial_id:
            return trial
    raise AssertionError(f"trial {trial_id} missing from the snapshot")


def _pod_export_documents(
    adapter: source_module.ArtifactStoreSnapshotSource, trial: tuple[str, str, str]
) -> list[dict]:
    """Decode every pod_export artifact through the content endpoint's bytes."""
    documents: list[dict] = []
    for entry in _inventory(adapter, trial):
        if entry["kind"] != "pod_export":
            continue
        download = adapter.stream_resolved_artifact(
            *trial, entry["artifact_id"], entry["sha256"]
        )
        documents.append(yaml.safe_load(b"".join(download.chunks)))
    return documents


# --- generation: deterministic, isolated, non-destructive ----------------------


def test_generate_is_deterministic_and_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    corpus.generate(root)
    first = _fingerprint(root)

    corpus.generate(root)

    assert _fingerprint(root) == first


def test_generate_writes_within_the_root_and_labels_the_dataset() -> None:
    assert corpus.DATASET_ID == "storage-compatibility"
    assert corpus.DATASET_NAME.startswith("Synthetic")
    assert corpus.DEFAULT_ROOT.startswith("/")
    # No real store/raw/runs path is ever referenced by the corpus constants.
    assert "eval-artifacts" not in str(corpus.DEFAULT_ROOT)


def test_generate_keeps_the_four_roots_separate(tmp_path: Path) -> None:
    roots = corpus.generate(tmp_path / "corpus")

    for directory in (roots.store, roots.raw, roots.runs, roots.legacy_runs):
        assert directory.is_dir()
    # The store holds only materialized Trials; the raw root holds only project
    # trees; the runs roots hold only the authoritative spend records.
    assert (roots.store / COMPLETE[0] / COMPLETE[1] / COMPLETE[2] / "run-manifest.yaml").is_file()
    assert (roots.raw / "demo-project-complete-1").is_dir()
    assert not (roots.raw / COMPLETE[0] / COMPLETE[1]).exists()
    assert (roots.runs / COMPLETE[0] / f"{COMPLETE[2]}.yaml").is_file()
    assert (roots.legacy_runs / HISTORICAL[0] / f"{HISTORICAL[2]}.yaml").is_file()


def test_generate_leaves_unknown_files_untouched(tmp_path: Path) -> None:
    roots = corpus.generate(tmp_path / "corpus")
    sentinel = roots.runs / "keep-me.txt"
    sentinel.write_text("do not delete\n", encoding="utf-8")

    corpus.generate(roots.root)

    assert sentinel.read_text(encoding="utf-8") == "do not delete\n"


# --- snapshot: identity, dataset, counts ---------------------------------------


def test_snapshot_dataset_identity_and_summary(tmp_path: Path) -> None:
    adapter = _adapter(corpus.generate(tmp_path / "corpus"))

    snapshot = adapter.snapshot()

    assert snapshot["dataset"] == {
        "id": corpus.DATASET_ID,
        "name": corpus.DATASET_NAME,
    }
    assert snapshot["summary"] == {
        "targets": 3,
        "trials": 3,
        "identified": 2,
        "partial": 1,
        "missed": 2,
        "degraded": 0,
    }


def test_snapshot_trials_carry_full_identity_and_instance(tmp_path: Path) -> None:
    adapter = _adapter(corpus.generate(tmp_path / "corpus"))

    trials = adapter.snapshot()["trials"]

    identities = {
        (t["target_id"], t["target_run_id"], t["trial_id"]) for t in trials
    }
    assert {COMPLETE, INTERRUPTED, HISTORICAL} == identities
    assert {t["instance_id"] for t in trials} == {corpus.INSTANCE_ID}
    assert {t["project_id"] for t in trials} == {
        "demo-project-complete-1",
        "demo-project-interrupted-1",
        "demo-project-historical-1",
    }


def test_no_host_path_leaks_into_the_snapshot(tmp_path: Path) -> None:
    roots = corpus.generate(tmp_path / "corpus")

    snapshot = _adapter(roots).snapshot()

    assert str(roots.root) not in repr(snapshot)


# --- complete Trial: inventory == allowlisted files on disk --------------------


def test_complete_inventory_equals_allowlisted_files_on_disk(tmp_path: Path) -> None:
    roots = corpus.generate(tmp_path / "corpus")
    adapter = _adapter(roots)

    entries = _inventory(adapter, COMPLETE)

    project = roots.raw / "demo-project-complete-1"
    on_disk = {
        path.relative_to(project).as_posix()
        for path in project.rglob("*")
        if path.is_file() and not path.name.startswith(".")
    }
    listed = {entry["relative_path"] for entry in entries}
    assert listed == on_disk
    # The captured inventory re-derives every digest from the file it lists.
    for entry in entries:
        assert entry["artifact_id"] == hashlib.sha256(
            entry["relative_path"].encode("utf-8")
        ).hexdigest()
        assert entry["sha256"] == hashlib.sha256(
            (project / entry["relative_path"]).read_bytes()
        ).hexdigest()


def test_complete_inventory_detail_and_content_round_trip(tmp_path: Path) -> None:
    adapter = _adapter(corpus.generate(tmp_path / "corpus"))

    entries = _inventory(adapter, COMPLETE)
    assert entries
    for entry in entries:
        detail = adapter.get_resolved_artifact(
            *COMPLETE, entry["artifact_id"]
        )
        assert detail["entry"]["relative_path"] == entry["relative_path"]
        download = adapter.stream_resolved_artifact(
            *COMPLETE, entry["artifact_id"], entry["sha256"]
        )
        data = b"".join(download.chunks)
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]


def test_complete_inventory_covers_every_producer_kind(tmp_path: Path) -> None:
    adapter = _adapter(corpus.generate(tmp_path / "corpus"))

    kinds = Counter(entry["kind"] for entry in _inventory(adapter, COMPLETE))

    assert FOUR_KINDS <= set(kinds)
    assert kinds["pod_export"] == len(corpus.TERMINAL_REASONS)
    assert kinds["pod_variant"] == len(corpus.TERMINAL_REASONS)
    assert kinds["experiment_log"] == len(corpus.TERMINAL_REASONS)


def test_complete_test_specs_split_produced_and_consumed(tmp_path: Path) -> None:
    adapter = _adapter(corpus.generate(tmp_path / "corpus"))

    paths = [
        entry["relative_path"]
        for entry in _inventory(adapter, COMPLETE)
        if entry["kind"] == "test_spec"
    ]

    assert any("/produced/" in path for path in paths)
    assert any("/consumed/" in path for path in paths)


# --- pod exports: the persisted envelope and the six terminal reasons ----------


def test_complete_pod_exports_cover_the_six_terminal_reasons(tmp_path: Path) -> None:
    adapter = _adapter(corpus.generate(tmp_path / "corpus"))

    documents = _pod_export_documents(adapter, COMPLETE)

    reasons = Counter(doc["evidence"]["terminal_reason"] for doc in documents)
    assert set(reasons) == set(corpus.TERMINAL_REASONS)
    assert all(count == 1 for count in reasons.values())
    # The producer's persisted envelope: verdict at the root, D5 under evidence.
    for doc in documents:
        assert set(doc) == {"verdict", "evidence"}
        assert isinstance(doc["evidence"]["iterations"], int)
        assert isinstance(doc["evidence"]["clean"], bool)


def test_pod_export_preserves_the_zero_iteration_unclean_boundary(tmp_path: Path) -> None:
    adapter = _adapter(corpus.generate(tmp_path / "corpus"))

    boundary = {
        doc["evidence"]["terminal_reason"]: doc["evidence"]
        for doc in _pod_export_documents(adapter, COMPLETE)
    }["no-symptom-evidence"]

    assert boundary["iterations"] == 0
    assert boundary["clean"] is False


def test_pod_export_uses_the_real_filename_layout(tmp_path: Path) -> None:
    adapter = _adapter(corpus.generate(tmp_path / "corpus"))

    exports = [
        entry["relative_path"]
        for entry in _inventory(adapter, COMPLETE)
        if entry["kind"] == "pod_export"
    ]

    assert exports
    for path in exports:
        assert path.endswith(f"/{corpus.POD_RUN_ID}.yaml")
        assert not path.endswith("/export.yaml")


def test_pod_export_evidence_is_not_the_verdict_axis(tmp_path: Path) -> None:
    """terminal_reason lives under evidence and is never the verdict."""
    adapter = _adapter(corpus.generate(tmp_path / "corpus"))

    for doc in _pod_export_documents(adapter, COMPLETE):
        assert doc["verdict"] in {"successful", "unsuccessful"}
        assert doc["evidence"]["terminal_reason"] in corpus.TERMINAL_REASONS
        assert doc["verdict"] != doc["evidence"]["terminal_reason"]


# --- evidence chains resolve only inside their own Trial -----------------------


def test_complete_evidence_chain_resolves_inside_the_same_trial(tmp_path: Path) -> None:
    adapter = _adapter(corpus.generate(tmp_path / "corpus"))
    entries = _inventory(adapter, COMPLETE)
    listed = {entry["relative_path"] for entry in entries}
    spec_files = {
        entry["relative_path"] for entry in entries if entry["kind"] == "test_spec"
    }
    project_id = "demo-project-complete-1"

    trial = _trial(adapter.snapshot(), COMPLETE[2])
    linked: list[str] = []
    unresolved_directories: list[str] = []
    for verdict in trial["verdicts"]:
        for reference in verdict["evidence"]:
            candidate = reference
            if candidate.startswith(f"{project_id}/"):
                candidate = candidate[len(project_id) + 1 :]
            if candidate in listed:
                linked.append(candidate)
            else:
                unresolved_directories.append(candidate)

    assert linked, "the complete Trial must expose at least one linkable reference"
    # `spec_dir` names a directory, never a linkable file: it stays visible as
    # an unresolved reference rather than being faked into an artifact.
    assert unresolved_directories
    assert all(candidate not in listed for candidate in unresolved_directories)
    # The unresolved reference is the *directory* that holds the produced specs,
    # not one of the spec files themselves.
    assert any(
        candidate
        and any(spec_path.startswith(f"{candidate}/") for spec_path in spec_files)
        for candidate in unresolved_directories
    )


def test_evidence_never_leaks_across_trials(tmp_path: Path) -> None:
    roots = corpus.generate(tmp_path / "corpus")
    adapter = _adapter(roots)
    complete = {
        entry["relative_path"]: entry["sha256"] for entry in _inventory(adapter, COMPLETE)
    }
    historical = {
        entry["relative_path"]: entry["sha256"]
        for entry in _inventory(adapter, HISTORICAL)
    }

    assert complete and historical
    # The two Trials share the same relative layout; the pod-execution paths
    # exist only in the complete Trial's captured inventory.
    pod_paths = {path for path in complete if "test-executor-pod" in path}
    assert pod_paths
    assert pod_paths.isdisjoint(historical)
    # Where a shared reference exists, each Trial resolves its own bytes, so the
    # hunting artifacts carry distinct digests - never the other Trial's file.
    shared_hunting = {
        path for path in set(complete) & set(historical) if path.startswith("hunting/")
    }
    assert shared_hunting
    assert all(complete[path] != historical[path] for path in shared_hunting)


# --- interrupted Trial: partial artifacts, no invented evidence ----------------


def test_interrupted_trial_is_partial_with_no_pod_export(tmp_path: Path) -> None:
    adapter = _adapter(corpus.generate(tmp_path / "corpus"))

    trial = _trial(adapter.snapshot(), INTERRUPTED[2])
    entries = _inventory(adapter, INTERRUPTED)

    assert trial["artifact_summary"] == {
        "status": "project_snapshot_unavailable",
        "hunting": 0,
        "skills": 0,
    }
    assert entries, "the interrupted Trial still reads its external raw tree"
    assert not any(entry["kind"] == "pod_export" for entry in entries)


def test_interrupted_trial_synthesizes_no_evidence(tmp_path: Path) -> None:
    adapter = _adapter(corpus.generate(tmp_path / "corpus"))

    trial = _trial(adapter.snapshot(), INTERRUPTED[2])

    assert all(verdict["evidence"] == [] for verdict in trial["verdicts"])


def test_interrupted_trial_spend_is_absent_not_zero(tmp_path: Path) -> None:
    adapter = _adapter(corpus.generate(tmp_path / "corpus"))

    spend = _trial(adapter.snapshot(), INTERRUPTED[2])["spend"]

    assert spend["status"] == "available"
    assert spend["spent_tokens"] is None  # absent, never a guessed zero
    assert spend["spend_overshoot"] == 0  # a real zero is preserved
    assert spend["spend_by_agent"] is None


def test_refresh_adds_a_new_artifact_to_the_partial_trial(tmp_path: Path) -> None:
    roots = corpus.generate(tmp_path / "corpus")
    adapter = _adapter(roots)
    before = {entry["relative_path"] for entry in _inventory(adapter, INTERRUPTED)}

    corpus.refresh(roots.root)

    after = {entry["relative_path"] for entry in _inventory(adapter, INTERRUPTED)}
    added = after - before
    assert len(added) == 1
    assert any(path.endswith("demo-delta-spec.yaml") for path in added)


# --- historical Trial: schema v1 in the legacy root, raw fallback --------------


def test_historical_trial_manifest_is_schema_v1(tmp_path: Path) -> None:
    roots = corpus.generate(tmp_path / "corpus")

    text = (
        roots.store / HISTORICAL[0] / HISTORICAL[1] / HISTORICAL[2] / "run-manifest.yaml"
    ).read_text(encoding="utf-8")

    assert "schema_version: 1" in text


def test_historical_trial_falls_back_to_the_raw_project(tmp_path: Path) -> None:
    adapter = _adapter(corpus.generate(tmp_path / "corpus"))

    body = adapter.list_resolved_artifacts(*HISTORICAL)

    assert body["status"] == "available"
    assert body["source"] == "project_storage"
    assert body["fallback_reason"] == "project_artifacts_unavailable"
    assert _flatten(body["groups"])


def test_historical_trial_reports_no_captured_graph(tmp_path: Path) -> None:
    adapter = _adapter(corpus.generate(tmp_path / "corpus"))

    body = adapter.resolved_graph(*HISTORICAL)

    assert body["status"] == "unavailable"
    assert body["reason"] == "project_graph_unavailable"


# --- graph: the complete Trial's L0/L1 projection is meaningful ----------------


def test_complete_graph_is_captured_and_non_empty(tmp_path: Path) -> None:
    adapter = _adapter(corpus.generate(tmp_path / "corpus"))

    body = adapter.resolved_graph(*COMPLETE)

    assert body["status"] == "available"
    assert body["source"] == "trial_snapshot"
    assert body["project_id"] == "demo-project-complete-1"
    graph = body["graph"]
    assert len(graph["nodes"]) >= 3
    assert graph["links"]
    types = {node["type"] for node in graph["nodes"]}
    assert {"L1Service", "Endpoint", "Parameter"} <= types


def test_prefixes_of_the_graph_are_reported_when_available(tmp_path: Path) -> None:
    adapter = _adapter(corpus.generate(tmp_path / "corpus"))

    body = adapter.resolved_graph(*COMPLETE)

    assert body["captured_at"] == corpus.CAPTURED_AT
    assert body["sha256"]


# --- spend: primary and legacy roots, zero vs absent ---------------------------


def test_spend_reads_the_primary_root(tmp_path: Path) -> None:
    adapter = _adapter(corpus.generate(tmp_path / "corpus"))

    spend = _trial(adapter.snapshot(), COMPLETE[2])["spend"]

    assert spend["status"] == "available"
    assert spend["spent_tokens"] == 1234
    assert spend["spend_by_agent"] == {
        "hunter": {"total_tokens": 900},
        "pod": {"total_tokens": 334},
    }


def test_spend_reads_the_legacy_root_and_keeps_a_zero(tmp_path: Path) -> None:
    adapter = _adapter(corpus.generate(tmp_path / "corpus"))

    spend = _trial(adapter.snapshot(), HISTORICAL[2])["spend"]

    assert spend["status"] == "available"
    assert spend["spent_tokens"] == 0  # zero is a value, not absence
    assert spend["reason"] is None


# --- refresh: new data without an API restart ----------------------------------


def test_refresh_materializes_a_new_trial_without_restart(tmp_path: Path) -> None:
    roots = corpus.generate(tmp_path / "corpus")
    adapter = _adapter(roots)
    before = {t["trial_id"] for t in adapter.snapshot()["trials"]}

    corpus.refresh(roots.root)

    after = {t["trial_id"] for t in adapter.snapshot()["trials"]}
    assert DELTA[2] in after - before
    assert _trial(adapter.snapshot(), DELTA[2])["spend"]["spent_tokens"] == 777


def test_refresh_updates_an_existing_spend_record(tmp_path: Path) -> None:
    roots = corpus.generate(tmp_path / "corpus")
    adapter = _adapter(roots)
    assert _trial(adapter.snapshot(), INTERRUPTED[2])["spend"]["spent_tokens"] is None

    corpus.refresh(roots.root)

    assert _trial(adapter.snapshot(), INTERRUPTED[2])["spend"]["spent_tokens"] == 4321


def test_refresh_never_touches_the_historical_capture(tmp_path: Path) -> None:
    roots = corpus.generate(tmp_path / "corpus")
    trial_dir = roots.store / HISTORICAL[0] / HISTORICAL[1] / HISTORICAL[2]
    before = _fingerprint(trial_dir)

    corpus.refresh(roots.root)

    assert _fingerprint(trial_dir) == before


def test_refresh_is_idempotent(tmp_path: Path) -> None:
    roots = corpus.generate(tmp_path / "corpus")
    corpus.refresh(roots.root)
    once = _fingerprint(roots.root)

    corpus.refresh(roots.root)

    assert _fingerprint(roots.root) == once


def test_refresh_is_a_separate_action_not_a_background_timer(tmp_path: Path) -> None:
    """`generate` alone never writes the delta; only `refresh` adds it."""
    roots = corpus.generate(tmp_path / "corpus")
    adapter = _adapter(roots)

    assert DELTA[2] not in {t["trial_id"] for t in adapter.snapshot()["trials"]}


def test_instructions_expose_every_root_and_a_demo_only_command(
    tmp_path: Path,
) -> None:
    roots = corpus.generate(tmp_path / "corpus")

    text = corpus.instructions(roots)

    assert str(roots.store) in text
    assert str(roots.raw) in text
    assert str(roots.runs) in text
    assert str(roots.legacy_runs) in text
    assert "28090" in text
    assert "--root" in text and str(roots.root) in text


# --- the production validator accepts every verdict chain ----------------------


def _validate_case(roots: "corpus.Roots", spec: "corpus.CaseSpec"):
    """Validate one case's `verdicts.yaml` with the real production reader."""
    trial_dir = roots.store / spec.target_id / spec.target_run_id / spec.trial_id
    rows = yaml.safe_load((trial_dir / "verdicts.yaml").read_text(encoding="utf-8"))
    return orchestrator_verdicts.validate_verdicts(
        rows,
        data_root=roots.raw,
        files=FileStore(),
        eval_sha=spec.eval_sha,
        stack_fingerprint=spec.stack_fingerprint,
    )


@pytest.mark.parametrize("spec", corpus.CASES, ids=lambda spec: spec.trial_id)
def test_every_case_verdict_chain_passes_the_production_validator(
    tmp_path: Path, spec: "corpus.CaseSpec"
) -> None:
    roots = corpus.generate(tmp_path / "corpus")

    verdicts = _validate_case(roots, spec)

    assert verdicts, "every case must expose at least one verdict row"
    for verdict in verdicts:
        if verdict.identified in ("identified", "partial"):
            assert verdict.evidence_chain is not None


def test_historical_case_chain_points_at_a_real_log_and_pod_export(
    tmp_path: Path,
) -> None:
    roots = corpus.generate(tmp_path / "corpus")
    adapter = _adapter(roots)
    project_id = "demo-project-historical-1"
    entries = {entry["relative_path"]: entry for entry in _inventory(adapter, HISTORICAL)}

    trial = _trial(adapter.snapshot(), HISTORICAL[2])
    linked: list[str] = []
    for verdict in trial["verdicts"]:
        for reference in verdict["evidence"]:
            candidate = reference
            if candidate.startswith(f"{project_id}/"):
                candidate = candidate[len(project_id) + 1 :]
            if candidate in entries:
                linked.append(candidate)

    logs = [path for path in linked if path.endswith("/experiment-log/0.yaml")]
    exports = [path for path in linked if entries[path]["kind"] == "pod_export"]
    assert logs, "the historical chain must resolve a real ExperimentLog"
    assert len(exports) == 1, "the historical chain must resolve exactly one PodExport"
    # The export keeps the producer's official `<spec_id>/<run_id>.yaml` layout.
    export_path = exports[0]
    assert export_path.endswith(f"/{corpus.POD_RUN_ID}.yaml")
    assert "/test-executor-pod/" in export_path

    # Inventory/detail/content expose the new artifacts, and the export carries
    # the real envelope: verdict at the root, D5 under evidence.
    for path in logs + exports:
        entry = entries[path]
        detail = adapter.get_resolved_artifact(*HISTORICAL, entry["artifact_id"])
        assert detail["entry"]["relative_path"] == path
        download = adapter.stream_resolved_artifact(
            *HISTORICAL, entry["artifact_id"], entry["sha256"]
        )
        body = yaml.safe_load(b"".join(download.chunks))
        if entry["kind"] == "pod_export":
            assert set(body) == {"verdict", "evidence"}
            assert body["verdict"] in {"successful", "unsuccessful"}
            assert body["evidence"]["terminal_reason"] in corpus.TERMINAL_REASONS
            assert isinstance(body["evidence"]["iterations"], int)
            assert isinstance(body["evidence"]["clean"], bool)


def test_historical_invariants_survive_the_chain_fix(tmp_path: Path) -> None:
    roots = corpus.generate(tmp_path / "corpus")
    adapter = _adapter(roots)

    # Still a schema-v1 historical capture read from the raw fallback...
    manifest = (
        roots.store / HISTORICAL[0] / HISTORICAL[1] / HISTORICAL[2] / "run-manifest.yaml"
    ).read_text(encoding="utf-8")
    assert "schema_version: 1" in manifest
    inventory = adapter.list_resolved_artifacts(*HISTORICAL)
    assert inventory["source"] == "project_storage"
    assert inventory["fallback_reason"] == "project_artifacts_unavailable"
    # ...with no captured graph and a real zero spend from the legacy root.
    assert adapter.resolved_graph(*HISTORICAL)["status"] == "unavailable"
    assert _trial(adapter.snapshot(), HISTORICAL[2])["spend"]["spent_tokens"] == 0
    # And the interrupted Trial still invents no PodExport.
    assert not any(
        entry["kind"] == "pod_export" for entry in _inventory(adapter, INTERRUPTED)
    )


# --- the printed startup command is really executable --------------------------


def _serve_command(instructions_text: str) -> str:
    """The read-API startup line, joining its backslash continuations."""
    lines = instructions_text.splitlines()
    index = next(i for i, line in enumerate(lines) if "uvicorn" in line)
    start = index
    while start > 0 and lines[start - 1].rstrip().endswith("\\"):
        start -= 1
    parts: list[str] = []
    cursor = start
    while cursor < len(lines):
        raw = lines[cursor].strip()
        parts.append(raw.rstrip("\\").strip())
        if not raw.endswith("\\"):
            break
        cursor += 1
    return " ".join(part for part in parts if part)


def test_instructions_command_runs_from_the_root_with_the_eval_environment(
    tmp_path: Path,
) -> None:
    # A corpus root that contains a space: the command must still parse.
    roots = corpus.generate(tmp_path / "my corpus")
    command = _serve_command(corpus.instructions(roots))
    assert "uvicorn" in command and "28090" in command

    stub_dir = tmp_path / "stub-bin"
    stub_dir.mkdir()
    args_out = tmp_path / "argv.txt"
    env_out = tmp_path / "env.txt"
    stub = stub_dir / "python"
    stub.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$@" > "{args_out}"\n'
        f'env > "{env_out}"\n',
        encoding="utf-8",
    )
    stub.chmod(0o755)

    env = {"PATH": f"{stub_dir}{os.pathsep}{os.environ.get('PATH', '')}"}
    result = subprocess.run(
        ["sh", "-c", command], cwd=REPO_ROOT, env=env, capture_output=True, text=True
    )

    assert result.returncode == 0, result.stderr
    # The stub replaced only the Python process: it receives the uvicorn argv...
    argv = args_out.read_text(encoding="utf-8").splitlines()
    assert argv == ["-m", "uvicorn", "read_api.app:app", "--port", "28090"]
    # ...and the whole EVAL_* environment, in the Python process - not a `cd`.
    envmap = dict(
        line.split("=", 1)
        for line in env_out.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )
    for key, value in roots.environment().items():
        assert envmap.get(key) == value, key
    assert envmap.get("PYTHONPATH") == "eval"


def test_instructions_refresh_command_quotes_a_root_with_spaces(tmp_path: Path) -> None:
    roots = corpus.generate(tmp_path / "my corpus")

    text = corpus.instructions(roots)

    assert f"'{roots.root}'" in text or f'"{roots.root}"' in text


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
