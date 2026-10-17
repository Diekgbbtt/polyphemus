"""Unit tier: the external-bootstrap runner, part 4 - state and config.

`runner/state.py` is the run's handoff: one JSON document per run, written
atomically after every transition, with deterministic per-target session ids.
`runner/config.py` turns a `run.yaml` into a `RunConfig` whose every path is
absolute, and whose resolved snapshot is what makes `resume`/`status`
self-contained.

Both seams are pure file I/O over a temp directory: no network, no models.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


def _on_path(rel: str) -> None:
    path = str(REPO_ROOT / rel)
    if path not in sys.path:
        sys.path.insert(0, path)


_on_path("tools/bootstrap")
_on_path("eval")
_on_path("src")

from runner import state as state_mod  # noqa: E402
from runner.config import load_config, load_resolved  # noqa: E402
from runner.harness import ModelRef  # noqa: E402
from runner.state import RunState, new_state, session_id  # noqa: E402


# --- session ids ------------------------------------------------------------


def test_session_id_is_deterministic_and_path_safe():
    assert session_id("w2-regeneration", "white-jotter") == "ses_bt_w2_regen_white_jotter_creator"
    assert session_id("w2-regeneration", "white-jotter") == session_id(
        "w2-regeneration", "white-jotter"
    )
    assert session_id("r", "a/b") == "ses_bt_r_a_b_creator"


def test_target_state_seeds_its_creator_session():
    run = new_state("run-one", targets=["shop"])
    assert run.target("shop").session_creator == "ses_bt_run_one_shop_creator"
    assert run.target("shop").creator_session("other") == "ses_bt_run_one_shop_creator"


# --- state persistence ------------------------------------------------------


def test_state_round_trips_through_disk(tmp_path):
    run = new_state("r1", config_digest="abc123", targets=["a", "b"])
    phase = run.target("a").phase("authn")
    phase.read = state_mod.DONE
    phase.gate = state_mod.DONE
    phase.session = "ses_x"
    run.target("a").gates["auth_only"] = state_mod.DONE
    run.target("a").status = state_mod.DONE
    path = run.save(tmp_path)
    assert path == tmp_path / "state.json"

    loaded = RunState.load(tmp_path)
    assert loaded.run_id == "r1"
    assert loaded.config_digest == "abc123"
    assert list(loaded.targets) == ["a", "b"]
    assert loaded.target("a").phase("authn").read == state_mod.DONE
    assert loaded.target("a").gates == {"auth_only": state_mod.DONE}
    assert loaded.target("b").session_creator == "ses_bt_r1_b_creator"


def test_state_save_is_atomic_and_leaves_no_temp_files(tmp_path):
    run = new_state("r1", targets=["a"])
    run.save(tmp_path)
    run.target("a").status = state_mod.ACTIVE
    run.save(tmp_path)
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "state.json"]
    assert leftovers == []
    on_disk = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert on_disk["targets"]["a"]["status"] == state_mod.ACTIVE


def test_state_load_fails_loudly_on_a_missing_or_broken_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        RunState.load(tmp_path)
    (tmp_path / "state.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        RunState.load(tmp_path)


def test_state_document_keeps_the_contract_shape(tmp_path):
    run = new_state("r1", config_digest="d", targets=["a"])
    run.target("a").phase("l1").read = state_mod.DONE
    run.target("a").phase("l1").gate = state_mod.DONE
    run.target("a").lifecycle.verified_teardown = True
    run.save(tmp_path)
    doc = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert sorted(doc) == ["run", "targets"]
    assert sorted(doc["run"]) == ["config_digest", "created", "id", "notes", "status", "updated"]
    record = doc["targets"]["a"]
    assert {
        "target",
        "session_creator",
        "base_url",
        "status",
        "repair_attempts",
        "model",
        "gates",
        "notes",
        "lifecycle",
        "phases",
    } <= set(record)
    assert set(record["phases"]["l1"]) >= {
        "read",
        "gate",
        "gate_output",
        "session",
        "turns",
        "repairs",
        "timeouts",
        "logs",
    }


# --- state transitions ------------------------------------------------------


def test_first_incomplete_phase_walks_authn_then_l1():
    run = new_state("r1", targets=["a"])
    assert run.first_incomplete_phase("a") == "authn"
    record = run.target("a")
    record.phase("authn").read = state_mod.DONE
    record.phase("authn").gate = state_mod.DONE
    assert run.first_incomplete_phase("a") == "l1"
    record.phase("l1").read = state_mod.DONE
    record.phase("l1").gate = state_mod.DONE
    assert run.first_incomplete_phase("a") is None


def test_a_phase_with_a_green_read_but_a_red_gate_is_not_complete():
    run = new_state("r1", targets=["a"])
    record = run.target("a")
    record.phase("authn").read = state_mod.DONE
    record.phase("authn").gate = state_mod.FAILED
    assert run.first_incomplete_phase("a") == "authn"
    assert record.phase("authn").complete is False


def test_status_table_reports_each_target_phase_and_teardown():
    run = new_state("r1", targets=["a", "b"])
    a = run.target("a")
    a.phase("authn").read = state_mod.DONE
    a.phase("authn").gate = state_mod.DONE
    a.phase("l1").read = state_mod.ACTIVE
    a.status = state_mod.ACTIVE
    a.lifecycle.verified_teardown = True
    rows = {row["target"]: row for row in run.status_table()}
    assert rows["a"]["authn"] == state_mod.DONE
    assert rows["a"]["l1"] == state_mod.ACTIVE
    assert rows["a"]["teardown"] == "verified"
    assert rows["b"]["authn"] == "-"
    assert rows["b"]["session"] == "ses_bt_r1_b_creator"


def test_status_table_marks_a_failed_phase_and_an_unverified_teardown():
    run = new_state("r1", targets=["a"])
    record = run.target("a")
    record.phase("authn").read = state_mod.DONE
    record.phase("authn").gate = state_mod.FAILED
    record.lifecycle.verified_teardown = False
    row = run.status_table()[0]
    assert row["authn"] == state_mod.FAILED
    assert row["teardown"] == "unverified"


def test_status_table_names_leftover_containers_instead_of_hiding_them():
    run = new_state("r1", targets=["a"])
    record = run.target("a")
    record.status = state_mod.DONE
    record.lifecycle.verified_teardown = False
    record.lifecycle.leftovers = ["web_a-app-1", "web_a-db-1"]
    row = run.status_table()[0]
    # Not silently `done`: the teardown cell carries the leftover count, and the
    # target's status stays what the run decided (a leftover is reporting only).
    assert row["teardown"] == "leftovers(2)"
    assert row["status"] == state_mod.DONE


def test_config_digest_is_stable_and_order_insensitive():
    left = {"a": 1, "b": [2, 3]}
    right = {"b": [2, 3], "a": 1}
    assert state_mod.config_digest(left) == state_mod.config_digest(right)
    assert state_mod.config_digest(left) != state_mod.config_digest({"a": 2, "b": [2, 3]})


# --- config: loading and resolution -----------------------------------------


MINIMAL = {
    "run": {"id": "r1", "targets": ["shop", "blog"]},
    "environment": {"driver": "attach", "base_url": "http://203.0.113.9:8080/"},
    "paths": {},
}


def _write(tmp_path: Path, payload: dict, name: str = "run.yaml") -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def test_load_config_applies_every_pinned_default(tmp_path):
    config = load_config(_write(tmp_path, MINIMAL), repo_root=REPO_ROOT)
    assert config.run.id == "r1"
    assert config.run.targets == ("shop", "blog")
    assert config.run.agent == "data-dep-worker"
    assert config.run.model == ModelRef("opencode-go", "deepseek-v4.1-flash", "high")
    assert config.run.turn_timeout_s == 3600.0
    assert config.run.repair_attempts == 3
    assert config.run.timeout_reprompts == 1
    assert config.run.retry.attempts == 3
    assert config.run.retry.backoff_s == (60.0, 300.0, 900.0)
    assert config.run.readiness.retries == 60
    assert config.run.readiness.interval_s == 5.0
    assert config.run.readiness.require_http is True
    assert config.run.readiness.per_target_require_http == {}
    assert config.run.readiness.require_http_for("shop") is True
    assert config.run.teardown_on_failure is True
    assert config.run.continue_on_failure is True
    assert config.paths.kbs == REPO_ROOT / "eval/data/webexploitbench"
    assert config.paths.staging == REPO_ROOT / "eval/data-dependencies"
    assert config.paths.validator == REPO_ROOT / "tools/bootstrap/validate_data_dependencies.py"
    assert config.paths.contract == REPO_ROOT / "tools/bootstrap/DATA-DEPENDENCIES.md"
    assert config.paths.meta_skill == REPO_ROOT / "skills/meta/authn-skill-writing/SKILL.md"
    assert config.paths.authn_prompt == REPO_ROOT / "tools/bootstrap/prompts/data-dep-authn.md"
    assert config.paths.l1_prompt == REPO_ROOT / "tools/bootstrap/prompts/data-dep-l1.md"


def test_load_config_reads_the_override_shape(tmp_path):
    payload = {
        "run": {
            "id": "w2",
            "worktree": str(REPO_ROOT),
            "targets": ["shop"],
            "agent": "general",
            "model": {"providerID": "opencode", "id": "nemotron-3.5-super-vl-free", "variant": "low"},
            "per_target_model": {
                "shop": {"providerID": "opencode", "id": "big-pickle", "variant": "max"}
            },
            "turn_timeout_s": 60,
            "repair_attempts": 1,
            "timeout_reprompts": 2,
            "retry": {"attempts": 2, "backoff_s": [5, 10]},
            "readiness": {
                "retries": 3,
                "interval_s": 1.5,
                "per_target_require_http": {"shop": False},
            },
            "teardown_on_failure": False,
            "continue_on_failure": False,
        },
        "environment": {
            "driver": "ssh",
            "ssh": "eval-server-polyphemus",
            "web_root": "/root/WebExploitBench",
            "targetctl": "/root/wb",
            "public_host": "203.0.113.9",
        },
        "paths": {"kbs": "eval/data/webexploitbench", "staging": "eval/data-dependencies"},
    }
    config = load_config(_write(tmp_path, payload), repo_root=REPO_ROOT)
    assert config.run.agent == "general"
    assert config.run.model == ModelRef("opencode", "nemotron-3.5-super-vl-free", "low")
    assert config.run.model_for("shop") == ModelRef("opencode", "big-pickle", "max")
    assert config.run.model_for("other") == config.run.model
    assert config.run.turn_timeout_s == 60
    assert config.run.retry.backoff_s == (5.0, 10.0)
    assert config.run.readiness.retries == 3
    assert config.run.readiness.interval_s == 1.5
    assert config.run.readiness.require_http_for("shop") is False
    assert config.run.readiness.require_http_for("blog") is True
    assert config.run.continue_on_failure is False
    assert config.environment.driver == "ssh"
    assert config.environment.targetctl == "/root/wb"
    assert config.environment.public_host == "203.0.113.9"


def test_load_config_rejects_a_missing_identity_or_targets(tmp_path):
    with pytest.raises(ValueError):
        load_config(_write(tmp_path, {"run": {"targets": ["shop"]}, "paths": {}}), repo_root=REPO_ROOT)
    with pytest.raises(ValueError):
        load_config(_write(tmp_path, {"run": {"id": "r", "targets": []}, "paths": {}}), repo_root=REPO_ROOT)
    with pytest.raises(ValueError):
        load_config(
            _write(
                tmp_path,
                {"run": {"id": "r", "targets": ["s"]}, "environment": {"driver": "wat"}},
            ),
            repo_root=REPO_ROOT,
        )


def test_resolved_snapshot_round_trips_and_keeps_paths_absolute(tmp_path):
    config = load_config(_write(tmp_path, MINIMAL), repo_root=REPO_ROOT)
    snapshot = tmp_path / "rundir" / "config.resolved.yaml"
    snapshot.parent.mkdir()
    snapshot.write_text(yaml.safe_dump(config.resolved(), sort_keys=False), encoding="utf-8")
    reloaded = load_resolved(snapshot)
    assert reloaded.run.id == config.run.id
    assert reloaded.paths.validator == config.paths.validator
    assert reloaded.paths.staging == config.paths.staging
    assert reloaded.digest == config.digest


def test_with_targets_restricts_the_plan_and_rejects_unknown_names(tmp_path):
    config = load_config(_write(tmp_path, MINIMAL), repo_root=REPO_ROOT)
    narrowed = config.with_targets(["blog"])
    assert narrowed.run.targets == ("blog",)
    assert narrowed.paths == config.paths
    with pytest.raises(ValueError):
        config.with_targets(["nope"])


def test_rundir_defaults_below_the_worktree(tmp_path):
    config = load_config(_write(tmp_path, MINIMAL), repo_root=REPO_ROOT)
    assert config.rundir() == REPO_ROOT / ".bootstrap-runs" / "r1"
    assert config.rundir(tmp_path) == tmp_path / "r1"
