"""The surfer loop (#275, D5/D31/N17).

The surfer asserts instance state in the background and prompts the orchestrator
on a cap-reached or failed state; the orchestrator decides terminate, destroy or
a bounded fix-and-restart, or escalates into a hold. Every effect is injected -
the state source, the decider agent turn, the command runner, the REST client,
the repair kit, the trial resumer, the clock, and the hold state - so the loop is
exercised without Docker, a live stack, or an agent. Import performs no I/O.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from advance.app_state import AppState
from orchestrator import alignment, api, instances, surfer, trial
from orchestrator.commands import CommandResult
from orchestrator.files import FileStore, hunt_configs_dir
from orchestrator.instances import InstancePaths
from orchestrator.setup import (
    EvalSetup,
    Instance,
    PreloadedArtifacts,
    PreloadedTestSpec,
    TargetConfig,
    TargetRun,
)


# --- fixtures and helpers -----------------------------------------------------


def make_paths(tmp_path: Path, instance_id: str = "arm-a", *, worktree: bool = True):
    instance = Instance(instance_id=instance_id, targets=())
    paths = instances.instance_paths(
        instance, tmp_path / "instances", repo=tmp_path / "repo", branch="eval"
    )
    if worktree:
        paths.worktree.mkdir(parents=True, exist_ok=True)
    return paths


def make_setup(instance_id: str = "arm-a", target_id: str = "t1") -> EvalSetup:
    return EvalSetup(
        schema_version=1,
        artifact_store="/srv/store",
        instances=(
            Instance(
                instance_id=instance_id,
                targets=(
                    TargetRun(
                        target_id=target_id,
                        target_config=TargetConfig(lifecycle="image", params={}),
                    ),
                ),
            ),
        ),
    )


def failed_trigger(
    *, instance_id: str = "arm-a", target_id: str = "t1", project_id: str = "pid",
    run_kind: str = "hunting", run_id: str = "h1", start_phase: str = "hunting",
    detail: str = "hunting interrupted",
) -> surfer.Trigger:
    return surfer.Trigger(
        kind=surfer.FAILED_RUN,
        instance_id=instance_id,
        detail=detail,
        target_id=target_id,
        project_id=project_id,
        run_kind=run_kind,
        run_id=run_id,
        start_phase=start_phase,
    )


def state_with(*triggers: surfer.Trigger, idle: bool = False) -> surfer.SurfacedState:
    return surfer.SurfacedState(idle=idle, triggers=tuple(triggers))


class StaticAsserter:
    def __init__(self, state: surfer.SurfacedState) -> None:
        self.state = state
        self.calls = 0

    def assert_state(self) -> surfer.SurfacedState:
        self.calls += 1
        return self.state


class StaticDecider:
    def __init__(self, decision: surfer.SurferDecision) -> None:
        self.decision = decision
        self.requests: list[surfer.SurferRequest] = []

    def decide(self, request: surfer.SurferRequest) -> surfer.SurferDecision:
        self.requests.append(request)
        return self.decision


_EXPLODE = "the decider must never be dispatched"


class ExplodingDecider:
    def decide(self, request):  # pragma: no cover - a dry-run never dispatches
        raise AssertionError(_EXPLODE)


class FakeApi:
    def __init__(self) -> None:
        self.calls: list = []

    def __call__(self, call):
        self.calls.append(call)
        return {}

    @property
    def paths(self) -> list[str]:
        return [f"{c.method} {c.path}" for c in self.calls]


class RecordingResumer:
    def __init__(self) -> None:
        self.plans: list[surfer.ResumePlan] = []

    def resume(self, plan: surfer.ResumePlan) -> str:
        self.plans.append(plan)
        return f"{plan.target_id}-resumed"


class FakeRepairKit:
    """Records the bounded repair and restart calls; supports what it is told."""

    def __init__(self, supported=("env", "replace_artifacts")) -> None:
        self.supported = set(supported)
        self.applied: list[str] = []
        self.restarted: list[str] = []
        self.projects: list[str] = []

    def supports(self, repair: str) -> bool:
        return repair in self.supported

    def apply(self, repair: str, *, project_id: str) -> None:
        if repair not in self.supported:
            raise surfer.SurferError(f"unsupported repair: {repair!r}")
        self.applied.append(repair)
        self.projects.append(project_id)

    def restart(self, repair: str) -> None:
        self.restarted.append(repair)


def make_surfer(
    asserter,
    decider,
    *,
    tmp_path: Path,
    state=None,
    runner=None,
    api_runner=None,
    repair_kit=None,
    resumer=None,
    instances=("arm-a",),
    dry_run=False,
    config=None,
    sleep=None,
    now=None,
    log=None,
):
    paths = [make_paths(tmp_path, instance_id=i, worktree=False) for i in instances]
    return surfer.Surfer(
        config or surfer.SurferConfig(),
        asserter=asserter,
        decider=decider,
        instances=tuple(paths),
        runner=runner,
        api=api_runner,
        repairs=(lambda trigger: repair_kit) if repair_kit is not None else None,
        resumer=resumer,
        state=state,
        dry_run=dry_run,
        sleep=sleep,
        now=now or (lambda: "2026-09-28T00:00:00+00:00"),
        log=log,
    )


# --- no trigger / assertion source --------------------------------------------


def test_no_trigger_is_a_no_op_and_never_calls_the_decider(tmp_path) -> None:
    asserter = StaticAsserter(state_with(idle=True))
    decider = StaticDecider(surfer.SurferDecision(surfer.TERMINATE))
    api_runner = FakeApi()
    kit = FakeRepairKit()

    outcome = make_surfer(
        asserter, decider, tmp_path=tmp_path, api_runner=api_runner, repair_kit=kit
    ).cycle()

    assert outcome.no_op is True
    assert outcome.decision is None
    assert decider.requests == []
    assert api_runner.calls == []
    assert kit.applied == []


def test_cap_reached_is_detected_from_the_trial_cap_accounting(tmp_path) -> None:
    record = {
        "instance_id": "arm-a",
        "target_id": "t1",
        "project_id": "pid",
        "terminal": "stopped",
        "start_phase": "hunting",
        "phases": [{"phase": "hunting", "status": "stopped", "run_id": "h1"}],
        "cap": 2,
        "stop_count": 2,
        "final_count": 3,
        "overshoot": 1,
    }
    source = surfer.SurferStateSource(
        app_state=lambda: AppState(idle=True, projects=()),
        trial_log=StaticTrialLog([record]),
        signals=surfer.CreditExhaustionReader(),
        evidence=lambda: (),
    )

    state = source.assert_state()

    assert [t.kind for t in state.triggers] == [surfer.CAP_REACHED]
    assert state.triggers[0].start_phase == "hunting"
    assert state.triggers[0].project_id == "pid"
    assert "cap 2" in state.triggers[0].detail
    # The cap trigger names the hunting run so `terminate` can actually stop it:
    # a trigger with no run is unactionable.
    assert state.triggers[0].run_kind == "hunting"
    assert state.triggers[0].run_id == "h1"


def test_the_cap_trigger_carries_the_record_baseline() -> None:
    """The resume path reads the persisted baseline off the cap record."""
    record = {
        "instance_id": "arm-a",
        "target_id": "t1",
        "project_id": "pid",
        "terminal": "stopped",
        "start_phase": "hunting",
        "phases": [{"phase": "hunting", "status": "stopped", "run_id": "h1"}],
        "cap": 2,
        "stop_count": 2,
        "final_count": 3,
        "overshoot": 1,
        "cap_baseline": ["old.yaml", "older.yaml"],
    }

    triggers = surfer.cap_triggers(record)

    assert triggers[0].cap_baseline == ("old.yaml", "older.yaml")


def test_a_malformed_cap_baseline_is_ignored() -> None:
    record = {
        "instance_id": "arm-a",
        "target_id": "t1",
        "project_id": "pid",
        "phases": [{"phase": "hunting", "status": "stopped", "run_id": "h1"}],
        "cap": 2,
        "stop_count": 2,
        "cap_baseline": "not-a-list",
    }

    assert surfer.cap_triggers(record)[0].cap_baseline is None


def test_a_failed_hunting_resume_plan_carries_the_record_baseline(tmp_path) -> None:
    """A resumed hunting trial keeps the record's trial-scoped baseline."""
    record = {
        "instance_id": "arm-a",
        "target_id": "t1",
        "project_id": "pid",
        "terminal": "failed",
        "start_phase": "hunting",
        "phases": [
            {"phase": "hunting", "status": "failed", "run_id": "h1", "failure": None}
        ],
        "cap_baseline": ["old.yaml"],
    }
    trigger = surfer.failed_run_trigger(record)
    assert trigger is not None and trigger.cap_baseline == ("old.yaml",)
    asserter = StaticAsserter(state_with(trigger))
    decider = StaticDecider(surfer.SurferDecision(surfer.FIX, repair=surfer.REPAIR_ENV))
    kit = FakeRepairKit(supported=("env",))
    resumer = RecordingResumer()

    make_surfer(
        asserter, decider, tmp_path=tmp_path, repair_kit=kit, resumer=resumer
    ).cycle()

    assert resumer.plans[0].cap_baseline == ("old.yaml",)


