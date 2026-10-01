"""The trial engine (ticket #270): phases, chaining, cap, pre-mined artifacts.

Every external effect is injected: the REST client (`ApiRunner`), the
filesystem (`FileStore`), the command runner (pillar #269), the clock, and the
reachability probe. A live trial is deferred to the e2e phase; these tests pin
the decisions through the seams.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from orchestrator import api, routing, setup, trial
from orchestrator.commands import Command, CommandResult
from orchestrator.files import (
    FileStore,
    authn_skill_path,
    hunt_configs_dir,
    hunter_test_specs_fault_dir,
)
from orchestrator.instances import InstanceError
from orchestrator.workitems import WorkItemGateError
from orchestrator.targets.base import TargetError


class FakeApi:
    def __init__(self, routes: dict | None = None):
        self.routes = routes or {}
        self.calls: list = []

    def __call__(self, call):
        self.calls.append(call)
        key = f"{call.method} {call.path}"
        for needle, resp in self.routes.items():
            if needle in key:
                return resp
        raise AssertionError(f"unexpected API call {key}")


class FakeClock:
    def __init__(self, start: float = 0.0):
        self.t = start

    def __call__(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


class SeqListFileStore(FileStore):
    """A `FileStore` whose consumed-hunt-config listing pops a scripted sequence.

    The trial-scoped poll reads the consumed listing once per iteration, so
    scripting that listing models the baseline snapshot, the new configs a run
    consumes, and the in-flight overshoot (R7: the listing re-read after the
    stop differs from the one observed at it). Every other directory (and
    `count_files`, the hunting-entry gate) reads the real tree, so a pre-mined
    artifact's presence is asserted against the test's own files.
    """

    def __init__(self, listings, consumed_dir):
        super().__init__()
        self._listings = [list(names) for names in listings]
        self._consumed = Path(consumed_dir)

    def list_files(self, directory):
        if Path(directory) != self._consumed:
            return FileStore.list_files(self, directory)
        if self._listings:
            return [Path(name) for name in self._listings.pop(0)]
        return []

    def count_files(self, directory) -> int:
        # The gate's presence check reads the real tree, never the poll script.
        return len(FileStore.list_files(self, directory))


class AtomicFileStore(FileStore):
    """Records the atomic writes, so the trial record's writer is provable."""

    def __init__(self) -> None:
        self.atomic: list[Path] = []

    def write_text_atomic(self, path, text) -> None:  # type: ignore[override]
        self.atomic.append(Path(path))
        super().write_text_atomic(path, text)


class SeamFileStore(FileStore):
    """Records the read primitives the trial must route through the seam."""

    def __init__(self) -> None:
        self.is_file_calls: list[Path] = []

    def is_file(self, path) -> bool:  # type: ignore[override]
        self.is_file_calls.append(Path(path))
        return super().is_file(path)


GRAPH_L1_L0 = {
    "nodes": [{"type": "L1Service"}, {"type": "Endpoint"}],
    "links": [],
}

PROJECTS = {"projects": [{"project_id": "pid"}]}


def _config(tmp_path, **overrides) -> trial.TrialConfig:
    base = dict(
        instance_id="arm-a",
        target_id="t1",
        start_phase="recon",
        project_name="eval-t1",
        target_seed="t.test",
        data_root=tmp_path / "data",
        runs_root=tmp_path / "runs",
        budget_s=100.0,
        poll_s=10.0,
    )
    base.update(overrides)
    return trial.TrialConfig(**base)


def _trial(
    tmp_path,
    api_runner,
    *,
    files=None,
    runner=None,
    clock=None,
    reachable=None,
    **overrides,
) -> trial.Trial:
    clock = clock or FakeClock()
    return trial.Trial(
        _config(tmp_path, **overrides),
        api_runner=api_runner,
        files=files if files is not None else FileStore(),
        runner=runner,
        clock=clock,
        sleep=clock.sleep,
        reachable=reachable or (lambda: True),
    )


def _cap_store(tmp_path, listings, project_id: str = "pid") -> SeqListFileStore:
    """A `SeqListFileStore` scoped to the `pid` project's consumed directory."""
    return SeqListFileStore(
        listings, hunt_configs_dir(tmp_path / "data", project_id, "consumed")
    )


# --- the recon -> hunting run -------------------------------------------------


def _full_routes() -> dict:
    return {
        "GET /projects/pid/recon/r1": {
            "status": "complete",
            "per_job": [{"job": "crawl", "status": "complete"}],
            "stats": {"analysis_drained": True},
        },
        "GET /projects/pid/hunting/h1": {"status": "complete"},
        "POST /projects/pid/hunting": {"hunting_run_id": "h1"},
        "POST /projects/pid/recon": {"run_id": "r1"},
        "GET /projects/pid/graph": GRAPH_L1_L0,
        "PUT /projects/pid/settings": {"ok": True},
        "POST /projects": {"project_id": "pid"},
        "GET /projects": PROJECTS,
    }


