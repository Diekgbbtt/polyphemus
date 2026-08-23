"""The hunting agent (#83, as of #164 W5): the turn-by-turn ReAct host.

The hunt-orchestrator (#82) feeds this module one declarative `HuntConfig` per
hunt (IA-2); the harness drives the model through the ratified tool surface
(`hunts_store` / `notes` / `graph_view` / `kb_query` / `exec`, R3/R1/R2) as a
turn-by-turn ReAct loop OVER the state-graph hunter (`hunter_graph.py`), and
writes exactly the record kinds the model's tool calls signal.

The harness is the TURN-BY-TURN DRIVER (ADR R4): per LLM step it runs ONE
`arun_session_turn` on the per-hunt `HuntSession(run_id, hunt_id)` thread, so
every LLM call rides the session seam and the checkpointer, compaction (#95 D9),
and capability (#99) negotiation attach. Each step is a STRUCTURED step request
(`HunterStep`): the model either requests one tool call or concludes the hunt.
The harness executes the tool itself - the tools are bound OUTSIDE the agent
(spec 4: the built-in session seam runs the whole model<->tool loop in ONE
`agent.invoke`, so intermediate tool calls do NOT return control; the explicit
node-per-step topology gives the harness control between steps), feeds the tool
result back as the next turn's input, and, when the write carried a lifecycle
status verbatim, drives the state graph's DETECTION + PUSH (R4, GP8c): the lists
move and the phase-transition constant (G9) is injected in the tool-call
response - a constant, never the system prompt. The passive machine NEVER gates
a tool call on the current state and never rejects an illegal transition.

The loop continues until the model concludes the hunt (the hypothesis list
exhausted) -> the graph lands END -> IDLE. The verdict-consumption workflow
graph is OUT OF SCOPE (R4/GP2-b): there is no `waiting-for-verdict` node;
`derive_verdict` stays a PURE function here but is STALE - its wiring lives in
the out-of-scope verdict graph. The dispatch result therefore reports the
terminal state and carries NO derived verdict.

Retired here (R1, spec 8): the prompt-composed `dispatch_fn` and its `kb` /
`pod` / `author` / `judge` seams. The symptom-technique KB typed seam
(`symptom_kb.py`, `SymptomTechniqueQuery`) is retired - the model consumes the
`AnswerBundleV1`-shaped dict the `kb_query` tool returns directly in its author
lane. The back-edge is cut completely (GP5) and replaced by the `exec` tool;
the exec tool is UNBOUNDED at the harness level (R2b) with the partition guard
(Q8): exec never produces the hypothesis verdict - the pod remains the only
source of experimental evidence for the committed hypothesis.

Everything external is a typed seam, injected at construction: the `graph_view` /
`kb_query` / `exec` tool bodies, the per-project `HunterMemoryStore`, the session
`model_factory` / `checkpointer` / compaction `middleware`. Never raise out of
`dispatch_fn`; every collaborator failure degrades (fail-open) and is flagged in
the feedback (O3/O4/C2/C3). The whole hunt runs under `hunting_span(run_id,
hunt_id)` + the `hunt_session` ContextVar rollback lane (unchanged) and under
`module_context("hunting")`, so `get_session_checkpointer()` resolves the
hunting module's in-memory index.

This module imports no driver and performs no I/O at import (CODING_STANDARD
section 6): the LLM seam pieces resolve lazily on call.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field

from polymerhus.attack.hunting.hunt_orchestrator import (
    DispatchResult,
    HuntConfig,
)
from polymerhus.attack.hunting.hunter_graph import build_hunter_graph
from polymerhus.attack.hunting.hunter_memory import HunterMemoryStore
from polymerhus.attack.hunting.hunter_state import FAULT_STATUSES
from polymerhus.attack.hunting.hunter_tools import (
    ExecFn,
    GraphViewFn,
    KbQueryFn,
    build_hunter_tools,
)
from polymerhus.attack.hunting.hunting_tracing import (
    flush_hunting_traces,
    hunting_span,
    trace_span,
)

logger = logging.getLogger(__name__)

# The hunter's session role (the `hunting_hunter` role record; `HuntSession`
# defaults to it). Single point of truth so the harness never hardcodes a string
# differently from the role registry / session address.
_HUNTER_ROLE = "hunting_hunter"

# The step-budget safety bound: the turn-by-turn loop is the model's to conclude,
# but a stalled or looping model must never pin a hunt forever (fail-open O3).
_MAX_STEPS = 60

# The D7 hypothesis verdict (Q3-amended, implementation doc 2.3): four values,
# derived by the harness, never by the LLM. KEPT PURE and STALE (R4): the wiring
# node lives in the OUT-OF-SCOPE verdict-consumption graph.
HypothesisVerdict = Literal[
    "successful", "unsuccessful", "insufficient-evidence", "underspecified-spec",
]


# --- the structured step request (Structured Output, R4) ----------------------

class HunterStep(BaseModel):
    """One ReAct step the model emits per turn (the structured output contract).

    `action="tool"` requests EXACTLY ONE tool call - `tool` names one of the five
    tools and `args` carries that tool's args (the per-tool args schemas from
    `hunter_tools.py`, `extra="forbid"`); the harness executes it and returns the
    result (plus any injected phase-transition constant, G9) as the next turn's
    input. `action="answer"` concludes the hunt - the harness lands the graph at
    END (idle). `reasoning` is the step's Chain-of-Thought, never the action
    itself. `extra="forbid"` (the pod's D84-22 discipline): an unknown field on a
    step is a contract violation and degrades the turn."""

    action: Literal["tool", "answer"]
    reasoning: str = ""
    tool: str = ""
    args: dict = Field(default_factory=dict)
    answer: str = ""

    model_config = ConfigDict(extra="forbid")


# --- the stable system prompt (single-sourced from the SKILL.md) ---------------

# The stable system prompt is single-sourced from
# `skills/hunting/hunting-agent/SKILL.md` through the shared `skill_for`
# (FR-SKILLIF), degraded to the terse fallback below when the mount is
# unavailable. The harness embeds it ahead of the FIRST step's input; the per-hunt
# session checkpointer carries it across the later steps, so it is never repeated
# into the conversation (the stateful-thread pattern, R4).
_HUNTING_AGENT_SKILL_FALLBACK = (
    "You are the hunting agent: the hypothesis formulation and verification "
    "agent of the hunting design/execution partition. For the dispatched "
    "HuntConfig, formulate candidate fault hypotheses for the testable unit, "
    "author a TestImplementationSpec for each candidate worth testing, and "
    "verify each hypothesis through the test-executor pod, ending with an "
    "evidence-backed verdict. You are a scientist, not a script writer: every "
    "spec is an experiment design, every claim must be backed by evidence you "
    "actually hold, and the pod is the only source of experimental evidence - "
    "you never declare success, the evidence does. A hypothesis is a candidate "
    "specific fault of the dispatched class. One hypothesis per spec; no "
    "bulldozing - never re-dispatch a closed candidate without new evidence. "
    "Degraded grounding (empty or raising KB, missing config parts) degrades "
    "the run, never raises; flag the gap in the feedback."
)


def _load_hunting_agent_skill() -> str:
    """The stable system prompt, single-sourced from
    `skills/hunting/hunting-agent/SKILL.md` through the shared `skill_for`:
    YAML frontmatter stripped, cached in-process, degraded to the terse
    fallback above when the mount is unavailable."""
    from polymerhus.recon.domain.skills import skill_for

    return skill_for("hunting/hunting-agent", fallback=_HUNTING_AGENT_SKILL_FALLBACK)


# --- pure helpers (kept from the #83 harness) ---------------------------------

def derive_verdict(
    terminal_reason: str,
    *,
    clean: bool,
    init_validation: list[str] | None = None,
) -> HypothesisVerdict:
    """The D7 verdict derivation (D67-02, Q3-amended; implementation doc 2.3).

    PURE and STALE as of R4: the wiring node lives in the OUT-OF-SCOPE
    verdict-consumption graph, not in this harness. Reads ONLY the pod's
    terminal reason plus the single `clean` flag (plus `init_validation` for the
    INIT-rejection case) - never per-variant machine outcomes, never the LLM.

    A terminal reason outside the ratified map is uninterpretable, so the
    derivation is conservative - `insufficient-evidence`, never a success or a
    clean absence claim (fail-open).
    """
    init_validation = init_validation or []
    if terminal_reason == "technical-infeasibility" and init_validation:
        return "underspecified-spec"
    if terminal_reason == "symptom-confirmed":
        return "successful"
    if terminal_reason in (
        "space-exhausted", "technical-infeasibility", "specific-defence-prevention",
    ):
        return "unsuccessful"
    if terminal_reason in ("no-symptom-evidence", "budget-timeout"):
        return "unsuccessful" if clean else "insufficient-evidence"
    return "insufficient-evidence"


def derive_technological_axis(card: dict | None) -> str:
    """The deterministic technological axis of a unit's index card (IA-8/D10).

    Prefers the typed spine's `api_paradigm`, then its `navigation_model`;
    falling back to the unit's kind (lowercased) keeps the axis deterministic
    and non-empty. A card with no axis signal reports "unknown". Pure and
    fail-open: a malformed card degrades to "unknown", never raises."""
    if not card:
        return "unknown"
    try:
        spine = card.get("spine") or {}
        for key in ("api_paradigm", "navigation_model"):
            value = spine.get(key)
            if value:
                return str(value).lower()
        kind = card.get("kind")
        return str(kind).lower() if kind else "unknown"
    except Exception:  # noqa: BLE001 - fail-open: an unreadable card is unknown
        return "unknown"


def _fmt_list(items) -> str:
    if not items:
        return "(none)"
    return "; ".join(str(i) for i in items)


def _config_gaps(config: HuntConfig) -> list[str]:
    """The O3 gap flags for a degraded HuntConfig: the agent still authors from
    the present parts (C4) and flags each missing part in the feedback."""
    gaps: list[str] = []
    if not (config.surface_context or {}).get("cards"):
        gaps.append("surface context missing (no adapted index cards); grounding degraded")
    if not config.prompt_template.rationale:
        gaps.append("orchestrator rationale missing; grounding degraded")
    if not config.target_caveats:
        gaps.append("target caveats missing; grounding degraded")
    return gaps


# --- the composed step templates (Template reuse) -----------------------------

# The step protocol: the structured-output contract the model follows every turn
# (Structured Output + Chain-of-Thought). Never changes across steps - the
# constant is the template; the variable parts (the hunt grounding, the tool
# surface, the state) compose the first step below and the tool results carry
# the later steps.
_STEP_PROTOCOL = (
    "Each turn emit EXACTLY ONE step as a structured object with the fields "
    "action, reasoning, tool, args, answer.\n"
    "- In 'reasoning', think step-by-step before deciding the action.\n"
    "- action='tool': request exactly one tool call. Set 'tool' to one of the "
    "tool names below and 'args' to that tool's args (a JSON object). The "
    "harness executes the tool and returns its result as the next message. A "
    "result may carry a <phase-transition-hint> - follow it as the next "
    "reasoning phase.\n"
    "- action='answer': conclude the hunt when the candidate set is exhausted "
    "or you judge every candidate processed; put the final rationale in "
    "'answer'.\n"
    "Never invent tool results. Never declare a hypothesis verified without "
    "evidence you actually hold. PARTITION GUARD: the exec tool never produces "
    "the hypothesis verdict - the pod remains the only source of experimental "
    "evidence for the committed hypothesis; exec results only inform your "
    "reasoning."
)

# The tool surface the model requests against (Template reuse): the same five
# tools `build_hunter_tools` binds, described verbatim from their contracts
# (`hunter_tools.py`). The model sees the surface here - the tools are executed
# by the harness between steps, never by the agent itself.
_TOOL_SURFACE = (
    "Tool surface - you request exactly ONE tool call per step:\n"
    "- hunts_store: the status-bearing memory seam. read / write. write takes "
    "the fault/spec object carrying the status verbatim (hypothesised | "
    "verified | dropped | specified) plus the fault_key and the fault_keyword / "
    "strategy_keyword naming the produced spec file; mode=create FAILS on a "
    "duplicate spec (reflect and merge or refresh, never duplicate), "
    "mode=update re-authors in place. read is by fault_key plus optional "
    "statuses / attributes filters.\n"
    "- notes: one note per fault covering all decisions that concern it. "
    "read / write; write options append | update | delete; the read is the "
    "grep-match read, latest-first.\n"
    "- graph_view: the read-only L0/L1 target-knowledge view. Takes a "
    "read-only Cypher query plus optional params; write-shaped calls are "
    "rejected.\n"
    "- kb_query: query the fault knowledge base (LightRAG) to ground your "
    "reasoning: the scenario's attack_goal and concern, the technology stack, "
    "target references, input vectors, known facts, the acceptable technique "
    "families, unsupported claims, observed evidence, and the retrieval "
    "config. Returns an AnswerBundleV1-shaped bundle: a summary, per-entity "
    "explanations with provenance references, and knowledge gaps. Consume it "
    "directly in your reasoning; an empty or degraded result means the KB has "
    "nothing further - degrade to your HuntConfig grounding and continue.\n"
    "- exec: run a command on the target's Kali execution surface: cheap "
    "claim-verification probes inside the loop. Each call is bounded by "
    "EXEC_TIMEOUT_S (an optional shorter timeout_s is accepted); the probe "
    "frequency is unbounded - you decide when to probe. PARTITION GUARD: exec "
    "never produces the hypothesis verdict."
)


def _compose_grounding(config: HuntConfig) -> str:
    """The HuntConfig's five-part parameter set rendered once, ahead of the
    first step (the #83 authoring template, reused verbatim in shape)."""
    tpl = config.prompt_template
    surface = config.surface_context or {}
    return (
        f"You are dispatched to hunt {config.unit_id} for fault class "
        f"{config.fault_class}.\n"
        f"Orchestrator's fault-matching rationale: {tpl.rationale or '(none)'}\n"
        f"Suggested extension points: {_fmt_list(tpl.extension_points)}\n"
        f"Adversarial-capability and environmental-precondition assumptions: "
        f"{_fmt_list(tpl.assumptions)}\n"
        f"Supposed payload vectors: {_fmt_list(tpl.supposed_payload_vectors)}\n"
        f"L0 fault-applicability evidence: {_fmt_list(tpl.l0_evidence)}\n"
        f"Adapted surface context (index card of {config.unit_id}): "
        f"{_fmt_list(surface.get('cards') or []) if surface.get('cards') else '(no adapted index cards)'}\n"
        f"Target caveats: {_fmt_list(config.target_caveats)}\n"
        f"Prior-hunt insights: {_fmt_list(config.prior_hunt_insights)}\n"
        f"Fault-targeting tool registry: {_fmt_list(config.tool_registry)}"
    )


def _state_summary(state: dict) -> str:
    """The semantic state rendered for the model / the terminal feedback: the
    `HuntState` lists (the model's write-time rank order), never the trail
    (replay only, never authoritative)."""
    lines = [f"phase: {state.get('phase', 'grounding')}"]
    for key, label in (
        ("hypothesised_faults", "hypothesised"),
        ("verified_faults", "verified"),
        ("dropped_faults", "dropped"),
        ("ratified_specs", "ratified"),
    ):
        for item in state.get(key) or []:
            if not isinstance(item, dict):
                continue
            ident = item.get("fault_id") or item.get("spec_id")
            mechanism = str(item.get("mechanism") or "")[:80]
            lines.append(f"- {label}: {ident} {mechanism}")
    if len(lines) == 1:
        lines.append("- (no faults tracked yet)")
    return "\n".join(lines)


def _compose_first_step(config: HuntConfig, state: dict) -> str:
    """The first step's input: the stable skill ahead of the hunt grounding, the
    tool surface, the current state, and the step protocol. Later steps resume
    the thread from the checkpoint, so the skill/surface/grounding are never
    repeated into the conversation."""
    return "\n\n".join([
        _load_hunting_agent_skill(),
        _compose_grounding(config),
        _TOOL_SURFACE,
        _state_summary(state),
        _STEP_PROTOCOL,
    ])


def _status_write(args: Any) -> tuple[str, dict] | None:
    """The observation the harness extracts from a `hunts_store` write: the
    `status` verbatim plus the fault/spec object. A non-write, a missing spec,
    or a status outside the lifecycle -> None (no state move - the passive
    machine records only what the model signalled on a lifecycle write)."""
    if not isinstance(args, dict) or args.get("command") != "write":
        return None
    spec = args.get("spec")
    if not isinstance(spec, dict):
        return None
    status = spec.get("status")
    if status not in FAULT_STATUSES:
        return None
    return status, dict(spec)


def _last_tool_call_id(messages) -> str | None:
    """The tool_call id of the step's AIMessage (the structured `HunterStep`
    call), so the harness can close it with the ToolMessage the next turn reads.
    None when the turn carried no tool call (a degraded step, fail-open)."""
    for message in reversed(messages or ()):
        tool_calls = getattr(message, "tool_calls", None) or []
        if tool_calls:
            return tool_calls[0].get("id")
    return None


def _terminal_feedback(state: dict, answer: str) -> str:
    """The terminal feedback: the model's concluding rationale plus the final
    semantic state (the trail stays replay-only, never in the feedback)."""
    answer = answer.strip()
    if answer:
        return f"{answer} | {_state_summary(state)}"
    return _state_summary(state)


# --- the harness --------------------------------------------------------------

def build_hunting_agent(
    *,
    run_id: str,
    project_id: str = "",
    memory_store: HunterMemoryStore | None = None,
    graph_view_fn: GraphViewFn | None = None,
    kb_fn: KbQueryFn | None = None,
    exec_fn: ExecFn | None = None,
    checkpointer=None,
    middleware=None,
    model_factory=None,
    observe: bool = True,
) -> Callable[[HuntConfig], Awaitable[DispatchResult]]:
    """Build the turn-by-turn hunting-agent dispatch seam (IA-2).

    `run_id` / `project_id` are the hunt's run and project (the project keys the
    per-project `HunterMemoryStore`); `memory_store` is that per-project store
    and `graph_view_fn` / `kb_fn` / `exec_fn` the injected tool seams (each
    absent degrades fail-open, O3/O4/C2/C3). `checkpointer` defaults to
    `get_session_checkpointer()` under `module_context("hunting")`; `middleware`
    defaults to the R5 compaction middleware (`build_hunter_compaction_middleware`,
    #95 D9) - capability (#99) negotiation attaches via the session seam itself.
    `model_factory` injects a fake model for tests; `observe` toggles session
    observability. Returns `async dispatch_fn(config: HuntConfig) -> DispatchResult`
    (the async-native harness; sync callers use `build_sync_hunting_agent`).

    The closure binds the injected seams once; each dispatch (hunt) compiles
    its OWN in-memory state graph (OUTLIER-1, no graph-level checkpointer),
    binds the per-hunt tool surface, and drives its turn-by-turn loop on its
    `HuntSession(run_id, hunt_id)` thread."""
    import inspect

    async def _await_seam(fn: Callable, *args):
        """Await an async seam, else offload a sync one to a worker thread
        (the unchanged #83 discipline - thin sync fakes stay injectable)."""
        if inspect.iscoroutinefunction(fn):
            return await fn(*args)
        return await asyncio.to_thread(fn, *args)

    async def _invoke_tool(tools_by_name: dict[str, Any], name: str, args: Any) -> str:
        """Execute one tool call the model requested. An unknown tool, malformed
        args, or a raising tool degrades to a denoted fail-open result - never a
        raise into the turn (O3/O4)."""
        tool = tools_by_name.get(name)
        if tool is None:
            return json.dumps({"error": "unknown_tool", "tool": name, "degraded": True})
        if not isinstance(args, dict):
            return json.dumps({"error": "invalid_args", "tool": name, "degraded": True})
        try:
            return str(await _await_seam(tool.invoke, args))
        except Exception as exc:  # noqa: BLE001 - fail-open, never into the turn
            logger.warning("hunter tool %s failed (%s)", name, exc)
            return json.dumps({"error": "tool_failed", "tool": name, "detail": str(exc)})

    async def _run_hunt(
        config: HuntConfig,
        feedback: list[str],
        checkpointer,
        middleware,
    ) -> DispatchResult:
        hunt_id = config.hunt_id
        compiled = build_hunter_graph().compile()
        tools_by_name = {
            tool.name: tool for tool in build_hunter_tools(
                store=memory_store, project_id=project_id,
                graph_view_fn=graph_view_fn, kb_fn=kb_fn, exec_fn=exec_fn,
            )
        }
        state: dict = {"phase": "grounding", "trail": []}

        from langchain.agents.structured_output import ToolStrategy  # noqa: PLC0415
        from langchain_core.messages import HumanMessage, ToolMessage  # noqa: PLC0415
        from polymerhus.app.llm.session import arun_session_turn  # noqa: PLC0415
        from polymerhus.app.llm.session_address import HuntSession  # noqa: PLC0415

        thread_id = HuntSession(run_id, hunt_id).thread_id
        new_messages = [HumanMessage(content=_compose_first_step(config, state))]

        for _step in range(_MAX_STEPS):
            try:
                turn = await arun_session_turn(
                    _HUNTER_ROLE, thread_id, new_messages,
                    checkpointer=checkpointer,
                    response_format=ToolStrategy(HunterStep),
                    middleware=middleware,
                    model_factory=model_factory,
                    observe=observe,
                )
            except Exception as exc:  # noqa: BLE001 - O3/C2/C3: degrade, never raise
                logger.warning("hunt %s step degraded (%s)", hunt_id, exc, exc_info=True)
                feedback.append(f"hunter turn unavailable ({exc})")
                break
            trace_span("hunter-step", input={"step": _step + 1})

            step = turn.content
            if not isinstance(step, HunterStep):
                # A degraded turn (unparseable / None content): the model did not
                # emit a structured step - fail-open, keep the hunt's state.
                feedback.append("hunter step degraded: no structured step returned")
                break

            if step.action != "tool":
                # The model concluded the hunt: the hypothesis list is exhausted
                # -> END -> idle (verdict consumption is the OUT-OF-SCOPE graph).
                state["phase"] = "concluded"
                feedback.append(_terminal_feedback(state, step.answer))
                return _assemble(state, feedback)

            call_id = _last_tool_call_id(turn.messages)
            if call_id is None:
                feedback.append("hunter step degraded: no tool call id on the step")
                break

            result = await _invoke_tool(tools_by_name, step.tool, step.args)
            observed = _status_write(step.args) if step.tool == "hunts_store" else None
            if observed is not None:
                status, fault = observed
                try:
                    # DETECTION + PUSH (R4, GP8c): the state tracker moves the
                    # lists and injects the phase-transition constant (G9).
                    driven = await compiled.ainvoke({
                        **state, "observed_status": status, "observed_fault": fault,
                    })
                    state = driven
                except Exception as exc:  # noqa: BLE001 - fail-open, keep serving
                    logger.warning("hunt %s state tracking degraded (%s)", hunt_id, exc)
                    feedback.append(f"state tracking degraded ({exc})")
                # The constant rides THIS tool-call response and is consumed:
                # it must never leak onto a later, unrelated tool result.
                hint = state.get("injected_constant")
                if hint:
                    result = (
                        f"{result}\n\n<phase-transition-hint>\n{hint}\n"
                        f"</phase-transition-hint>"
                    )
                    state["injected_constant"] = None
            trace_span("hunter-tool", input={"tool": step.tool, "args": step.args},
                       output=result[:500])
            new_messages = [ToolMessage(tool_call_id=call_id, content=result)]

        feedback.append(f"hunt {hunt_id} step budget exhausted ({_MAX_STEPS} steps)")
        return _assemble(state, feedback)

    def _assemble(state: dict, feedback: list[str]) -> DispatchResult:
        """The terminal assembly (the deterministic surface, spec 2.4): the
        terminal state summary rides the feedback; the hypothesis verdict is
        deliberately None - the verdict-consumption graph is OUT OF SCOPE and
        derives it from the pod-verdict messages the surfer feeds the idle hunt."""
        parts = [p for p in feedback if p]
        return DispatchResult(
            hypothesis_verdict=None,
            feedback=" | ".join(parts) if parts else _state_summary(state),
        )

    async def dispatch_fn(config: HuntConfig) -> DispatchResult:
        hunt_id = config.hunt_id
        feedback: list[str] = list(_config_gaps(config))
        # The seam pieces resolve lazily so this module stays driver-free at
        # import (CODING_STANDARD section 6): the checkpointer resolves under
        # `module_context("hunting")` (the module index), the R5 compaction
        # middleware (#95 D9) is built from the hunter role, and `hunt_session`
        # keeps the sync rollback lane stateful on the per-hunt thread.
        from polymerhus.attack.hunting.llm import (  # noqa: PLC0415
            build_hunter_compaction_middleware,
            hunt_session,
        )
        from polymerhus.app.llm.checkpoints import (  # noqa: PLC0415
            get_session_checkpointer,
            module_context,
        )
        try:
            with hunting_span(run_id, hunt_id), hunt_session(run_id, hunt_id):
                with module_context("hunting"):
                    cp = checkpointer if checkpointer is not None else get_session_checkpointer()
                    mw = middleware if middleware is not None else [build_hunter_compaction_middleware()]
                    return await _run_hunt(config, feedback, cp, mw)
        except Exception as exc:  # noqa: BLE001 - never raise out of dispatch_fn
            logger.warning("hunt %s degraded (%s)", hunt_id, exc, exc_info=True)
            return DispatchResult(hypothesis_verdict=None,
                                  feedback=f"hunt {hunt_id} degraded: {exc}")
        finally:
            flush_hunting_traces()

    return dispatch_fn


def build_sync_hunting_agent(**kwargs):
    """The SYNC lane of the hunting-agent harness: a thin wrapper that runs the
    async `build_hunting_agent` dispatch to completion, so the harness canon is
    never re-implemented (the mirror of `hunt_orchestrator.run_orchestration`).

    Sync injectable seams travel through `asyncio.to_thread` inside the canon;
    async seams are awaited natively. When called from a running event loop,
    `run_coro_blocking` runs the dispatch on a separate thread so `asyncio.run`
    is never re-entered on the caller's loop."""
    from polymerhus.recon.control.async_bridge import run_coro_blocking  # noqa: PLC0415

    dispatch_fn = build_hunting_agent(**kwargs)

    def dispatch(config: HuntConfig) -> DispatchResult:
        return run_coro_blocking(dispatch_fn(config))

    return dispatch