# --- the trial-wide token budget ----------------------------------------------


def test_token_budget_reached_is_detected_from_the_record() -> None:
    record = {
        "instance_id": "arm-a",
        "target_id": "t1",
        "project_id": "pid",
        "terminal": "stopped",
        "start_phase": "hunting",
        "phases": [{"phase": "hunting", "status": "stopped", "run_id": "h1"}],
        "token_budget": 500,
        "spent_tokens": 600,
        "spend_overshoot": 100,
    }
    source = surfer.SurferStateSource(
        app_state=lambda: AppState(idle=True, projects=()),
        trial_log=StaticTrialLog([record]),
        signals=surfer.CreditExhaustionReader(),
        evidence=lambda: (),
    )

    state = source.assert_state()

    assert [t.kind for t in state.triggers] == [surfer.TOKEN_BUDGET_REACHED]
    assert state.triggers[0].start_phase == "hunting"
    assert state.triggers[0].project_id == "pid"
    assert "500" in state.triggers[0].detail
    assert "600" in state.triggers[0].detail
    # The spend trigger names the stopped run so `terminate` can stop it.
    assert state.triggers[0].run_kind == "hunting"
    assert state.triggers[0].run_id == "h1"


def test_the_spend_trigger_names_the_phase_it_stopped_in() -> None:
    record = {
        "instance_id": "arm-a",
        "target_id": "t1",
        "project_id": "pid",
        "phases": [{"phase": "recon", "status": "stopped", "run_id": "r1"}],
        "token_budget": 500,
        "spent_tokens": 600,
    }

    triggers = surfer.spend_triggers(record)

    assert triggers[0].run_kind == "recon"
    assert triggers[0].run_id == "r1"
    assert triggers[0].start_phase == "recon"


def test_the_spend_trigger_carries_the_record_baseline() -> None:
    """The resume path reads the persisted baseline off the spend record."""
    record = {
        "instance_id": "arm-a",
        "target_id": "t1",
        "project_id": "pid",
        "phases": [{"phase": "hunting", "status": "stopped", "run_id": "h1"}],
        "token_budget": 500,
        "spent_tokens": 600,
        "spend_baseline": 1000,
    }

    triggers = surfer.spend_triggers(record)

    assert triggers[0].spend_baseline == 1000


def test_a_malformed_spend_baseline_is_ignored() -> None:
    record = {
        "instance_id": "arm-a",
        "target_id": "t1",
        "project_id": "pid",
        "phases": [{"phase": "hunting", "status": "stopped", "run_id": "h1"}],
        "token_budget": 500,
        "spent_tokens": 600,
        "spend_baseline": "not-an-int",
    }

    assert surfer.spend_triggers(record)[0].spend_baseline is None


def test_a_missing_spend_baseline_is_ignored() -> None:
    record = {
        "instance_id": "arm-a",
        "target_id": "t1",
        "project_id": "pid",
        "phases": [{"phase": "hunting", "status": "stopped", "run_id": "h1"}],
        "token_budget": 500,
        "spent_tokens": 600,
    }

    assert surfer.spend_triggers(record)[0].spend_baseline is None


def test_a_spend_below_budget_is_not_a_trigger() -> None:
    record = {
        "instance_id": "arm-a",
        "target_id": "t1",
        "project_id": "pid",
        "phases": [{"phase": "hunting", "status": "stopped", "run_id": "h1"}],
        "token_budget": 500,
        "spent_tokens": 499,
    }

    assert surfer.spend_triggers(record) == []


def test_no_token_budget_is_not_a_trigger() -> None:
    record = {
        "instance_id": "arm-a",
        "target_id": "t1",
        "project_id": "pid",
        "phases": [{"phase": "hunting", "status": "stopped", "run_id": "h1"}],
        "spent_tokens": 600,
    }

    assert surfer.spend_triggers(record) == []


def test_a_token_stop_resume_plan_carries_the_spend_baseline(tmp_path) -> None:
    """A resumed trial keeps the record's spend baseline, not a fresh snapshot."""
    record = {
        "instance_id": "arm-a",
        "target_id": "t1",
        "project_id": "pid",
        "terminal": "stopped",
        "start_phase": "hunting",
        "phases": [{"phase": "hunting", "status": "stopped", "run_id": "h1"}],
        "token_budget": 500,
        "spent_tokens": 600,
        "spend_baseline": 1000,
    }
    trigger = surfer.spend_triggers(record)[0]
    asserter = StaticAsserter(state_with(trigger))
    decider = StaticDecider(surfer.SurferDecision(surfer.FIX, repair=surfer.REPAIR_ENV))
    kit = FakeRepairKit(supported=("env",))
    resumer = RecordingResumer()

    make_surfer(
        asserter, decider, tmp_path=tmp_path, repair_kit=kit, resumer=resumer
    ).cycle()

    assert resumer.plans[0].spend_baseline == 1000


