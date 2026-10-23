"""The staged triage decision tree.

The triager walks four decisions in this order:

1. **failure and symptom confirmation** (compact, no tools);
2. **divergence** (the typed skill procedure and the executed trail, no tools);
3. **bounded variant mining** (the full triager context and tool surface, only
   when the spec carries a populated procedure attribute);
4. **terminal verdict** (compact, no variant).

The order is STRUCTURAL: the confirmed and failed paths short-circuit before the
divergence and mining stages run, and the miner never runs when the spec carries
no populated procedure attribute to bend into a variant. The stage callables are
injected (`TriageStages`) so the contract tier and the unit tier observe the
order without a live model; the production defaults are the stateful turns in
`agents.py`.
"""
from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from typing import Callable

from polymerhus.attack.hunting.pod.types import (
    NO_SYMPTOM_EVIDENCE,
    SYMPTOM_CONFIRMED,
    SYMPTOM_CONFIRMED_CLASS,
    skill_procedure_from_spec,
)
from polymerhus.attack.hunting.pod.variant_basis import PROCEDURE_GAP_FIELD

StageFn = Callable[[dict, object, list, object], dict]


@dataclass(frozen=True)
class TriageStages:
    """The four stage seams of the staged triager.

    Each callable has the shape `(spec, observation, messages, log) -> dict`.
    A sync callable is offloaded to a worker thread; an async one is awaited.
    `assess` returns a `TriageDecision`, `diverge` a `DivergenceDecision`,
    `mine` a `TriagerDecision`, and `terminal` a `TerminalDecision` (the models
    live in `agents.py`)."""

    assess: StageFn
    diverge: StageFn
    mine: StageFn
    terminal: StageFn


def has_populated_procedure(spec: dict) -> bool:
    """Whether the spec's typed `SkillProcedure` carries at least one populated
    field - the only material a bounded variant can bend.

    An absent excerpt or an all-empty one has nothing to diff, so the miner is
    skipped and the terminal stage decides. This is the deterministic gate the
    staged tree promises: the full miner is paid only when a variant is
    derivable."""
    procedure = skill_procedure_from_spec(spec)
    if procedure is None:
        return False
    return any(str(getattr(procedure, field) or "").strip()
               for field in PROCEDURE_GAP_FIELD.values())


async def _call_stage(fn: StageFn, *args):
    """Await an async stage, else offload a sync one to a worker thread - the
    same `_await_seam` pattern the graph uses, so the context-local pod session
    reaches sync fakes too."""
    if inspect.iscoroutinefunction(fn):
        return await fn(*args)
    return await asyncio.to_thread(fn, *args)


def _as_model(model, raw):
    """Coerce a stage result to its typed decision model.

    A dict is validated through the model; a model passes through; anything
    else is the model's default. A malformed dict raises and the orchestrator's
    fail-open wrapper degrades honestly."""
    if isinstance(raw, model):
        return raw
    if isinstance(raw, dict):
        return model(**raw)
    return model()


def _normalize_decision(raw) -> dict:
    """Normalise the miner's decision to the graph-facing dict.

    The graph validates a terminal and resolves a variant; an unknown action
    degrades to a safe terminal so a malformed stage result never mints."""
    if hasattr(raw, "model_dump"):
        decision = raw.model_dump()
    elif isinstance(raw, dict):
        decision = dict(raw)
    else:
        decision = {}
    if decision.get("action") not in ("terminate", "variant"):
        decision["action"] = "terminate"
    if decision["action"] == "terminate":
        decision.setdefault("verdict", "unsuccessful")
        decision.setdefault("terminal_reason", NO_SYMPTOM_EVIDENCE)
        decision.setdefault("clean", False)
    decision.setdefault("note", "")
    return decision


def _pod_harness_or_none():
    from polymerhus.attack.hunting.pod.llm import pod_harness  # noqa: PLC0415

    return pod_harness()


def _order_of(hc) -> int:
    from polymerhus.attack.hunting.pod.pod_memory import order_of  # noqa: PLC0415

    return order_of(getattr(hc, "variant_ref", "") or "")


def _divergence_delta(spec, observation, log, hc) -> list[dict]:
    from polymerhus.attack.hunting.pod.context import (  # noqa: PLC0415
        compose_divergence_delta,
    )

    if hc is None:
        return [{"role": "human", "content": " (no bound pod harness)"}]
    return [{"role": "human", "content": compose_divergence_delta(
        log, spec, observation, store=hc.memory_store, spec_id=hc.spec_id,
        order=_order_of(hc))}]


