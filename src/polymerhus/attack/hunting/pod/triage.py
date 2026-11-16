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

import inspect
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
    hit). Every saver shape is served: an async-only `aget_tuple` (a
    `BaseCheckpointSaver` subclass whose inherited `get_tuple` raises), a
    coroutine-shaped `get_tuple`, and a dual sync saver. Each read attempt
    falls through to the next on its own failure."""
    if checkpointer is None:
        return 0
    config = {"configurable": {"thread_id": thread_id}}
    readers = []
    aget = getattr(checkpointer, "aget_tuple", None)
    if aget is not None:
        readers.append(aget)
    get_tuple = getattr(checkpointer, "get_tuple", None)
    if get_tuple is not None:
        readers.append(get_tuple)
    for read in readers:
        try:
            tup = read(config)
            if inspect.isawaitable(tup):
                tup = await tup
        except Exception:  # noqa: BLE001 - fail-open: an unreadable saver costs no decision
            logger.debug("thread-count read failed on %s", type(checkpointer).__name__)
            continue
        if tup is None:
            continue
        checkpoint = getattr(tup, "checkpoint", None)
        if checkpoint is None and isinstance(tup, dict):
            checkpoint = tup
        values = (checkpoint or {}).get("channel_values") or {}
        return len(values.get("messages") or [])
    return 0


def _is_provider_error(exc: BaseException) -> bool:
    """Whether one closing-turn failure is the typed provider failure (#329)."""
    from polymerhus.app.llm.provider_failure import as_provider_error

    return as_provider_error(exc) is not None


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
    from langchain_core.messages import ToolMessage

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

    # The CONSTANT base surface, bound ONCE per decision (invariant 2): the
    # read-only triager tools plus the #236 skill binding. Only the two gate
    # closures vary by phase; they overlay the base dict per step.
    binding = auth_capable_binding(
        role_id, task_skills=harness_ctx.task_skills,
        project_id=project_id or None,
        with_readonly_auth_store=True)
    base_list = [*triager_react_tools(
        harness_ctx.memory_store, harness_ctx.spec_id, log=harness_ctx.log,
        variant_ref=harness_ctx.variant_ref or "",
        graph_view_fn=harness_ctx.graph_view_fn,
        browser_tool=harness_ctx.browser_tool), *binding.tools]
    base_tools = {t.name: t for t in base_list}
    request_tools = [*[_openai_tool_dict(t) for t in base_list],
                     *triage_request_tools()]

    def _surface(assessment, phase) -> tuple[list[dict], dict]:
        """The per-step surface: the constant base plus the gates re-bound to
        the live phase. The request-side dicts are the hoisted constants; only
        the executor dict gains the phase's gate closures."""
        by_name = {**base_tools,
                   **build_triage_gate_tools(facts, assessment, phase)}
        return (request_tools, by_name)

    # The thread's prior message count rides the facts: every decision's
    # packet is unique on its thread, so a re-dispatched pod's lap-1 packet is
    # never byte-identical to the one already there (an identical stamped id
    # would replace in place instead of appending).
    facts = {**facts, "prior_turns": await _thread_message_count(
        session_ctx.checkpointer, mem_key)}
    state: dict = {
        "phase": "assess", "observed_signal": None, "observed_args": None,
        "observed_outcome": None, "facts": dict(facts), "assessment": None,
        "injected_constant": None, "trail": [], "decision": None,
    }
    # The ASSESS verbatim and the bound-skill LISTING ride the first decision
    # of the THREAD - the lap counter on a resumed pod is not enough (a
    # resumed pod starts at lap N on a thread that has never seen either).
    include_base = lap <= 1 or facts.get("prior_turns", 0) == 0
    base_parts = []
    if include_base:
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
                                            include_verbatim=include_base))
    base = "\n\n".join(part for part in base_parts if part)
    new_messages = _dicts_to_lc([{"role": "human", "content": base}])
    rejections: list[str] = []
    steps = 0
    results: list = []

    for _step in range(max_steps):
        steps = _step + 1
        request_tools, tools_by_name = _surface(
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
                # The gate closures are phase transaction gates: after an
                # accepted signal the machine may have moved, so the surface's
                # gates re-bind to the LIVE phase before the next call in this
                # turn is answered.
                tools_by_name.update(build_triage_gate_tools(
                    facts, state.get("assessment"), state["phase"]))
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
        new_messages = list(results)

    # The thread contract (#280 positional adjacency): the gate's answer must
    # FOLLOW its call in the thread. The loop exits as soon as the machine is
    # done OR the budget exhausts, so the final tool results would otherwise
    # dangle - and any resume of this thread (the next lap, a re-dispatched
    # pod) would trip the adjacency contract. The closing turns feed the
    # PENDING results back - each round sends only the calls it has NOT yet
    # answered, never a consumed answer (an orphan `tool` message is rejected
    # by the upstream with a 400 this repo does not classify as a provider
    # failure). The replies are discarded. The gates are CLOSED on a closing
    # turn (whatever phase the machine holds), so a post-decision submission
    # is a coded rejection, never an accepted signal. A closing turn whose
    # model emits more calls gets its calls answered once more (bounded); the
    # budget is surfaced for the operator.
    closing_tools = {**base_tools,
                     **build_triage_gate_tools(facts, state.get("assessment"),
                                               "close")}
    closing_budget = 3
    pending = list(results)
    last_round_emitted_calls = False
    while pending and closing_budget:
        closing_budget -= 1
        try:
            closing = await turn_fn(
                role_id, mem_key, list(pending),
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
        except Exception as exc:
            # A closing turn is cosmetic by definition (the replies are
            # discarded): its failure must never cost the pod a decision the
            # machine already reached. Break with the results as they stand -
            # the input results are persisted BEFORE the model call, so the
            # gate answers are already in the thread and only the closing
            # reply is lost. A provider failure with NO reached decision
            # still propagates (#329: the surfer owns the retry).
            if _is_provider_error(exc) and state.get("decision") is None:
                raise
            logger.warning(
                "triage closing turn failed on %s (%s); the decision stands",
                mem_key, exc)
            break
        calls = _last_tool_calls(closing.messages)
        if not calls:
            break
        last_round_emitted_calls = True
        pending = []
        for tc in calls:
            answer = await invoke_fn(closing_tools, tc.get("name", ""),
                                     tc.get("args") or {})
            if not gate_accepted(answer) and tc.get("name") in (
                    ASSESSMENT_TOOL, DECISION_TOOL):
                rejections.append(answer)
            pending.append(ToolMessage(tool_call_id=tc.get("id") or "",
                                       content=answer))
    if pending and closing_budget == 0 and last_round_emitted_calls:
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
    # The phase path: the ratified vocabulary (assess, assess>decide,
    # assess>variant, assess>decide>variant, assess>decide>terminal). An
    # advance records the phase the machine moved to; a decision records its
    # kind - unless it landed at ASSESS, where a confirmation is the bare
    # assess path and only a divergence extends it.
    tokens = ["assess"]
    advanced = False
    for entry in state.get("trail", []):
        kind = str(entry.get("kind") or "")
        if kind in ("variant", "terminal"):
            if advanced:
                tokens.append(kind)
            elif kind == "variant":
                tokens.append("variant")
            # a terminal landing at ASSESS is the bare assess path
        else:
            advanced = True
            tokens.append(str(entry.get("phase") or "decide"))

    return {"decision": decision, "assessment": state.get("assessment"),
            "steps": steps, "rejections": rejections,
            "phase_path": ">".join(tokens)}


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