def test_recon_trial_runs_recon_then_hunting_and_records(tmp_path) -> None:
    api_runner = FakeApi(_full_routes())

    record = _trial(tmp_path, api_runner).run()

    assert record.project_id == "pid"
    assert [p.phase for p in record.phases] == ["recon", "hunting"]
    assert record.phases[0].run_id == "r1"
    assert record.phases[1].run_id == "h1"
    assert record.phases[0].status == "complete"
    assert record.phases[1].status == "complete"
    assert record.terminal == "complete"
    # The recon launch is the combined recon+analysis dispatch.
    recon_launch = next(c for c in api_runner.calls if c.path.endswith("/recon"))
    assert recon_launch.body == {"with_analysis": True}
    # The trial record is persisted into the trial directory.
    assert record.trial_dir is not None
    written = yaml.safe_load(Path(record.trial_dir, "trial.yaml").read_text())
    assert written["project_id"] == "pid"
    assert written["terminal"] == "complete"


def test_analysis_entry_skips_recon_and_launches_analysis(tmp_path) -> None:
    api_runner = FakeApi(
        {
            "GET /projects/pid/recon/r0": {
                "status": "complete",
                "per_job": [{"job": "crawl", "status": "complete"}],
                "stats": {},
            },
            "POST /projects/pid/analysis": {"analysis_run_id": "a1"},
            "GET /projects/pid/analysis/r0": {"status": "drained"},
            "GET /projects/pid/hunting/h1": {"status": "complete"},
            "POST /projects/pid/hunting": {"hunting_run_id": "h1"},
            "GET /projects/pid/graph": GRAPH_L1_L0,
        }
    )

    record = _trial(
        tmp_path,
        api_runner,
        start_phase="analysis",
        project_id="pid",
        recon_run_id="r0",
    ).run()

    assert [p.phase for p in record.phases] == ["analysis", "hunting"]
    assert record.phases[0].run_id == "a1"
    assert record.terminal == "complete"
    paths = [c.path for c in api_runner.calls]
    assert not any(p.endswith("/recon") for p in paths)
    assert not any(p.endswith("/projects") for p in paths)


def test_hunting_entry_launches_hunting_directly(tmp_path) -> None:
    api_runner = FakeApi(
        {
            "GET /projects/pid/hunting/h1": {"status": "complete"},
            "POST /projects/pid/hunting": {"hunting_run_id": "h1"},
            "GET /projects/pid/graph": GRAPH_L1_L0,
        }
    )

    record = _trial(
        tmp_path, api_runner, start_phase="hunting", project_id="pid"
    ).run()

    assert [p.phase for p in record.phases] == ["hunting"]
    paths = [c.path for c in api_runner.calls]
    assert not any(p.endswith("/recon") for p in paths)
    assert not any("/analysis" in p for p in paths)


def test_recon_entry_block_records_a_blocked_terminal(tmp_path) -> None:
    api_runner = FakeApi(
        {
            "PUT /projects/pid/settings": {"ok": True},
            "POST /projects": {"project_id": "pid"},
            "GET /projects": PROJECTS,
        }
    )

    record = _trial(tmp_path, api_runner, target_seed=None).run()

    assert record.terminal == "blocked"
    assert record.phases[0].entered is False
    assert any("target_seed" in b for b in record.phases[0].blocks)
    assert not any(c.path.endswith("/recon") for c in api_runner.calls)


def test_run_uses_the_injected_reachability_probe(tmp_path) -> None:
    api_runner = FakeApi(_full_routes())

    record = _trial(tmp_path, api_runner, reachable=lambda: False).run()

    assert record.terminal == "blocked"
    assert any("reachable" in b for b in record.phases[0].blocks)
    assert not any(c.path.endswith("/recon") for c in api_runner.calls)


# --- the hunting cap ----------------------------------------------------------


def test_cap_stops_hunting_and_records_the_overshoot(tmp_path) -> None:
    api_runner = FakeApi(
        {
            "GET /projects/pid/hunting/h1": {"status": "running"},
            "POST /projects/pid/hunting/h1/stop": {"stopping": True},
            "POST /projects/pid/hunting": {"hunting_run_id": "h1"},
            "GET /projects/pid/graph": GRAPH_L1_L0,
        }
    )
    # The poll's consumed listing: the empty baseline snapshot, the two new
    # configs observed at the stop, then the in-flight overshoot on re-read (R7).
    files = _cap_store(
        tmp_path, [[], ["a.yaml", "b.yaml"], ["a.yaml", "b.yaml", "c.yaml"]]
    )

    record = _trial(
        tmp_path,
        api_runner,
        files=files,
        start_phase="hunting",
        project_id="pid",
        hunt_config_budget=2,
    ).run()

    assert record.terminal == "stopped"
    assert record.cap == 2
    # Trial-scoped: only the configs consumed during this trial count, not the
    # empty baseline this fresh trial snapped.
    assert record.cap_baseline == []
    assert record.stop_count == 2
    assert record.final_count == 3
    assert record.overshoot == 1
    assert any(c.path.endswith("/stop") for c in api_runner.calls)