def _triager_delta(spec, observation, log, hc) -> list[dict]:
    from polymerhus.attack.hunting.pod.context import (  # noqa: PLC0415
        compose_triager_delta,
    )

    if hc is None:
        return [{"role": "human", "content": " (no bound pod harness)"}]
    return [{"role": "human", "content": compose_triager_delta(
        log, spec, observation, store=hc.memory_store, spec_id=hc.spec_id,
        order=_order_of(hc))}]


def _terminal_delta(spec, observation, log, hc) -> list[dict]:
    from polymerhus.attack.hunting.pod.context import (  # noqa: PLC0415
        compose_terminal_delta,
    )

    if hc is None:
        return [{"role": "human", "content": " (no bound pod harness)"}]
    return [{"role": "human", "content": compose_terminal_delta(
        log, spec, observation, store=hc.memory_store, spec_id=hc.spec_id,
        order=_order_of(hc))}]


def make_staged_triager(stages: TriageStages):
    """Build the graph's `triager_fn` from the four stage seams.

    The returned coroutine walks the tree strictly:

    - a failed runner mints the recovery variant (the current behaviour);
    - a confirmed symptom terminates `successful` / `symptom-confirmed` and the
      deterministic terminal writes the `PodExport`;
    - a diverged runner mints the divergence recovery variant;
    - otherwise the miner runs only when a populated procedure attribute exists,
      else the compact terminal stage decides the verdict.

    A provider failure propagates as the typed `ProviderUnavailableError`; any
    other stage exception degrades to a safe `no-symptom-evidence` terminal,
    exactly like the single-turn triager it replaces."""

    async def triager(spec, observation, messages, log):
        from polymerhus.app.llm.provider_failure import as_provider_error  # noqa: PLC0415
        from polymerhus.attack.hunting.pod.agents import (  # noqa: PLC0415
            DivergenceDecision,
            TerminalDecision,
            TriageDecision,
        )

        try:
            assessment = _as_model(
                TriageDecision,
                await _call_stage(stages.assess, spec, observation, list(messages), log))
            if assessment.runner_failed:
                return {"classification": "runner-failure", "action": "variant",
                        "runner_failed": True,
                        "note": assessment.note or "the runner execution failed",
                        "feedback": assessment.note or "recover the failed execution"}
            if assessment.symptom_confirmed:
                return {"classification": SYMPTOM_CONFIRMED_CLASS,
                        "action": "terminate", "verdict": "successful",
                        "terminal_reason": SYMPTOM_CONFIRMED, "clean": True,
                        "note": assessment.note or "verification symptom observed"}

            hc = _pod_harness_or_none()
            divergence = _as_model(
                DivergenceDecision,
                await _call_stage(stages.diverge, spec, observation,
                                  _divergence_delta(spec, observation, log, hc), log))
            if divergence.runner_diverged:
                return {"classification": "runner-divergence", "action": "variant",
                        "runner_diverged": True,
                        "note": divergence.note or "the execution diverged from the spec",
                        "feedback": divergence.note or "return the execution to the spec"}

            if has_populated_procedure(spec):
                mined = await _call_stage(
                    stages.mine, spec, observation,
                    _triager_delta(spec, observation, log, hc), log)
                return _normalize_decision(mined)

            terminal = _as_model(
                TerminalDecision,
                await _call_stage(stages.terminal, spec, observation,
                                  _terminal_delta(spec, observation, log, hc), log))
            return {"classification": terminal.classification or "symptom-absent",
                    "action": "terminate", "verdict": terminal.verdict,
                    "terminal_reason": terminal.terminal_reason,
                    "clean": terminal.clean, "note": terminal.note}
        except Exception as exc:  # noqa: BLE001 - fail-open safe terminal
            failure = as_provider_error(exc)
            if failure is not None:
                # #329: a provider failure is infrastructure, not a triager
                # assessment. Propagate the typed error; never launder a throttle
                # into a benign domain verdict.
                raise failure from exc
            return {"classification": "noise", "action": "terminate",
                    "verdict": "unsuccessful", "terminal_reason": NO_SYMPTOM_EVIDENCE,
                    "clean": False, "note": f"triager degraded: {exc}"}

    return triager
