"""The hunting agent (#83, as of #164 W5): the turn-by-turn ReAct host.

The hunt-orchestrator (#82) feeds this module one declarative `HuntConfig` per
hunt (IA-2); the harness drives the model through the ratified tool surface
(`hunts_store` / `notes` / `graph_view` / `kb_query` / `exec`, R3/R1/R2) as a
turn-by-turn ReAct loop OVER the state-graph hunter (`hunter_graph.py`).
Persistence rides the per-project hunter memory store (spec 6) - the harness
writes no hunt-store records - and the harness derives no verdict: the hunt
idles at END (spec 2.4, R4/GP2-b).

The harness is the TURN-BY-TURN DRIVER (ADR R4): per LLM step it runs ONE
`arun_session_turn` on the per-hunt `HuntSession(run_id, hunt_id)` thread, so
every LLM call rides the session seam and the checkpointer, compaction (#95 D9),
and capability (#99) negotiation attach. Each turn uses the STANDARD tool
interface: the five tools are bound REQUEST-ONLY (`convert_to_openai_tool`) so
their JSON schemas ride the generation request's `tools` body, but no ToolNode
is created - the model emits a real tool call per turn (valid args per schema)
and concludes with a plain answer, and the harness stays the sole executor.
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

from polymerhus.attack.hunting.hunt_orchestrator import (
    DispatchResult,
    HuntConfig,
)
from polymerhus.attack.hunting.hunt_store import HuntStore
from polymerhus.attack.hunting.hunter_graph import build_hunter_graph
from polymerhus.attack.hunting.hunter_memory import HunterMemoryStore
from polymerhus.attack.hunting.hunter_state import D3_HINT, FAULT_STATUSES
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


# --- the turn contract (the standard tool interface, R4) ----------------------

# The turn carries NO wrapper schema. The five tools are bound to the generation
# request request-only (`tools=[convert_to_openai_tool(t) for t in tools]` - the
# schemas ride the request's `tools` body, but the agent's ToolNode is never
# created, so the harness remains the sole executor). The model emits a REAL
# tool call per turn (name + args per that tool's JSON schema) and concludes
# with a plain answer (no tool calls). The harness reads the turn's tool calls,
# executes them, drives the passive state machine on each status write, and
# feeds the ToolMessages back as the next turn's input.


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


def _fmt_aggregated_endpoints(endpoints) -> str:
    """Deterministic render of the aggregated L0 endpoints a card carries
    (#201): `METHOD path (baseurl: X)` plus `[service: slug]` when the entry
    carries an owning service (a System card's linked-services aggregates) -
    the typed identity props, sorted. An absent or empty slot renders
    '(none)'; a malformed entry is skipped, never a raise."""
    lines = []
    for entry in endpoints:
        if not isinstance(entry, dict):
            continue
        parts = []
        if entry.get("method"):
            parts.append(entry["method"])
        if entry.get("path"):
            parts.append(entry["path"])
        if entry.get("baseurl"):
            parts.append(f"(baseurl: {entry['baseurl']})")
        if entry.get("service_slug"):
            parts.append(f"[service: {entry['service_slug']}]")
        if parts:
            lines.append(" ".join(parts))
    return "; ".join(sorted(lines)) or "(none)"


def _config_gaps(config: HuntConfig) -> list[str]:
    """The O3 gap flags for a degraded HuntConfig: the agent still authors from
    the present parts (C4) and flags each missing part in the feedback. The
    #202 shape: the renamed `observed_defences` and the merged `preconditions`
    (both G1) are flagged on their new names, never the old vocabulary."""
    gaps: list[str] = []
    sc = config.surface_context or {}
    # both the canonical {"cards": [...]} wrapper and the legacy direct flat
    # shape (a card carrying `kind`) count as present (#201)
    if not (sc.get("cards") or sc.get("kind")):
        gaps.append("surface context missing (no adapted index cards); grounding degraded")
    if not config.prompt_template.rationale:
        gaps.append("orchestrator rationale missing; grounding degraded")
    if not config.observed_defences:
        gaps.append("observed target defences missing; falsification grounding degraded")
    if not config.preconditions:
        gaps.append("test preconditions missing; feasibility grounding degraded")
    return gaps


# --- the composed step templates (Template reuse) -----------------------------

# The step protocol: the structured-output contract the model follows every turn
# (Structured Output + Chain-of-Thought). Never changes across steps - the
# constant is the template; the variable parts (the hunt grounding, the tool
# surface, the state) compose the first step below and the tool results carry
# the later steps.
_STEP_PROTOCOL = (
    "Each turn you either call one or more of the tools below, or conclude the "
    "hunt.\n"
    "- A tool call is a standard function call: 'name' is one of the tool names "
    "below and 'args' is a JSON object conforming EXACTLY to that tool's JSON "
    "schema (the schemas are supplied with this request; unknown fields are "
    "rejected). The harness executes the tool and returns its result as the "
    "next message. A result may carry a <phase-transition-hint> - follow it as "
    "the next reasoning phase.\n"
    "- Conclude the hunt when the candidate set is exhausted or you judge every "
    "candidate processed: reply with a plain message carrying the final "
    "rationale (no tool call).\n"
    "Never invent tool results. Never declare a hypothesis verified without "
    "evidence you actually hold. PARTITION GUARD: the exec tool never produces "
    "the hypothesis verdict - the pod remains the only source of experimental "
    "evidence for the committed hypothesis; exec results only inform your "
    "reasoning."
)

# The tool surface the model requests against (Template reuse): derived from the
# actual bound tools' own contracts (`hunter_tools.py`), name + description -
# never a hand-written parallel copy (the tool contracts are the single source).
# The model sees the surface here - the tools are executed by the harness
# between steps, never by the agent itself.
def _tool_surface(tools) -> str:
    lines = "\n".join(f"- {t.name}: {t.description}" for t in tools)
    return f"Tool surface - you request exactly ONE tool call per step:\n{lines}"


def _compose_grounding(config: HuntConfig) -> str:
    """The HuntConfig's parameter set rendered once, ahead of the first step:
    the orchestrator's stretch (rationale, the G1 feasibility research
    direction, the vulnerability class - the initial concretisation, the L0
    evidence, the surface context, the ratification-phase `observed_defences`
    and `preconditions`) plus the further-concretisation material (sub-fault
    reflection ids, the downstream prior-hunt insights). Rendered from the
    current declarative shape (#165 typing rework + #202 lean config): ordered
    by the three goals (G1 feasibility -> G2 the vulnerability-class naming ->
    G3 further directions); the redundant slots (`technique_primitives`,
    `adversarial_capabilities`, `assumptions`, `tool_registry`, the renamed
    `target_caveats`) are gone - the #164 hunter owns the concrete-fault
    stretch."""
    tpl = config.prompt_template
    surface = config.surface_context or {}
    # The surface context is the adapted index-card: the ratified configs carry
    # it DIRECTLY (kind/key/label/spine/data_items/system_edges/aggregated_endpoints);
    # the `{"cards": [...]}` wrapper is the legacy/scripted shape. Render either.
    cards = surface.get("cards") or ([surface] if surface.get("kind") else [])
    surface_text = _fmt_list(cards) if cards else "(no adapted index cards)"
    aggregated: list[dict] = []
    for card in cards:
        if isinstance(card, dict):
            aggregated.extend(card.get("aggregated_endpoints") or [])
    if aggregated:
        surface_text += f"; aggregated endpoints: {_fmt_aggregated_endpoints(aggregated)}"
    return (
        f"You are dispatched to hunt {config.unit_id} for fault class "
        f"{config.fault_class}.\n"
        f"Orchestrator's fault-matching rationale: {tpl.rationale or '(none)'}\n"
        f"Vulnerability class (the initial concretisation): "
        f"{config.vulnerability_class or '(none)'}\n"
        f"Class-level research direction (feasibility): "
        f"{tpl.research_direction or '(none)'}\n"
        f"L0 fault-applicability evidence: {_fmt_list(tpl.l0_evidence)}\n"
        f"Adapted surface context (index card of {config.unit_id}): "
        f"{surface_text}\n"
        f"Observed target defences (hinder the tests / support falsification): "
        f"{_fmt_list(config.observed_defences)}\n"
        f"Test preconditions (attacker + environment): "
        f"{_fmt_list(config.preconditions)}\n"
        f"Sub-fault reflection material: {_fmt_list(config.sub_fault_ids)}\n"
        f"Prior-hunt insights (downstream specs + pod verdicts): "
        f"{_fmt_list(config.prior_hunt_insights)}"
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


def _compose_first_step(config: HuntConfig, state: dict, tool_surface: str) -> str:
    """The first step's input: the stable skill ahead of the hunt grounding, the
    tool surface, the current state, and the step protocol. Later steps resume
    the thread from the checkpoint, so the skill/surface/grounding are never
    repeated into the conversation."""
    return "\n\n".join([
        _load_hunting_agent_skill(),
        _compose_grounding(config),
        tool_surface,
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


def _last_tool_calls(messages) -> list[dict]:
    """The tool_calls of the CURRENT turn's AIMessage - the standard function-call
    contract. The agent returns right after the model node (no ToolNode), so the
    last message is this turn's AIMessage: [] means the model concluded with a
    plain answer. Never scans the history - a prior turn's resolved tool call
    must not be mistaken for a fresh one."""
    last = messages[-1] if messages else None
    if last is None:
        return []
    tool_calls = getattr(last, "tool_calls", None) or []
    return [dict(tc) for tc in tool_calls]


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
    hunt_store: HuntStore | None = None,
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
    and `hunt_store` the per-project `HuntStore` whose persisted config
    identities the fault_key gate validates against (#199 - absent degrades the
    gate to convention-only, fail-open); `graph_view_fn` / `kb_fn` / `exec_fn`
    the injected tool seams (each
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
        tools = build_hunter_tools(
            store=memory_store, project_id=project_id, hunt_store=hunt_store,
            graph_view_fn=graph_view_fn, kb_fn=kb_fn, exec_fn=exec_fn,
        )
        tools_by_name = {tool.name: tool for tool in tools}
        state: dict = {"phase": "grounding", "trail": []}

        from langchain_core.messages import HumanMessage, ToolMessage  # noqa: PLC0415
        from langchain_core.utils.function_calling import (  # noqa: PLC0415
            convert_to_openai_tool,
        )
        from polymerhus.app.llm.session import arun_session_turn  # noqa: PLC0415
        from polymerhus.app.llm.session_address import HuntSession  # noqa: PLC0415

        thread_id = HuntSession(run_id, hunt_id).thread_id
        new_messages = [HumanMessage(
            content=_compose_first_step(config, state, _tool_surface(tools)))]
        # The five tools ride the generation request REQUEST-ONLY (the standard
        # tool interface): each `convert_to_openai_tool` dict carries its JSON
        # schema in the request's `tools` body - the model emits valid args per
        # schema - but no ToolNode is created (all five are `built_in_tools`), so
        # the agent never executes them and the harness stays the sole executor
        # between turns (option B, the R4 turn-by-turn driver). Capability (#99)
        # still attaches natively via the session seam (A1 negotiation + A5
        # adaptor); every turn rides `arun_session_turn`.
        request_tools = [convert_to_openai_tool(t) for t in tools]

        for _step in range(_MAX_STEPS):
            try:
                turn = await arun_session_turn(
                    _HUNTER_ROLE, thread_id, new_messages,
                    checkpointer=checkpointer,
                    tools=request_tools,
                    middleware=middleware,
                    model_factory=model_factory,
                    observe=observe,
                )
            except Exception as exc:  # noqa: BLE001 - O3/C2/C3: degrade, never raise
                logger.warning("hunt %s step degraded (%s)", hunt_id, exc, exc_info=True)
                feedback.append(f"hunter turn unavailable ({exc})")
                break
            trace_span("hunter-step", input={"step": _step + 1})

            tool_calls = _last_tool_calls(turn.messages)
            if not tool_calls:
                # The model concluded the hunt with a plain answer: the
                # hypothesis list is exhausted -> END -> idle. The terminal phase
                # is `concluded` (spec 2.4's deterministic surface): the harness
                # lands the state, derives NO verdict (the verdict-consumption
                # graph is OUT OF SCOPE and derives it from the pod-verdict
                # messages the surfer feeds the idle hunt), and the dispatch
                # result reports the terminal state.
                state["phase"] = "concluded"
                feedback.append(_terminal_feedback(state, str(turn.content or "")))
                return _assemble(state, feedback)

            if not all(tc.get("id") for tc in tool_calls):
                feedback.append("hunter step degraded: a tool call carries no id")
                break

            results: list[ToolMessage] = []
            for tc in tool_calls:
                tool_name = str(tc.get("name") or "")
                tool_args = tc.get("args") or {}
                result = await _invoke_tool(tools_by_name, tool_name, tool_args)
                observed = _status_write(tool_args) if tool_name == "hunts_store" else None
                if observed is not None:
                    status, fault = observed
                    try:
                        # DETECTION + PUSH (R4, GP8c): the state tracker moves
                        # the lists and injects the phase-transition constant (G9).
                        driven = await compiled.ainvoke({
                            **state, "observed_status": status, "observed_fault": fault,
                        })
                        state = driven
                    except Exception as exc:  # noqa: BLE001 - fail-open, keep serving
                        logger.warning("hunt %s state tracking degraded (%s)", hunt_id, exc)
                        feedback.append(f"state tracking degraded ({exc})")
                elif tool_name == "kb_query" and state.get("phase") == "grounding":
                    # The grounding-phase D3 prompt (spec 2.3): a kb_query call
                    # while the harness is still grounded prompts the D3
                    # retrieval-gap check. Not a transition (no status write),
                    # so it injects here, never through the graph.
                    state["injected_constant"] = D3_HINT
                # The constant rides THIS tool-call response and is consumed:
                # it must never leak onto a later, unrelated tool result.
                hint = state.get("injected_constant")
                if hint:
                    result = (
                        f"{result}\n\n<phase-transition-hint>\n{hint}\n"
                        f"</phase-transition-hint>"
                    )
                    state["injected_constant"] = None
                trace_span("hunter-tool", input={"tool": tool_name, "args": tool_args},
                           output=result[:500])
                results.append(ToolMessage(tool_call_id=tc.get("id"), content=result))
            new_messages = results
        else:
            # A natural loop end (no break) is genuine budget exhaustion; the
            # break paths above already reported their own degradation, so a
            # degraded turn must never surface a budget message.
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