def test_cap_counts_only_the_consumed_directory(tmp_path) -> None:
    files = _cap_store(
        tmp_path, [["c0.yaml"], ["c0.yaml", "c1.yaml"], ["c0.yaml", "c1.yaml"]]
    )
    produced = hunt_configs_dir(tmp_path / "data", "pid", "produced")
    for i in range(5):
        files.write_text(produced / f"p{i}.yaml", "id: p\n")

    api_runner = FakeApi(
        {
            "GET /projects/pid/hunting/h1": {"status": "running"},
            "POST /projects/pid/hunting/h1/stop": {"stopping": True},
            "POST /projects/pid/hunting": {"hunting_run_id": "h1"},
            "GET /projects/pid/graph": GRAPH_L1_L0,
        }
    )

    record = _trial(
        tmp_path,
        api_runner,
        files=files,
        start_phase="hunting",
        project_id="pid",
        hunt_config_budget=1,
    ).run()

    # The five produced files never count, nor does the pre-existing consumed
    # `c0.yaml` (the baseline); only the one config consumed during this trial.
    assert record.cap_baseline == ["c0.yaml"]
    assert record.stop_count == 1
    assert record.final_count == 1
    assert record.overshoot == 0


def test_a_pre_existing_consumed_file_does_not_satisfy_the_cap(tmp_path) -> None:
    """A new trial's cap is trial-scoped: a prior run's configs are baseline."""
    api_runner = FakeApi(
        {
            "GET /projects/pid/hunting/h1": {"status": "running"},
            "POST /projects/pid/hunting/h1/stop": {"stopping": True},
            "POST /projects/pid/hunting": {"hunting_run_id": "h1"},
            "GET /projects/pid/graph": GRAPH_L1_L0,
        }
    )
    # Four pre-existing files, then one NEW file appears: cap=1 must stop only
    # after the new one, never at the baseline.
    pre = ["c0.yaml", "c1.yaml", "c2.yaml", "c3.yaml"]
    files = _cap_store(tmp_path, [pre, pre + ["new.yaml"], pre + ["new.yaml"]])

    record = _trial(
        tmp_path,
        api_runner,
        files=files,
        start_phase="hunting",
        project_id="pid",
        hunt_config_budget=1,
    ).run()

    assert record.terminal == "stopped"
    assert record.cap_baseline == pre
    assert record.stop_count == 1
    assert record.final_count == 1
    assert record.overshoot == 0


def test_the_trial_scoped_overshoot_counts_only_new_files(tmp_path) -> None:
    """stop_count and final_count are trial-scoped, not the project total."""
    api_runner = FakeApi(
        {
            "GET /projects/pid/hunting/h1": {"status": "running"},
            "POST /projects/pid/hunting/h1/stop": {"stopping": True},
            "POST /projects/pid/hunting": {"hunting_run_id": "h1"},
            "GET /projects/pid/graph": GRAPH_L1_L0,
        }
    )
    pre = ["c0.yaml", "c1.yaml"]
    # A second new file lands in flight, so the re-read overshoots by one.
    files = _cap_store(
        tmp_path, [pre, pre + ["new.yaml"], pre + ["new.yaml", "extra.yaml"]]
    )

    record = _trial(
        tmp_path,
        api_runner,
        files=files,
        start_phase="hunting",
        project_id="pid",
        hunt_config_budget=1,
    ).run()

    assert record.stop_count == 1
    assert record.final_count == 2
    assert record.overshoot == 1
    assert record.cap_baseline == pre


def test_empty_baseline_and_empty_consumed_never_stop(tmp_path) -> None:
    api_runner = FakeApi(
        {
            "GET /projects/pid/hunting/h1": {"status": "running"},
            "POST /projects/pid/hunting/h1/stop": {"stopping": True},
            "POST /projects/pid/hunting": {"hunting_run_id": "h1"},
            "GET /projects/pid/graph": GRAPH_L1_L0,
        }
    )
    clock = FakeClock()
    files = _cap_store(tmp_path, [[], []])  # always empty consumed

    record = _trial(
        tmp_path,
        api_runner,
        files=files,
        clock=clock,
        start_phase="hunting",
        project_id="pid",
        hunt_config_budget=1,
        budget_s=15.0,
        poll_s=10.0,
    ).run()

    assert record.terminal == "timeout"
    assert record.stop_count is None
    assert record.cap_baseline == []
    # It never issued a stop: the empty trial-scoped count is below the cap.
    assert not any(c.path.endswith("/stop") for c in api_runner.calls)


def test_the_record_round_trips_the_cap_baseline(tmp_path) -> None:
    api_runner = FakeApi(
        {
            "GET /projects/pid/hunting/h1": {"status": "running"},
            "POST /projects/pid/hunting/h1/stop": {"stopping": True},
            "POST /projects/pid/hunting": {"hunting_run_id": "h1"},
            "GET /projects/pid/graph": GRAPH_L1_L0,
        }
    )
    pre = ["old.yaml"]
    files = _cap_store(tmp_path, [pre, pre + ["new.yaml"], pre + ["new.yaml"]])

    record = _trial(
        tmp_path,
        api_runner,
        files=files,
        start_phase="hunting",
        project_id="pid",
        hunt_config_budget=1,
    ).run()

    assert record.cap_baseline == ["old.yaml"]
    written = yaml.safe_load(Path(record.trial_dir, "trial.yaml").read_text())
    assert written["cap_baseline"] == ["old.yaml"]


