"""The hunting agent (S3 8.4-8.9, T6 #379): the turn-by-turn ReAct host.

The harness drives the model through the ratified loop tool surface
(`hunts_store` / `notes` / `graph_view` / `kb_query` / `exec` / `skill_list` /
`skill_load`, R3/R1/R2, S3 8.7) as a turn-by-turn ReAct loop OVER the
pass-chain tracker (`hunter_graph.py`). It is dispatched with ONE loop PAYLOAD
(S2 8.2: the loop record, the unit context, the trust agreement or transition,
the programming fault, the two classes, the evidence, the likelihood and the
target context) - never a `HuntConfig` (retired T6). Persistence rides the
per-project hunter memory store under the loop dispatch id
`<unit_name>__<loop_id>` (S3 8.9), and the harness derives no verdict: the hunt
idles at END (R4/GP2-b).

The harness is the TURN-BY-TURN DRIVER (ADR R4): per LLM step it runs ONE
`arun_session_turn` on the per-hunt `HuntSession(run_id, hunt_key)` thread, so
every LLM call rides the session seam and the checkpointer, compaction (#95 D9),
and capability (#99) negotiation attach. Each turn uses the STANDARD tool
interface: the tools are bound REQUEST-ONLY (`convert_to_openai_tool`) so
their JSON schemas ride the generation request's `tools` body, but no ToolNode
is created - the model emits a real tool call per turn (valid args per schema)
and concludes with a plain answer, and the harness stays the sole executor.
The harness executes the tool itself - the tools are bound OUTSIDE the agent
(spec 4: the built-in session seam runs the whole model<->tool loop in ONE
`agent.invoke`, so intermediate tool calls do NOT return control; the explicit
node-per-step topology gives the harness control between steps), feeds the tool
result back as the next turn's input, and, when the call carried a declared
pass-exit signal, drives the tracker's DETECTION + PUSH (S4 14): the state
moves, the trail records it, and the exited pass's constant is injected in the
tool-call response - a constant, never the system prompt. The signal is read
off the model's REAL call before the tool runs, so the passive machine NEVER
gates a tool call on the tracked state and never rejects a signal: it records
what the model signalled.

The loop continues until the model concludes the hunt (a plain answer) or the
tracked state lands `complete` - the terminal pass, after which there is no
model work (S3 8.4). The verdict-consumption workflow graph is OUT OF SCOPE
(R4/GP2-b): there is no `waiting-for-verdict` node. The dispatch result
therefore reports the terminal state and carries NO derived verdict - T5
retired the stale `derive_verdict` (S4 14.11).

Retired here (R1, spec 8): the prompt-composed `dispatch_fn` and its `kb` /
`pod` / `author` / `judge` seams. The back-edge is cut completely (GP5) and
replaced by the `exec` tool; the exec tool is UNBOUNDED at the harness level
(R2b) with the partition guard (Q8): exec probes inform the assumption check
and never manufacture a symptom - the test-executor pod remains the only
source of experimental evidence for a ratified spec.

Everything external is a typed seam, injected at construction: the `graph_view` /
`kb_query` / `exec` tool bodies, the per-project `HunterMemoryStore`, the session
`model_factory` / `checkpointer` / compaction `middleware`. Never raise out of
`dispatch_fn` EXCEPT for a `ProviderUnavailableError`: every other collaborator
failure degrades (fail-open) and is flagged in the feedback (O3/O4/C2/C3),
while a provider failure is infrastructure and propagates so the run pauses
(`interrupted`) rather than concluding with no spec and no typed reason (#312).
The whole hunt runs under the handler-carried trace
(attributed `arun_session_turn` steps with the run tag for the join, explicit
thin-exception step spans) + the `hunt_session` ContextVar rollback lane
(unchanged) and under `module_context("hunting")`, so `get_session_checkpointer()`
resolves the hunting module's in-memory index.

This module imports no driver and performs no I/O at import (CODING_STANDARD
section 6): the LLM seam pieces resolve lazily on call.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from typing import Any, Awaitable, Callable

from polymerhus.attack.hunting.hunter_graph import build_hunter_graph
from polymerhus.attack.hunting.hunter_memory import (
    HunterMemoryStore,
    spec_identifier,
)
from polymerhus.attack.hunting.hunter_state import (
    COMPLETE,
    GROUNDING_KB_HINT,
    detect_phase_signal,
)
from polymerhus.attack.hunting.hunter_tools import (
    ExecFn,
    GraphViewFn,
    KbQueryFn,
    build_hunter_tools,
)
from polymerhus.attack.hunting.hunting_tracing import (
    flush_hunting_traces,
    trace_span,
)
from polymerhus.attack.hunting.spec_contract import TargetIdentity
from polymerhus.app.llm.provider_failure import (
    ProviderUnavailableError,
    as_provider_error,
)

logger = logging.getLogger(__name__)

# The hunter's session role (the `hunting_hunter` role record; `HuntSession`
# defaults to it). Single point of truth so the harness never hardcodes a string
# differently from the role registry / session address.
_HUNTER_ROLE = "hunting_hunter"

# The step-budget safety bound: the turn-by-turn loop is the model's to conclude,
# but a stalled or looping model must never pin a hunt forever (fail-open O3).
_MAX_STEPS = 60

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

# The stable system prompt is read directly from this module's `prompts/` dir:
# `hunting-agent.md` (the role, the loop ontology, the discipline, the decision
# tree, the eight passes, the spec body, and the tools) plus its companion
# `examples.md` (the off-path worked examples Example 2-4 the main body points
# at), concatenated into ONE prompt. Memoized on first call (no
# import-time I/O). A missing prompt file is a
# defect: FAIL-CLOSED (raise), so the harness never starts a hunt without its
# prompt. The harness serves it as `system_prompt=` on EVERY `arun_session_turn`
# (the orchestrator's [SystemMessage(skill), HumanMessage(prompt)] composed-turn
# precedent, `llm.build_gate_reason_fn`): the installed `create_agent` prepends
# it ephemerally at each model invocation and never persists it into the
# checkpointer state, so per-turn passing is cheap (no accumulation) and
# required (a fresh agent is built per turn - first-turn-only would lose the
# skill on the resumed thread). The #95 compactor's `_dedup_system_messages`
# never sees it (it is not in the trail); the first HumanMessage stays the
# per-dispatch instance data below.
_HUNTING_AGENT_SKILL: str | None = None


def _load_hunting_agent_skill() -> str:
    """The stable system prompt, read directly from this module's `prompts/`
    dir: `hunting-agent.md` plus its companion `examples.md`, concatenated into
    ONE prompt (the off-path worked examples are part of the same system
    message, so the reference in the body resolves). Memoized in-process,
    FAIL-CLOSED on a missing file (raise)."""
    global _HUNTING_AGENT_SKILL
    if _HUNTING_AGENT_SKILL is None:
        from pathlib import Path  # noqa: PLC0415

        from polymerhus.attack.hunting.cortex import with_cortex  # noqa: PLC0415
        from polymerhus.attack.hunting.hunter_tools import (  # noqa: PLC0415
            render_spec_contract,
        )

        prompts = Path(__file__).resolve().parent / "prompts"
        main = (prompts / "hunting-agent.md").read_text(encoding="utf-8")
        marker = "<!-- SPEC_BODY -->"
        if marker not in main:
            raise ValueError(
                "hunting-agent.md is missing the generated spec-body marker")
        main = main.replace(marker, render_spec_contract())
        examples = (prompts / "examples.md").read_text(encoding="utf-8")
        _HUNTING_AGENT_SKILL = with_cortex(
            main.rstrip("\n") + "\n\n" + examples)
    return _HUNTING_AGENT_SKILL


# --- pure helpers (kept from the #83 harness) ---------------------------------

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


def _payload_gaps(payload: Mapping[str, Any]) -> list[str]:
    """The O3 gap flags for a degraded loop payload: the agent still authors
    from the present parts and flags each missing part in the feedback."""
    gaps: list[str] = []
    if not payload.get("unit_id"):
        gaps.append("unit identity missing; grounding degraded")
    if not payload.get("programming_fault"):
        gaps.append("programming fault missing; grounding degraded")
    trust = payload.get("trust_agreement") or payload.get("dynamic_state")
    if not trust:
        gaps.append("trust agreement/transition missing; falsification grounding degraded")
    sharpening = payload.get("technical_sharpening")
    if not isinstance(sharpening, Mapping) or not sharpening.get("interface_agreements"):
        gaps.append("interface agreements missing; grounding degraded")
    target = payload.get("target_context")
    if not isinstance(target, Mapping) or not target.get("baseline_refs"):
        gaps.append("no baseline ref recorded; author the target identity yourself")
    return gaps


# --- the composed step templates (Template reuse) -----------------------------

# The step protocol: the structured-output contract the model follows every turn
# (Structured Output + Chain-of-Thought). Never changes across steps - the
# constant is the template; the variable parts (the loop grounding, the tool
# surface, the state) compose the first step below and the tool results carry
# the later steps.
_STEP_PROTOCOL = (
    "Each turn you either call one or more of the tools below, or conclude the "
    "hunt.\n"
    "- A tool call is a standard function call: 'name' is one of the tool names "
    "below and 'args' is a JSON object conforming EXACTLY to that tool's JSON "
    "schema (the schemas are supplied with this request; unknown fields are "
    "rejected). The harness executes the tool and returns its result as the "
    "next message. When the workflow transitions to a new pass, the ending tool "
    "response carries a <phase-transition-hint> naming the next pass; follow "
    "it. A hint is guidance, never a gate: no call is refused for the pass the "
    "state is in.\n"
    "- Conclude with a plain message carrying the final rationale (no tool "
    "call) only when the terminal spec-set write has landed or no pass has "
    "work left; the terminal write itself ends the hunt.\n"
    "Never invent tool results. Never claim an assumption falsified without a "
    "probe result you actually hold. PARTITION GUARD: exec probes inform the "
    "assumption check and never manufacture a symptom - the test-executor pod "
    "remains the only source of experimental evidence for a ratified spec."
)

def _render(value: Any) -> str:
    """Deterministic render of one payload slot: JSON for mappings/lists, the
    scalar verbatim, `(none)` for an absent one. A non-serialisable value falls
    back to its str form - the render never raises into the first step."""
    if value is None or value == "" or value == [] or value == {}:
        return "(none)"
    if isinstance(value, (dict, list, tuple)):
        try:
            return json.dumps(value, sort_keys=True, default=str)
        except (TypeError, ValueError):
            return str(value)
    return str(value)


_SHARPENING_AGREEMENT_FIELDS = ("id", "statement", "confidence")


def _project_agreement(value: Any) -> Any:
    """One technical-sharpening agreement projected to its load-bearing fields.

    The agreement's evidence entries are already represented by the loop
    evidence the payload carries; repeating them in the sharpening block is the
    occupancy defect this projection removes. A non-mapping value passes
    through unchanged so a malformed payload still degrades visibly."""
    if not isinstance(value, Mapping):
        return value
    return {
        field: value[field]
        for field in _SHARPENING_AGREEMENT_FIELDS
        if field in value
    }


def _project_sharpening(value: Any) -> Any:
    """Project the payload's technical sharpening to ids, statements, and
    confidence, preserving the three agreement families."""
    if not isinstance(value, Mapping):
        return value
    projected: dict[str, Any] = {}
    for family in ("interface_agreements", "control_flows", "data_flows"):
        items = value.get(family)
        if isinstance(items, (list, tuple)):
            projected[family] = [_project_agreement(item) for item in items]
        elif items is not None:
            projected[family] = items
    return projected


def _compose_grounding(payload: Mapping[str, Any]) -> str:
    """The loop payload rendered once, ahead of the first step (S2 8.2): the
    loop's context (the unit, the trust agreement or dynamic-state transition,
    the programming fault, the two classes), the technical sharpening, the
    evidence the hunter may choose a baseline from, the likelihood/confidence
    and the target context. The rationale stays vulnerability-level - the
    payload carries no failure modes, no narrowed vector and no pre-authored
    payload vector space, so the hunter keeps the room to engineer its
    procedure."""
    unit_id = str(payload.get("unit_id") or "(unknown unit)")
    loop_id = str(payload.get("loop_id") or "(unknown loop)")
    sharpening = payload.get("technical_sharpening") or {}
    target = payload.get("target_context") or {}
    impact = (payload.get("loop") or {}).get("impact") or {}
    end_impact = str(impact.get("end_impact") or "(none)")
    return (
        f"You are dispatched to hunt {unit_id} for one threat-model loop.\n"
        f"Loop: {loop_id} (dispatch id "
        f"{payload.get('dispatch_id') or '(none)'}), likelihood "
        f"{payload.get('likelihood') or '(none)'}.\n"
        f"Canonical class: {payload.get('canonical_class') or '(none)'}; "
        f"web-vulnerability suite class: "
        f"{payload.get('web_vulnerability_class') or '(none)'}.\n"
        f"Vulnerability-level rationale: "
        f"{payload.get('vulnerability_rationale') or '(none)'}\n"
        f"Likelihood rationale: "
        f"{payload.get('likelihood_rationale') or '(none)'}\n"
        f"End impact: {end_impact} (VC "
        f"{impact.get('confidentiality') or 'none'}, VI "
        f"{impact.get('integrity') or 'none'}, VA "
        f"{impact.get('availability') or 'none'})\n"
        f"Confidence degree: {payload.get('confidence') or '(none)'}\n"
        f"Programming fault: {_render(payload.get('programming_fault'))}\n"
        f"Trust agreement: {_render(payload.get('trust_agreement'))}\n"
        f"Dynamic-state transition/violation: "
        f"{_render(payload.get('dynamic_state'))}\n"
        f"Technical sharpening (interface agreements, control flows, data "
        f"flows): {_render(_project_sharpening(sharpening))}\n"
        f"Loop evidence (choose a baseline from the request/http-history "
        f"refs): {_render(payload.get('evidence'))}\n"
        f"Target context: {_render(target)}"
    )


def _state_summary(state: dict) -> str:
    """The semantic state rendered for the model / the terminal feedback: the
    tracked pass and the spec set channel (the trail stays replay-only, never
    authoritative)."""
    lines = [f"state: {state.get('state', 'grounding')}"]
    for spec in state.get("specs") or []:
        if not isinstance(spec, dict):
            continue
        ident = spec.get("spec_id") or ""
        summary = str(spec.get("summary") or "")[:80]
        lines.append(f"- {spec.get('status', '?')}: {ident} {summary}".rstrip())
    if len(lines) == 1:
        lines.append("- (no specs tracked yet)")
    return "\n".join(lines)


def _store_write_ok(result: str) -> bool:
    """True when a `hunts_store` tool response is a persisted success
    (`{"ok": true, ...}`), including a successful `finalize`; anything else - a
    coded rejection, a duplicate signal, an unreadable result - is not a
    persisted set."""
    try:
        payload = json.loads(result)
    except (TypeError, ValueError):
        return False
    return isinstance(payload, dict) and payload.get("ok") is True


def _fold_persisted_specs(
    state: dict,
    store: HunterMemoryStore | None,
    project_id: str,
    hunt_key: str,
    result: str,
    tool_args: Mapping[str, Any],
) -> None:
    """Fold the persisted spec set into the tracker's `specs` channel (T6).

    The terminal `state: complete` must follow a PERSISTED set: the harness
    reads the produced set back from the store after a successful write and
    projects it onto `HuntState.specs` (`SpecItem`). A store read failure
    falls back to the write payload's own entries, so the channel is never
    left stale (the persisted store stays authoritative for the spec set)."""
    try:
        payload = json.loads(result)
    except (TypeError, ValueError):
        return
    paths = {
        str(entry.get("spec_id") or ""): str(entry.get("path") or "")
        for entry in (payload.get("specs") or [])
        if isinstance(entry, dict)
    }
    bodies: list[Mapping[str, Any]] = []
    if store is not None:
        try:
            bodies = list(store.read_specs(
                project_id, hunt_key, sides=("produced",)))
        except Exception as exc:  # noqa: BLE001 - fail-open: the write is authoritative
            logger.warning(
                "hunt %s spec-set read-back degraded (%s); folding the write "
                "payload instead", hunt_key, exc)
    if not bodies:
        one = tool_args.get("spec")
        bodies = [one] if isinstance(one, Mapping) else []
    folded: list[dict] = []
    for body in bodies:
        provenance = body.get("provenance")
        provenance = provenance if isinstance(provenance, Mapping) else {}
        discriminators = body.get("discriminators")
        if not isinstance(discriminators, list):
            discriminators = []
        try:
            spec_id = spec_identifier(
                str(provenance.get("web_vulnerability_class")
                    or provenance.get("canonical_class") or ""),
                discriminators,
            )
        except ValueError:
            continue
        folded.append({
            "spec_id": spec_id,
            "status": str(body.get("status") or ""),
            "discriminators": list(discriminators),
            "spec_ref": paths.get(spec_id, ""),
            "verification_symptoms": list(body.get("verification_symptoms") or []),
            "summary": str(body.get("rationale") or "")[:200],
        })
    if folded:
        state["specs"] = folded


_HUNTER_CHAIN = (
    "Grounded in the application overview above, your loop payload, the "
    "current state, and the step protocol follow."
)


def _overview_message_for(overview_fn, project_id: str) -> str:
    """The dedicated Overview HumanMessage content for one dispatch (Q4).

    The Overview is read settings-only (`read_application_overview`; the whole
    L1 inventory read would be waste here) and rendered cleanly. Fail-open: any
    read error degrades to "" and the first turn keeps its single-message
    shape."""
    from polymerhus.analysis.l1_inventory import read_application_overview  # noqa: PLC0415
    from polymerhus.analysis.overview import overview_message  # noqa: PLC0415

    try:
        value = (overview_fn or read_application_overview)(project_id)
    except Exception:  # noqa: BLE001 - framing is fail-open, the hunt is not
        logger.warning("hunter: overview read failed; dispatch without it",
                       exc_info=True)
        return ""
    return overview_message(value)


def _compose_first_step(payload: Mapping[str, Any], state: dict, *,
                        chained: bool = False) -> str:
    """The first step's HUMAN input: the loop grounding, the current state, and
    the step protocol, in that order. The stable skill rides the SYSTEM channel
    (`system_prompt=` on every turn - the orchestrator's
    [SystemMessage(skill), HumanMessage(prompt)] composed-turn precedent), never
    this message: this message is per-dispatch instance data (the correct human
    channel), while the skill is the stable system prompt. The request tool
    schemas ride the request prefix; the loop does not repeat them. Later steps
    resume the thread from the checkpoint, so the grounding is never repeated
    into the conversation.

    The Q4 model: the structured Overview rides its OWN dedicated HumanMessage
    ahead of this one; when it does, `chained=True` opens this message with the
    verbatim that couples the two messages."""
    lead = f"{_HUNTER_CHAIN}\n\n" if chained else ""
    return lead + "\n\n".join([
        _compose_grounding(payload),
        _state_summary(state),
        _STEP_PROTOCOL,
    ])


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
    graph_view_fn: GraphViewFn | None = None,
    kb_fn: KbQueryFn | None = None,
    exec_fn: ExecFn | None = None,
    http_search_fn=None,
    http_get_fn=None,
    suite_classes=(),
    suite_read_fn=None,
    overview_fn=None,
    checkpointer=None,
    middleware=None,
    model_factory=None,
    observe: bool = True,
) -> Callable[[Mapping[str, Any]], Awaitable[dict[str, Any]]]:
    """Build the turn-by-turn hunting-agent dispatch seam (IA-2).

    `run_id` / `project_id` are the hunt's run and project (the project keys the
    per-project `HunterMemoryStore`); `memory_store` is that per-project store;
    each dispatch BINDS the loop's own hunt key (`<unit_name>__<loop_id>`,
    S3 8.9, the payload's `dispatch_id`) into the tool surface so the store
    tools can only address that loop; `graph_view_fn` / `kb_fn` / `exec_fn` are
    the injected tool seams (each absent degrades fail-open, O3/O4/C2/C3).
    `checkpointer` defaults to `get_session_checkpointer()` under
    `module_context("hunting")`; `middleware` defaults to the R5 compaction
    middleware (`build_hunter_compaction_middleware`, #95 D9) - capability
    (#99) negotiation attaches via the session seam itself. `model_factory`
    injects a fake model for tests; `observe` toggles session observability.
    Returns `async dispatch_fn(payload: Mapping) -> dict` (the async-native
    harness; sync callers use `build_sync_hunting_agent`). The payload is the
    loop dispatch record materialised by the surfer (S2 8.2).

    The closure binds the injected seams once; each dispatch (hunt) compiles
    its OWN in-memory state graph (OUTLIER-1, no graph-level checkpointer),
    binds the per-hunt tool surface, and drives its turn-by-turn loop on its
    `HuntSession(run_id, hunt_key)` thread."""
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
        payload: Mapping[str, Any],
        feedback: list[str],
        checkpointer,
        middleware,
    ) -> dict[str, Any]:
        hunt_key = str(payload.get("dispatch_id") or "")
        if not hunt_key:
            # The store key and the session id derive from the dispatch id; a
            # payload without one cannot address its own loop. Degrade loudly
            # rather than write into a fabricated folder.
            feedback.append(
                "loop payload carries no dispatch_id; the hunt cannot address "
                "its own spec folder")
            return _assemble({"state": "grounding", "specs": [], "trail": []},
                             feedback)
        compiled = build_hunter_graph().compile()
        # The target identity is symbolic: the dispatch context carries the
        # canonical target URL, and the store injects it into every spec write.
        target_context = payload.get("target_context")
        target_context = (
            target_context if isinstance(target_context, dict) else {})
        target_url = str(target_context.get("target_url") or "").strip()
        target_identity = (
            TargetIdentity(
                url=target_url,
                unit_id=str(payload.get("unit_id")
                            or target_context.get("unit_id") or ""),
            )
            if target_url else None
        )
        tools = build_hunter_tools(
            store=memory_store, project_id=project_id, hunt_key=hunt_key,
            run_id=run_id, target_identity=target_identity,
            graph_view_fn=graph_view_fn, kb_fn=kb_fn, exec_fn=exec_fn,
            http_search_fn=http_search_fn, http_get_fn=http_get_fn,
            suite_classes=suite_classes, suite_read_fn=suite_read_fn,
        )
        state: dict = {"state": "grounding", "specs": [], "trail": []}

        from langchain_core.messages import HumanMessage, ToolMessage  # noqa: PLC0415
        from langchain_core.utils.function_calling import (  # noqa: PLC0415
            convert_to_openai_tool,
        )
        from polymerhus.app.llm.session import arun_session_turn  # noqa: PLC0415
        from polymerhus.app.llm.session_address import HuntSession  # noqa: PLC0415
        from polymerhus.app.auth.seams import auth_capable_binding  # noqa: PLC0415

        # The skill seams ride BOTH planes of the hybrid loop (the declaration /
        # execution split): the binding's `load_skill` tool is declared
        # request-only alongside the five hunter tools AND registered in the
        # harness executor map, joined by the tool name; the index middleware
        # joins the turn middleware and carries the role's bounded skill set.
        binding = auth_capable_binding(
            _HUNTER_ROLE, project_id=project_id or None,
            with_readonly_auth_store=True)
        tools = list(tools) + binding.tools
        tools_by_name = {tool.name: tool for tool in tools}
        middleware = list(middleware) + binding.middleware

        thread_id = HuntSession(run_id, hunt_key).thread_id
        # The stable skill rides the SYSTEM channel on EVERY turn (the
        # orchestrator's composed-turn precedent): `create_agent` prepends it
        # ephemerally per model invocation without persisting it, so per-turn
        # passing is cheap and required. Fail-closed here (raise) so a hunt
        # never starts without its prompt.
        skill = _load_hunting_agent_skill()
        overview = _overview_message_for(overview_fn, project_id)
        first_step = _compose_first_step(
            payload, state, chained=bool(overview))
        # ONE pinned instance-context message: the compaction pin preserves the
        # application overview AND the loop grounding together.
        first_content = f"{overview}\n\n{first_step}" if overview else first_step
        new_messages = [HumanMessage(content=first_content)]
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
                    system_prompt=skill,
                    middleware=middleware,
                    context=binding.context,
                    model_factory=model_factory,
                    observe=observe,
                    extra_tags=[run_id],
                    usage_scope=project_id,
                )
            except ProviderUnavailableError:
                # #329/#312: a provider failure is infrastructure, never a hunt
                # degrade - propagate it so the run pauses (`interrupted`) rather
                # than concluding with no spec and no reason. Genuine internal
                # errors keep the O3/C2/C3 fail-open below.
                raise
            except Exception as exc:  # noqa: BLE001 - O3/C2/C3: degrade, never raise
                # #312: a REAL provider turn raises a RAW error (an
                # `openai.RateLimitError` / `TimeoutError` / httpx transport),
                # never the typed `ProviderUnavailableError`, so the branch above
                # is dead for the production hunter. Classify the raw raise at
                # the seam exactly as the pod (`pod.py`) and the orchestrator
                # abort (`read_only_graph.py`) do, then propagate the typed
                # error so the run pauses instead of quiescing `complete` with
                # zero specs (the trial-2 outcome). A genuine non-provider error
                # keeps the fail-open degrade below.
                failure = as_provider_error(exc)
                if failure is not None:
                    logger.warning(
                        "hunt %s step hit a provider failure (%s); propagating it "
                        "instead of degrading", hunt_key, exc)
                    raise failure from exc
                logger.warning("hunt %s step degraded (%s)", hunt_key, exc, exc_info=True)
                feedback.append(f"hunter turn unavailable ({exc})")
                break
            trace_span("hunter-step", input={"step": _step + 1},
                       run_id=run_id,
                       tags=["attack", "hunting", "hunting-agent"])

            tool_calls = _last_tool_calls(turn.messages)
            if not tool_calls:
                # The model concluded the hunt with a plain answer: the harness
                # lands the state, derives NO verdict (the verdict-consumption
                # graph is OUT OF SCOPE and derives it from the pod-verdict
                # messages the surfer feeds the idle hunt), and the dispatch
                # result reports the tracked pass.
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
                # DETECTION + PUSH (S4 14): the signal is read off the model's
                # REAL call, so the passive machine is never gated by the
                # tool's own acceptance. The one-spec write (GENERATE) and the
                # `finalize` call (VERIFY-CLAIMS) are the AUTHORITATIVE exits
                # (S4 14.8: the store writes remain authoritative for the spec
                # set): a coded rejection (a duplicate identity, a missing
                # derivation input, an undecided draft) persists no exit, so it
                # is no signal and the tracker stays put. A persisted set folds
                # into the `specs` channel, so the terminal `state: complete`
                # follows the set the store holds.
                signal = detect_phase_signal(tool_name, tool_args)
                if signal is not None and signal.get("kind") in (
                        "spec_set_write", "spec_set_finalize"):
                    if _store_write_ok(result):
                        _fold_persisted_specs(
                            state, memory_store, project_id, hunt_key,
                            result, tool_args)
                    else:
                        signal = None
                if signal is not None:
                    try:
                        state = await compiled.ainvoke(
                            {**state, "observed_signal": signal})
                    except Exception as exc:  # noqa: BLE001 - fail-open, keep serving
                        logger.warning("hunt %s state tracking degraded (%s)", hunt_key, exc)
                        feedback.append(f"state tracking degraded ({exc})")
                    if signal.get("kind") == "kb_query" and state.get("state") == "grounding":
                        # The grounding retrieval-gap rider (S4 14.7/Q53): a KB
                        # call while the tracker is still in GROUNDING prompts
                        # the gap check. Not a transition (the grounding exit
                        # remains the phase-summary note), so it injects here.
                        state["injected_constant"] = GROUNDING_KB_HINT
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
                           output=result[:500], run_id=run_id,
                           tags=["attack", "hunting", "hunting-agent"])
                results.append(ToolMessage(tool_call_id=tc.get("id"), content=result))
            new_messages = results
            if state.get("state") == COMPLETE:
                # The chain is complete: the terminal spec-set write landed and
                # there is no model work left (S3 8.4). The hunt ends here, with
                # the terminal state in the feedback; the surfer dispatches the
                # pod from the persisted set.
                feedback.append(_terminal_feedback(state, ""))
                return _assemble(state, feedback)
        else:
            # A natural loop end (no break) is genuine budget exhaustion; the
            # break paths above already reported their own degradation, so a
            # degraded turn must never surface a budget message.
            feedback.append(f"hunt {hunt_key} step budget exhausted ({_MAX_STEPS} steps)")
        return _assemble(state, feedback)

    def _assemble(state: dict, feedback: list[str]) -> dict[str, Any]:
        """The terminal assembly (the deterministic surface, spec 2.4): the
        tracked pass and the terminal summary ride the returned mapping; the
        hypothesis verdict is deliberately absent - the verdict-consumption
        graph is OUT OF SCOPE and derives it from the pod-verdict messages the
        surfer feeds the idle hunt."""
        parts = [p for p in feedback if p]
        return {
            "state": state.get("state", "grounding"),
            "feedback": " | ".join(parts) if parts else _state_summary(state),
        }

    async def dispatch_fn(payload: Mapping[str, Any]) -> dict[str, Any]:
        payload = payload if isinstance(payload, Mapping) else {}
        hunt_key = str(payload.get("dispatch_id") or "(unaddressed loop)")
        feedback: list[str] = list(_payload_gaps(payload))
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
            # Convergence: no hand-written agent span - the dispatch trace rides
            # the handler (attributed session turns, run tag for the join) while
            # the step records below carry their own explicit run correlation.
            with hunt_session(run_id, hunt_key, project_id=project_id):
                with module_context("hunting"):
                    cp = checkpointer if checkpointer is not None else get_session_checkpointer()
                    mw = middleware if middleware is not None else [build_hunter_compaction_middleware()]
                    return await _run_hunt(payload, feedback, cp, mw)
        except ProviderUnavailableError:
            # #329/#312: a provider failure is infrastructure, never a hunt
            # degrade - propagate it (mirroring the pod) so the run pauses
            # (`interrupted`) rather than returning a spec-less outcome and
            # letting the run quiesce `complete` with no typed reason.
            raise
        except Exception as exc:  # noqa: BLE001 - never raise out of dispatch_fn
            # #312: a raw provider error that escaped the per-turn seam (a lazy
            # seam resolution, hunt-session setup) is classified here too, so no
            # untyped provider raise is ever degraded into a spec-less result.
            failure = as_provider_error(exc)
            if failure is not None:
                logger.warning(
                    "hunt %s hit a provider failure (%s); propagating it instead "
                    "of degrading", hunt_key, exc)
                raise failure from exc
            logger.warning("hunt %s degraded (%s)", hunt_key, exc, exc_info=True)
            return {"state": "grounding",
                    "feedback": f"hunt {hunt_key} degraded: {exc}"}
        finally:
            flush_hunting_traces()

    return dispatch_fn


def build_sync_hunting_agent(**kwargs):
    """The SYNC lane of the hunting-agent harness: a thin wrapper that runs the
    async `build_hunting_agent` dispatch to completion, so the harness canon is
    never re-implemented.

    Sync injectable seams travel through `asyncio.to_thread` inside the canon;
    async seams are awaited natively. When called from a running event loop,
    `run_coro_blocking` runs the dispatch on a separate thread so `asyncio.run`
    is never re-entered on the caller's loop."""
    from polymerhus.recon.control.async_bridge import run_coro_blocking  # noqa: PLC0415

    dispatch_fn = build_hunting_agent(**kwargs)

    def dispatch(payload: Mapping[str, Any]) -> dict[str, Any]:
        return run_coro_blocking(dispatch_fn(payload))

    return dispatch