def test_a_failed_hunting_resume_plan_carries_the_spend_baseline(tmp_path) -> None:
    """A failed-run trigger also carries the record's spend baseline."""
    record = {
        "instance_id": "arm-a",
        "target_id": "t1",
        "project_id": "pid",
        "terminal": "failed",
        "start_phase": "hunting",
        "phases": [
            {"phase": "hunting", "status": "failed", "run_id": "h1", "failure": None}
        ],
        "spend_baseline": 1000,
    }
    trigger = surfer.failed_run_trigger(record)
    assert trigger is not None and trigger.spend_baseline == 1000
    asserter = StaticAsserter(state_with(trigger))
    decider = StaticDecider(surfer.SurferDecision(surfer.FIX, repair=surfer.REPAIR_ENV))
    kit = FakeRepairKit(supported=("env",))
    resumer = RecordingResumer()

    make_surfer(
        asserter, decider, tmp_path=tmp_path, repair_kit=kit, resumer=resumer
    ).cycle()

    assert resumer.plans[0].spend_baseline == 1000


def test_a_failed_run_is_detected_from_the_record_phase(tmp_path) -> None:
    record = {
        "instance_id": "arm-a",
        "target_id": "t1",
        "project_id": "pid",
        "terminal": "failed",
        "start_phase": "hunting",
        "phases": [
            {"phase": "recon", "status": "complete", "run_id": "r1"},
            {"phase": "hunting", "status": "failed", "run_id": "h1", "failure": None},
        ],
    }
    source = surfer.SurferStateSource(
        app_state=lambda: AppState(idle=False, projects=()),
        trial_log=StaticTrialLog([record]),
        signals=surfer.CreditExhaustionReader(),
        evidence=lambda: (),
    )

    state = source.assert_state()

    assert [t.kind for t in state.triggers] == [surfer.FAILED_RUN]
    trigger = state.triggers[0]
    assert trigger.run_kind == "hunting"
    assert trigger.run_id == "h1"
    assert trigger.start_phase == "hunting"


def test_an_interrupted_phase_is_a_failed_run() -> None:
    record = {
        "instance_id": "arm-a",
        "project_id": "pid",
        "phases": [{"phase": "analysis", "status": "interrupted", "run_id": "a1"}],
    }
    source = surfer.SurferStateSource(
        app_state=lambda: AppState(idle=False, projects=()),
        trial_log=StaticTrialLog([record]),
        signals=surfer.CreditExhaustionReader(),
        evidence=lambda: (),
    )

    state = source.assert_state()

    assert state.triggers[0].kind == surfer.FAILED_RUN
    assert state.triggers[0].start_phase == "analysis"


def test_credit_exhaustion_evidence_classifies_as_a_failure_signal() -> None:
    reader = surfer.CreditExhaustionReader()
    evidence = (
        surfer.FailureEvidence(
            instance_id="arm-a",
            text="litellm: Error code: 429 - insufficient_quota (billing hard limit reached)",
            source="trial_record",
            target_id="t1",
            project_id="pid",
        ),
    )

    signals = reader.read(evidence)

    assert [s.kind for s in signals] == [surfer.CREDIT_EXHAUSTION]
    assert signals[0].instance_id == "arm-a"


def test_a_credit_exhaustion_signal_becomes_a_trigger(tmp_path) -> None:
    evidence = (
        surfer.FailureEvidence(
            instance_id="arm-a",
            text="provider error: exceeded your current quota",
            source="run_error",
            project_id="pid",
        ),
    )
    source = surfer.SurferStateSource(
        app_state=lambda: AppState(idle=True, projects=()),
        trial_log=StaticTrialLog([]),
        signals=surfer.CreditExhaustionReader(),
        evidence=lambda: evidence,
    )

    state = source.assert_state()

    assert [t.kind for t in state.triggers] == [surfer.FAILURE_SIGNAL]
    assert state.triggers[0].signal == surfer.CREDIT_EXHAUSTION
    assert state.triggers[0].instance_id == "arm-a"


def test_run_error_evidence_reads_a_failed_recon_job_error() -> None:
    """I9: the production reader surfaces the run's own error payload via REST."""
    record = {
        "instance_id": "arm-a",
        "target_id": "t1",
        "project_id": "pid",
        "phases": [{"phase": "recon", "status": "complete", "run_id": "r1"}],
    }

    class FakeApi:
        def __init__(self) -> None:
            self.paths: list[str] = []

        def __call__(self, call):
            self.paths.append(call.path)
            return {
                "per_job": [
                    {"job": "crawl", "status": "failed", "error": "boom"},
                    {"job": "content", "status": "complete", "error": None},
                ]
            }

    api_runner = FakeApi()
    reader = surfer.RunErrorEvidence(api_runner, StaticTrialLog([record]))

    evidence = reader()

    assert api_runner.paths == ["/projects/pid/recon/r1"]
    assert len(evidence) == 1
    assert evidence[0].text == "boom"
    assert evidence[0].source == "run_error"
    assert evidence[0].instance_id == "arm-a"


def test_a_live_run_error_credit_exhaustion_becomes_a_trigger() -> None:
    record = {
        "instance_id": "arm-a",
        "target_id": "t1",
        "project_id": "pid",
        "terminal": "complete",
        "phases": [{"phase": "recon", "status": "complete", "run_id": "r1"}],
    }

    class FakeApi:
        def __call__(self, call):
            return {
                "per_job": [
                    {
                        "job": "crawl",
                        "status": "failed",
                        "error": "litellm: insufficient_quota (billing hard limit)",
                    }
                ]
            }

    trial_log = StaticTrialLog([record])
    source = surfer.SurferStateSource(
        app_state=lambda: AppState(idle=True, projects=()),
        trial_log=trial_log,
        signals=surfer.CreditExhaustionReader(),
        evidence=surfer.RunErrorEvidence(FakeApi(), trial_log),
    )

    state = source.assert_state()

    assert [t.kind for t in state.triggers] == [surfer.FAILURE_SIGNAL]
    assert state.triggers[0].signal == surfer.CREDIT_EXHAUSTION


def test_run_error_evidence_skips_a_non_mapping_record() -> None:
    class ExplodingApi:
        def __call__(self, call):  # pragma: no cover - never reached
            raise AssertionError("no API call for a malformed record")

    reader = surfer.RunErrorEvidence(ExplodingApi(), StaticTrialLog(["oops"]))

    assert reader() == ()


