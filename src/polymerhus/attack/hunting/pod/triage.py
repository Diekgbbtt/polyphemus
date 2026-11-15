"""The triage harness (lifecycle v2): the two-phase chain on one thread.

The triager walks TWO phases in this order:

1. **ASSESS** - one turn through `submit_assessment` (confirmation,
   divergence, clean, note);
2. **DECIDE** - one turn through `submit_decision` (the honest terminal, or
   ONE new falsifiable variant).

The order is STRUCTURAL: the machine advances only on an accepted gate call,
and the decision - never a pod terminal - is what the graph renders. The
harness loop (`run_triage_harness`) mirrors `build_hunting_agent`: one
`arun_session_turn` per step, the immutable contract prompt and the constant
request-only tool surface on every step, the harness as the sole tool
executor, and the phase packet appended once to the accepted gate response.
"""
from __future__ import annotations

import logging
from typing import Sequence

from polymerhus.attack.hunting.pod.types import (
    NO_SYMPTOM_EVIDENCE,
    skill_concretised_procedure_from_spec,
)
from polymerhus.attack.hunting.pod.variant_basis import PROCEDURE_GAP_FIELD

logger = logging.getLogger(__name__)

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


async def _thread_message_count(checkpointer, thread_id: str) -> int:
    """The thread's persisted message count, or 0 (stateless or unreadable -
    fail-open: the packet then simply repeats, which only a re-dispatch can
    hit). An async-native saver is read through its async seam."""
    if checkpointer is None:
        return 0
    try:
        from polymerhus.app.llm.session import (
            _aread_thread_state,
            _read_thread_state,
        )

        if getattr(checkpointer, "aget_tuple", None) is not None and \
                not hasattr(checkpointer, "get_tuple"):
            state = await _aread_thread_state(checkpointer, thread_id)
        else:
            state = _read_thread_state(checkpointer, thread_id)
        return len((state or {}).get("messages") or [])
    except Exception:  # noqa: BLE001 - fail-open, never into the turn
        return 0


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
    from polymerhus.app.auth.seams import auth_capable_binding
    from polymerhus.app.llm.skills import _bound_skills
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
    from polymerhus.attack.hunting.pod.triage_graph import (
    DECIDE_PACKET_SENTINEL,
    build_triage_graph,
)
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

    def _surface(assessment, phase) -> tuple[list[dict], dict]:
        """The CONSTANT tool surface: the read-only triager tools, the #236
        skill binding (load_skill + record_skill_lesson + the read-only auth
        store), and the two gates, bound once per lap and identical on every
        step. The request-side dicts are projected once; the gate schemas come
        from the gate models, so the schema the model sees is the schema the
        gate validates."""
        base = triager_react_tools(
            harness_ctx.memory_store, harness_ctx.spec_id, log=harness_ctx.log,
            variant_ref=harness_ctx.variant_ref or "",
            graph_view_fn=harness_ctx.graph_view_fn,
            browser_tool=harness_ctx.browser_tool)
        binding = auth_capable_binding(
            role_id, task_skills=harness_ctx.task_skills,
            project_id=project_id or None,
            with_readonly_auth_store=True)
        base = [*base, *binding.tools]
        by_name = {tool.name: tool for tool in base}
        by_name.update(build_triage_gate_tools(facts, assessment, phase))
        return ([*[_openai_tool_dict(tool) for tool in base],
                 *triage_request_tools()], by_name, binding)

    state: dict = {
        "phase": "assess", "observed_signal": None, "observed_args": None,
        "observed_outcome": None, "facts": dict(facts), "assessment": None,
        "injected_constant": None, "trail": [], "decision": None,
    }
    # The thread's prior message count rides the facts: every decision's
    # packet is unique on its thread, so a re-dispatched pod's lap-1 packet is
    # never byte-identical to the one already there (an identical stamped id
    # would replace in place instead of appending).
    facts["prior_turns"] = await _thread_message_count(session_ctx.checkpointer,
                                                       mem_key)
    request_tools, tools_by_name, binding = _surface(None, "assess")
    # The ASSESS verbatim rides the base packet on the FIRST decision of the
    # thread - the lap counter on a resumed pod is not enough (a resumed pod
    # starts at lap N on a thread that has never seen the verbatim).
    include_verbatim = lap <= 1 or facts.get("prior_turns", 0) == 0
    base_parts = []
    if lap <= 1:
        # Q5: the bound-skill LISTING rides the first human message - the one
        # phase surface that names the skills, never the system prompt.
        from polymerhus.app.llm.skills import render_skill_index

        listing = render_skill_index(
            _bound_skills(binding.context),
            project_id=project_id or None)
        if listing:
            base_parts.append(listing)
    base_parts.append(compose_assess_packet(log, spec, observation, facts,
                                            store=store, spec_id=spec_id,
                                            order=order,
                                            include_verbatim=include_verbatim))
    base = "\n\n".join(part for part in base_parts if part)
    new_messages = _dicts_to_lc([{"role": "human", "content": base}])
    rejections: list[str] = []
    steps = 0
    results: list = []

    for _step in range(max_steps):
        steps = _step + 1
        request_tools, tools_by_name, binding = _surface(
            state.get("assessment"), state["phase"])
        turn = await turn_fn(
            role_id, mem_key, new_messages,
            checkpointer=session_ctx.checkpointer,
            tools=request_tools,
            system_prompt=contract,
            middleware=list(middleware),
            context=binding.context,
            observe=True,
            extra_tags=[run_id, mem_key, f"lap:{lap}",
                        f"phase:{state['phase']}"],
            usage_scope=project_id,
            model_factory=harness_ctx.model_factory,
        )
        tool_calls = _last_tool_calls(turn.messages)
        if not tool_calls:
            # A model error, never a verdict: the bounded correction. The
            # previous step's results were already delivered (they rode this
            # turn's input), so they must not be re-sent.
            results = []
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
                state = await graph.ainvoke({
                    **state, "observed_signal": signal,
                    "observed_args": tc.get("args") or {}})
            # The advance node set the SENTINEL only when the route continues
            # (an assessment that advanced to DECIDE); the packet is composed
            # here, once, and the DECIDE material is this lap's state.
            if state.get("injected_constant") == DECIDE_PACKET_SENTINEL:
                material = compose_decide_packet(log, spec, facts, store=store,
                                                 spec_id=spec_id, order=order)
                result = (f"{result}\n\n<phase-packet>\n"
                          f"{load_pod_decide_verbatim()}\n\n{material}\n"
                          "</phase-packet>")
                state = {**state, "injected_constant": None}
            results.append(ToolMessage(tool_call_id=tc.get("id") or "",
                                       content=result))
        if state["phase"] == "done":
            break
        new_messages = [
            m if isinstance(m, (ToolMessage, HumanMessage, AIMessage)) else m
            for m in results]

    # The thread contract (#280 positional adjacency): the gate's answer must
    # FOLLOW its call in the thread. The loop exits as soon as the machine is
    # done, so the final tool results would otherwise dangle - and any resume
    # of this thread (the next lap, a re-dispatched pod) would trip the
    # adjacency contract. The closing turns feed the results back; the replies
    # are discarded. The gates are CLOSED on a closing turn (the machine is
    # done), so a post-decision submission is a coded rejection, never an
    # accepted signal. A closing turn whose model emits more calls gets its
    # calls answered once more (bounded); on exhaustion the leftover calls are
    # surfaced for the operator.
    closing_tools = {**{t.name: t for t in
                        (triager_react_tools(
                            harness_ctx.memory_store, harness_ctx.spec_id,
                            log=harness_ctx.log,
                            variant_ref=harness_ctx.variant_ref or "",
                            graph_view_fn=harness_ctx.graph_view_fn,
                            browser_tool=harness_ctx.browser_tool))},
                     **build_triage_gate_tools(facts, state.get("assessment"),
                                               "done")}
    closing_budget = 3
    while results and closing_budget:
        closing_budget -= 1
        closing = await turn_fn(
            role_id, mem_key, list(results),
            checkpointer=session_ctx.checkpointer,
            tools=request_tools,
            system_prompt=contract,
            middleware=list(middleware),
            context=binding.context,
            observe=True,
            extra_tags=[run_id, mem_key, f"lap:{lap}", "phase:close"],
            usage_scope=project_id,
            model_factory=harness_ctx.model_factory,
        )
        calls = _last_tool_calls(closing.messages)
        if not calls:
            break
        results = [
            ToolMessage(tool_call_id=tc.get("id") or "",
                        content=await invoke_fn(closing_tools,
                                                tc.get("name", ""),
                                                tc.get("args") or {}))
            for tc in calls]
    if results and not closing_budget:
        logger.warning(
            "triage closing budget exhausted with unanswered tool calls on %s",
            mem_key)

    decision = state.get("decision")
    if decision is None:
        # The budget exhausted without a gate call: the same honest degrade the
        # malformed-decision path has always used. It is marked `degraded` - a
        # NO-EVALUATION outcome, which a control-plane kill overrides (the
        # harness terminal stands; no domain verdict is fabricated).
        decision = {
            "action": "terminate", "classification": "noise",
            "verdict": "unsuccessful", "terminal_reason": NO_SYMPTOM_EVIDENCE,
            "clean": False, "degraded": True,
            "note": ("triage step budget exhausted without a gate submission; "
                     "degraded"),
        }
    # The phase path: the ratified vocabulary. An advance records the phase
    # the machine moved to; a decision records the decision kind.
    def _path_token(entry: dict) -> str:
        if entry.get("kind") in ("variant", "terminal"):
            return str(entry["kind"])
        return str(entry.get("phase", ""))

    return {"decision": decision, "assessment": state.get("assessment"),
            "steps": steps, "rejections": rejections,
            "phase_path": ">".join(
                ["assess", *[_path_token(e) for e in state.get("trail", [])]])}


def has_populated_procedure(spec: dict) -> bool:
    """Whether the spec's typed `SkillProcedure` carries at least one populated
    field - the only material a bounded variant can bend.

    An absent excerpt or an all-empty one has nothing to diff, so no variant
    basis is derivable: `variant_allowed` is false and the triager terminates
    with the honest terminal."""
    procedure = skill_concretised_procedure_from_spec(spec)
    if procedure is None:
        return False
    return any(str(getattr(procedure, field) or "").strip()
               for field in PROCEDURE_GAP_FIELD.values())
