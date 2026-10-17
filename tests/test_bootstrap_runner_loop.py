"""Unit tier: the external-bootstrap runner, part 5 - the orchestration loop.

This is THE high seam of the module (the architecture doc, section 3.1): the
loop is driven with a scripted fake harness, a recording fake environment, a
scripted fake gate, and a temp run directory. The tests assert external
behaviour only - the order of phases, that no phase advances on a red gate, that
repair is bounded, that teardown is verified by observation, that one bad target
does not lose the others, and that a crashed run resumes at its first incomplete
phase.

No network, no model, no docker, no ssh.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _on_path(rel: str) -> None:
    path = str(REPO_ROOT / rel)
    if path not in sys.path:
        sys.path.insert(0, path)


_on_path("tools/bootstrap")
_on_path("eval")
_on_path("src")

from orchestrator.commands import Command, CommandResult  # noqa: E402

from runner import state as state_mod  # noqa: E402
from runner.config import ReadinessPolicy  # noqa: E402
from runner.env import ContainerFact, Observation  # noqa: E402
from runner.gates import AUTH_ONLY, FULL, GateResult  # noqa: E402
from runner.harness import (  # noqa: E402
    HarnessError,
    ModelRef,
    TurnResult,
    TurnTimeout,
    is_retryable,
)
from runner.orchestrator import (  # noqa: E402
    Dispatch,
    Orchestrator,
    build_instructions,
    ready_to_work,
    rewrite_base_url,
)
from runner.wrappers import WrapperFacts, WrapperSources  # noqa: E402

# --- fakes ------------------------------------------------------------------

PROMPT_TEXT = "PROMPT BODY\n"
CONTRACT_TEXT = "CONTRACT BODY\n"
META_TEXT = "META BODY\n"


def _facts(target="shop"):
    return WrapperFacts(
        target=target,
        base_url="http://203.0.113.9:48287/",
        web_root="/root/WebExploitBench",
        worktree="/wt",
        staging="/wt/eval/data-dependencies",
        target_dir=f"/wt/eval/data/webexploitbench/{target}",
        lifecycle_hint=("/root/wb ps shop",),
        path_semantics="Every path is local to this machine.",
    )


def _sources(mode="auth_only"):
    invocation = (
        "PYTHONPATH=src python3 tools/bootstrap/validate_data_dependencies.py "
        f"{'--auth-only' if mode == AUTH_ONLY else ''} "
        "--staging /wt/eval/data-dependencies shop".replace("  ", " ")
    )
    return WrapperSources(
        prompt_path="tools/bootstrap/prompts/data-dep-authn.md",
        prompt_text=PROMPT_TEXT,
        contract_path="tools/bootstrap/DATA-DEPENDENCIES.md",
        contract_text=CONTRACT_TEXT,
        meta_skill_path="skills/meta/authn-skill-writing/SKILL.md",
        meta_skill_text=META_TEXT,
        validator_path="tools/bootstrap/validate_data_dependencies.py",
        validator_invocation=invocation,
    )


class FakeHarness:
    """A scripted harness: records the wrappers, answers with canned turns."""

    def __init__(self) -> None:
        self.created: list = []
        self.prompts: list[tuple[str, str]] = []
        self.interrupts: list[str] = []
        self.turns: list[object] = []
        self.missing: set[str] = set()
        # Sessions whose create fails retryably N more times (a flaky transport).
        self.flaky: dict[str, int] = {}

    def create_session(self, spec) -> str:
        self.created.append(spec)
        if spec.session_id in self.missing:
            raise HarnessError(f"session {spec.session_id} is gone")
        remaining = self.flaky.get(spec.session_id, 0)
        if remaining:
            self.flaky[spec.session_id] = remaining - 1
            raise HarnessError("connection reset while creating the session", retryable=True)
        return spec.session_id

    def prompt(self, session_id: str, text: str) -> str:
        self.prompts.append((session_id, text))
        return str(len(self.prompts))

    def wait_terminal(self, session_id: str, timeout_s: float) -> TurnResult:
        answer = self.turns.pop(0) if self.turns else _turn(session_id, "succeeded")
        if isinstance(answer, Exception):
            raise answer
        return answer

    def interrupt(self, session_id: str) -> CommandResult:
        self.interrupts.append(session_id)
        return CommandResult(0, "", "")


def _turn(session_id="ses_bt_r1_shop_creator", outcome="succeeded", error=""):
    return TurnResult(
        session_id=session_id,
        outcome=outcome,
        ok=outcome == "succeeded" and not error,
        # Same classification the real harness applies to a turn's error text.
        retryable=is_retryable(error) if error else False,
        error=error,
        model={"id": "deepseek-v4.1-flash-free", "providerID": "opencode", "variant": "high"},
        messages=(
            {"id": "m1", "type": "assistant", "content": [{"text": "done"}]},
            {"id": "m2", "type": "idle", "outcome": outcome},
        ),
    )


def _fact(state="running", health="healthy", exit_code=0, service="app", target="shop"):
    return ContainerFact(
        name=f"web_{target}-{service}-1",
        service=service,
        state=state,
        health=health,
        exit_code=exit_code,
    )


class FakeEnv:
    """A recording environment: canned observations, and every command logged.

    With no scripted observations the fake simulates one deployment: the target
    is cold until `up`, ready while it is up, and cold again after `down` (so the
    teardown observation reports zero containers, as a clean teardown must).
    """

    def __init__(self, observations=None, *, containers: bool = True) -> None:
        self.observations = list(observations or [])
        self.commands: list[tuple[str, str]] = []
        self._containers = containers
        self._deployed = False

    def _next(self, target: str) -> Observation:
        if self.observations:
            return self.observations.pop(0)
        if not self._deployed:
            return Observation(target=target, containers=(), url=None, http_status="000")
        return Observation(
            target=target,
            containers=(_fact(target=target),),
            url="http://203.0.113.9:48287/",
            http_status="200",
        )

    def up(self, target: str) -> CommandResult:
        self.commands.append(("up", target))
        self._deployed = True
        return CommandResult(0, "UI: http://0.0.0.0:48287/\n", "")

    def down(self, target: str) -> CommandResult:
        self.commands.append(("down", target))
        self._deployed = False
        return CommandResult(0, "", "")

    def observe(self, target: str) -> Observation:
        self.commands.append(("observe", target))
        return self._next(target)

    def supported_containers(self) -> bool:
        return self._containers


class ScriptedGate:
    """A gate whose every answer is scripted; returns the verbatim failure text."""

    def __init__(self, script=None) -> None:
        self.script = list(script or [])
        self.calls: list[tuple[str, str]] = []

    def run(self, target: str, mode: str) -> GateResult:
        self.calls.append((target, mode))
        answer = self.script.pop(0) if self.script else True
        if isinstance(answer, tuple):
            ok, output = answer
        else:
            ok, output = bool(answer), ("OK" if answer else "FAIL")
        return GateResult(
            ok=ok,
            output=output,
            command=("python3", "validate_data_dependencies.py", "--staging", "/staging", target),
            mode=mode,
        )


class Logs:
    def __init__(self) -> None:
        self.written: list[Path] = []

    def __call__(self, path: Path, text: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        self.written.append(path)
        return path


def _orchestrator(
    tmp_path,
    *,
    targets=("shop",),
    gate=None,
    env=None,
    harness=None,
    instructions=None,
    **overrides,
):
    run = overrides.pop("run", None)
    config = _config(tmp_path, targets=targets, **overrides)
    if run is not None:
        config = _config(tmp_path, targets=targets, run_overrides=run)
    harness = harness or FakeHarness()
    env = env or FakeEnv()
    gate = gate or ScriptedGate()
    logs = Logs()
    state = state_mod.new_state(
        config.run.id, config_digest=config.digest, targets=config.run.targets
    )
    orch = Orchestrator(
        config=config,
        harness=harness,
        env=env,
        gate=gate,
        state=state,
        rundir=tmp_path / "rundir",
        instructions=(
            instructions
            if instructions is not None
            else {
                "authn": Dispatch(text="AUTHN WRAPPER"),
                "l1": Dispatch(text="L1 WRAPPER"),
            }
        ),
        write_log=logs,
        sleep=lambda _s: None,
    )
    return orch, harness, env, gate, state, logs


def _config(tmp_path, *, targets=("shop",), run_overrides=None):
    from runner.config import EnvironmentSection, PathsSection, RunConfig, RunSection

    overrides = dict(run_overrides or {})
    return RunConfig(
        run=RunSection(
            id="r1",
            worktree=tmp_path,
            targets=tuple(targets),
            **overrides,
        ),
        environment=EnvironmentSection(
            driver="ssh",
            ssh="srv",
            web_root="/root/WebExploitBench",
            public_host="203.0.113.9",
        ),
        paths=PathsSection(
            kbs=tmp_path / "kbs",
            staging=tmp_path / "staging",
            prompts=tmp_path / "prompts",
            contract=tmp_path / "contract.md",
            meta_skill=tmp_path / "meta.md",
            validator=tmp_path / "validator.py",
            authn_prompt=tmp_path / "prompts" / "data-dep-authn.md",
            l1_prompt=tmp_path / "prompts" / "data-dep-l1.md",
        ),
        source_dir=tmp_path / "run.yaml",
    )


# --- pure helpers -----------------------------------------------------------


def test_rewrite_base_url_swaps_only_the_placeholder_host():
    assert (
        rewrite_base_url("http://0.0.0.0:48287/", public_host="203.0.113.9")
        == "http://203.0.113.9:48287/"
    )
    assert (
        rewrite_base_url("http://127.0.0.1:8080/", public_host="203.0.113.9")
        == "http://203.0.113.9:8080/"
    )
    # A real host is left alone; the URL's path is preserved.
    assert (
        rewrite_base_url("http://198.51.100.4:80/webtools/", public_host="203.0.113.9")
        == "http://198.51.100.4:80/webtools/"
    )
    assert rewrite_base_url("http://0.0.0.0:1/", public_host="") == "http://0.0.0.0:1/"


def test_ready_to_work_reports_none_only_when_every_signal_agrees():
    ready = Observation(
        target="shop", containers=(_fact(),), url="http://x/", http_status="200"
    )
    assert ready_to_work(ready) is None
    assert ready_to_work(Observation("shop", (), "http://x/", "200")) is not None


def test_build_instructions_uses_the_wrapper_builders():
    instructions = build_instructions(
        _config(Path("/tmp"), targets=("shop",)),
        facts_for=_facts,
        sources_for=lambda mode: _sources(mode),
        validator_invocation=lambda target, mode: f"validate --staging /s {target}" + (
            " --auth-only" if mode == AUTH_ONLY else ""
        ),
    )
    assert "AUTHN" not in instructions["authn"].text
    assert "authentication bootstrapper" in instructions["authn"].text
    assert "L1-surface producer" in instructions["l1"].text
    assert "validate --staging /s shop --auth-only" in instructions["authn"].text
    assert "/root/WebExploitBench/shop/vulnerability/" in instructions["l1"].text


# --- the loop: order --------------------------------------------------------


def test_one_target_runs_observe_up_dispatch_gate_dispatch_gate_down(tmp_path):
    orch, harness, env, gate, state, _ = _orchestrator(tmp_path)
    summary = orch.run_plan()
    assert summary.failed == ()
    assert summary.completed == ("shop",)
    kinds = [kind for kind, _target in env.commands]
    assert kinds[0] == "observe"
    assert "up" in kinds
    assert kinds[-1] == "observe"
    assert kinds.count("down") == 1
    # The gate order proves the phases are gated before advancing.
    assert gate.calls == [("shop", AUTH_ONLY), ("shop", FULL)]
    assert state.first_incomplete_phase("shop") is None
    assert state.target("shop").status == state_mod.DONE
    assert state.target("shop").lifecycle.verified_teardown is True


def test_the_two_phases_run_in_one_session_and_in_order(tmp_path):
    orch, harness, _env, _gate, _state, _ = _orchestrator(tmp_path)
    orch.run_plan()
    assert [(session, text) for session, text in harness.prompts] == [
        ("ses_bt_r1_shop_creator", "AUTHN WRAPPER"),
        ("ses_bt_r1_shop_creator", "L1 WRAPPER"),
    ]
    assert [spec.session_id for spec in harness.created] == ["ses_bt_r1_shop_creator"]
    assert harness.created[0].agent == "data-dep-worker"


def test_a_callable_instructions_source_resolves_per_target_at_dispatch(tmp_path):
    """The CLI's production shape: a target's wrappers are built when dispatched.

    The base URL is a fact only the environment reports, so the CLI hands the
    orchestrator a callable keyed by target; the orchestrator resolves it per
    dispatch, and memoisation is the caller's business. The assertion is on what
    the harness actually received, not on how often the callable ran.
    """

    def instructions_for(target: str):
        return {
            "authn": Dispatch(text=f"AUTHN {target}"),
            "l1": Dispatch(text=f"L1 {target}"),
        }

    orch, harness, _env, _gate, state, _ = _orchestrator(
        tmp_path, targets=("a", "b"), instructions=instructions_for
    )
    summary = orch.run_plan()
    assert summary.completed == ("a", "b")
    # Each target's own wrappers reached that target's session, in phase order.
    assert [text for _session, text in harness.prompts] == [
        "AUTHN a",
        "L1 a",
        "AUTHN b",
        "L1 b",
    ]
    assert [session for session, _text in harness.prompts] == [
        "ses_bt_r1_a_creator",
        "ses_bt_r1_a_creator",
        "ses_bt_r1_b_creator",
        "ses_bt_r1_b_creator",
    ]
    assert state.target("a").status == state_mod.DONE
    assert state.target("b").status == state_mod.DONE


def test_targets_run_serially_up_down_up_down(tmp_path):
    orch, harness, env, _gate, _state, _ = _orchestrator(tmp_path, targets=("a", "b"))
    orch.run_plan()
    lifecycle = [(kind, target) for kind, target in env.commands if kind in {"up", "down"}]
    assert lifecycle == [("up", "a"), ("down", "a"), ("up", "b"), ("down", "b")]
    assert [spec.session_id for spec in harness.created] == [
        "ses_bt_r1_a_creator",
        "ses_bt_r1_b_creator",
    ]


def test_a_ready_target_is_reused_instead_of_redeployed(tmp_path):
    env = FakeEnv(
        observations=[
            Observation("shop", (_fact(),), "http://203.0.113.9:1/", "200"),
            Observation("shop", (), None, "000"),
        ]
    )
    orch, _harness, env, _gate, _state, _ = _orchestrator(tmp_path, env=env)
    orch.run_plan()
    assert ("up", "shop") not in env.commands
    assert ("down", "shop") in env.commands


def test_a_cold_target_is_deployed_and_waited_for(tmp_path):
    cold = Observation("shop", (), None, "000")
    warm = Observation("shop", (_fact(),), "http://0.0.0.0:48287/", "200")
    env = FakeEnv(observations=[cold, cold, warm, Observation("shop", (), None, "000")])
    orch, _harness, env, _gate, state, _ = _orchestrator(tmp_path, env=env)
    orch.run_plan()
    kinds = [kind for kind, _ in env.commands]
    assert kinds.count("observe") == 4
    assert ("up", "shop") in env.commands
    assert state.target("shop").base_url == "http://203.0.113.9:48287/"


def test_a_known_permanent_5xx_is_accepted_only_when_the_policy_relaxes_it(tmp_path):
    """The eval-server prestashop case: containers up, the probed route 500s.

    The default rule refuses that target; the per-target relaxation accepts it
    and the run state records the raw status, so the decision is evidence.
    """
    from runner.config import ReadinessPolicy

    five_hundred = Observation("shop", (_fact(),), "http://203.0.113.9:1/", "500")
    env = FakeEnv(
        observations=[
            five_hundred,  # the reuse observation
            Observation("shop", (), None, "000"),  # teardown, clean
        ]
    )
    relaxed = ReadinessPolicy(per_target_require_http={"shop": False})
    orch, _h, _e, _g, state, _l = _orchestrator(
        tmp_path, env=env, run={"readiness": relaxed}
    )
    orch.run_plan()
    assert ("up", "shop") not in env.commands
    assert state.target("shop").base_url == "http://203.0.113.9:1/"
    assert any("http 500" in note for note in state.target("shop").notes)


def test_a_permanent_5xx_fails_the_target_under_the_default_rule(tmp_path):
    from runner.config import ReadinessPolicy

    five_hundred = Observation("shop", (_fact(),), "http://203.0.113.9:1/", "500")
    env = FakeEnv(
        observations=[
            five_hundred,  # the reuse observation
            five_hundred,  # readiness wait, attempt 1
            five_hundred,  # readiness wait, attempt 2
            Observation("shop", (), None, "000"),  # teardown, clean
        ]
    )
    strict = ReadinessPolicy(retries=2, interval_s=0.0)
    orch, _h, _e, _g, state, _l = _orchestrator(
        tmp_path, env=env, run={"readiness": strict}
    )
    orch.run_plan()
    assert state.target("shop").status == "failed"
    assert any("never ready" in note and "http 500" in note for note in state.target("shop").notes)


# --- gating and bounded repair ---------------------------------------------


def test_a_red_auth_gate_repairs_verbatim_then_advances(tmp_path):
    gate = ScriptedGate(
        [
            (
                False,
                "FAIL eval/data/webexploitbench/shop\n"
                "  [auth] credentials.yaml: accounts must be a mapping",
            ),
            True,
            True,
        ]
    )
    orch, harness, _env, gate, state, logs = _orchestrator(tmp_path, gate=gate)
    orch.run_plan()
    assert gate.calls == [("shop", AUTH_ONLY), ("shop", AUTH_ONLY), ("shop", FULL)]
    repair_text = harness.prompts[1][1]
    assert "credentials.yaml: accounts must be a mapping" in repair_text
    assert "[auth]" in repair_text
    # The L1 wrapper is the third prompt: authn, repair, then l1.
    assert harness.prompts[2][1] == "L1 WRAPPER"
    assert state.target("shop").phase("authn").repairs == 1
    assert any("01-dispatch" in p.name for p in logs.written)
    assert any("02-repair" in p.name for p in logs.written)


def test_a_permanently_red_gate_fails_the_target_after_the_repair_budget(tmp_path):
    gate = ScriptedGate([(False, "FAIL shop\n  [overview] bad")] * 10)
    orch, harness, env, gate, state, _ = _orchestrator(
        tmp_path, gate=gate, run={"repair_attempts": 2}
    )
    summary = orch.run_plan()
    assert summary.failed == ("shop",)
    assert summary.completed == ()
    assert len(gate.calls) == 3  # one dispatch plus the two bounded repairs
    assert len(harness.prompts) == 3
    assert all(call[1] == AUTH_ONLY for call in gate.calls)
    record = state.target("shop")
    assert record.status == state_mod.FAILED
    assert record.phase("authn").gate == state_mod.FAILED
    assert record.phase("authn").repairs == 2
    # The failure still tears the target down.
    assert ("down", "shop") in env.commands


def test_a_red_l1_gate_does_not_replay_the_green_authn_phase(tmp_path):
    gate = ScriptedGate([True, (False, "FAIL shop\n  [l1_surface] units empty"), True])
    orch, harness, _env, gate, state, _ = _orchestrator(tmp_path, gate=gate)
    orch.run_plan()
    assert gate.calls == [("shop", AUTH_ONLY), ("shop", FULL), ("shop", FULL)]
    assert harness.prompts[0][1] == "AUTHN WRAPPER"
    assert harness.prompts[1][1] == "L1 WRAPPER"
    assert "units empty" in harness.prompts[2][1]
    assert state.target("shop").phase("authn").repairs == 0
    assert state.target("shop").phase("l1").repairs == 1


def test_the_gate_never_runs_after_a_permanently_red_read(tmp_path):
    harness = FakeHarness()
    harness.turns = [_turn(outcome="failed", error="worker said no")] * 5
    gate = ScriptedGate()
    orch, _h, _env, gate, state, _ = _orchestrator(tmp_path, harness=harness, gate=gate)
    summary = orch.run_plan()
    assert summary.failed == ("shop",)
    assert gate.calls == []
    assert state.target("shop").phase("authn").read == state_mod.FAILED


# --- provider failure policy ------------------------------------------------


def test_a_retryable_provider_failure_is_retried_then_succeeds(tmp_path):
    harness = FakeHarness()
    harness.turns = [
        _turn(outcome="failed", error="FreeTierError 403"),
        _turn(outcome="succeeded"),
        _turn(outcome="succeeded"),
    ]
    sleeps: list[float] = []
    orch, harness, _env, _gate, state, _ = _orchestrator(tmp_path, harness=harness)
    orch.sleep = sleeps.append
    summary = orch.run_plan()
    assert summary.failed == ()
    assert sleeps == [60.0]
    assert len(harness.prompts) == 3
    assert state.target("shop").phase("authn").turns == 2


def test_the_provider_backoff_ladder_is_bounded_by_the_config(tmp_path):
    harness = FakeHarness()
    harness.turns = [_turn(outcome="failed", error="429 rate limit")] * 6
    sleeps: list[float] = []
    orch, _h, _env, gate, state, _ = _orchestrator(tmp_path, harness=harness)
    orch.sleep = sleeps.append
    summary = orch.run_plan()
    assert summary.failed == ("shop",)
    assert sleeps == [60.0, 300.0]
    assert gate.calls == []
    assert state.target("shop").phase("authn").read == state_mod.FAILED


def test_a_hard_provider_failure_is_not_retried(tmp_path):
    harness = FakeHarness()
    harness.turns = [_turn(outcome="failed", error="session not found")] * 3
    sleeps: list[float] = []
    orch, _h, _env, gate, state, _ = _orchestrator(tmp_path, harness=harness)
    orch.sleep = sleeps.append
    summary = orch.run_plan()
    assert summary.failed == ("shop",)
    assert sleeps == []
    assert gate.calls == []
    assert state.target("shop").phase("authn").read == state_mod.FAILED


def test_a_retryable_harness_error_takes_the_same_backoff_ladder(tmp_path):
    """A transport/provider HarnessError is a provider failure, not a timeout."""
    harness = FakeHarness()
    harness.turns = [
        HarnessError("FreeTierError 403", retryable=True),
        _turn(outcome="succeeded"),
        _turn(outcome="succeeded"),
    ]
    sleeps: list[float] = []
    orch, harness, _env, _gate, state, _ = _orchestrator(tmp_path, harness=harness)
    orch.sleep = sleeps.append
    summary = orch.run_plan()
    assert summary.completed == ("shop",)
    assert sleeps == [60.0]
    phase = state.target("shop").phase("authn")
    assert phase.turns == 2
    assert phase.timeouts == 0  # the timeout branch never swallowed it
    assert len(harness.prompts) == 3


def test_an_exhausted_harness_ladder_fails_one_target_and_the_run_continues(tmp_path):
    harness = FakeHarness()
    harness.turns = [HarnessError("429 rate limit", retryable=True)] * 3 + [
        _turn(outcome="succeeded"),
        _turn(outcome="succeeded"),
    ]
    sleeps: list[float] = []
    orch, _h, env, gate, state, _ = _orchestrator(
        tmp_path, targets=("shop", "blog"), harness=harness
    )
    orch.sleep = sleeps.append
    summary = orch.run_plan()
    assert summary.failed == ("shop",)
    assert summary.completed == ("blog",)
    assert sleeps == [60.0, 300.0]
    assert state.target("shop").status == state_mod.FAILED
    assert state.target("shop").phase("authn").read == state_mod.FAILED
    assert gate.calls == [("blog", AUTH_ONLY), ("blog", FULL)]
    assert ("down", "shop") in env.commands


def test_a_retryable_session_creation_failure_is_retried_by_the_ladder(tmp_path):
    harness = FakeHarness()
    harness.flaky = {"ses_bt_r1_shop_creator": 1}
    sleeps: list[float] = []
    orch, harness, _env, _gate, state, _ = _orchestrator(tmp_path, harness=harness)
    orch.sleep = sleeps.append
    summary = orch.run_plan()
    assert summary.completed == ("shop",)
    assert sleeps == [60.0]
    assert state.target("shop").status == state_mod.DONE
    assert len([spec for spec in harness.created if spec.session_id == "ses_bt_r1_shop_creator"]) == 2


def test_a_hard_session_creation_failure_fails_the_target_without_aborting(tmp_path):
    harness = FakeHarness()
    harness.missing = {"ses_bt_r1_shop_creator"}
    sleeps: list[float] = []
    orch, _h, env, gate, state, _ = _orchestrator(
        tmp_path, targets=("shop", "blog"), harness=harness
    )
    orch.sleep = sleeps.append
    summary = orch.run_plan()
    assert summary.failed == ("shop",)
    assert summary.completed == ("blog",)
    assert sleeps == []
    assert gate.calls == [("blog", AUTH_ONLY), ("blog", FULL)]
    assert state.target("shop").phase("authn").read == state_mod.FAILED
    assert ("down", "shop") in env.commands


def test_a_hard_repair_turn_failure_fails_the_phase_not_the_run(tmp_path):
    gate = ScriptedGate([(False, "FAIL shop\n  [auth] nope"), True, True])
    harness = FakeHarness()
    harness.turns = [
        _turn(outcome="succeeded"),
        HarnessError("session not found", retryable=False),
        _turn(outcome="succeeded"),
        _turn(outcome="succeeded"),
    ]
    orch, _h, env, gate, state, _ = _orchestrator(
        tmp_path, targets=("shop", "blog"), harness=harness, gate=gate
    )
    summary = orch.run_plan()
    assert summary.failed == ("shop",)
    assert summary.completed == ("blog",)
    assert state.target("shop").phase("authn").repairs == 1
    assert state.target("shop").phase("authn").gate == state_mod.FAILED
    assert state.target("shop").status == state_mod.FAILED
    assert ("down", "shop") in env.commands


def test_a_turn_timeout_interrupts_and_reprompts_once(tmp_path):
    harness = FakeHarness()
    harness.turns = [
        TurnTimeout("session did not reach a terminal turn within 3600s"),
        _turn(outcome="succeeded"),
        _turn(outcome="succeeded"),
    ]
    orch, harness, _env, _gate, state, logs = _orchestrator(tmp_path, harness=harness)
    summary = orch.run_plan()
    assert summary.failed == ()
    assert harness.interrupts == ["ses_bt_r1_shop_creator"]
    assert "resume" in harness.prompts[1][1].lower()
    assert state.target("shop").phase("authn").timeouts == 1
    assert any("timeout" in p.name for p in logs.written)


def test_a_second_timeout_fails_the_phase(tmp_path):
    harness = FakeHarness()
    harness.turns = [TurnTimeout("no terminal")] * 2
    orch, harness, _env, gate, state, _ = _orchestrator(
        tmp_path, harness=harness, run={"timeout_reprompts": 1}
    )
    summary = orch.run_plan()
    assert summary.failed == ("shop",)
    assert harness.interrupts == ["ses_bt_r1_shop_creator"]
    assert gate.calls == []
    assert state.target("shop").phase("authn").read == state_mod.FAILED


def test_a_gone_session_is_recreated_for_its_next_dispatch(tmp_path):
    harness = FakeHarness()
    record = state_mod.new_state("r1", targets=["shop"])
    record.target("shop").phase("authn").read = state_mod.DONE
    record.target("shop").phase("authn").gate = state_mod.DONE
    orch, harness, _env, _gate, _state, _ = _orchestrator(tmp_path, harness=harness)
    session = "ses_bt_r1_shop_creator"
    orch.state.targets["shop"] = record.target("shop")
    assert orch.state.target("shop").session_creator == session
    orch.run_plan()
    assert session in [spec.session_id for spec in harness.created]


# --- teardown verification --------------------------------------------------


def test_teardown_leftovers_are_recorded_as_evidence(tmp_path):
    leftover = Observation("shop", (_fact(service="app"), _fact(service="db")), None, "000")
    env = FakeEnv(
        observations=[
            Observation("shop", (_fact(),), "http://203.0.113.9:1/", "200"),
            leftover,
        ]
    )
    orch, _h, _env, _gate, state, _ = _orchestrator(tmp_path, env=env)
    summary = orch.run_plan()
    record = state.target("shop")
    assert record.lifecycle.verified_teardown is False
    assert record.lifecycle.leftovers == ["web_shop-app-1", "web_shop-db-1"]
    assert any("leftover" in note for note in record.notes)
    assert summary.notes
    # Leftovers are never silent: the run summary names the target, and the
    # status row carries the count (the target is still done, not failed).
    assert summary.teardown_unverified == ("shop",)
    assert summary.completed == ("shop",)
    row = state.status_table()[0]
    assert row["status"] == state_mod.DONE
    assert row["teardown"] == "leftovers(2)"


def test_attach_mode_reports_unverifiable_teardown_rather_than_assuming_it(tmp_path):
    env = FakeEnv(containers=False)
    orch, _h, _env, _gate, state, _ = _orchestrator(tmp_path, env=env)
    orch.run_plan()
    record = state.target("shop")
    assert record.lifecycle.verified_teardown is None
    assert any("unverifiable" in note for note in record.notes)


# --- failure policy ---------------------------------------------------------


def test_one_bad_target_does_not_lose_the_others(tmp_path):
    gate = ScriptedGate([(False, "FAIL shop\n  [auth] nope")] * 3 + [True, True, True, True])
    orch, harness, env, _gate, state, _ = _orchestrator(
        tmp_path, targets=("shop", "blog"), gate=gate, run={"repair_attempts": 1}
    )
    summary = orch.run_plan()
    assert summary.failed == ("shop",)
    assert summary.completed == ("blog",)
    assert state.target("shop").status == state_mod.FAILED
    assert state.target("blog").status == state_mod.DONE
    assert ("down", "shop") in env.commands and ("down", "blog") in env.commands


def test_continue_on_failure_false_stops_after_the_failed_target(tmp_path):
    gate = ScriptedGate([(False, "FAIL shop\n  [auth] nope")] * 3)
    orch, _h, env, _gate, _state, _ = _orchestrator(
        tmp_path,
        targets=("shop", "blog"),
        gate=gate,
        run={"repair_attempts": 1, "continue_on_failure": False},
    )
    summary = orch.run_plan()
    assert summary.failed == ("shop",)
    assert ("up", "blog") not in env.commands
    assert summary.stopped_early is True


def test_teardown_on_failure_false_keeps_the_failed_target_up(tmp_path):
    gate = ScriptedGate([(False, "FAIL shop\n  [auth] nope")] * 3)
    orch, _h, env, _gate, _state, _ = _orchestrator(
        tmp_path, gate=gate, run={"repair_attempts": 1, "teardown_on_failure": False}
    )
    summary = orch.run_plan()
    assert summary.failed == ("shop",)
    assert ("down", "shop") not in env.commands


def test_a_target_that_never_becomes_ready_is_failed_with_evidence(tmp_path):
    env = FakeEnv(observations=[Observation("shop", (), None, "000")] * 10)
    orch, harness, env, gate, state, _ = _orchestrator(
        tmp_path, env=env, run={"readiness": ReadinessPolicy(retries=3, interval_s=0)}
    )
    summary = orch.run_plan()
    assert summary.failed == ("shop",)
    assert gate.calls == []
    assert harness.prompts == []
    assert state.target("shop").phases == {}


# --- resume -----------------------------------------------------------------


def test_a_complete_target_is_skipped_on_a_second_run(tmp_path):
    orch, harness, env, gate, _state, _ = _orchestrator(tmp_path)
    orch.run_plan()
    prompts_after_first = list(harness.prompts)
    summary = orch.run_plan()
    assert summary.skipped == ("shop",)
    assert harness.prompts == prompts_after_first
    assert ("up", "shop") not in env.commands[2:]


def test_resume_continues_at_the_first_incomplete_phase(tmp_path):
    orch, harness, _env, gate, state, _ = _orchestrator(tmp_path)
    # Simulate a crash after the authn phase passed.
    record = state.target("shop")
    record.phase("authn").read = state_mod.DONE
    record.phase("authn").gate = state_mod.DONE
    record.status = state_mod.ACTIVE
    summary = orch.run_plan()
    assert summary.completed == ("shop",)
    assert harness.prompts == [("ses_bt_r1_shop_creator", "L1 WRAPPER")]
    assert gate.calls == [("shop", FULL)]


def test_resume_reruns_a_phase_whose_gate_was_red(tmp_path):
    orch, harness, _env, gate, state, _ = _orchestrator(tmp_path)
    record = state.target("shop")
    record.phase("authn").read = state_mod.DONE
    record.phase("authn").gate = state_mod.FAILED
    record.phase("authn").repairs = 3
    summary = orch.run_plan()
    assert summary.completed == ("shop",)
    assert harness.prompts[0][1] == "AUTHN WRAPPER"
    assert gate.calls == [("shop", AUTH_ONLY), ("shop", FULL)]


def test_a_targets_filter_restricts_the_run(tmp_path):
    orch, _h, env, _gate, _state, _ = _orchestrator(tmp_path, targets=("a", "b"))
    summary = orch.run_plan(targets=["b"])
    assert summary.completed == ("b",)
    assert [t for kind, t in env.commands if kind == "up"] == ["b"]


def test_pre_existing_artifacts_are_archived_before_the_first_dispatch(tmp_path):
    kb = tmp_path / "kbs" / "shop"
    kb.mkdir(parents=True)
    (kb / "research-notes.md").write_text("OLD LEAK\n", encoding="utf-8")
    bundle = tmp_path / "staging" / "shop" / "auth"
    bundle.mkdir(parents=True)
    (bundle / "credentials.yaml").write_text("accounts: {}\n", encoding="utf-8")
    orch, harness, _env, _gate, _state, _ = _orchestrator(tmp_path)
    summary = orch.run_plan()
    assert summary.completed == ("shop",)
    slot = tmp_path / "rundir" / "shop" / "pre-existing"
    assert (slot / "kb" / "research-notes.md").read_text(encoding="utf-8") == "OLD LEAK\n"
    assert not kb.exists()
    assert (slot / "auth-bundle" / "auth" / "credentials.yaml").exists()
    assert not (tmp_path / "staging" / "shop").exists()
    assert harness.prompts[0][0] == "ses_bt_r1_shop_creator"


def test_the_pre_existing_archive_is_idempotent_across_a_resume(tmp_path):
    kb = tmp_path / "kbs" / "shop"
    kb.mkdir(parents=True)
    (kb / "operator_kb.md").write_text("OLD\n", encoding="utf-8")
    gate = ScriptedGate([True] + [(False, "FAIL shop\n  [overview] old")] * 10)
    orch, _h, _env, _gate, _state, _ = _orchestrator(tmp_path, gate=gate)
    first = orch.run_plan()
    assert first.failed == ("shop",)
    slot = tmp_path / "rundir" / "shop" / "pre-existing" / "kb"
    assert (slot / "operator_kb.md").read_text(encoding="utf-8") == "OLD\n"
    # The failed phase's earlier attempt wrote fresh artifacts; a resume must
    # leave them alone and keep the archived original.
    kb.mkdir(parents=True, exist_ok=True)
    (kb / "operator_kb.md").write_text("FRESH\n", encoding="utf-8")
    gate.script[:] = [True] * 4
    second = orch.run_plan()
    assert second.completed == ("shop",)
    assert (kb / "operator_kb.md").read_text(encoding="utf-8") == "FRESH\n"
    assert (slot / "operator_kb.md").read_text(encoding="utf-8") == "OLD\n"


# --- persistence and logs ---------------------------------------------------


def test_every_transition_is_persisted(tmp_path):
    orch, _h, _env, _gate, _state, _ = _orchestrator(tmp_path)
    orch.run_plan()
    saved = json.loads((tmp_path / "rundir" / "state.json").read_text(encoding="utf-8"))
    assert saved["targets"]["shop"]["status"] == state_mod.DONE
    assert saved["targets"]["shop"]["phases"]["l1"]["gate"] == state_mod.DONE
    assert saved["run"]["config_digest"] == orch.state.config_digest


def test_logs_are_written_beside_the_state(tmp_path):
    orch, _h, _env, _gate, state, logs = _orchestrator(tmp_path)
    orch.run_plan()
    names = sorted(path.name for path in logs.written)
    assert "01-dispatch.log" in names
    assert any(name.startswith("01-gate") for name in names)
    for path in logs.written:
        assert path.parent.parent.name == "shop"
    # Every written log is ALSO registered on its phase state, rundir-relative,
    # so status and a resume can point at the evidence.
    registered = state.target("shop").phase("authn").logs + state.target("shop").phase("l1").logs
    assert sorted(registered) == sorted(
        str(path.relative_to(tmp_path / "rundir")) for path in logs.written
    )
    assert "shop/authn/01-dispatch.log" in registered


def test_logs_carry_the_prompt_the_transcript_tail_and_the_gate_output(tmp_path):
    gate = ScriptedGate([(False, "FAIL shop\n  [auth] nope"), True, True])
    orch, _h, _env, _gate, _state, logs = _orchestrator(tmp_path, gate=gate)
    orch.run_plan()
    dispatch = next(p for p in logs.written if p.name == "01-dispatch.log")
    text = dispatch.read_text(encoding="utf-8")
    assert "AUTHN WRAPPER" in text
    assert "assistant" in text and "idle" in text
    assert "done" in text
    gate_log = next(p for p in logs.written if p.name.startswith("01-gate"))
    assert "[auth] nope" in gate_log.read_text(encoding="utf-8")


def test_a_reused_rundir_keeps_the_previous_state(tmp_path):
    orch, _h, _env, _gate, _state, _ = _orchestrator(tmp_path)
    (tmp_path / "rundir").mkdir()
    (tmp_path / "rundir" / "state.json").write_text(
        json.dumps({"run": {"id": "r1", "status": "interrupted"}}), encoding="utf-8"
    )
    summary = orch.run_plan()
    assert summary.state_path == tmp_path / "rundir" / "state.json"
    assert summary.state_path.is_file()