def test_run_error_evidence_is_fail_soft_on_an_api_error() -> None:
    record = {
        "instance_id": "arm-a",
        "project_id": "pid",
        "phases": [{"phase": "recon", "status": "complete", "run_id": "r1"}],
    }

    class ExplodingApi:
        def __call__(self, call):
            raise trial.api.ApiError(call, 0, "connection refused")

    logs: list[dict] = []
    reader = surfer.RunErrorEvidence(
        ExplodingApi(), StaticTrialLog([record]), log=logs.append
    )

    assert reader() == ()
    assert any(r.get("event") == "run_error_evidence_failed" for r in logs)


def test_an_unrelated_error_is_not_a_credit_signal() -> None:
    reader = surfer.CreditExhaustionReader()

    assert reader.read(
        (
            surfer.FailureEvidence(
                instance_id="arm-a", text="connection refused", source="run_error"
            ),
        )
    ) == ()


def test_state_source_reports_the_app_state_idle_verdict() -> None:
    source = surfer.SurferStateSource(
        app_state=lambda: AppState(idle=False, projects=({"project_id": "pid"},)),
        trial_log=StaticTrialLog([]),
        signals=surfer.CreditExhaustionReader(),
        evidence=lambda: (),
    )

    state = source.assert_state()

    assert state.idle is False
    assert state.projects == ({"project_id": "pid"},)


class StaticTrialLog:
    def __init__(self, records) -> None:
        self._records = tuple(records)

    def records(self):
        return self._records


def test_file_trial_log_surfaces_an_invalid_record(tmp_path) -> None:
    # A corrupt record is skipped, never fatal, but it is named on the log seam
    # so the operator sees it rather than an unexplained missing trigger.
    good = tmp_path / "runs" / "comfyui" / "trial-1"
    good.mkdir(parents=True)
    (good / "trial.yaml").write_text("trial_id: trial-1\n", encoding="utf-8")
    broken = tmp_path / "runs" / "comfyui" / "trial-2"
    broken.mkdir(parents=True)
    (broken / "trial.yaml").write_text("trial_id: [unclosed\n", encoding="utf-8")
    non_mapping = tmp_path / "runs" / "comfyui" / "trial-3"
    non_mapping.mkdir(parents=True)
    (non_mapping / "trial.yaml").write_text("- just\n- a list\n", encoding="utf-8")

    logs: list[dict] = []
    log = surfer.FileTrialLog(tmp_path / "runs", log=logs.append)

    records = log.records()

    assert [r["trial_id"] for r in records] == ["trial-1"]
    invalid = [rec for rec in logs if rec.get("event") == "trial_record_invalid"]
    assert len(invalid) == 2
    assert {Path(rec["path"]).name for rec in invalid} == {"trial.yaml"}
    assert {Path(rec["path"]).parent.name for rec in invalid} == {"trial-2", "trial-3"}


def test_a_non_mapping_phase_entry_is_skipped_and_logged() -> None:
    """I3: `phases: [oops]` is a named invalid-record event, never a crash."""
    logs: list[dict] = []
    record = {
        "instance_id": "arm-a",
        "target_id": "t1",
        "project_id": "pid",
        "terminal": "failed",
        "phases": ["oops"],
    }
    source = surfer.SurferStateSource(
        app_state=lambda: AppState(idle=False, projects=()),
        trial_log=StaticTrialLog([record]),
        signals=surfer.CreditExhaustionReader(),
        evidence=lambda: (),
        log=logs.append,
    )

    state = source.assert_state()

    assert state.triggers == ()
    invalid = [r for r in logs if r.get("event") == "surfer_record_invalid"]
    assert len(invalid) == 1
    assert "phases[0]" in invalid[0]["error"]


def test_a_non_list_phases_value_is_skipped_and_logged() -> None:
    logs: list[dict] = []
    record = {"instance_id": "arm-b", "project_id": "pid", "phases": 7}
    source = surfer.SurferStateSource(
        app_state=lambda: AppState(idle=True, projects=()),
        trial_log=StaticTrialLog([record]),
        signals=surfer.CreditExhaustionReader(),
        evidence=lambda: (),
        log=logs.append,
    )

    assert source.assert_state().triggers == ()
    assert any(r.get("event") == "surfer_record_invalid" for r in logs)


def test_a_malformed_record_does_not_hide_a_valid_one() -> None:
    good = {
        "instance_id": "arm-a",
        "target_id": "t1",
        "project_id": "pid",
        "terminal": "stopped",
        "phases": [{"phase": "hunting", "status": "stopped", "run_id": "h1"}],
        "cap": 2,
        "stop_count": 2,
        "final_count": 3,
    }
    bad = {"instance_id": "arm-b", "project_id": "pid", "phases": [{"phase": "recon"}, "oops"]}
    logs: list[dict] = []
    source = surfer.SurferStateSource(
        app_state=lambda: AppState(idle=True, projects=()),
        trial_log=StaticTrialLog([bad, good]),
        signals=surfer.CreditExhaustionReader(),
        evidence=lambda: (),
        log=logs.append,
    )

    kinds = [trigger.kind for trigger in source.assert_state().triggers]

    assert kinds == [surfer.CAP_REACHED]
    assert any(r.get("event") == "surfer_record_invalid" for r in logs)


def test_the_phase_readers_tolerate_a_non_mapping_entry() -> None:
    # Every reader that walks `phases` is shape-guarded, not only the source.
    record = {"start_phase": "hunting", "phases": ["oops"]}

    assert surfer.failed_run_trigger(record) is None
    assert surfer.resume_phase(record) == "hunting"
    assert surfer.cap_triggers(record) == []
    assert surfer.trial_evidence([record]) == ()


def test_terminate_touches_no_command_runner_and_writes_no_hold(
    tmp_path, recording_runner
) -> None:
    runner = recording_runner()
    api_runner = FakeApi()
    state = alignment.AlignmentState(tmp_path / "alignment.yaml")
    asserter = StaticAsserter(state_with(failed_trigger(run_kind="hunting", run_id="h1")))
    decider = StaticDecider(surfer.SurferDecision(surfer.TERMINATE))

    outcome = make_surfer(
        asserter, decider, tmp_path=tmp_path, runner=runner, api_runner=api_runner,
        state=state,
    ).cycle()

    assert outcome.action == surfer.TERMINATE
    assert runner.calls == []
    assert state.holds() == ()


def test_fix_touches_no_api_runner_and_writes_no_hold(tmp_path) -> None:
    api_runner = FakeApi()
    state = alignment.AlignmentState(tmp_path / "alignment.yaml")
    asserter = StaticAsserter(state_with(failed_trigger()))
    decider = StaticDecider(surfer.SurferDecision(surfer.FIX, repair=surfer.REPAIR_ENV))
    kit = FakeRepairKit(supported=("env",))

    outcome = make_surfer(
        asserter, decider, tmp_path=tmp_path, api_runner=api_runner,
        repair_kit=kit, resumer=RecordingResumer(), state=state,
    ).cycle()

    assert outcome.action == surfer.FIX
    assert api_runner.calls == []
    assert state.holds() == ()