def test_a_resumed_trial_keeps_its_baseline_and_does_not_reset_the_count(
    tmp_path,
) -> None:
    """A resumed trial carries the record's baseline; its count continues."""
    stop_routes = {
        "GET /projects/pid/hunting/h1": {"status": "running"},
        "POST /projects/pid/hunting/h1/stop": {"stopping": True},
        "POST /projects/pid/hunting": {"hunting_run_id": "h1"},
        "GET /projects/pid/graph": GRAPH_L1_L0,
    }
    pre = ["old.yaml"]
    first = _trial(
        tmp_path,
        FakeApi(stop_routes),
        files=_cap_store(tmp_path, [pre, pre + ["a.yaml"], pre + ["a.yaml"]]),
        start_phase="hunting",
        project_id="pid",
        hunt_config_budget=1,
    ).run()
    assert first.cap_baseline == ["old.yaml"]
    assert first.stop_count == 1

    # Re-enter hunting from the record: its baseline rides along, so the
    # config consumed by the first trial still counts toward the resumed cap.
    resumed_cfg = replace(
        _config(
            tmp_path,
            start_phase="hunting",
            project_id="pid",
            hunt_config_budget=2,
        ),
        cap_baseline=first.cap_baseline,
    )
    resumed_clock = FakeClock()
    resumed = trial.Trial(
        resumed_cfg,
        api_runner=FakeApi(stop_routes),
        files=_cap_store(
            tmp_path,
            [pre + ["a.yaml"], pre + ["a.yaml", "b.yaml"], pre + ["a.yaml", "b.yaml"]],
        ),
        clock=resumed_clock,
        sleep=resumed_clock.sleep,
        reachable=lambda: True,
    ).run()

    # Had the baseline reset, iteration one would clear the cap (empty count)
    # and never reach the cumulative two; this asserts the count continued.
    assert resumed.terminal == "stopped"
    assert resumed.cap_baseline == ["old.yaml"]
    assert resumed.stop_count == 2
    assert resumed.final_count == 2
    assert resumed.overshoot == 0


# --- pre-mined artifacts ------------------------------------------------------


def test_premined_artifacts_are_placed_in_produced_and_consumed_lazily(
    tmp_path,
) -> None:
    source = tmp_path / "premined"
    source.mkdir()
    (source / "unit_CWE-1_sqli.yaml").write_text("id: a\n")
    (source / "unit_CWE-2_xss.yaml").write_text("id: b\n")

    api_runner = FakeApi(
        {
            "GET /projects/pid/hunting/h1": {"status": "complete"},
            "POST /projects/pid/hunting": {"hunting_run_id": "h1"},
            "GET /projects/pid/graph": GRAPH_L1_L0,
        }
    )
    files = FileStore()

    record = _trial(
        tmp_path,
        api_runner,
        files=files,
        start_phase="hunting",
        project_id="pid",
        preloaded_hunting_artifacts=setup.PreloadedArtifacts(configs=str(source)),
        hunt_config_budget=5,
    ).run()

    produced = hunt_configs_dir(tmp_path / "data", "pid", "produced")
    assert sorted(p.name for p in files.list_files(produced)) == [
        "unit_CWE-1_sqli.yaml",
        "unit_CWE-2_xss.yaml",
    ]
    # No bespoke read path: the trial never uploaded/fabricated a config
    # through the API - it wrote to the pipeline's own produced/ inbox.
    rendered = " ".join(c.display() for c in api_runner.calls)
    assert "CWE" not in rendered
    assert "hunt_config" not in rendered

    # The pipeline's normal lazy read moves them; the cap then counts them.
    consumed = hunt_configs_dir(tmp_path / "data", "pid", "consumed")
    for path in files.list_files(produced):
        files.write_text(consumed / path.name, files.read_text(path))
        path.unlink()
    assert files.count_files(consumed) == 2
    assert record.project_id == "pid"


