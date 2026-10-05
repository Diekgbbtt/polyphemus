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
from orchestrator.commands import Command
from orchestrator.files import (
    FileStore,
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


class SeqUsageApi(FakeApi):
    """A `FakeApi` whose usage route pops a scripted token total per call.

    The token-budget poll reads the usage endpoint once per check, plus one
    re-read after a stop for the overshoot, so scripting the totals models the
    baseline snapshot, the consumption, and the in-flight overshoot.
    """

    def __init__(self, routes: dict | None = None, totals=()):
        super().__init__(routes)
        self._totals = list(totals)
        self.usage_calls = 0

    def __call__(self, call):
        if call.path.endswith("/usage"):
            self.usage_calls += 1
            total = self._totals.pop(0) if self._totals else 0
            self.calls.append(call)
            return {
                "project_id": "pid",
                "total_tokens": total,
                "generated_tokens": total,
                "calls": 1,
                "by_agent": {"recon": {"total_tokens": total}},
            }
        return super().__call__(call)


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


def test_recon_trial_enables_streamed_analysis_in_settings(tmp_path) -> None:
    # #321: the batched/post-recon path is obsolete; every fresh trial turns on
    # settings.recon.streaming_analysis so recon's per-job chunks feed the queued
    # analysis consumer and the L1 AGGREGATES get written.
    api_runner = FakeApi(_full_routes())

    _trial(tmp_path, api_runner).run()

    settings = next(c for c in api_runner.calls if c.path == "/projects/pid/settings")
    assert settings.body["recon"]["streaming_analysis"] is True


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


def test_run_proceeds_without_a_reachability_probe(tmp_path) -> None:
    api_runner = FakeApi(_full_routes())

    record = _trial(tmp_path, api_runner).run()

    assert record.terminal == "complete"
    assert any(c.path.endswith("/recon") for c in api_runner.calls)




# --- the trial-wide token budget ----------------------------------------------


def _usage_routes() -> dict:
    return {
        "GET /projects/pid/hunting/h1": {"status": "running"},
        "POST /projects/pid/hunting/h1/stop": {"stopping": True},
        "POST /projects/pid/hunting": {"hunting_run_id": "h1"},
        "GET /projects/pid/graph": GRAPH_L1_L0,
    }


def test_no_token_budget_makes_no_usage_call(tmp_path) -> None:
    api_runner = SeqUsageApi()

    t = _trial(tmp_path, api_runner, project_id="pid", token_budget=None)

    assert t._check_spend("pid", "recon", "r1") is None
    assert api_runner.usage_calls == 0


def test_the_spend_check_returns_a_spend_result_on_a_stop(tmp_path) -> None:
    # The spec contract is `SpendResult | None`: a stop returns the result, a
    # below-budget check returns None. Call sites only test truthiness.
    api_runner = SeqUsageApi(_usage_routes(), totals=[1500, 1700])

    t = _trial(
        tmp_path, api_runner, project_id="pid", token_budget=500, spend_baseline=1000
    )

    result = t._check_spend("pid", "hunting", "h1")

    assert isinstance(result, trial.SpendResult)
    assert result.spent == 500
    assert result.overshoot == 200


def test_the_budget_counts_generated_tokens_not_the_cache_heavy_raw_total(tmp_path) -> None:
    # The raw total is over budget from the first read, but it is almost all
    # re-read input, so the GENERATED axis decides the stop. Counting the raw
    # total would stop the trial at ~zero new tokens - the half-occupancy bug.
    class RawHeavyApi(FakeApi):
        def __init__(self, routes, generated_seq):
            super().__init__(routes)
            self._generated = list(generated_seq)
            self.usage_calls = 0

        def __call__(self, call):
            if call.path.endswith("/usage"):
                self.usage_calls += 1
                generated = self._generated.pop(0)
                self.calls.append(call)
                return {
                    "project_id": "pid",
                    "total_tokens": 50_000_000,
                    "generated_tokens": generated,
                    "calls": 1,
                    "by_agent": {},
                }
            return super().__call__(call)

    api_runner = RawHeavyApi(_usage_routes(), generated_seq=[10, 100])
    t = _trial(tmp_path, api_runner, project_id="pid", token_budget=500)

    # Baseline capped 10 (raw 50M ignored), then capped 100 -> spent 90 < 500.
    assert t._check_spend("pid", "hunting", "h1") is None
    assert t._check_spend("pid", "hunting", "h1") is None
    assert not any(c.path.endswith("/stop") for c in api_runner.calls)


def test_token_budget_stops_the_run_and_records_the_spend(tmp_path) -> None:
    # The first read snapshots the baseline (1000); the second read reaches the
    # budget (500 spent); the third is the post-stop re-read for the overshoot.
    api_runner = SeqUsageApi(_usage_routes(), totals=[1000, 1500, 1500])

    record = _trial(
        tmp_path,
        api_runner,
        start_phase="hunting",
        project_id="pid",
        token_budget=500,
    ).run()

    stop = next(c for c in api_runner.calls if c.path.endswith("/stop"))
    assert stop.path == "/projects/pid/hunting/h1/stop"
    assert record.terminal == "stopped"
    assert record.token_budget == 500
    assert record.spend_baseline == 1000
    assert record.spent_tokens == 500
    assert record.spend_overshoot == 0
    assert record.spend_by_agent == {"recon": {"total_tokens": 1500}}
    written = yaml.safe_load(Path(record.trial_dir, "trial.yaml").read_text())
    assert written["spent_tokens"] == 500
    assert written["spend_baseline"] == 1000


def test_the_baseline_is_the_project_total_at_the_first_check(tmp_path) -> None:
    api_runner = SeqUsageApi(_usage_routes(), totals=[1000, 1500, 1500])

    record = _trial(
        tmp_path,
        api_runner,
        start_phase="hunting",
        project_id="pid",
        token_budget=500,
    ).run()

    # The project started at 1000: only the 500 consumed during the trial count.
    assert record.spend_baseline == 1000
    assert record.spent_tokens == 500


def test_the_token_budget_is_trial_wide_and_stops_recon(tmp_path) -> None:
    api_runner = SeqUsageApi(
        {
            "GET /projects/pid/recon/r1": {"status": "running"},
            "POST /projects/pid/recon/r1/stop": {"stopped": True},
            "POST /projects/pid/recon": {"run_id": "r1"},
            "GET /projects/pid/graph": GRAPH_L1_L0,
            "GET /projects": PROJECTS,
        },
        totals=[1000, 1500, 1500],
    )

    record = _trial(
        tmp_path,
        api_runner,
        start_phase="recon",
        project_id="pid",
        token_budget=500,
    ).run()

    stop = next(c for c in api_runner.calls if c.path.endswith("/stop"))
    assert stop.path == "/projects/pid/recon/r1/stop"
    assert record.terminal == "stopped"
    assert [p.phase for p in record.phases] == ["recon"]
    assert record.phases[0].status == "stopped"
    assert record.spent_tokens == 500
    # A recon stop never chains into hunting.
    assert not any(c.path.endswith("/hunting") for c in api_runner.calls)


def test_an_analysis_token_stop_names_the_recon_run_id(tmp_path) -> None:
    # The analysis stop endpoint is keyed by the recon run id; the surrogate
    # `analysis_run_id` is only the launch handle. The record must carry the id
    # the stop verb expects, or the surfer's terminate is a silent no-op.
    api_runner = SeqUsageApi(
        {
            "GET /projects/pid/recon/r0": {
                "status": "complete",
                "per_job": [{"job": "crawl", "status": "complete"}],
                "stats": {},
            },
            "POST /projects/pid/analysis/r0/stop": {"stopped": True},
            "POST /projects/pid/analysis": {"analysis_run_id": "a1"},
            "GET /projects/pid/analysis/r0": {"status": "draining"},
            "GET /projects/pid/graph": GRAPH_L1_L0,
        },
        totals=[1000, 1500, 1500],
    )

    record = _trial(
        tmp_path,
        api_runner,
        start_phase="analysis",
        project_id="pid",
        recon_run_id="r0",
        token_budget=500,
    ).run()

    stop = next(c for c in api_runner.calls if c.path.endswith("/stop"))
    assert stop.path == "/projects/pid/analysis/r0/stop"
    assert record.terminal == "stopped"
    assert [p.phase for p in record.phases] == ["analysis"]
    # The analysis consumer id is the surrogate; the recon id is the stop key.
    assert record.phases[0].run_id == "a1"
    assert record.phases[0].stop_run_id == "r0"
    # The analysis stop ends the trial; it never chains into hunting.
    assert not any(c.path.endswith("/hunting") for c in api_runner.calls)


def test_a_resumed_trial_does_not_re_snapshot_the_baseline(tmp_path) -> None:
    api_runner = SeqUsageApi(_usage_routes(), totals=[1500, 1500])

    record = _trial(
        tmp_path,
        api_runner,
        start_phase="hunting",
        project_id="pid",
        token_budget=500,
        spend_baseline=1000,
    ).run()

    # Against the carried 1000 baseline the first read already clears the
    # budget; a fresh snapshot at 1500 would spend zero and never stop.
    assert record.terminal == "stopped"
    assert record.spend_baseline == 1000
    assert record.spent_tokens == 500
    assert api_runner.usage_calls == 2


def test_the_spend_overshoot_counts_tokens_spent_past_the_budget(tmp_path) -> None:
    api_runner = SeqUsageApi(_usage_routes(), totals=[1000, 1500, 1700])

    record = _trial(
        tmp_path,
        api_runner,
        start_phase="hunting",
        project_id="pid",
        token_budget=500,
    ).run()

    # 1700 total - 1000 baseline - 500 budget = 200 spent past the bound.
    assert record.spent_tokens == 500
    assert record.spend_overshoot == 200


def test_the_spend_check_stops_hunting(tmp_path) -> None:
    api_runner = SeqUsageApi(_usage_routes(), totals=[1000, 1500, 1500])

    record = _trial(
        tmp_path,
        api_runner,
        start_phase="hunting",
        project_id="pid",
        token_budget=500,
    ).run()

    assert record.terminal == "stopped"
    assert record.spent_tokens == 500
    assert sum(1 for c in api_runner.calls if c.path.endswith("/stop")) == 1


def test_a_malformed_usage_payload_never_falsely_stops(tmp_path) -> None:
    # The usage endpoint is advisory: a malformed capped value reads as zero, so
    # the trial times out rather than falsely tripping the budget.
    api_runner = FakeApi(
        {
            "GET /projects/pid/usage": {"generated_tokens": "not-an-int", "by_agent": "oops"},
            "GET /projects/pid/hunting/h1": {"status": "running"},
            "POST /projects/pid/hunting": {"hunting_run_id": "h1"},
            "GET /projects/pid/graph": GRAPH_L1_L0,
        }
    )

    record = _trial(
        tmp_path,
        api_runner,
        start_phase="hunting",
        project_id="pid",
        token_budget=500,
        budget_s=25.0,
        poll_s=10.0,
    ).run()

    assert record.terminal == "timeout"
    assert not any(c.path.endswith("/stop") for c in api_runner.calls)


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


def _write_data_dependencies(tmp_path) -> Path:
    base = tmp_path / "dd"
    (base / "auth").mkdir(parents=True)
    (base / "auth" / "overview.yaml").write_text("login_endpoint: https://x/login\n")
    (base / "auth" / "credentials.yaml").write_text("accounts: {}\n")
    skill = base / "skills" / "authn"
    (skill / "references").mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: authn\ndescription: d\nmetadata:\n  version: '1.0'\n---\n\n# authn\n"
    )
    (skill / "references" / "login.sh").write_text("#!/bin/sh\n")
    (base / "operator_kb.md").write_text("# KB\n")
    return base