# --- the decisions ------------------------------------------------------------


def test_terminate_stops_the_named_runs_through_the_api(tmp_path) -> None:
    trigger = failed_trigger(run_kind="recon", run_id="r1")
    asserter = StaticAsserter(state_with(trigger))
    api_runner = FakeApi()
    decider = StaticDecider(surfer.SurferDecision(surfer.TERMINATE, reason="budget blown"))
    kit = FakeRepairKit()

    outcome = make_surfer(
        asserter, decider, tmp_path=tmp_path, api_runner=api_runner, repair_kit=kit
    ).cycle()

    assert outcome.action == surfer.TERMINATE
    assert outcome.escalated is False
    assert api_runner.paths == ["POST /projects/pid/recon/r1/stop"]
    assert kit.applied == []


def test_destroy_tears_the_instance_down_through_instances_down(
    tmp_path, recording_runner
) -> None:
    runner = recording_runner()
    trigger = failed_trigger()
    asserter = StaticAsserter(state_with(trigger))
    decider = StaticDecider(surfer.SurferDecision(surfer.DESTROY, reason="unrecoverable"))
    paths = make_paths(tmp_path, "arm-a")  # worktree exists, so compose down runs

    instance = surfer.Surfer(
        surfer.SurferConfig(),
        asserter=asserter,
        decider=decider,
        instances=(paths,),
        runner=runner,
        now=lambda: "2026-09-28T00:00:00+00:00",
    )
    outcome = instance.cycle()

    assert outcome.action == surfer.DESTROY
    assert any("down -v --remove-orphans" in t for t in runner.argv_texts)
    assert any("worktree" in t and "remove" in t for t in runner.argv_texts)


def test_fix_env_recreates_restarts_and_resumes_at_the_recorded_phase(tmp_path) -> None:
    trigger = failed_trigger(start_phase="hunting", project_id="pid", target_id="t1")
    asserter = StaticAsserter(state_with(trigger))
    decider = StaticDecider(surfer.SurferDecision(surfer.FIX, repair=surfer.REPAIR_ENV))
    kit = FakeRepairKit(supported=("env",))
    resumer = RecordingResumer()

    outcome = make_surfer(
        asserter, decider, tmp_path=tmp_path, repair_kit=kit, resumer=resumer
    ).cycle()

    assert outcome.action == surfer.FIX
    assert kit.applied == ["env"]
    assert kit.projects == ["pid"]
    assert kit.restarted == ["env"]
    assert len(resumer.plans) == 1
    plan = resumer.plans[0]
    assert plan.start_phase == "hunting"
    assert plan.project_id == "pid"
    assert plan.target_id == "t1"
    assert "surfer" in plan.intervention


def test_the_fabricated_lock_repair_is_not_a_bounded_repair(tmp_path) -> None:
    # `.execute.lock`/`.project.lease` exist nowhere in the pipeline (the app's
    # locks are in-process), so `clear_lock` was a fabricated repair. No repair
    # may claim it (CODING_STANDARD section 12).
    assert "clear_lock" not in surfer.REPAIR_KINDS

    trigger = failed_trigger()
    asserter = StaticAsserter(state_with(trigger))
    decider = StaticDecider(surfer.SurferDecision(surfer.FIX, repair="clear_lock"))
    state = alignment.AlignmentState(tmp_path / "alignment.yaml")
    resumer = RecordingResumer()

    outcome = make_surfer(
        asserter, decider, tmp_path=tmp_path, repair_kit=FakeRepairKit(),
        resumer=resumer, state=state,
    ).cycle()

    assert outcome.escalated is True
    assert outcome.hold is not None
    assert "clear_lock" in outcome.hold.rationale
    assert resumer.plans == []


def test_replace_artifacts_needs_preloaded_configuration(tmp_path) -> None:
    kit = surfer.SurferRepairKit(
        make_paths(tmp_path), runner=None, data_root=tmp_path / "data", preloaded=None
    )

    assert kit.supports(surfer.REPAIR_REPLACE_ARTIFACTS) is False


def test_replace_artifacts_replaces_the_premined_configs(tmp_path) -> None:
    source = tmp_path / "premined" / "c1.yaml"
    source.parent.mkdir(parents=True)
    source.write_text("id: c1\n", encoding="utf-8")
    preloaded = PreloadedArtifacts(configs=str(source))
    kit = surfer.SurferRepairKit(
        make_paths(tmp_path), runner=None, data_root=tmp_path / "data", preloaded=preloaded
    )

    assert kit.supports(surfer.REPAIR_REPLACE_ARTIFACTS) is True
    kit.apply(surfer.REPAIR_REPLACE_ARTIFACTS, project_id="pid")

    produced = hunt_configs_dir(tmp_path / "data", "pid", "produced")
    assert (produced / "c1.yaml").is_file()


# --- structural enforcement: no code change is ever applied -------------------


def test_a_code_change_repair_attempt_escalates_and_is_never_applied(tmp_path) -> None:
    trigger = failed_trigger()
    asserter = StaticAsserter(state_with(trigger))
    decider = StaticDecider(
        surfer.SurferDecision(surfer.FIX, repair="edit_source", reason="patch the bug")
    )
    kit = FakeRepairKit(supported=("env", "replace_artifacts"))
    resumer = RecordingResumer()
    state = alignment.AlignmentState(tmp_path / "alignment.yaml")

    outcome = make_surfer(
        asserter, decider, tmp_path=tmp_path, repair_kit=kit, resumer=resumer, state=state
    ).cycle()

    assert outcome.escalated is True
    assert outcome.hold is not None
    assert "edit_source" in outcome.hold.rationale
    assert kit.applied == []
    assert resumer.plans == []
    assert len(state.unresolved_holds()) == 1


def test_an_unsupported_repair_is_handled_once(tmp_path) -> None:
    # A repair outside the bounded set escalates structurally; that escalation
    # is recorded so the same trigger is not re-decided on the next cycle.
    state = alignment.AlignmentState(tmp_path / "alignment.yaml")
    asserter = StaticAsserter(state_with(failed_trigger()))
    decider = StaticDecider(
        surfer.SurferDecision(surfer.FIX, repair="edit_source", reason="patch the bug")
    )
    engine = make_surfer(
        asserter, decider, tmp_path=tmp_path, repair_kit=FakeRepairKit(), state=state
    )

    first = engine.cycle()
    second = engine.cycle()

    assert first.escalated is True
    assert second.no_op is True
    assert second.hold is None
    assert len(decider.requests) == 1
    assert len(state.unresolved_holds()) == 1
    handled = state.applied_for(surfer.HANDLED_SHA, surfer.HANDLED_FINGERPRINT)
    assert surfer.trigger_key(asserter.state.triggers[0]) in handled