def test_premined_test_specs_land_under_their_fault_key(tmp_path) -> None:
    source = tmp_path / "specs" / "unit_CWE-89_sqli.yaml"
    source.parent.mkdir()
    source.write_text("spec: a\n")

    api_runner = FakeApi(
        {
            "GET /projects/pid/hunting/h1": {"status": "complete"},
            "POST /projects/pid/hunting": {"hunting_run_id": "h1"},
            "GET /projects/pid/graph": GRAPH_L1_L0,
        }
    )
    files = FileStore()
    preloaded = setup.PreloadedArtifacts(
        test_specs=(
            setup.PreloadedTestSpec(path=str(source), fault_key="unit_CWE-89_sqli"),
        )
    )

    _trial(
        tmp_path,
        api_runner,
        files=files,
        start_phase="hunting",
        project_id="pid",
        preloaded_hunting_artifacts=preloaded,
    ).run()

    produced = hunter_test_specs_fault_dir(
        tmp_path / "data", "pid", "unit_CWE-89_sqli", "produced"
    )
    assert [p.name for p in files.list_files(produced)] == ["unit_CWE-89_sqli.yaml"]
    # No bespoke read path: the spec lands in the pipeline's own fault-key
    # produced/ inbox, and no API call references the artifact.
    rendered = " ".join(c.display() for c in api_runner.calls)
    assert "CWE" not in rendered
    assert "test-specs" not in rendered


def test_premined_plan_lists_both_inboxes_and_issues_no_calls(tmp_path) -> None:
    preloaded = setup.PreloadedArtifacts(
        configs="/mnt/configs",
        test_specs=(setup.PreloadedTestSpec(path="/mnt/a.yaml", fault_key="fault-a"),),
    )

    plan = trial.Trial(
        _config(tmp_path, project_id="pid", preloaded_hunting_artifacts=preloaded)
    ).plan()

    step = next(s for s in plan.steps if s.label == "pre-mined hunting artifacts")
    assert step.calls == ()
    assert str(hunt_configs_dir(tmp_path / "data", "pid", "produced")) in step.files
    assert (
        str(hunter_test_specs_fault_dir(tmp_path / "data", "pid", "fault-a", "produced"))
        in step.files
    )


# --- budget -------------------------------------------------------------------


def test_budget_timeout_is_recorded_not_raised(tmp_path) -> None:
    api_runner = FakeApi(
        {
            "GET /projects/pid/recon/r1": {"status": "running"},
            "POST /projects/pid/recon": {"run_id": "r1"},
            "GET /projects/pid/graph": GRAPH_L1_L0,
            "GET /projects": PROJECTS,
        }
    )
    clock = FakeClock()

    record = _trial(
        tmp_path,
        api_runner,
        clock=clock,
        project_id="pid",
        budget_s=25.0,
        poll_s=10.0,
    ).run()

    assert record.terminal == "timeout"
    assert record.phases[0].status == "timeout"
    assert clock.t >= 25.0


# --- bootstrap: auth, scaffold, plan ------------------------------------------


def test_recon_entry_seeds_auth_and_places_the_authn_skill(tmp_path) -> None:
    api_runner = FakeApi(
        {
            "PUT /projects/pid/auth": {"ok": True},
            "GET /projects/pid/auth": {"overview": "sign in", "accounts": [{"name": "a"}]},
            "GET /projects/pid/recon/r1": {
                "status": "complete",
                "per_job": [{"job": "crawl", "status": "complete"}],
                "stats": {"analysis_drained": True},
            },
            "GET /projects/pid/hunting/h1": {"status": "complete"},
            "POST /projects/pid/hunting": {"hunting_run_id": "h1"},
            "POST /projects/pid/recon": {"run_id": "r1"},
            "GET /projects/pid/graph": GRAPH_L1_L0,
            "PUT /projects/pid/settings": {"ok": True},
            "POST /projects": {"project_id": "pid"},
            "GET /projects": PROJECTS,
        }
    )

    record = _trial(
        tmp_path,
        api_runner,
        auth_surface=True,
        auth={
            "overview": "sign in",
            "accounts": [{"name": "a"}],
            "authn_skill": "# authn\n",
        },
    ).run()

    assert record.terminal == "complete"
    auth_call = next(c for c in api_runner.calls if c.path.endswith("/auth"))
    assert auth_call.body == {"overview": "sign in", "accounts": [{"name": "a"}]}
    skill = authn_skill_path(tmp_path / "data", "pid")
    assert skill.exists()


def test_scaffold_command_runs_through_the_command_runner(
    tmp_path, recording_runner
) -> None:
    api_runner = FakeApi(_full_routes())
    runner = recording_runner(routes={"scaffold.py": CommandResult(0, "services: 3\n")})
    spec = trial.ScaffoldSpec(cwd=str(tmp_path), kb="eval/kbs/t/operator_kb.md")

    record = _trial(tmp_path, api_runner, runner=runner, scaffold=spec).run()

    assert record.terminal == "complete"
    scaffold_calls = [c for c in runner.calls if "scaffold.py" in " ".join(c.argv)]
    assert len(scaffold_calls) == 1
    assert "pid" in " ".join(scaffold_calls[0].argv)
    import os

    assert scaffold_calls[0].env == {
        "PYTHONPATH": os.pathsep.join(("src", str(tmp_path)))
    }