def test_recon_entry_places_the_data_dependencies_and_the_l1_surface(tmp_path) -> None:
    base = _write_data_dependencies(tmp_path)
    class ServerFileStore(FileStore):
        """Models the server's write: after the authn placement, the canonical
        skill file exists, so the trial's landing check (and the recon gate) pass."""

        def __init__(self) -> None:
            self.skill_written = False

        def exists(self, path):  # type: ignore[override]
            if Path(path).name == "SKILL.md" and self.skill_written:
                return True
            return super().exists(path)

        def is_file(self, path):  # type: ignore[override]
            if Path(path).name == "SKILL.md" and self.skill_written:
                return True
            return super().is_file(path)

    files = ServerFileStore()

    class ServerApi(FakeApi):
        def __call__(self, call):
            if call.file is not None and call.path.endswith("authn-skill"):
                files.skill_written = True
            return super().__call__(call)

    api_runner = ServerApi(
        {
            # ordered before `_full_routes`' `GET /projects` needle, which would
            # otherwise substring-match the auth path first
            "GET /projects/pid/auth": {"overview": {"mechanism": "none"},
                                       "accounts": {"a": {"origin": "operator"}}},
            **_full_routes(),
            "POST /projects/pid/data-dependencies/auth-overview": {"ok": True},
            "POST /projects/pid/data-dependencies/auth-credentials": {"ok": True},
            "POST /projects/pid/data-dependencies/authn-skill": {"ok": True},
            "POST /projects/pid/data-dependencies/l1": {
                "ok": True, "services_written": 3, "systems_written": 2},
        }
    )

    record = _trial(
        tmp_path,
        api_runner,
        files=files,
        data_dir=base,
        auth_surface=True,
        operator_kb=str(base / "operator_kb.md"),
    ).run()

    assert record.terminal == "complete"
    uploads = {
        c.path.rsplit("/", 1)[-1]: c
        for c in api_runner.calls
        if c.file is not None
    }
    assert set(uploads) == {"auth-overview", "auth-credentials", "authn-skill", "l1"}
    assert uploads["auth-overview"].file.data == b"login_endpoint: https://x/login\n"
    assert uploads["auth-credentials"].file.data == b"accounts: {}\n"
    assert uploads["l1"].file.data == b"# KB\n"
    # the skill is packed as a tar.gz of bundle-relative members
    import io
    import tarfile

    with tarfile.open(fileobj=io.BytesIO(uploads["authn-skill"].file.data), mode="r:gz") as archive:
        assert sorted(archive.getnames()) == ["SKILL.md", "references/login.sh"]
    # no obsolete seed_auth PUT survives
    assert not any(c.path.endswith("/auth") and c.method == "PUT" for c in api_runner.calls)


def test_the_l1_endpoint_is_not_called_without_a_knowledge_base(tmp_path) -> None:
    api_runner = FakeApi(_full_routes())

    record = _trial(tmp_path, api_runner).run()

    assert record.terminal == "complete"
    assert not any(
        c.path.endswith("/data-dependencies/l1") for c in api_runner.calls
    )


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


def test_the_plan_names_the_token_budget_when_set(tmp_path) -> None:
    plan = _trial(tmp_path, api_runner=None, token_budget=1234).plan()

    note = next(s.note for s in plan.steps if s.label == "hunting entry + launch")
    assert "token budget 1234" in note


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
                            "target_key": "mock/webmock",
                            "target_id": "t1",
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
