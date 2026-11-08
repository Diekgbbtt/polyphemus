"""Unit tier: the SkillEvolution experiment switch.

`SKILL_EVOLUTION_ENABLED=0` turns the whole skill-evolution system off for one
experiment arm: no project evolver controller, no `meta/meta-write-skill`
binding, no `record_skill_lesson` tool, and no lesson line in the pod prompts.
The default is on, so production behaviour is unchanged.
"""
from __future__ import annotations

import pytest

from polymerhus.app.llm import evolver, skills
from polymerhus.app.llm.skills import SKILL_EVOLUTION_ENV, skill_evolution_enabled
from polymerhus.attack.hunting.pod import prompts as pod_prompts


class _FakeRuntime:
    """The minimum runtime surface `ensure_project_evolver` touches."""

    def __init__(self) -> None:
        self.scheduled: list[tuple[str, str]] = []
        self.ensured: list[str] = []

    def has_run(self, module: str, session_id: str) -> bool:
        return False

    def ensure_running(self, module: str) -> None:
        self.ensured.append(module)

    def schedule(self, module: str, coro, name: str) -> str:
        self.scheduled.append((module, name))
        coro.close()
        return name


def test_the_switch_defaults_on(monkeypatch):
    monkeypatch.delenv(SKILL_EVOLUTION_ENV, raising=False)

    assert skill_evolution_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "OFF", " 0 "])
def test_the_switch_accepts_the_off_spellings(monkeypatch, value):
    monkeypatch.setenv(SKILL_EVOLUTION_ENV, value)

    assert skill_evolution_enabled() is False


@pytest.mark.parametrize("value", ["1", "true", "yes", "on", ""])
def test_the_switch_treats_every_other_value_as_on(monkeypatch, value):
    monkeypatch.setenv(SKILL_EVOLUTION_ENV, value)

    assert skill_evolution_enabled() is True


def test_disabled_skips_the_project_evolver_controller(monkeypatch):
    monkeypatch.setenv(SKILL_EVOLUTION_ENV, "0")
    runtime = _FakeRuntime()

    assert evolver.ensure_project_evolver("proj-1", runtime=runtime) is None
    assert runtime.scheduled == []


def test_enabled_starts_the_project_evolver_controller(monkeypatch):
    monkeypatch.delenv(SKILL_EVOLUTION_ENV, raising=False)
    runtime = _FakeRuntime()

    session = evolver.ensure_project_evolver("proj-1", runtime=runtime)

    assert session == evolver.evolver_session_id("proj-1")
    assert runtime.scheduled == [("skills", session)]


def test_disabled_refuses_a_forced_evolution_pass(monkeypatch):
    monkeypatch.setenv(SKILL_EVOLUTION_ENV, "0")
    runtime = _FakeRuntime()

    with pytest.raises(evolver.SkillEvolutionDisabled):
        evolver.launch_evolution_pass("proj-1", "ssrf", runtime=runtime)


def test_disabled_omits_the_lesson_tool(monkeypatch):
    monkeypatch.setenv(SKILL_EVOLUTION_ENV, "0")

    tools = skills.build_skill_tools("proj-1")

    assert [tool.name for tool in tools] == ["load_skill"]


def test_disabled_omits_the_meta_skill_binding(monkeypatch):
    monkeypatch.setenv(SKILL_EVOLUTION_ENV, "0")

    assert skills.skills_for_role("skill_evolver") == ()


def test_disabled_removes_the_lesson_line_from_the_pod_prompts(monkeypatch):
    monkeypatch.setenv(SKILL_EVOLUTION_ENV, "0")
    monkeypatch.setattr(pod_prompts, "_RUNNER_SKILL", None)
    monkeypatch.setattr(pod_prompts, "_TRIAGER_SKILL", None)

    assert "record_skill_lesson" not in pod_prompts.load_pod_runner_skill()
    assert "record_skill_lesson" not in pod_prompts.load_pod_triager_skill()


def test_enabled_keeps_the_lesson_line_in_the_pod_prompts(monkeypatch):
    monkeypatch.delenv(SKILL_EVOLUTION_ENV, raising=False)
    monkeypatch.setattr(pod_prompts, "_RUNNER_SKILL", None)
    monkeypatch.setattr(pod_prompts, "_TRIAGER_SKILL", None)

    assert "record_skill_lesson" in pod_prompts.load_pod_runner_skill()
    assert "record_skill_lesson" in pod_prompts.load_pod_triager_skill()