def test_an_unknown_decision_kind_escalates(tmp_path) -> None:
    asserter = StaticAsserter(state_with(failed_trigger()))
    decider = StaticDecider(surfer.SurferDecision("patch_code", reason="rewrite the hunter"))
    state = alignment.AlignmentState(tmp_path / "alignment.yaml")

    outcome = make_surfer(asserter, decider, tmp_path=tmp_path, state=state).cycle()

    assert outcome.escalated is True
    assert outcome.hold is not None
    assert "patch_code" in outcome.hold.rationale
    assert len(state.unresolved_holds()) == 1


def test_an_unknown_decision_kind_is_handled_once(tmp_path) -> None:
    # The structural escalation is recorded like any other decision, so an
    # unchanged trigger does not re-prompt the decider every cycle.
    state = alignment.AlignmentState(tmp_path / "alignment.yaml")
    asserter = StaticAsserter(state_with(failed_trigger()))
    decider = StaticDecider(surfer.SurferDecision("patch_code", reason="rewrite the hunter"))
    engine = make_surfer(asserter, decider, tmp_path=tmp_path, state=state)

    first = engine.cycle()
    second = engine.cycle()

    assert first.escalated is True
    assert second.no_op is True
    assert second.hold is None
    assert len(decider.requests) == 1
    assert len(state.unresolved_holds()) == 1
    handled = state.applied_for(surfer.HANDLED_SHA, surfer.HANDLED_FINGERPRINT)
    assert surfer.trigger_key(asserter.state.triggers[0]) in handled


def test_a_supported_repair_the_kit_cannot_apply_escalates(tmp_path) -> None:
    asserter = StaticAsserter(state_with(failed_trigger()))
    decider = StaticDecider(surfer.SurferDecision(surfer.FIX, repair=surfer.REPAIR_ENV))
    kit = FakeRepairKit(supported=("replace_artifacts",))
    state = alignment.AlignmentState(tmp_path / "alignment.yaml")

    outcome = make_surfer(
        asserter, decider, tmp_path=tmp_path, repair_kit=kit, state=state
    ).cycle()

    assert outcome.escalated is True
    assert kit.applied == []


# --- escalation holds ---------------------------------------------------------


def test_escalate_writes_a_hold_that_blocks_new_trials(tmp_path) -> None:
    asserter = StaticAsserter(state_with(failed_trigger()))
    decider = StaticDecider(
        surfer.SurferDecision(surfer.ESCALATE, reason="operator must fund the account")
    )
    state = alignment.AlignmentState(tmp_path / "alignment.yaml")

    outcome = make_surfer(asserter, decider, tmp_path=tmp_path, state=state).cycle()

    assert outcome.escalated is True
    assert outcome.hold is not None
    assert "operator must fund the account" in outcome.hold.rationale
    with pytest.raises(alignment.AlignmentHoldError) as excinfo:
        state.require_no_holds()
    assert outcome.hold.hold_id in str(excinfo.value)


def test_rerunning_the_same_escalation_is_skipped_and_does_not_duplicate_the_hold(
    tmp_path,
) -> None:
    state = alignment.AlignmentState(tmp_path / "alignment.yaml")
    asserter = StaticAsserter(state_with(failed_trigger()))
    decider = StaticDecider(surfer.SurferDecision(surfer.ESCALATE, reason="same reason"))

    first = make_surfer(asserter, decider, tmp_path=tmp_path, state=state).cycle()
    second = make_surfer(asserter, decider, tmp_path=tmp_path, state=state).cycle()

    assert first.hold is not None
    assert second.no_op is True
    assert second.hold is None
    assert second.skipped  # the identity is reported as already handled
    assert len(decider.requests) == 1
    assert len(state.holds()) == 1
    assert state.holds()[0].hold_id == first.hold.hold_id


# --- cross-cycle idempotency (the handled-trigger record) ---------------------


def test_two_cycles_on_the_same_terminal_state_act_once(tmp_path) -> None:
    state = alignment.AlignmentState(tmp_path / "alignment.yaml")
    asserter = StaticAsserter(state_with(failed_trigger()))
    decider = StaticDecider(surfer.SurferDecision(surfer.FIX, repair=surfer.REPAIR_ENV))
    kit = FakeRepairKit(supported=("env",))
    resumer = RecordingResumer()
    engine = make_surfer(
        asserter, decider, tmp_path=tmp_path, repair_kit=kit, resumer=resumer, state=state
    )

    first = engine.cycle()
    second = engine.cycle()

    assert first.action == surfer.FIX
    assert second.no_op is True
    assert second.skipped == (surfer.trigger_key(asserter.state.triggers[0]),)
    assert len(decider.requests) == 1
    assert kit.applied == ["env"]
    assert len(resumer.plans) == 1


def test_a_second_distinct_trigger_is_handled_too(tmp_path) -> None:
    # Two real triggers on one state: a failed hunting run and a cap-reached
    # run. Both name a run, so `terminate` stops both; the second cycle is a
    # no-op because both identities were recorded.
    state = alignment.AlignmentState(tmp_path / "alignment.yaml")
    cap_record = {
        "instance_id": "arm-a",
        "target_id": "t1",
        "project_id": "pid",
        "terminal": "stopped",
        "start_phase": "hunting",
        "phases": [{"phase": "hunting", "status": "stopped", "run_id": "h2"}],
        "cap": 2,
        "stop_count": 2,
        "final_count": 3,
    }
    triggers = (failed_trigger(run_kind="hunting", run_id="h1"),) + tuple(
        surfer.cap_triggers(cap_record)
    )
    asserter = StaticAsserter(state_with(*triggers))
    decider = StaticDecider(surfer.SurferDecision(surfer.TERMINATE))
    api_runner = FakeApi()
    engine = make_surfer(
        asserter, decider, tmp_path=tmp_path, api_runner=api_runner, state=state
    )

    first = engine.cycle()
    second = engine.cycle()

    assert first.action == surfer.TERMINATE
    assert api_runner.paths == [
        "POST /projects/pid/hunting/h1/stop",
        "POST /projects/pid/hunting/h2/stop",
    ]
    assert second.no_op is True
    assert len(decider.requests) == 1
    handled = state.applied_for(surfer.HANDLED_SHA, surfer.HANDLED_FINGERPRINT)
    assert surfer.trigger_key(triggers[0]) in handled
    assert surfer.trigger_key(triggers[1]) in handled


