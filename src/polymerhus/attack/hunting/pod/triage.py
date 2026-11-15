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
from typing import Callable, Sequence

from polymerhus.attack.hunting.pod.types import (
    NO_SYMPTOM_EVIDENCE,
    SYMPTOM_CONFIRMED,
    SYMPTOM_CONFIRMED_CLASS,
    skill_concretised_procedure_from_spec,
)
from polymerhus.attack.hunting.pod.variant_basis import PROCEDURE_GAP_FIELD

StageFn = Callable[[dict, object, list, object], dict]

MAX_TRIAGE_STEPS = 6
"""The bounded turn budget of one triage decision. A model that never submits
through the gate exhausts it, and the harness degrades to the honest terminal
instead of looping."""


def _openai_tool_dict(tool) -> dict:
    """One request-only OpenAI tool dict for a bound BaseTool - the hunter's
    `request_tools` shape: the JSON schema rides the request body, and no
    ToolNode is created, so the harness stays the sole executor."""
    from langchain_core.utils.function_calling import convert_to_openai_tool

    return convert_to_openai_tool(tool)


def gate_correction(phase: str) -> str:
    """The bounded correction message for a turn with no tool call: the model
    must submit through the phase's gate, with the exact fields its schema
    shows. A model error, never a verdict."""
    tool = "submit_assessment" if phase == "assess" else "submit_decision"
    return (f"You replied without calling a tool. Submit through `{tool}` now, "
            "with the exact fields its schema shows. Do not answer in prose.")