def test_reachability_probe_maps_the_kali_http_code(tmp_path) -> None:
    from orchestrator import instances
    from orchestrator.setup import parse_eval_setup

    setup = parse_eval_setup(
        {
            "schema_version": 1,
            "artifact_store": "/srv/a",
            "instances": [
                {
                    "instance_id": "arm-a",
                    "targets": [
                        {
                            "target_id": "t1",
                            "target_config": {
                                "lifecycle": "image",
                                "params": {"image": "nginx", "port": 18080},
                            },
                        }
                    ],
                }
            ],
        }
    )
    paths = instances.instance_paths(
        setup.instances[0], tmp_path / "instances", repo=tmp_path, branch="eval"
    )

    class Runner:
        def __init__(self, code):
            self.code = code
            self.calls = []

        def __call__(self, command):
            self.calls.append(command)
            return CommandResult(0, self.code)

    happy = Runner("200")
    assert trial.make_reachability_probe(paths, happy, "http://t-x.target/")() is True
    assert any("curl" in " ".join(c.argv) for c in happy.calls)
    assert trial.make_reachability_probe(paths, Runner("502"), "http://x/")() is False
    assert trial.make_reachability_probe(paths, Runner(""), "http://x/")() is False


def test_front_url_is_the_synthetic_host(tmp_path) -> None:
    cfg = _config(tmp_path)
    assert trial.front_url(cfg) == f"http://{routing.synthetic_host('arm-a/t1')}/"


def test_plan_lists_the_calls_without_reading(tmp_path) -> None:
    plan = _trial(tmp_path, api_runner=None).plan()

    text = "\n".join(
        f"{step.label}\n" + "\n".join(c.display() for c in step.calls) + "\n" + step.note
        for step in plan.steps
    )
    assert "POST /projects" in text
    assert "with_analysis" in text
    assert "poll" in text.lower()


# --- chaining: setup outcome -> repair or escalate ----------------------------


def test_classify_failure_names_the_configuration_repair() -> None:
    env = trial.classify_failure(InstanceError("command failed: python3 eval/env_preflight.py x"))
    assert env.layer == trial.CONFIGURATION
    assert env.repair == "env"

    stack = trial.classify_failure(InstanceError("command failed (1): docker compose -p ph up -d"))
    assert stack.layer == trial.CONFIGURATION
    assert stack.repair == "stack"

    work_item = trial.classify_failure(WorkItemGateError("eval work items incomplete: x"))
    assert work_item.layer == trial.CONFIGURATION
    assert work_item.repair == "work_items"

    target = trial.classify_failure(TargetError("target never answered"))
    assert target.layer == trial.ESCALATE

    unknown = trial.classify_failure(RuntimeError("boom"))
    assert unknown.layer == trial.ESCALATE


class FakeRepair:
    def __init__(self, supported=("env", "stack", "work_items")):
        self.supported = set(supported)
        self.applied: list[str] = []

    def supports(self, repair: str) -> bool:
        return repair in self.supported

    def apply(self, repair: str) -> None:
        self.applied.append(repair)


def _chain_config(tmp_path) -> trial.TrialConfig:
    return _config(tmp_path)


def test_chain_repairs_a_configuration_failure_and_retries_once(tmp_path) -> None:
    repair = FakeRepair()
    attempts = {"n": 0}

    def bring_up():
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise InstanceError("command failed: python3 eval/env_preflight.py x")
        return ["up"]

    t = trial.Trial(_chain_config(tmp_path), api_runner=None)
    result = t.chain(bring_up, repair)

    assert result == ["up"]
    assert repair.applied == ["env"]
    assert attempts["n"] == 2


def test_chain_escalates_after_a_second_failure(tmp_path) -> None:
    repair = FakeRepair()

    def bring_up():
        raise InstanceError("command failed: docker compose -p ph up -d")

    t = trial.Trial(_chain_config(tmp_path), api_runner=None)
    with pytest.raises(trial.EscalationError, match="docker compose"):
        t.chain(bring_up, repair)
    assert repair.applied == ["stack"]


def test_chain_escalates_a_non_configuration_failure_without_repair(tmp_path) -> None:
    repair = FakeRepair()

    def bring_up():
        raise TargetError("target never answered")

    t = trial.Trial(_chain_config(tmp_path), api_runner=None)
    with pytest.raises(trial.EscalationError, match="target never answered"):
        t.chain(bring_up, repair)
    assert repair.applied == []


def test_chain_escalates_a_configuration_repair_the_kit_cannot_apply(tmp_path) -> None:
    repair = FakeRepair(supported=("stack",))

    def bring_up():
        raise InstanceError("command failed: python3 eval/env_preflight.py x")

    t = trial.Trial(_chain_config(tmp_path), api_runner=None)
    with pytest.raises(trial.EscalationError, match="env"):
        t.chain(bring_up, repair)
    assert repair.applied == []


def test_chain_starts_the_eval_when_setup_succeeds(tmp_path) -> None:
    repair = FakeRepair()
    t = trial.Trial(_chain_config(tmp_path), api_runner=None)

    assert t.chain(lambda: ["up"], repair) == ["up"]
    assert repair.applied == []


# --- the concrete instance repair ---------------------------------------------


