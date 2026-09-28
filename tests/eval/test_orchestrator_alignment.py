"""The alignment step (#274, D37/D42/N18).

The daemon is mechanical: it emits the manifest/fingerprint delta and never
decides. The orchestrator asserts the delta, interposes an agent turn (the
`AlignmentDecider` seam) with the delta, the documented impact map, and the
environment context, then executes the returned actions or escalates and holds
a jump it cannot align without an operator decision.

These tests inject a fake decider and a recording runner; no Docker, no agent.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator import alignment, instances
from orchestrator.commands import CommandResult
from orchestrator.instances import InstancePaths
from orchestrator.setup import (
    AlignmentDeclarations,
    DeclaredMigration,
    DeclaredRebuild,
    Instance,
)


# --- fixtures and helpers -----------------------------------------------------


def make_paths(tmp_path: Path, instance_id: str = "arm-a") -> InstancePaths:
    instance = Instance(instance_id=instance_id, targets=())
    return instances.instance_paths(
        instance,
        tmp_path / "instances",
        repo=tmp_path / "repo",
        branch="eval",
    )


def make_environment(
    paths: InstancePaths,
    declarations: AlignmentDeclarations | None = None,
) -> alignment.AlignmentEnvironment:
    return alignment.AlignmentEnvironment(
        instances=(paths,),
        declarations=declarations or AlignmentDeclarations(),
    )


def art(name: str, artifact_class: str, before: str = "old", after: str = "new") -> dict:
    return {
        "name": name,
        "artifact_class": artifact_class,
        "before_sha": before,
        "after_sha": after,
    }


def decision_input(
    changed: list[dict] | None = None,
    images_changed: list[dict] | None = None,
    *,
    dev_sha: str = "dev-sha",
    eval_sha: str = "eval-sha",
    dev_fp: str = "fp-dev",
    eval_fp: str = "fp-eval",
) -> dict:
    return {
        "dev_sha": dev_sha,
        "eval_sha": eval_sha,
        "all_idle": True,
        "delta": {
            "changed": changed or [],
            "unchanged": [],
            "images_changed": images_changed or [],
            "images_unchanged": [],
        },
        "fingerprints": {"dev": dev_fp, "eval": eval_fp},
    }


class FakeDecider:
    """A decider that records its request and returns a scripted decision."""

    def __init__(self, decision: alignment.AlignmentDecision) -> None:
        self.decision = decision
        self.requests: list[alignment.AlignmentRequest] = []

    def decide(self, request: alignment.AlignmentRequest) -> alignment.AlignmentDecision:
        self.requests.append(request)
        return self.decision


class RecordingRunner:
    def __init__(self, routes: dict[str, CommandResult] | None = None) -> None:
        self.routes = routes or {}
        self.commands = []

    def __call__(self, command):
        self.commands.append(command)
        argv = " ".join(command.argv)
        for needle, result in self.routes.items():
            if needle in argv:
                return result
        return CommandResult(0)

    @property
    def argv_texts(self) -> list[str]:
        return [" ".join(c.argv) for c in self.commands]


def make_state(tmp_path: Path) -> alignment.AlignmentState:
    return alignment.AlignmentState(tmp_path / "alignment.yaml")


# --- no change / arbitrary decisions -----------------------------------------


def test_no_change_is_a_no_op_and_never_calls_the_decider(tmp_path: Path) -> None:
    runner = RecordingRunner()
    decider = FakeDecider(alignment.AlignmentDecision(actions=()))
    outcome = alignment.run(
        decision_input(),
        decider=decider,
        environment=make_environment(make_paths(tmp_path)),
        runner=runner,
        state=make_state(tmp_path),
    )

    assert outcome.no_op is True
    assert outcome.escalated is False
    assert outcome.results == ()
    assert decider.requests == []
    assert runner.commands == []


def test_a_changed_class_with_no_action_is_honoured_not_auto_failed(tmp_path: Path) -> None:
    runner = RecordingRunner()
    decider = FakeDecider(alignment.AlignmentDecision(actions=(), escalation=None))
    outcome = alignment.run(
        decision_input([art("db", "schema_data_layout")]),
        decider=decider,
        environment=make_environment(make_paths(tmp_path)),
        runner=runner,
        state=make_state(tmp_path),
    )

    assert outcome.results == ()
    assert outcome.hold is None
    assert outcome.escalated is False
    assert runner.commands == []
    assert len(decider.requests) == 1


def test_unknown_artifact_class_reaches_the_decider(tmp_path: Path) -> None:
    """No hardcoded policy: an unrecognised class is passed through verbatim."""
    runner = RecordingRunner()
    decider = FakeDecider(
        alignment.AlignmentDecision(actions=(), escalation="unknown class needs a decision")
    )
    outcome = alignment.run(
        decision_input([art("mystery", "mystery_class")]),
        decider=decider,
        environment=make_environment(make_paths(tmp_path)),
        runner=runner,
        state=make_state(tmp_path),
    )

    assert len(decider.requests) == 1
    changed = decider.requests[0].decision_input["delta"]["changed"]
    assert any(entry["artifact_class"] == "mystery_class" for entry in changed)
    assert outcome.escalated is True


# --- executors ----------------------------------------------------------------


def test_kali_change_restarts_kali(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    runner = RecordingRunner()
    decider = FakeDecider(
        alignment.AlignmentDecision(
            actions=(alignment.DecisionAction(kind="restart", component="kali"),)
        )
    )

    outcome = alignment.run(
        decision_input([art("kali", "exec_plane")]),
        decider=decider,
        environment=make_environment(paths),
        runner=runner,
        state=make_state(tmp_path),
    )

    assert outcome.results[0].status == "applied"
    container = instances.compose_project(paths.instance)
    assert runner.argv_texts == [f"docker restart {container}-kali-1"]


def test_gateway_change_restarts_litellm(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    runner = RecordingRunner()
    decider = FakeDecider(
        alignment.AlignmentDecision(
            actions=(alignment.DecisionAction(kind="restart", component="litellm"),)
        )
    )

    outcome = alignment.run(
        decision_input([art("gateway", "gateway")]),
        decider=decider,
        environment=make_environment(paths),
        runner=runner,
        state=make_state(tmp_path),
    )

    assert outcome.results[0].status == "applied"
    container = instances.compose_project(paths.instance)
    # litellm is the gateway process inside the agent container (D10).
    assert runner.argv_texts == [f"docker restart {container}-agent-1"]


def test_compose_change_force_recreates_only_the_named_services(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    runner = RecordingRunner()
    decider = FakeDecider(
        alignment.AlignmentDecision(
            actions=(
                alignment.DecisionAction(kind="recreate", services=("agent", "postgres")),
            )
        )
    )

    outcome = alignment.run(
        decision_input([art("compose", "topology_env")]),
        decider=decider,
        environment=make_environment(paths),
        runner=runner,
        state=make_state(tmp_path),
    )

    assert outcome.results[0].status == "applied"
    argv = runner.argv_texts[0]
    assert "up -d --force-recreate agent postgres" in argv
    assert "neo4j" not in argv
    assert runner.commands[0].cwd == str(paths.worktree)


def test_config_align_runs_preflight_and_recreates_on_keyset_change(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    runner = RecordingRunner(
        routes={"env_preflight": CommandResult(0, stdout="added (1): NEWKEY\nextra (0): -\n")}
    )
    decider = FakeDecider(
        alignment.AlignmentDecision(
            actions=(alignment.DecisionAction(kind="config_align", instance="arm-a"),)
        )
    )

    outcome = alignment.run(
        decision_input([art("env_schema", "config_schema")]),
        decider=decider,
        environment=make_environment(paths),
        runner=runner,
        state=make_state(tmp_path),
    )

    assert outcome.results[0].status == "applied"
    assert "env_preflight.py" in runner.argv_texts[0]
    assert "--force-recreate" in runner.argv_texts[1]


def test_config_align_skips_the_recreate_when_the_keyset_is_unchanged(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    runner = RecordingRunner(
        routes={"env_preflight": CommandResult(0, stdout="added (0): -\nextra (0): -\n")}
    )
    decider = FakeDecider(
        alignment.AlignmentDecision(
            actions=(alignment.DecisionAction(kind="config_align", instance="arm-a"),)
        )
    )

    outcome = alignment.run(
        decision_input([art("env_schema", "config_schema")]),
        decider=decider,
        environment=make_environment(paths),
        runner=runner,
        state=make_state(tmp_path),
    )

    assert len(runner.commands) == 1
    assert "env_preflight.py" in runner.argv_texts[0]
    assert "--force-recreate" not in runner.argv_texts[0]


def test_an_explicit_decision_command_is_executed_without_a_declaration(tmp_path: Path) -> None:
    """A command supplied in the decision itself needs no declaration."""
    paths = make_paths(tmp_path)
    runner = RecordingRunner()
    decider = FakeDecider(
        alignment.AlignmentDecision(
            actions=(
                alignment.DecisionAction(
                    kind="migration",
                    artifact_class="schema_data_layout",
                    command=("python3", "ad-hoc-migration.py"),
                ),
            )
        )
    )

    outcome = alignment.run(
        decision_input([art("db", "schema_data_layout")]),
        decider=decider,
        environment=make_environment(paths),
        runner=runner,
        state=make_state(tmp_path),
    )

    assert outcome.results[0].status == "applied"
    assert runner.argv_texts == ["python3 ad-hoc-migration.py"]


def test_declared_migration_is_executed(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    declarations = AlignmentDeclarations(
        migrations=(
            DeclaredMigration(
                artifact_class="schema_data_layout",
                command=("python3", "eval/migrations/0001.py"),
            ),
        )
    )
    runner = RecordingRunner()
    decider = FakeDecider(
        alignment.AlignmentDecision(
            actions=(
                alignment.DecisionAction(
                    kind="migration", artifact_class="schema_data_layout"
                ),
            )
        )
    )

    outcome = alignment.run(
        decision_input([art("db", "schema_data_layout")]),
        decider=decider,
        environment=make_environment(paths, declarations),
        runner=runner,
        state=make_state(tmp_path),
    )

    assert outcome.results[0].status == "applied"
    assert runner.argv_texts == ["python3 eval/migrations/0001.py"]


def test_declared_rebuild_is_executed(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    declarations = AlignmentDeclarations(
        rebuilds=(
            DeclaredRebuild(
                artifact_class="image_definition",
                image="agent",
                command=("docker", "build", "-t", "ph-agent", "."),
            ),
        )
    )
    runner = RecordingRunner()
    decider = FakeDecider(
        alignment.AlignmentDecision(
            actions=(
                alignment.DecisionAction(
                    kind="rebuild", artifact_class="image_definition", image="agent"
                ),
            )
        )
    )

    outcome = alignment.run(
        decision_input([art("image_definitions", "image_definition")]),
        decider=decider,
        environment=make_environment(paths, declarations),
        runner=runner,
        state=make_state(tmp_path),
    )

    assert outcome.results[0].status == "applied"
    assert runner.argv_texts == ["docker build -t ph-agent ."]


def test_a_migration_without_a_declaration_fails_loudly(tmp_path: Path) -> None:
    """The decider may not invent a command; an unresolvable action is a failure."""
    paths = make_paths(tmp_path)
    runner = RecordingRunner()
    decider = FakeDecider(
        alignment.AlignmentDecision(
            actions=(
                alignment.DecisionAction(
                    kind="migration", artifact_class="schema_data_layout"
                ),
            )
        )
    )

    outcome = alignment.run(
        decision_input([art("db", "schema_data_layout")]),
        decider=decider,
        environment=make_environment(paths),
        runner=runner,
        state=make_state(tmp_path),
    )

    assert outcome.ok is False
    assert outcome.results[0].status == "failed"
    assert runner.commands == []


# --- escalation and holds -----------------------------------------------------


def test_undeclared_schema_jump_escalates_and_writes_a_hold(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    runner = RecordingRunner()
    state = make_state(tmp_path)
    decider = FakeDecider(
        alignment.AlignmentDecision(
            actions=(), escalation="no declared migration for schema_data_layout"
        )
    )

    outcome = alignment.run(
        decision_input([art("db", "schema_data_layout")]),
        decider=decider,
        environment=make_environment(paths),
        runner=runner,
        state=state,
    )

    assert outcome.escalated is True
    assert outcome.hold is not None
    assert "no declared migration" in outcome.hold.rationale
    holds = state.unresolved_holds()
    assert len(holds) == 1
    assert holds[0].hold_id == outcome.hold.hold_id
    assert runner.commands == []


@pytest.mark.parametrize("artifact_class", ["platform", "image_definition"])
def test_undeclared_platform_or_image_jump_escalates_and_holds(
    tmp_path: Path, artifact_class: str
) -> None:
    state = make_state(tmp_path)
    decider = FakeDecider(
        alignment.AlignmentDecision(
            actions=(), escalation=f"no declaration for {artifact_class}"
        )
    )

    outcome = alignment.run(
        decision_input([art("group", artifact_class)]),
        decider=decider,
        environment=make_environment(make_paths(tmp_path)),
        runner=RecordingRunner(),
        state=state,
    )

    assert outcome.escalated is True
    assert outcome.hold is not None
    assert artifact_class in outcome.hold.rationale
    assert len(state.unresolved_holds()) == 1


def test_rerunning_an_escalation_does_not_duplicate_the_hold(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    state = make_state(tmp_path)
    decider = FakeDecider(
        alignment.AlignmentDecision(actions=(), escalation="operator decision needed")
    )
    payload = decision_input([art("db", "schema_data_layout")])

    first = alignment.run(
        payload,
        decider=decider,
        environment=make_environment(paths),
        runner=RecordingRunner(),
        state=state,
    )
    second = alignment.run(
        payload,
        decider=decider,
        environment=make_environment(paths),
        runner=RecordingRunner(),
        state=state,
    )

    assert first.hold is not None and second.hold is not None
    assert first.hold.hold_id == second.hold.hold_id
    assert len(state.holds()) == 1


def test_hold_blocks_start_and_resolve_clears_it(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    state = make_state(tmp_path)
    decider = FakeDecider(
        alignment.AlignmentDecision(actions=(), escalation="case A needs a decision")
    )
    outcome = alignment.run(
        decision_input([art("db", "schema_data_layout")]),
        decider=decider,
        environment=make_environment(paths),
        runner=RecordingRunner(),
        state=state,
    )
    hold = outcome.hold
    assert hold is not None

    with pytest.raises(alignment.AlignmentHoldError) as excinfo:
        state.require_no_holds()
    assert hold.hold_id in str(excinfo.value)
    assert "case A needs a decision" in str(excinfo.value)

    resolved = state.resolve_hold(hold.hold_id, "operator ran the migration by hand")

    assert resolved.resolved is True
    assert resolved.decision == "operator ran the migration by hand"
    state.require_no_holds()  # no longer raises


def test_resolving_an_unknown_hold_fails_loudly(tmp_path: Path) -> None:
    state = make_state(tmp_path)
    with pytest.raises(alignment.AlignmentError):
        state.resolve_hold("nope", "decision")


# --- idempotency, dry-run, failures ------------------------------------------


def test_rerun_reports_already_applied_actions_instead_of_repeating(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    runner = RecordingRunner()
    state = make_state(tmp_path)
    decider = FakeDecider(
        alignment.AlignmentDecision(
            actions=(alignment.DecisionAction(kind="restart", component="kali"),)
        )
    )
    payload = decision_input([art("kali", "exec_plane")])

    first = alignment.run(
        payload, decider=decider, environment=make_environment(paths),
        runner=runner, state=state,
    )
    calls_after_first = len(runner.commands)
    second = alignment.run(
        payload, decider=decider, environment=make_environment(paths),
        runner=runner, state=state,
    )

    assert first.results[0].status == "applied"
    assert second.results[0].status == "skipped"
    assert len(runner.commands) == calls_after_first


def test_dry_run_plans_everything_and_executes_nothing(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    runner = RecordingRunner()
    state = make_state(tmp_path)
    decider = FakeDecider(
        alignment.AlignmentDecision(
            actions=(alignment.DecisionAction(kind="restart", component="kali"),)
        )
    )

    outcome = alignment.run(
        decision_input([art("kali", "exec_plane")]),
        decider=decider,
        environment=make_environment(paths),
        runner=runner,
        state=state,
        dry_run=True,
    )

    assert outcome.results[0].status == "planned"
    assert runner.commands == []
    assert state.applied_for("dev-sha", "fp-dev") == frozenset()


def test_action_failure_is_surfaced_with_evidence_and_not_recorded(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    runner = RecordingRunner(
        routes={"docker restart": CommandResult(1, stderr="no such container")}
    )
    state = make_state(tmp_path)
    decider = FakeDecider(
        alignment.AlignmentDecision(
            actions=(alignment.DecisionAction(kind="restart", component="kali"),)
        )
    )

    outcome = alignment.run(
        decision_input([art("kali", "exec_plane")]),
        decider=decider,
        environment=make_environment(paths),
        runner=runner,
        state=state,
    )

    result = outcome.results[0]
    assert result.status == "failed"
    assert "no such container" in result.evidence
    assert outcome.ok is False
    assert state.applied_for("dev-sha", "fp-dev") == frozenset()


# --- the impact map is guidance data, not code -------------------------------


def test_impact_map_is_data_the_request_carries(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    decider = FakeDecider(alignment.AlignmentDecision(actions=(), escalation="x"))
    alignment.run(
        decision_input([art("kali", "exec_plane")]),
        decider=decider,
        environment=make_environment(paths),
        runner=RecordingRunner(),
        state=make_state(tmp_path),
    )

    request = decider.requests[0]
    classes = {entry.artifact for entry in request.impact_map}
    assert "kali/**" in classes
    assert request.environment["instances"][0]["instance_id"] == "arm-a"


def test_dry_run_escalation_writes_no_hold(tmp_path: Path) -> None:
    state = make_state(tmp_path)
    decider = FakeDecider(
        alignment.AlignmentDecision(actions=(), escalation="needs an operator")
    )

    outcome = alignment.run(
        decision_input([art("db", "schema_data_layout")]),
        decider=decider,
        environment=make_environment(make_paths(tmp_path)),
        runner=RecordingRunner(),
        state=state,
        dry_run=True,
    )

    assert outcome.escalated is True
    assert outcome.hold is None
    assert state.holds() == ()


def test_load_decision_parses_actions_and_rejects_unknown_kinds(tmp_path: Path) -> None:
    from orchestrator.files import FileStore

    files = FileStore()
    good = tmp_path / "good.yaml"
    good.write_text(
        "actions:\n  - kind: restart\n    component: kali\n", encoding="utf-8"
    )
    decision = alignment.load_decision(good, files=files)
    assert decision.actions[0].component == "kali"

    bad = tmp_path / "bad.yaml"
    bad.write_text("actions:\n  - kind: teleport\n", encoding="utf-8")
    with pytest.raises(alignment.AlignmentError, match="teleport"):
        alignment.load_decision(bad, files=files)


def test_subagent_decider_writes_the_input_dispatches_and_reads_the_decision(
    tmp_path: Path,
) -> None:
    from orchestrator.files import FileStore

    files = FileStore()
    request = alignment.AlignmentRequest(
        prompt=Path("prompt.md"),
        input_file=tmp_path / "input.yaml",
        destination=tmp_path / "decision.yaml",
        decision_input={"delta": {"changed": []}},
        impact_map=alignment.IMPACT_MAP,
        environment={"instances": []},
    )
    # The agent, as the configured command would, writes the destination.
    files.write_text(request.destination, "actions:\n  - kind: restart\n    component: kali\n")
    runner = RecordingRunner()

    decider = alignment.SubagentAlignmentDecider(
        runner, ("python3", "agent.py", "{input}", "{destination}"), files=files
    )
    decision = decider.decide(request)

    assert decision.actions[0].kind == "restart"
    assert request.input_file.is_file()
    assert "impact_map" in files.read_text(request.input_file)
    assert runner.argv_texts[0].endswith(
        f"{request.input_file} {request.destination}"
    )

