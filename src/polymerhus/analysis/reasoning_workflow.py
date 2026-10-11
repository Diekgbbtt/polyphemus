"""The reasoning workflow: the decomposed sub-problem chain a proposer role runs.

A role's reasoning is an ordered `ReasoningWorkflow` of `SubProblem`s, one LLM
turn each. Every turn speaks the ONE structured envelope `AnalysisTurn` - a strict
superset of the curator's `L1DeltaBatch` plus `claims` - so the tool set is
byte-identical across a role's calls and the provider prompt cache never toggles
(the constant-request-shape rule, ADR D26). A reasoning sub-problem populates
`claims`; an extraction sub-problem populates the delta lists. The pipeline maps
an `AnalysisTurn` to an `L1DeltaBatch` with `to_delta_batch`, which DROPS the
claims, so `L1DeltaBatch` stays the pure curator input.

Dependencies are injected VERBATIM (ADR D24): each sub-problem's human message
carries the artifacts of every source it names in `inject` - the volatile base
sources the role body seeds (the Service slice, the inventory, ...) plus the
prior sub-problems it lists in `depends_on`, rendered from their own turns. No
dependency rides the session trail, so compaction can never evict one.
"""
from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from polymerhus.analysis.analyser_types import L1DeltaBatch


class Claim(BaseModel):
    """One compact structured judgment from a reasoning sub-problem: the subject
    it is about, the assertion it holds, the evidence, and its verdict. It is the
    typed datum a dependency hands to a dependent sub-problem, in place of prose
    that compaction could summarise away (ADR D23/D24)."""

    subject: str
    assertion: str
    evidence: str = ""
    verdict: str = ""


class AnalysisTurn(L1DeltaBatch):
    """The single LLM-facing envelope: the curator's `L1DeltaBatch` delta lists plus
    the reasoning `claims`. The delta lists are the extraction artifacts; `claims`
    is the reasoning artifact. `L1DeltaBatch` remains the pure curator input."""

    claims: list[Claim] = Field(default_factory=list)


# The declared artifact vocabulary: the AnalysisTurn fields a sub-problem may
# emit. `emit` naming anything outside this set is a workflow defect.
ARTIFACT_NAMES: frozenset[str] = frozenset(AnalysisTurn.model_fields)


def to_delta_batch(turn: AnalysisTurn) -> L1DeltaBatch:
    """Map the LLM envelope to the pure curator input, dropping `claims`."""
    return L1DeltaBatch.model_validate(turn.model_dump(exclude={"claims"}))


class SubProblem(BaseModel):
    """One distinct reasoning sub-problem: one LLM turn.

    - `id` and `name` identify it; `id` is the artifact-store key a dependent
      sub-problem names in `inject` / `depends_on`.
    - `prompt` is the sub-problem's task text (the volatile part of the human
      message).
    - `inject` lists the sources rendered VERBATIM into the human message: a base
      source the role body seeded, or an earlier sub-problem's `id`.
    - `emit` lists the `AnalysisTurn` fields this sub-problem populates.
    - `depends_on` names the earlier sub-problems whose artifacts it consumes.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    prompt: str
    inject: tuple[str, ...] = ()
    emit: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()


class ReasoningWorkflow(BaseModel):
    """A role's ordered sub-problems. Validation is deliberately strict: an
    undeclared emit, a forward/unknown dependency, or a duplicate id is a role
    definition defect that must fail at construction, not at run time."""

    model_config = ConfigDict(frozen=True)

    role_id: str
    sub_problems: tuple[SubProblem, ...]

    @model_validator(mode="after")
    def _validate(self) -> "ReasoningWorkflow":
        seen: set[str] = set()
        for sp in self.sub_problems:
            if sp.id in seen:
                raise ValueError(
                    f"workflow {self.role_id!r}: duplicate sub-problem id {sp.id!r}")
            undeclared = [name for name in sp.emit if name not in ARTIFACT_NAMES]
            if not sp.emit or undeclared:
                raise ValueError(
                    f"workflow {self.role_id!r}: sub-problem {sp.id!r} emits an "
                    f"undeclared artifact {undeclared or list(sp.emit)!r}; declared "
                    f"artifacts are {sorted(ARTIFACT_NAMES)}")
            for dep in sp.depends_on:
                if dep not in seen:
                    raise ValueError(
                        f"workflow {self.role_id!r}: sub-problem {sp.id!r} depends on "
                        f"{dep!r}, which is not an earlier sub-problem")
            seen.add(sp.id)
        return self


@dataclass(frozen=True)
class WorkflowRun:
    """The recorded run: each sub-problem's `AnalysisTurn` (or None on exhaustion)
    and the rendered artifact store keyed by source name / sub-problem id."""

    turns: dict[str, AnalysisTurn | None] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return value


def render_artifact(name: str, turn: AnalysisTurn) -> str:
    """Render one emitted artifact from a turn, deterministically and losslessly -
    this is what a dependent sub-problem receives VERBATIM."""
    payload = _jsonable(getattr(turn, name))
    return f"{name}: {json.dumps(payload, ensure_ascii=False, sort_keys=True)}"


def render_emitted(sub_problem: SubProblem, turn: AnalysisTurn | None) -> str:
    """Render every artifact a sub-problem emitted; empty when the turn is None."""
    if turn is None:
        return ""
    return "\n".join(render_artifact(name, turn) for name in sub_problem.emit)


def render_turn(sub_problem: SubProblem, artifacts: Mapping[str, str]) -> str:
    """The human message for one sub-problem: its prompt, then each injected
    source rendered verbatim, in declared order."""
    parts = [sub_problem.prompt]
    for name in sub_problem.inject:
        rendered = artifacts.get(name)
        if rendered:
            parts.append(rendered)
    return "\n\n".join(parts)


def run_workflow(
    workflow: ReasoningWorkflow,
    *,
    invoke_fn: Callable[..., Any],
    system_prompt: str,
    base_artifacts: Mapping[str, str] | None = None,
    halt_when: Callable[[SubProblem, "AnalysisTurn | None"], bool] | None = None,
) -> WorkflowRun:
    """Run a workflow's sub-problems in order, one stateful turn each.

    `invoke_fn(messages, *, schema, system_prompt)` is the injected LLM seam; every
    call binds `AnalysisTurn`, so the tool set is constant across the chain. A
    sub-problem's `depends_on` artifacts are re-injected from the recorded turns -
    never read from the session trail. A None turn is recorded and rendered empty;
    whether that degrades the step is the CALLER's policy, expressed through
    `halt_when` (the fail-closed reflection gate, for the roles that need it): when
    the predicate holds the chain stops, so no later turn runs on an exhausted
    premise."""
    from langchain_core.messages import HumanMessage

    artifacts: dict[str, str] = dict(base_artifacts or {})
    turns: dict[str, AnalysisTurn | None] = {}
    for sub_problem in workflow.sub_problems:
        message = HumanMessage(content=render_turn(sub_problem, artifacts))
        turn = invoke_fn([message], schema=AnalysisTurn, system_prompt=system_prompt)
        turns[sub_problem.id] = turn
        artifacts[sub_problem.id] = render_emitted(sub_problem, turn)
        if halt_when is not None and halt_when(sub_problem, turn):
            break
    return WorkflowRun(turns=turns, artifacts=artifacts)