def _instance_paths(tmp_path):
    from orchestrator import instances
    from orchestrator.setup import parse_eval_setup

    setup = parse_eval_setup(
        {
            "schema_version": 1,
            "artifact_store": "/srv/a",
            "instances": [
                {
                    "instance_id": "arm-a",
                    "targets": [
                        {
                            "target_id": "t1",
                            "target_config": {
                                "lifecycle": "image",
                                "params": {"image": "nginx", "port": 18080},
                            },
                        }
                    ],
                }
            ],
        }
    )
    return instances.instance_paths(
        setup.instances[0], tmp_path / "instances", repo=tmp_path, branch="eval"
    )


def test_instance_repair_env_reruns_preflight_and_render(tmp_path, recording_runner) -> None:
    runner = recording_runner()
    repair = trial.InstanceRepair(_instance_paths(tmp_path), runner)

    repair.apply("env")

    texts = runner.argv_texts
    assert any("env_preflight.py" in t for t in texts)
    assert any("config" in t for t in texts)


def test_instance_repair_stack_recreates_the_instance(tmp_path, recording_runner) -> None:
    runner = recording_runner()
    repair = trial.InstanceRepair(_instance_paths(tmp_path), runner)

    repair.apply("stack")

    assert any("up -d" in t for t in runner.argv_texts)


