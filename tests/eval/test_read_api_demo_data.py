"""The synthetic demo store for the /eval pages (#278).

These tests pin the generator's contract with the *real* materializer, not just
with the UI payload: manifests come from the production builder, every evidence
reference of a complete trial resolves to a real file or directory inside that
trial, and the verdicts/diagnoses pass the production readers (including the
pairing rule). They also keep the corpus honest - exact counts through
`build_snapshot`, the full-pipeline / hunting-only / failure-injection scenarios,
deterministic regeneration, non-destructive idempotency, and the absence of host
paths, credentials or links.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from orchestrator import diagnosis as orchestrator_diagnosis
from orchestrator import files as orchestrator_files
from orchestrator import store as orchestrator_store
from orchestrator import verdicts as orchestrator_verdicts
from read_api import app as app_module
from read_api import demo_data
from read_api import source as source_module
from read_api.projection import build_snapshot

MANIFEST = "run-manifest.yaml"
VERDICTS = "verdicts.yaml"
DIAGNOSES = "diagnoses.yaml"


def _tree(root: Path) -> dict[str, dict[str, list[str]]]:
    """The generated layout as `{target: {target_run: [trial, ...]}}`."""
    out: dict[str, dict[str, list[str]]] = {}
    for target in sorted(p for p in root.iterdir() if p.is_dir()):
        runs: dict[str, list[str]] = {}
        for run in sorted(p for p in target.iterdir() if p.is_dir()):
            runs[run.name] = sorted(p.name for p in run.iterdir() if p.is_dir())
        out[target.name] = runs
    return out


def _trial_dirs(root: Path) -> list[Path]:
    return sorted(p for p in root.glob("*/*/*") if p.is_dir())


def _trial_dirs_with_verdicts(root: Path) -> list[Path]:
    return [trial for trial in _trial_dirs(root) if (trial / VERDICTS).is_file()]


def _verdict_rows(trial_dir: Path) -> list[dict]:
    return yaml.safe_load((trial_dir / VERDICTS).read_text(encoding="utf-8"))


def _manifest(trial_dir: Path) -> dict:
    return yaml.safe_load((trial_dir / MANIFEST).read_text(encoding="utf-8"))


def _chain_refs(rows: list[dict]) -> list[str]:
    """The unique evidence references a set of verdict rows names, sorted."""
    refs: set[str] = set()
    for row in rows:
        chain = row.get("evidence_chain")
        if not chain:
            continue
        refs.add(chain["hunt_config"])
        refs.add(chain["spec_dir"])
        refs.add(chain["pod_export"])
        refs.update(chain["experiment_logs"])
    return sorted(refs)


def _walk(value: object):
    yield value
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


# --- the corpus ----------------------------------------------------------------


def test_generator_creates_the_declared_corpus(tmp_path: Path) -> None:
    root = demo_data.generate(tmp_path / "store")

    assert _tree(root) == {
        "comfyui-1": {
            "run-demo-a": ["trial-1", "trial-2"],
            "run-demo-real-shape": ["trial-stopped-cap-10"],
        },
        "jetlinks-1": {"run-demo-a": ["trial-1"]},
        "white-jotter-1": {"run-demo-a": ["trial-1"], "run-demo-b": ["trial-2"]},
    }


def test_snapshot_summary_matches_the_demo_contract(tmp_path: Path) -> None:
    root = demo_data.generate(tmp_path / "store")

    assert build_snapshot(root)["summary"] == {
        "targets": 3,
        "trials": 6,
        "identified": 5,
        "partial": 2,
        "missed": 7,
        "degraded": 1,
    }


def test_deduplicated_coverage_matches_the_demo_contract(tmp_path: Path) -> None:
    root = demo_data.generate(tmp_path / "store")

    coverage = build_snapshot(root)["coverage"]

    assert coverage["targets"] == {"tested": 3, "with_identified": 2, "without_identified": 1}
    assert coverage["vulnerabilities"] == {
        "total": 12,
        "found": 5,
        "not_found": 7,
        "partial": 1,
    }


def test_demo_repeats_a_comfyui_vuln_across_trials(tmp_path: Path) -> None:
    root = demo_data.generate(tmp_path / "store")

    snap = build_snapshot(root)
    by_id: dict[str, set[str]] = {}
    for trial in snap["trials"]:
        if trial["target_id"] != "comfyui-1":
            continue
        for verdict in trial["verdicts"]:
            by_id.setdefault(verdict["vuln_id"], set()).add(verdict["identified"])

    assert by_id["DEMO-CVE-2024-1003"] == {"partial", "identified"}
    assert by_id["DEMO-CVE-2024-1002"] == {"identified", "missed"}
    assert snap["summary"]["identified"] == 5


def test_targets_have_deterministic_counts(tmp_path: Path) -> None:
    root = demo_data.generate(tmp_path / "store")

    targets = {t["target_id"]: t for t in build_snapshot(root)["targets"]}
    assert targets["comfyui-1"] == {
        "target_id": "comfyui-1",
        "trial_count": 3,
        "identified_count": 3,
        "partial_count": 1,
        "missed_count": 4,
    }
    assert targets["jetlinks-1"] == {
        "target_id": "jetlinks-1",
        "trial_count": 1,
        "identified_count": 2,
        "partial_count": 0,
        "missed_count": 1,
    }
    assert targets["white-jotter-1"] == {
        "target_id": "white-jotter-1",
        "trial_count": 2,
        "identified_count": 0,
        "partial_count": 1,
        "missed_count": 2,
    }


def test_versions_demonstrate_the_declared_scenarios(tmp_path: Path) -> None:
    root = demo_data.generate(tmp_path / "store")

    versions = build_snapshot(root)["versions"]

    assert [(v["eval_sha"], v["stack_fingerprint"]) for v in versions] == [
        ("demo-sha-a", "demo-env-x"),
        ("demo-sha-a", "demo-env-z"),
        ("demo-sha-b", "demo-env-y"),
        ("demo-sha-c", "demo-env-w"),
    ]
    shared = versions[0]
    assert shared["targets"] == ["comfyui-1", "jetlinks-1"]
    assert (shared["identified"], shared["partial"], shared["missed"]) == (4, 1, 1)
    same_sha = versions[1]
    assert same_sha["stack_fingerprint"] == "demo-env-z"
    runs = {(t["target_run_id"], t["availability"]) for t in same_sha["trials"]}
    assert runs == {("run-demo-a", "complete"), ("run-demo-b", "degraded")}


def test_successes_contain_only_identified(tmp_path: Path) -> None:
    root = demo_data.generate(tmp_path / "store")

    snap = build_snapshot(root)
    identified = {
        (trial["target_id"], trial["target_run_id"], trial["trial_id"], verdict["vuln_id"])
        for trial in snap["trials"]
        for verdict in trial["verdicts"]
        if verdict["identified"] == "identified"
    }
    successes = {
        (row["target_id"], row["target_run_id"], row["trial_id"], row["vuln_id"])
        for row in snap["successes"]
    }
    assert len(snap["successes"]) == 5
    assert successes == identified
    for row in snap["successes"]:
        assert row["vuln_id"] and row["eval_sha"] and row["stack_fingerprint"]
        assert row["matched"]["unit"] and row["matched"]["fault_class"]
        assert row["matched"]["symptom"]


def test_partial_and_missed_verdicts_are_preserved_on_their_trials(tmp_path: Path) -> None:
    root = demo_data.generate(tmp_path / "store")

    verdicts = [
        v["identified"]
        for trial in build_snapshot(root)["trials"]
        for v in trial["verdicts"]
    ]
    assert verdicts.count("identified") == 5
    assert verdicts.count("partial") == 2
    assert verdicts.count("missed") == 7


# --- fidelity to the real materializer -----------------------------------------


def test_manifests_use_the_real_builder_contract(tmp_path: Path) -> None:
    root = demo_data.generate(tmp_path / "store")
    # The production builder's own output defines the exact shape (and key order).
    reference = orchestrator_store.build_run_manifest(
        {
            "trial_id": "t",
            "target_id": "x",
            "target_run_id": "r",
            "instance_id": "i",
            "project_id": "p",
            "start_phase": "recon",
            "terminal": "complete",
            "phases": [{"phase": "recon", "status": "complete", "run_id": "r1"}],
            "eval_sha": "s",
            "stack_fingerprint": "f",
        },
        ["p/hunting/x.yaml"],
        demo_data.DEMO_COPIED_AT,
        diagnoses_present=True,
    )

    manifests = sorted(root.rglob(MANIFEST))
    assert len(manifests) == 6
    for path in manifests:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert list(document) == list(reference)
        assert document["schema_version"] == orchestrator_store.STORE_SCHEMA_VERSION
        assert document["copied_at"] == demo_data.DEMO_COPIED_AT
        # The real builder's phase pointer carries `stop_run_id`.
        assert document["phases"] == [
            {
                "phase": p["phase"],
                "status": p["status"],
                "run_id": p["run_id"],
                "stop_run_id": p.get("stop_run_id"),
            }
            for p in document["phases"]
        ]


def test_chain_sources_equal_the_unique_evidence_references(tmp_path: Path) -> None:
    root = demo_data.generate(tmp_path / "store")

    for trial_dir in _trial_dirs(root):
        manifest = _manifest(trial_dir)
        rows = _verdict_rows(trial_dir) if (trial_dir / VERDICTS).is_file() else []

        assert manifest["chain_sources"] == _chain_refs(rows)
        positive = [row for row in rows if row["identified"] in ("identified", "partial")]
        if positive:
            assert manifest["chain_sources"], "a positive verdict names its chain"
        if rows and not positive:
            # A missed-only trial (the stopped-at-cap run) honestly names none.
            assert manifest["chain_sources"] == []
        assert manifest["diagnoses_present"] is (trial_dir / DIAGNOSES).is_file()


def test_every_evidence_reference_resolves_inside_its_trial(tmp_path: Path) -> None:
    root = demo_data.generate(tmp_path / "store")

    for trial_dir in _trial_dirs_with_verdicts(root):
        for row in _verdict_rows(trial_dir):
            chain = row["evidence_chain"]
            if chain is None:
                continue
            assert (trial_dir / chain["hunt_config"]).is_file()
            assert (trial_dir / chain["spec_dir"]).is_dir()
            assert (trial_dir / chain["pod_export"]).is_file()
            assert chain["experiment_logs"]
            for log in chain["experiment_logs"]:
                assert (trial_dir / log).is_file()
            for ref in _chain_refs([row]):
                assert not ref.startswith("/")
                assert ".." not in ref.split("/")
                assert (trial_dir / ref).exists()


def test_demo_artifacts_pass_the_production_readers(tmp_path: Path) -> None:
    root = demo_data.generate(tmp_path / "store")
    store = orchestrator_files.FileStore()

    for trial_dir in _trial_dirs_with_verdicts(root):
        manifest = _manifest(trial_dir)
        loaded = orchestrator_verdicts.load_verdicts(
            trial_dir / VERDICTS,
            files=store,
            data_root=trial_dir,
            eval_sha=manifest["eval_sha"],
            stack_fingerprint=manifest["stack_fingerprint"],
        )
        assert loaded
        entries = ()
        if (trial_dir / DIAGNOSES).is_file():
            entries = orchestrator_diagnosis.load_diagnoses(
                trial_dir / DIAGNOSES,
                files=store,
                verdicts=loaded,
                eval_sha=manifest["eval_sha"],
                stack_fingerprint=manifest["stack_fingerprint"],
            )
        # The pairing rule: every partial/missed verdict has exactly one entry.
        orchestrator_diagnosis.check_pairing(loaded, entries)


def test_diagnoses_pair_with_partial_and_missed(tmp_path: Path) -> None:
    root = demo_data.generate(tmp_path / "store")

    diagnosed = 0
    for trial in build_snapshot(root)["trials"]:
        needed = {v["vuln_id"] for v in trial["verdicts"] if v["identified"] != "identified"}
        got = {d["vuln"] for d in trial["diagnoses"]}
        assert got == needed
        for diagnosis in trial["diagnoses"]:
            assert diagnosis["failure_mode"]
            assert diagnosis["root_cause"]["type"]
            assert diagnosis["diagnosis_overview"]
            assert (diagnosis["closest_issue"] is None) != (
                diagnosis["proposed_issue"] is None
            )
        diagnosed += len(got)
    assert diagnosed == 9


def test_only_positive_and_ambiguous_verdicts_carry_a_chain(tmp_path: Path) -> None:
    root = demo_data.generate(tmp_path / "store")

    missed = 0
    for trial_dir in _trial_dirs_with_verdicts(root):
        for row in _verdict_rows(trial_dir):
            if row["identified"] == "missed":
                missed += 1
                # A missed verdict describes no match: no chain is required.
                assert row["evidence_chain"] is None
            else:
                assert row["evidence_chain"] is not None
    assert missed == 7


def test_the_corpus_covers_the_declared_scenarios(tmp_path: Path) -> None:
    root = demo_data.generate(tmp_path / "store")
    specs = demo_data.demo_trials()

    full = [s for s in specs if s.scenario == demo_data.FULL_PIPELINE]
    assert full, "the corpus needs a complete recon -> analysis -> hunting run"
    assert any([phase for phase, _, _ in s.phases] == ["recon", "analysis", "hunting"] for s in full)

    seeded = [s for s in specs if s.scenario == demo_data.HUNTING_ONLY]
    assert seeded, "the corpus needs a seeded, hunting-only run"
    for spec in seeded:
        assert spec.start_phase == "hunting"
        assert [phase for phase, _, _ in spec.phases] == ["hunting"]

    injected = [s for s in specs if s.scenario == demo_data.FAILURE_INJECTION]
    assert len(injected) == 1
    broken = injected[0]
    assert broken.verdicts is None
    assert broken.terminal == "interrupted"
    broken_dir = root / broken.target_id / broken.target_run_id / broken.trial_id
    assert (broken_dir / MANIFEST).is_file()
    assert not (broken_dir / VERDICTS).exists()
    assert not (broken_dir / DIAGNOSES).exists()
    # No chain was written for the interrupted run at all.
    assert not (broken_dir / broken.project_id).exists()

    capped = [s for s in specs if s.scenario == demo_data.STOPPED_AT_CAP]
    assert len(capped) == 1
    run = capped[0]
    assert run.start_phase == "recon"
    assert run.terminal == "stopped"
    assert [(phase, status) for phase, status, _ in run.phases] == [
        ("recon", "complete"),
        ("hunting", "stopped"),
    ]
    assert run.inventory == demo_data.REAL_SHAPE_INVENTORY


def test_evidence_references_are_synthetic_and_relative(tmp_path: Path) -> None:
    root = demo_data.generate(tmp_path / "store")

    refs = [
        ref
        for trial in build_snapshot(root)["trials"]
        for verdict in trial["verdicts"]
        for ref in verdict["evidence"]
    ]
    assert refs, "the demo must carry evidence references"
    for ref in refs:
        assert not ref.startswith("/")
        assert ".." not in ref.split("/")
        assert "://" not in ref
        # The real layout: <project_id>/hunting/...
        assert ref.startswith("demo-project-")
        assert "/hunting/" in ref


def test_the_degraded_trial_is_a_documented_failure_injection(tmp_path: Path) -> None:
    root = demo_data.generate(tmp_path / "store")

    degraded = build_snapshot(root)["degraded_trials"]
    assert degraded == [
        {
            "target_id": "white-jotter-1",
            "target_run_id": "run-demo-b",
            "trial_id": "trial-2",
            "reason": "verdicts_missing",
        }
    ]
    # The scenario is named in the generator and in the printed instructions.
    injected = [s for s in demo_data.demo_trials() if s.scenario == demo_data.FAILURE_INJECTION]
    assert injected[0].trial_id == "trial-2"
    assert "failure injection" in demo_data.instructions(root)
    broken = next(
        trial
        for trial in build_snapshot(root)["trials"]
        if (trial["target_run_id"], trial["trial_id"]) == ("run-demo-b", "trial-2")
    )
    # The new summaries never change the pre-existing degraded state.
    assert broken["availability"] == "degraded"
    assert broken["reason"] == "verdicts_missing"
    assert broken["verdicts"] == []


# --- schema-v2 project snapshots -----------------------------------------------


def test_demo_project_snapshot_counts_are_stable(tmp_path: Path) -> None:
    root = demo_data.generate(tmp_path / "store")

    snap = build_snapshot(root)
    by_key = {
        (trial["target_id"], trial["target_run_id"], trial["trial_id"]): trial
        for trial in snap["trials"]
    }
    # hunting = 5 per chained verdict (config, spec, variant, log, export);
    # skills = 4 (SKILL.md, reference, script, asset); graph = 1 service + units.
    expected = {
        ("comfyui-1", "run-demo-a", "trial-1"): (15, 4, 5, 4),
        ("comfyui-1", "run-demo-a", "trial-2"): (5, 4, 3, 2),
        ("jetlinks-1", "run-demo-a", "trial-1"): (10, 4, 4, 3),
        ("white-jotter-1", "run-demo-a", "trial-1"): (5, 4, 3, 2),
        # The real-shape run: 10 configs + 5 specs + 3 variants + 3 logs, no
        # skills.
        ("comfyui-1", "run-demo-real-shape", "trial-stopped-cap-10"): (21, 0, 4, 3),
    }
    for key, (hunting, skills, nodes, links) in expected.items():
        trial = by_key[key]
        assert trial["artifact_summary"] == {
            "status": "available",
            "hunting": hunting,
            "skills": skills,
        }
        assert trial["project_graph_summary"] == {
            "status": "available",
            "nodes": nodes,
            "links": links,
            "captured_at": demo_data.DEMO_CAPTURED_AT,
        }

    # The manifest fingerprint is present and shared by both sections.
    for trial_dir in _trial_dirs_with_verdicts(root):
        manifest = _manifest(trial_dir)
        assert manifest["project_snapshot"]["status"] == "available"
        fingerprint = manifest["project_snapshot"]["snapshot_sha256"]
        assert fingerprint
        assert fingerprint == manifest["project_artifacts"]["snapshot_sha256"]
        assert manifest["project_graph"]["sha256"]

    # Counts are stable across a regeneration.
    demo_data.generate(root)
    assert build_snapshot(root) == snap


def test_two_generations_in_separate_dirs_are_byte_identical(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    demo_data.generate(first)
    demo_data.generate(second)

    assert _demo_files(first) == _demo_files(second)
    assert build_snapshot(first) == build_snapshot(second)


def test_snapshot_carries_no_graph_bodies_inventory_or_binary(tmp_path: Path) -> None:
    root = demo_data.generate(tmp_path / "store")

    snap = build_snapshot(root)
    blob = json.dumps(snap)

    for token in (
        "relative_path",
        "artifact_id",
        "media_type",
        "representation",
        "entries",
        "sha256",
        "unit:",
        "service:",
        "PNG",
        "\\u0089",
    ):
        assert token not in blob, token
    for trial in snap["trials"]:
        assert set(trial["artifact_summary"]) == {"status", "hunting", "skills"}
        assert set(trial["project_graph_summary"]) == {
            "status",
            "nodes",
            "links",
            "captured_at",
        }


# --- safety, determinism, idempotency ------------------------------------------


def _demo_files(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_generated_files_carry_no_host_paths_links_or_credentials(tmp_path: Path) -> None:
    root = demo_data.generate(tmp_path / "store")

    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        assert not relative.startswith("/")
        assert ".." not in relative.split("/")
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # The synthetic binary asset: no text contract applies.
            continue
        lowered = text.lower()
        assert "http://" not in lowered and "https://" not in lowered
        for token in text.split():
            assert not token.startswith("/"), f"{relative}: {token}"
        # Credential *carriers*, not domain words: a synthetic symptom may
        # legitimately be called "default_admin_credentials".
        for pattern in (
            "password:",
            "password=",
            "secret:",
            "secret=",
            "token:",
            "token=",
            "api_key",
            "apikey",
            "authorization:",
            "bearer ",
        ):
            assert pattern not in lowered, f"{relative}: {pattern}"


def test_two_runs_are_byte_identical(tmp_path: Path) -> None:
    root = tmp_path / "store"
    demo_data.generate(root)
    first_snapshot, first_files = build_snapshot(root), _demo_files(root)

    demo_data.generate(root)
    second_snapshot, second_files = build_snapshot(root), _demo_files(root)

    assert first_snapshot == second_snapshot
    assert first_files == second_files


def test_foreign_files_are_preserved(tmp_path: Path) -> None:
    root = tmp_path / "store"
    foreign = root / "keep-me.txt"
    nested = root / "comfyui-1" / "notes.md"
    foreign.parent.mkdir(parents=True, exist_ok=True)
    nested.parent.mkdir(parents=True, exist_ok=True)
    foreign.write_text("mine", encoding="utf-8")
    nested.write_text("also mine", encoding="utf-8")

    demo_data.generate(root)

    assert foreign.read_text(encoding="utf-8") == "mine"
    assert nested.read_text(encoding="utf-8") == "also mine"


def test_every_generated_yaml_declares_the_data_is_synthetic(tmp_path: Path) -> None:
    root = demo_data.generate(tmp_path / "store")

    files = sorted(root.rglob("*.yaml"))
    assert len(files) > 10  # manifests, verdicts, diagnoses and the chains
    for path in files:
        assert "synthetic" in path.read_text(encoding="utf-8").lower()


def test_no_absolute_paths_leak_into_the_snapshot(tmp_path: Path) -> None:
    root = demo_data.generate(tmp_path / "store")

    snap = build_snapshot(root)
    blob = json.dumps(snap)
    assert str(root) not in blob
    for value in _walk(snap):
        if isinstance(value, str):
            assert not value.startswith("/"), value


# --- the stopped-at-cap real-shape trial ---------------------------------------

# One schema-v2 Trial mirrors the domain shape of the recent real eval: a
# recon -> hunting run stopped at the hunting cap, a 10/5/3/3 hunting inventory
# with no pod exports and no skills, and exactly one verdict of each outcome.
REAL_SHAPE_KEY = ("comfyui-1", "run-demo-real-shape", "trial-stopped-cap-10")
REAL_SHAPE_PROJECT = "demo-project-comfyui-1"


def _real_shape_dir(root: Path) -> Path:
    return root.joinpath(*REAL_SHAPE_KEY)


def _entries_by_kind(trial_dir: Path) -> dict[str, list[dict]]:
    by_kind: dict[str, list[dict]] = {}
    for entry in _manifest(trial_dir)["project_artifacts"]["entries"]:
        by_kind.setdefault(entry["kind"], []).append(entry)
    return by_kind


def test_real_shape_trial_mirrors_the_stopped_run(tmp_path: Path) -> None:
    root = demo_data.generate(tmp_path / "store")
    manifest = _manifest(_real_shape_dir(root))

    assert (
        manifest["target_id"],
        manifest["target_run_id"],
        manifest["trial_id"],
    ) == REAL_SHAPE_KEY
    assert manifest["project_id"] == REAL_SHAPE_PROJECT
    assert manifest["start_phase"] == "recon"
    assert manifest["terminal"] == "stopped"
    assert [(phase["phase"], phase["status"]) for phase in manifest["phases"]] == [
        ("recon", "complete"),
        ("hunting", "stopped"),
    ]
    # Clearly synthetic identity: no real SHA and no real stack fingerprint.
    assert manifest["eval_sha"].startswith("demo-")
    assert manifest["stack_fingerprint"].startswith("demo-")


def test_real_shape_inventory_matches_the_real_eval(tmp_path: Path) -> None:
    root = demo_data.generate(tmp_path / "store")
    by_kind = _entries_by_kind(_real_shape_dir(root))

    assert sum(len(entries) for entries in by_kind.values()) == 21
    assert len(by_kind["hunt_config"]) == 10
    assert len(by_kind["test_spec"]) == 5
    assert len(by_kind["pod_variant"]) == 3
    assert len(by_kind["experiment_log"]) == 3
    assert "pod_export" not in by_kind
    assert not any(
        entry["category"] == "skill"
        for entries in by_kind.values()
        for entry in entries
    )
    produced = [e for e in by_kind["test_spec"] if "/produced/" in e["relative_path"]]
    consumed = [e for e in by_kind["test_spec"] if "/consumed/" in e["relative_path"]]
    assert (len(produced), len(consumed)) == (2, 3)
    for entries in by_kind.values():
        for entry in entries:
            # The manifest entry path is project-relative (the catalog strips
            # the project id); the evidence chain carries the trial-relative one.
            assert entry["relative_path"].startswith("hunting/")
            assert not entry["relative_path"].startswith("/")
            assert ".." not in entry["relative_path"].split("/")


def test_real_shape_trial_is_a_complete_schema_v2_trial(tmp_path: Path) -> None:
    root = demo_data.generate(tmp_path / "store")
    trial = next(
        trial
        for trial in build_snapshot(root)["trials"]
        if (trial["target_id"], trial["target_run_id"], trial["trial_id"]) == REAL_SHAPE_KEY
    )

    assert trial["availability"] == "complete"
    assert trial["artifact_summary"] == {"status": "available", "hunting": 21, "skills": 0}
    graph = trial["project_graph_summary"]
    assert graph["status"] == "available"
    assert graph["nodes"] > 0
    assert graph["links"] > 0
    assert sorted(v["identified"] for v in trial["verdicts"]) == [
        "missed",
        "missed",
        "missed",
    ]
    # No positive evidence: every verdict is missed, so every chain is null.
    assert trial["verdicts"]
    assert all(v["evidence"] == [] for v in trial["verdicts"])
    # Exactly one diagnosis per missed verdict.
    assert sorted(d["vuln"] for d in trial["diagnoses"]) == [
        "DEMO-CVE-2024-5001",
        "DEMO-CVE-2024-5002",
        "DEMO-CVE-2024-5003",
    ]


def test_real_shape_verdicts_are_three_missed_with_null_chains(tmp_path: Path) -> None:
    root = demo_data.generate(tmp_path / "store")
    trial_dir = _real_shape_dir(root)

    rows = _verdict_rows(trial_dir)

    assert [row["identified"] for row in rows] == ["missed", "missed", "missed"]
    assert all(row["evidence_chain"] is None for row in rows)
    # A missed-only trial has no chain_sources at all.
    assert _manifest(trial_dir)["chain_sources"] == []


def test_real_shape_graph_is_non_empty(tmp_path: Path) -> None:
    root = demo_data.generate(tmp_path / "store")
    trial_dir = _real_shape_dir(root)

    graph = json.loads((trial_dir / "project-graph.json").read_text(encoding="utf-8"))
    assert graph["project_id"] == REAL_SHAPE_PROJECT
    assert graph["nodes"]
    assert graph["links"]
    for node in graph["nodes"]:
        assert isinstance(node["id"], str) and node["id"]
        assert isinstance(node["type"], str) and node["type"]
        assert isinstance(node["properties"], dict)
    for link in graph["links"]:
        assert link["source"] and link["target"] and link["type"]


# The production graph's L0/L1 vocabulary (kept in sync with the frontend
# `colors.ts` palette + `projection.ts` L1 set and the backend relationship
# names). The demo graph must speak exactly this language.
L0_TYPES = frozenset(
    {
        "Domain", "Subdomain", "IP", "Port", "Service", "DNSRecord", "BaseURL",
        "Endpoint", "Parameter", "Technology", "Certificate", "Header", "Secret",
        "ExternalDomain", "Traceroute", "Observation",
    }
)
L1_TYPES = frozenset(
    {"L1Service", "L1System", "L1DataItem", "L1TestableUnit", "SystemKind", "DataRelationshipKind"}
)
EDGE_TYPES = frozenset(
    {
        "AGGREGATES", "SURFACES_AT", "EVIDENCED_BY", "HAS_OBSERVATION",
        "HAS_PARAMETER", "HAS_HEADER", "BELONGS_TO", "DERIVED_FROM",
        "PRODUCES", "CONSUMES",
    }
)
CROSS_LAYER_EDGES = frozenset({"AGGREGATES", "SURFACES_AT", "EVIDENCED_BY"})


def _project_graph(graph: dict, *, l0: bool, l1: bool) -> tuple[list[dict], list[dict]]:
    """The frontend `projectGraph` projection, so the demo graph is checked as rendered."""
    type_by_id = {node["id"]: node["type"] for node in graph["nodes"]}
    is_l1 = lambda node_id: type_by_id.get(node_id) in L1_TYPES  # noqa: E731
    if l0 and l1:
        return graph["nodes"], graph["links"]
    if not l0 and not l1:
        return [], []
    if l0:
        nodes = [n for n in graph["nodes"] if n["type"] not in L1_TYPES]
        kept = {n["id"] for n in nodes}
        links = [
            link
            for link in graph["links"]
            if str(link["source"]) in kept and str(link["target"]) in kept
        ]
        return nodes, links
    anchored: set[str] = set()
    for link in graph["links"]:
        if link["type"] not in CROSS_LAYER_EDGES:
            continue
        source, target = str(link["source"]), str(link["target"])
        if is_l1(source) and not is_l1(target):
            anchored.add(target)
        if is_l1(target) and not is_l1(source):
            anchored.add(source)
    kept = {node["id"] for node in graph["nodes"] if node["type"] in L1_TYPES or node["id"] in anchored}
    nodes = [node for node in graph["nodes"] if node["id"] in kept]
    links = [
        link
        for link in graph["links"]
        if str(link["source"]) in kept
        and str(link["target"]) in kept
        and (is_l1(str(link["source"])) or is_l1(str(link["target"])))
    ]
    return nodes, links


def test_generated_graphs_use_production_types_and_project_meaningfully(tmp_path: Path) -> None:
    root = demo_data.generate(tmp_path / "store")
    graphs = sorted(root.glob("*/*/*/project-graph.json"))
    assert graphs, "every complete demo trial captures a graph"

    for path in graphs:
        graph = json.loads(path.read_text(encoding="utf-8"))
        for node in graph["nodes"]:
            assert node["type"] in (L0_TYPES | L1_TYPES), (path, node["type"])
        for link in graph["links"]:
            assert link["type"] in EDGE_TYPES, (path, link["type"])
        # Every projection (L0-only, L1-only, both) is non-empty in nodes and edges.
        for l0, l1 in ((True, False), (False, True), (True, True)):
            nodes, links = _project_graph(graph, l0=l0, l1=l1)
            assert nodes, (path.name, l0, l1, "nodes")
            assert links, (path.name, l0, l1, "links")


def test_real_shape_trial_is_served_by_the_read_api(tmp_path: Path) -> None:
    root = demo_data.generate(tmp_path / "store")
    client = TestClient(
        app_module.create_app(lambda: source_module.ArtifactStoreSnapshotSource(root))
    )
    target, run, trial = REAL_SHAPE_KEY

    snapshot = client.get("/snapshot")
    assert snapshot.status_code == 200
    row = next(
        item
        for item in snapshot.json()["trials"]
        if (item["target_id"], item["target_run_id"], item["trial_id"]) == REAL_SHAPE_KEY
    )
    assert row["project_id"] == REAL_SHAPE_PROJECT
    assert row["artifact_summary"] == {"status": "available", "hunting": 21, "skills": 0}

    graph = client.get(f"/trials/{target}/{run}/{trial}/project-graph")
    assert graph.status_code == 200
    assert graph.json()["status"] == "available"
    assert graph.json()["graph"]["nodes"]

    inventory = client.get(f"/trials/{target}/{run}/{trial}/artifacts")
    assert inventory.status_code == 200
    body = inventory.json()
    assert body["project_id"] == REAL_SHAPE_PROJECT
    entries = [
        entry
        for group in _walk(body["groups"])
        if isinstance(group, dict) and "entries" in group
        for entry in group["entries"]
    ]
    assert len(entries) == 21

    # Every one of the 21 artifacts has a readable detail and content endpoint.
    for entry in entries:
        artifact_id = entry["artifact_id"]
        detail = client.get(
            f"/trials/{target}/{run}/{trial}/artifacts/{artifact_id}"
        )
        assert detail.status_code == 200, artifact_id
        assert detail.json()["entry"]["artifact_id"] == artifact_id
        content = client.get(
            f"/trials/{target}/{run}/{trial}/artifacts/{artifact_id}/content"
        )
        assert content.status_code == 200, artifact_id
    assert str(root) not in snapshot.text