async def run_triage_harness(log, spec: dict, observation, facts, *, store,
                             spec_id: str, order: int, session_ctx,
                             harness_ctx, middleware: Sequence = (),
                             max_steps: int = MAX_TRIAGE_STEPS,
                             turn_fn=None, invoke_fn=None) -> dict:
    """The lifecycle v2 triage harness loop (the ratified turn-by-turn pattern,
    mirrored from `build_hunting_agent`).

    One `arun_session_turn` per step on the SAME per-pod `pod_triager` thread;
    the immutable contract prompt and the constant request-only tool list on
    every step; the harness as the sole tool executor; the phase packet
    appended once to the ACCEPTED gate response and consumed. A malformed gate
    call is a coded rejection (no phase move); a turn with no tool call gets a
    bounded correction; the step budget degrades to the honest terminal; a
    provider failure propagates (#329).

    Returns `{decision, assessment, steps, rejections}`; the pod graph's
    triager node renders the `PodExport` from the decision.
    """
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    from polymerhus.attack.hunting.hunting_agent import _last_tool_calls, invoke_tool
    from polymerhus.attack.hunting.pod.agents import triager_react_tools
    from polymerhus.attack.hunting.pod.context import (
        _dicts_to_lc,
        compose_assess_packet,
        compose_decide_packet,
    )
    from polymerhus.attack.hunting.pod.gates import (
        ASSESSMENT_TOOL,
        DECISION_TOOL,
        build_triage_gate_tools,
        gate_accepted,
        triage_request_tools,
    )
    from polymerhus.attack.hunting.pod.prompts import (
        load_pod_decide_verbatim,
        load_pod_triager_contract,
    )
    from polymerhus.attack.hunting.pod.triage_graph import build_triage_graph
    from polymerhus.attack.hunting.pod.triage_state import detect_triage_signal
    from polymerhus.app.llm.session import arun_session_turn

    if turn_fn is None:
        turn_fn = arun_session_turn
    if invoke_fn is None:
        invoke_fn = invoke_tool

    address = session_ctx.address
    mem_key = address.thread_id
    role_id = address.role_id
    project_id = getattr(getattr(harness_ctx, "capture_context", None),
                         "project_id", "") or ""
    run_id = getattr(getattr(harness_ctx, "capture_context", None),
                     "run_id", "") or mem_key
    lap = facts.get("lap", 1)
    contract = load_pod_triager_contract()
    graph = build_triage_graph().compile()

    def _surface(assessment) -> tuple[list[dict], dict]:
        """The CONSTANT tool surface: the read-only triager tools plus the two
        gates, bound once per lap and identical on every step. The request-side
        dicts are projected once; the gate schemas come from the gate models,
        so the schema the model sees is the schema the gate validates."""
        base = triager_react_tools(
            harness_ctx.memory_store, harness_ctx.spec_id, log=harness_ctx.log,
            variant_ref=harness_ctx.variant_ref or "",
            graph_view_fn=harness_ctx.graph_view_fn,
            browser_tool=harness_ctx.browser_tool)
        by_name = {tool.name: tool for tool in base}
        by_name.update(build_triage_gate_tools(facts, assessment))
        return ([*[_openai_tool_dict(tool) for tool in base],
                 *triage_request_tools()], by_name)

    state: dict = {
        "phase": "assess", "observed_signal": None, "observed_args": None,
        "observed_outcome": None, "facts": dict(facts), "assessment": None,
        "decide_packet": None, "injected_constant": None, "trail": [],
        "decision": None,
    }
    base = compose_assess_packet(log, spec, observation, facts, store=store,
                                 spec_id=spec_id, order=order,
                                 include_verbatim=lap <= 1)
    new_messages = _dicts_to_lc([{"role": "human", "content": base}])
    rejections: list[str] = []
    steps = 0

    for _step in range(max_steps):
        steps = _step + 1
        request_tools, tools_by_name = _surface(state.get("assessment"))
        turn = await turn_fn(
            role_id, mem_key, new_messages,
            checkpointer=session_ctx.checkpointer,
            tools=request_tools,
            system_prompt=contract,
            middleware=list(middleware),
            observe=True,
            extra_tags=[run_id, mem_key, f"lap:{lap}",
                        f"phase:{state['phase']}"],
            usage_scope=project_id,
            model_factory=harness_ctx.model_factory,
        )
        tool_calls = _last_tool_calls(turn.messages)
        if not tool_calls:
            new_messages = _dicts_to_lc(
                [{"role": "human", "content": gate_correction(state["phase"])}])
            continue
        results = []
        for tc in tool_calls:
            name = tc.get("name", "")
            result = await invoke_fn(tools_by_name, name, tc.get("args") or {})
            accepted = gate_accepted(result)
            if not accepted and name in (ASSESSMENT_TOOL, DECISION_TOOL):
                rejections.append(result)
            signal = detect_triage_signal(name, tc.get("args") or {})
            if signal is not None and not accepted:
                signal = None
            if signal is not None:
                # The packet is composed per advance: the DECIDE material is
                # this lap's state, and the verbatim rides with it once.
                material = compose_decide_packet(log, spec, facts, store=store,
                                                 spec_id=spec_id, order=order)
                packet = f"{load_pod_decide_verbatim()}\n\n{material}"
                state = await graph.ainvoke({
                    **state, "observed_signal": signal,
                    "observed_args": tc.get("args") or {},
                    "decide_packet": packet})
            packet = state.get("injected_constant")
            if packet:
                result = f"{result}\n\n<phase-packet>\n{packet}\n</phase-packet>"
                state = {**state, "injected_constant": None}
            results.append(ToolMessage(tool_call_id=tc.get("id") or "",
                                       content=result))
        if state["phase"] == "done":
            break
        new_messages = [
            m if isinstance(m, (ToolMessage, HumanMessage, AIMessage)) else m
            for m in results]

    decision = state.get("decision")
    if decision is None:
        # The budget exhausted without a gate call: the same honest degrade the
        # malformed-decision path has always used.
        decision = {
            "action": "terminate", "classification": "noise",
            "verdict": "unsuccessful", "terminal_reason": NO_SYMPTOM_EVIDENCE,
            "clean": False,
            "note": ("triage step budget exhausted without a gate submission; "
                     "degraded"),
        }
    return {"decision": decision, "assessment": state.get("assessment"),
            "steps": steps, "rejections": rejections}


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
    staged tree promises: the full miner is paid only when a variant could be
    derived."""
    procedure = skill_concretised_procedure_from_spec(spec)
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
        return [{"role": "human", "content": "no bound pod harness"}]
    return [{"role": "human", "content": compose_divergence_delta(
        log, spec, observation, store=hc.memory_store, spec_id=hc.spec_id,
        order=_order_of(hc))}]


def _triager_delta(spec, observation, log, hc) -> list[dict]:
    from polymerhus.attack.hunting.pod.context import (  # noqa: PLC0415
        compose_triager_delta,
    )

    if hc is None:
        return [{"role": "human", "content": "no bound pod harness"}]
    return [{"role": "human", "content": compose_triager_delta(
        log, spec, observation, store=hc.memory_store, spec_id=hc.spec_id,
        order=_order_of(hc))}]


def _terminal_delta(spec, observation, log, hc) -> list[dict]:
    from polymerhus.attack.hunting.pod.context import (  # noqa: PLC0415
        compose_terminal_delta,
    )

    if hc is None:
        return [{"role": "human", "content": "no bound pod harness"}]
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