def test_command_env_overlay_reaches_the_local_runner(tmp_path) -> None:
    from orchestrator.commands import Command, LocalRunner

    result = LocalRunner()(
        Command(
            argv=("python3", "-c", "import os; print(os.environ.get('EVAL_TRIAL_PROBE', ''))"),
            env={"EVAL_TRIAL_PROBE": "on"},
        )
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "on"


def test_command_display_renders_its_env() -> None:
    assert "PYTHONPATH=src" in Command(
        argv=("python3", "x.py"), env={"PYTHONPATH": "src"}
    ).display()


# --- the version identity (#271/D32) ------------------------------------------


def test_trial_record_stamps_the_version_identity(tmp_path) -> None:
    api_runner = FakeApi(_full_routes())

    record = _trial(
        tmp_path, api_runner, eval_sha="eval-sha-1", stack_fingerprint="fp-1"
    ).run()

    assert record.eval_sha == "eval-sha-1"
    assert record.stack_fingerprint == "fp-1"
    written = yaml.safe_load(Path(record.trial_dir, "trial.yaml").read_text())
    assert written["eval_sha"] == "eval-sha-1"
    assert written["stack_fingerprint"] == "fp-1"


def test_trial_record_defaults_the_version_identity_to_none(tmp_path) -> None:
    record = trial.TrialRecord(
        trial_id="t",
        instance_id="i",
        target_id="x",
        project_id="p",
        start_phase="recon",
        terminal="complete",
        phases=[],
        started_at="a",
        finished_at="b",
    )

    assert record.eval_sha is None
    assert record.stack_fingerprint is None
    assert record.assessment is None
    assert record.to_dict()["assessment"] is None


def test_trial_record_stamps_the_target_run_default_to_the_instance(tmp_path) -> None:
    record = _trial(tmp_path, FakeApi(_full_routes())).run()

    assert record.target_run_id == "arm-a"


def test_trial_record_honours_an_explicit_target_run(tmp_path) -> None:
    record = _trial(
        tmp_path, FakeApi(_full_routes()), target_run_id="run-1"
    ).run()

    assert record.target_run_id == "run-1"


# --- failed terminals and the P8 liveness gate (#270/P8) ----------------------


def test_failed_recon_terminal_stops_the_trial(tmp_path) -> None:
    api_runner = FakeApi(
        {
            "GET /projects/pid/recon/r1": {"status": "failed", "per_job": [], "stats": {}},
            "POST /projects/pid/recon": {"run_id": "r1"},
            "GET /projects/pid/graph": GRAPH_L1_L0,
            "GET /projects": PROJECTS,
        }
    )

    record = _trial(tmp_path, api_runner, project_id="pid").run()

    assert record.terminal == "failed"
    assert [p.phase for p in record.phases] == ["recon"]
    # It never chains into hunting (the fake has no hunting route at all).
    assert not any(c.path.endswith("/hunting") for c in api_runner.calls)


def test_failed_analysis_terminal_stops_the_trial(tmp_path) -> None:
    api_runner = FakeApi(
        {
            "GET /projects/pid/recon/r0": {
                "status": "complete",
                "per_job": [{"job": "crawl", "status": "complete"}],
                "stats": {},
            },
            "POST /projects/pid/analysis": {"analysis_run_id": "a1"},
            "GET /projects/pid/analysis/r0": {"status": "interrupted"},
            "GET /projects/pid/graph": GRAPH_L1_L0,
        }
    )

    record = _trial(
        tmp_path,
        api_runner,
        start_phase="analysis",
        project_id="pid",
        recon_run_id="r0",
    ).run()

    assert record.terminal == "failed"
    assert [p.phase for p in record.phases] == ["analysis"]
    assert not any(c.path.endswith("/hunting") for c in api_runner.calls)


def test_recon_complete_with_every_job_failed_is_a_failed_run(tmp_path) -> None:
    api_runner = FakeApi(
        {
            "GET /projects/pid/recon/r1": {
                "status": "complete",
                "per_job": [{"job": "crawl", "status": "failed"}],
                "stats": {},
            },
            "POST /projects/pid/recon": {"run_id": "r1"},
            "GET /projects/pid/graph": GRAPH_L1_L0,
            "GET /projects": PROJECTS,
        }
    )

    record = _trial(tmp_path, api_runner, project_id="pid").run()

    assert record.terminal == "failed"
    assert [p.phase for p in record.phases] == ["recon"]
    assert record.phases[0].failure is not None
    assert "failed" in record.phases[0].failure


def test_recon_complete_with_no_job_rows_is_a_failed_run(tmp_path) -> None:
    api_runner = FakeApi(
        {
            "GET /projects/pid/recon/r1": {
                "status": "complete",
                "per_job": [],
                "stats": {},
            },
            "POST /projects/pid/recon": {"run_id": "r1"},
            "GET /projects/pid/graph": GRAPH_L1_L0,
            "GET /projects": PROJECTS,
        }
    )

    record = _trial(tmp_path, api_runner, project_id="pid").run()

    assert record.terminal == "failed"
    assert "no job rows" in record.phases[0].failure


def test_a_single_failed_recon_job_is_a_recorded_note(tmp_path) -> None:
    """I8: a partial recon surface is a note on the recon phase, not dropped."""
    routes = _full_routes()
    routes["GET /projects/pid/recon/r1"] = {
        "status": "complete",
        "per_job": [
            {"job": "crawl", "status": "complete"},
            {"job": "content", "status": "failed"},
        ],
        "stats": {"analysis_drained": True},
    }

    record = _trial(tmp_path, FakeApi(routes), project_id="pid").run()

    recon = next(phase for phase in record.phases if phase.phase == "recon")
    assert any("content" in note and "failed" in note for note in recon.notes)
    assert any("content" in note and "failed" in note for note in record.notes)
    assert record.terminal != "failed"


# --- I2: an API transport failure is a written, visible failure ----------------

class ExplodingApi:
    """An `ApiRunner` whose every call fails at the transport layer."""

    def __init__(self, detail: str = "connection refused") -> None:
        self.detail = detail
        self.calls: list = []

    def __call__(self, call):
        self.calls.append(call)
        raise api.ApiError(call, 0, self.detail)


def test_api_transport_failure_writes_a_failed_record_with_the_phase(tmp_path) -> None:
    """I2: a mid-trial transport failure is recorded, never lost to a traceback."""
    api_runner = ExplodingApi()

    record = _trial(tmp_path, api_runner, project_id="pid", start_phase="hunting").run()

    assert record.terminal == "failed"
    assert record.phases, "the reached phase must be recorded"
    reached = record.phases[-1]
    assert reached.phase == "hunting"
    assert reached.entered is True
    assert reached.failure is not None and "connection refused" in reached.failure
    assert any("connection refused" in note for note in record.notes)
    written = yaml.safe_load(Path(record.trial_dir, "trial.yaml").read_text())
    assert written["terminal"] == "failed"
    assert "connection refused" in yaml.safe_dump(written)


def test_api_transport_failure_during_project_creation_is_recorded(tmp_path) -> None:
    """A failure before any phase lands on the entry phase, still recorded."""
    api_runner = ExplodingApi()

    record = _trial(tmp_path, api_runner, start_phase="recon").run()

    assert record.terminal == "failed"
    assert record.phases[-1].phase == "recon"
    assert "connection refused" in record.phases[-1].failure


# --- the trace id and the record writer (#271/D6) -----------------------------


def test_trial_record_stamps_the_trace_id(tmp_path) -> None:
    record = _trial(tmp_path, FakeApi(_full_routes()), trace_id="trace-1").run()

    assert record.trace_id == "trace-1"
    written = yaml.safe_load(Path(record.trial_dir, "trial.yaml").read_text())
    assert written["trace_id"] == "trace-1"


def test_default_trial_id_uses_the_injected_clock(tmp_path) -> None:
    cfg = _config(tmp_path)

    trial_id = trial._default_trial_id(cfg, lambda: "2026-09-28T12:34:56+00:00")

    assert "20260928T123456" in trial_id


def test_trial_record_is_written_atomically(tmp_path) -> None:
    files = AtomicFileStore()

    record = _trial(tmp_path, FakeApi(_full_routes()), files=files).run()

    written = Path(record.trial_dir, "trial.yaml")
    assert written in files.atomic


def test_premined_source_resolution_uses_the_file_store_seam(tmp_path) -> None:
    source = tmp_path / "premined"
    source.mkdir()
    (source / "unit_CWE-1_x.yaml").write_text("id: a\n")
    files = SeamFileStore()

    paths = trial._premined_sources(files, str(source))

    assert [path.name for path in paths] == ["unit_CWE-1_x.yaml"]
    # It asks the seam whether the source is a file before walking it.
    assert files.is_file_calls[0] == source