def test_two_distinct_cap_events_are_two_identities() -> None:
    # Two cap events in the same instance/target/project must not collapse into
    # one identity: each names its own hunting run.
    first = surfer.cap_triggers(
        {
            "instance_id": "arm-a",
            "target_id": "t1",
            "project_id": "pid",
            "phases": [{"phase": "hunting", "status": "stopped", "run_id": "h1"}],
            "cap": 2,
            "stop_count": 2,
        }
    )[0]
    second = surfer.cap_triggers(
        {
            "instance_id": "arm-a",
            "target_id": "t1",
            "project_id": "pid",
            "phases": [{"phase": "hunting", "status": "stopped", "run_id": "h2"}],
            "cap": 2,
            "stop_count": 2,
        }
    )[0]

    assert first.run_id == "h1"
    assert second.run_id == "h2"
    assert surfer.trigger_key(first) != surfer.trigger_key(second)


def test_terminate_without_a_named_run_escalates(tmp_path) -> None:
    # A trigger that names no run cannot be stopped. `terminate` must not record
    # success; it escalates instead.
    state = alignment.AlignmentState(tmp_path / "alignment.yaml")
    signal = surfer.Trigger(
        kind=surfer.FAILURE_SIGNAL,
        instance_id="arm-a",
        detail="credits exhausted",
        target_id="t1",
        project_id="pid",
        signal=surfer.CREDIT_EXHAUSTION,
    )
    asserter = StaticAsserter(state_with(signal))
    decider = StaticDecider(surfer.SurferDecision(surfer.TERMINATE))
    api_runner = FakeApi()
    engine = make_surfer(
        asserter, decider, tmp_path=tmp_path, api_runner=api_runner, state=state
    )

    outcome = engine.cycle()

    assert outcome.escalated is True
    assert outcome.action == surfer.ESCALATE
    assert outcome.hold is not None
    assert "no run" in outcome.detail
    assert api_runner.calls == []


def test_a_new_distinct_record_is_a_new_identity_and_acts(tmp_path) -> None:
    state = alignment.AlignmentState(tmp_path / "alignment.yaml")
    kit = FakeRepairKit(supported=("env",))
    resumer = RecordingResumer()
    decider = StaticDecider(surfer.SurferDecision(surfer.FIX, repair=surfer.REPAIR_ENV))
    asserter = StaticAsserter(state_with(failed_trigger(run_id="h1")))
    engine = make_surfer(
        asserter, decider, tmp_path=tmp_path, repair_kit=kit, resumer=resumer, state=state
    )

    engine.cycle()
    asserter.state = state_with(failed_trigger(run_id="h2"))  # a new failure event
    second = engine.cycle()

    assert second.action == surfer.FIX
    assert len(decider.requests) == 2
    assert len(resumer.plans) == 2


def test_the_handled_marker_survives_a_loop_restart(tmp_path) -> None:
    state_path = tmp_path / "alignment.yaml"
    kit = FakeRepairKit(supported=("env",))
    decider = StaticDecider(surfer.SurferDecision(surfer.FIX, repair=surfer.REPAIR_ENV))

    first = make_surfer(
        StaticAsserter(state_with(failed_trigger())),
        decider,
        tmp_path=tmp_path,
        repair_kit=kit,
        resumer=RecordingResumer(),
        state=alignment.AlignmentState(state_path),
    ).cycle()
    assert first.action == surfer.FIX

    # A fresh loop over the same state file (a restart) sees the marker.
    restarted = make_surfer(
        StaticAsserter(state_with(failed_trigger())),
        StaticDecider(surfer.SurferDecision(surfer.FIX, repair=surfer.REPAIR_ENV)),
        tmp_path=tmp_path,
        repair_kit=kit,
        resumer=RecordingResumer(),
        state=alignment.AlignmentState(state_path),
    )
    assert restarted.cycle().no_op is True


def test_alignment_resolve_rearms_the_trigger_and_it_re_escalates(tmp_path) -> None:
    """I7: resolving a surfer hold re-arms its triggers for the next cycle."""
    state = alignment.AlignmentState(tmp_path / "alignment.yaml")
    asserter = StaticAsserter(state_with(failed_trigger()))
    decider = StaticDecider(
        surfer.SurferDecision(surfer.ESCALATE, reason="fund the account")
    )
    engine = make_surfer(asserter, decider, tmp_path=tmp_path, state=state)

    first = engine.cycle()
    assert first.hold is not None
    assert state.applied_for(surfer.HANDLED_SHA, surfer.HANDLED_FINGERPRINT)

    state.resolve_hold(first.hold.hold_id, "operator funded the account")

    # Resolving clears the handled markers recorded under the hold's triggers.
    assert (
        state.applied_for(surfer.HANDLED_SHA, surfer.HANDLED_FINGERPRINT) == frozenset()
    )

    after = make_surfer(asserter, decider, tmp_path=tmp_path, state=state).cycle()

    # The condition persists, so the re-armed trigger re-escalates.
    assert after.escalated is True
    assert after.hold is not None
    assert after.hold.resolved is False
    assert len(decider.requests) == 2
    assert len(state.holds()) == 1
    assert len(state.unresolved_holds()) == 1
    # The operator's resolution context is recorded on the re-opened hold.
    assert any(
        entry.get("decision") == "operator funded the account"
        for entry in after.hold.history
    )


def test_act_once_is_kept_for_an_unresolved_trigger(tmp_path) -> None:
    state = alignment.AlignmentState(tmp_path / "alignment.yaml")
    asserter = StaticAsserter(state_with(failed_trigger()))
    decider = StaticDecider(
        surfer.SurferDecision(surfer.ESCALATE, reason="fund the account")
    )
    engine = make_surfer(asserter, decider, tmp_path=tmp_path, state=state)

    first = engine.cycle()
    second = engine.cycle()  # no resolve -> the marker still disarms it

    assert first.escalated is True
    assert second.no_op is True
    assert len(decider.requests) == 1


def test_a_skipped_trigger_is_logged(tmp_path) -> None:
    state = alignment.AlignmentState(tmp_path / "alignment.yaml")
    logs: list[dict] = []
    asserter = StaticAsserter(state_with(failed_trigger()))
    decider = StaticDecider(surfer.SurferDecision(surfer.TERMINATE))
    engine = make_surfer(
        asserter, decider, tmp_path=tmp_path, api_runner=FakeApi(), state=state,
        log=logs.append,
    )

    engine.cycle()
    engine.cycle()

    assert any(record.get("event") == "surfer_skip" for record in logs)


# --- dry-run, --once, interval ------------------------------------------------


def test_dry_run_asserts_but_never_dispatches_the_decider_and_mutates_nothing(
    tmp_path, recording_runner
) -> None:
    runner = recording_runner()
    api_runner = FakeApi()
    resumer = RecordingResumer()
    kit = FakeRepairKit()
    state = alignment.AlignmentState(tmp_path / "alignment.yaml")
    asserter = StaticAsserter(state_with(failed_trigger()))

    outcome = make_surfer(
        asserter,
        ExplodingDecider(),
        tmp_path=tmp_path,
        state=state,
        runner=runner,
        api_runner=api_runner,
        repair_kit=kit,
        resumer=resumer,
        dry_run=True,
    ).cycle()

    assert outcome.planned is True
    assert outcome.dry_run is True
    assert outcome.decision is None
    assert runner.calls == []
    assert api_runner.calls == []
    assert resumer.plans == []
    assert kit.applied == []
    assert state.holds() == ()
    # A dry-run never records a handled marker either.
    assert state.applied_for(surfer.HANDLED_SHA, surfer.HANDLED_FINGERPRINT) == frozenset()


def test_once_runs_exactly_one_cycle(tmp_path) -> None:
    asserter = StaticAsserter(state_with(idle=True))
    decider = StaticDecider(surfer.SurferDecision(surfer.ESCALATE))
    instance = make_surfer(asserter, decider, tmp_path=tmp_path)

    outcomes = instance.run(once=True)

    assert len(outcomes) == 1
    assert asserter.calls == 1


def test_the_loop_sleeps_for_the_configured_interval(tmp_path) -> None:
    sleeps: list[float] = []
    asserter = StaticAsserter(state_with(idle=True))
    decider = StaticDecider(surfer.SurferDecision(surfer.ESCALATE))
    instance = make_surfer(
        asserter,
        decider,
        tmp_path=tmp_path,
        config=surfer.SurferConfig(interval_s=7.0, max_cycles=3),
        sleep=sleeps.append,
    )

    outcomes = instance.run()

    assert len(outcomes) == 3
    assert sleeps == [7.0, 7.0]


# --- resume phase derivation --------------------------------------------------


@pytest.mark.parametrize(
    "record,expected",
    [
        (
            {
                "start_phase": "hunting",
                "phases": [
                    {"phase": "recon", "status": "complete"},
                    {"phase": "hunting", "status": "stopped", "run_id": "h1"},
                ],
            },
            "hunting",
        ),
        (
            {
                "start_phase": "recon",
                "phases": [{"phase": "recon", "status": "failed", "run_id": "r1"}],
            },
            "recon",
        ),
        (
            {
                "start_phase": "analysis",
                "phases": [
                    {"phase": "recon", "status": "complete"},
                    {"phase": "analysis", "status": "interrupted", "run_id": "a1"},
                ],
            },
            "analysis",
        ),
        (
            {
                "start_phase": "hunting",
                "phases": [
                    {"phase": "recon", "status": "complete"},
                    {"phase": "hunting", "status": "complete"},
                ],
            },
            "hunting",
        ),
    ],
)
def test_resume_phase_uses_the_recorded_phase(record, expected) -> None:
    assert surfer.resume_phase(record) == expected


# --- the decider seam ---------------------------------------------------------


def test_load_decision_parses_a_fix_and_requires_a_repair(tmp_path) -> None:
    files = FileStore()
    good = tmp_path / "good.yaml"
    good.write_text("decision: fix\nrepair: env\nreason: stale key\n", encoding="utf-8")
    decision = surfer.load_decision(good, files=files)
    assert decision.kind == surfer.FIX
    assert decision.repair == surfer.REPAIR_ENV

    bad = tmp_path / "bad.yaml"
    bad.write_text("decision: fix\n", encoding="utf-8")
    with pytest.raises(surfer.SurferError, match="repair"):
        surfer.load_decision(bad, files=files)


def test_load_decision_parses_terminate_and_escalate(tmp_path) -> None:
    files = FileStore()
    path = tmp_path / "d.yaml"
    path.write_text("decision: terminate\n", encoding="utf-8")
    assert surfer.load_decision(path, files=files).kind == surfer.TERMINATE

    path.write_text("decision: escalate\nreason: no way forward\n", encoding="utf-8")
    decision = surfer.load_decision(path, files=files)
    assert decision.kind == surfer.ESCALATE
    assert decision.reason == "no way forward"


def test_subagent_decider_writes_the_input_dispatches_and_reads_the_decision(
    tmp_path, recording_runner
) -> None:
    files = FileStore()
    runner = recording_runner()
    request = surfer.SurferRequest(
        prompt=Path("surfer.md"),
        input_file=tmp_path / "input.yaml",
        destination=tmp_path / "decision.yaml",
        state={"triggers": []},
        repairs=surfer.REPAIR_KINDS,
        environment={"instances": []},
    )
    files.write_text(request.destination, "decision: destroy\nreason: dead\n")

    decider = surfer.SubagentSurferDecider(
        runner, ("python3", "agent.py", "{input}", "{destination}"), files=files
    )
    decision = decider.decide(request)

    assert decision.kind == surfer.DESTROY
    assert request.input_file.is_file()
    assert "repairs" in files.read_text(request.input_file)
    assert runner.argv_texts[0].endswith(f"{request.input_file} {request.destination}")


# --- the trial engine records the surfer intervention -------------------------


class _TrialApi:
    """The minimal hunting-terminal route map the resume record test needs."""

    def __call__(self, call):
        key = f"{call.method} {call.path}"
        return {
            "GET /projects/pid/hunting/h1": {"status": "complete"},
            "POST /projects/pid/hunting": {"hunting_run_id": "h1"},
            "GET /projects/pid/graph": {"nodes": [{"type": "L1Service"}], "links": []},
        }[key]


def test_a_transport_failure_record_is_visible_to_the_surfer(tmp_path) -> None:
    """I2: the failed record an API transport error writes is a surfer trigger."""
    calls: list = []

    class ExplodingApi:
        def __call__(self, call):
            calls.append(call)
            raise trial.api.ApiError(call, 0, "connection refused")

    cfg = trial.TrialConfig(
        instance_id="arm-a",
        target_id="t1",
        start_phase="hunting",
        project_id="pid",
        data_root=tmp_path / "data",
        runs_root=tmp_path / "runs",
    )
    trial.Trial(cfg, api_runner=ExplodingApi()).run()

    source = surfer.SurferStateSource(
        app_state=lambda: AppState(idle=False, projects=()),
        trial_log=surfer.FileTrialLog(tmp_path / "runs"),
        signals=surfer.CreditExhaustionReader(),
        evidence=lambda: (),
    )

    state = source.assert_state()

    assert any(t.kind == surfer.FAILED_RUN for t in state.triggers)
    failed = next(t for t in state.triggers if t.kind == surfer.FAILED_RUN)
    assert failed.instance_id == "arm-a"
    assert "connection refused" in failed.detail


def test_a_resumed_trial_records_the_surfer_intervention(tmp_path) -> None:
    cfg = trial.TrialConfig(
        instance_id="arm-a",
        target_id="t1",
        start_phase="hunting",
        project_id="pid",
        data_root=tmp_path / "data",
        runs_root=tmp_path / "runs",
        intervention="surfer: resumed at hunting after fix env",
    )
    record = trial.Trial(cfg, api_runner=_TrialApi()).run()

    assert any("surfer: resumed at hunting" in note for note in record.notes)
    written = FileStore().read_text(Path(record.trial_dir) / "trial.yaml")
    assert "surfer: resumed at hunting" in written
