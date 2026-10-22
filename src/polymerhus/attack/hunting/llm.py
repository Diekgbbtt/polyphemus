"""The hunting module's own LLM bootstrap and role wiring (#94/#93).

Two things live here, both keyed off the hunting role records in
`app/llm/providers.py::HUNTING_ROLES` (`hunting_threat_modeller`,
`hunting_hunter`):

1. `validate_hunting_llm_config()` - the hunting module's OWN fail-fast, run at
   the HUNTING bootstrap, NEVER at app boot (operator ruling 2026-08-06). A bare
   environment that never launches a hunt must not be forced to configure the
   hunting model vars, so app boot validates only `ROLES` and this validates
   `HUNTING_ROLES` on the first hunt.

2. The production seam factories for the hunter's SYNC rollback lane
   (`build_author_fn` / `build_judge_fn`). The hunting-agent harness
   (`hunting_agent.build_hunting_agent`) drives `arun_session_turn` DIRECTLY on
   the per-hunt `HuntSession` thread as of #164 W5, so these factories are the
   thin SYNC lane only - no production wiring uses them.

Statefulness lives in the MAILBOX ACTORS (`attack/hunting/actors.py`,
feat/async-actor-agents): `threat_modeller.arun_modeller_pass` drives one turn
per gate state on ONE `ThreatModellerActor` per run (`hunting_threat_modeller`
session thread), and the per-hunt `HuntingHunterActor` (registered per run by
`HuntingActorRegistry`) owns the author/judge turns of each hunt on its
`HuntSession` thread. DECISION OF RECORD (2026-08-10): the async actor lane is
the production default; the sync factories are the test/rollback lane only.

The modeller's per-turn message is composed here (`_compose_modeller_prompt`),
and its system prompt is read directly from this module's `prompts/` dir
(`threat-modeller.md` via `_modeller_skill`), memoized on first call and
FAIL-CLOSED on a missing file.

This module imports no driver and no `app.config` chain: it is env-free at
import (the planner's `hunt_orchestrator` import retired with the pass in T2b).
The env-free home for the conciseness constant + appender re-exported below is
`conciseness.py`; everything that performs I/O (`invoke_role`, the message
classes, and the skill read) resolves lazily on call.
"""
from __future__ import annotations

import json
import logging
from typing import Callable

# The conciseness directive + appender are re-exported here for their public
# home; the env-free definition lives in `conciseness.py` so the tool modules
# import at module top without pulling `app.config` (#292).
from polymerhus.attack.hunting.conciseness import (
    HUNTING_CONCISENESS_DIRECTIVE,
    append_conciseness_directive,
)
logger = logging.getLogger(__name__)

# The hunting agent's authoring/judging role. Single point of truth so a caller
# never hard-codes a role_id string.
HUNTER_ROLE = "hunting_hunter"

# The per-hunt session context for the hunter's STATEFUL turns (#94): (run_id, hunt_id),
# set by the hunting agent around a hunt's author/judge calls so they RESUME the SAME
# per-hunt thread - the judge sees what the author reasoned, and a back-edge re-entry
# continues the same session. Passed out-of-band through a ContextVar so the
# `author(text)`/`judge(text)` seam contract stays unchanged (a test double ignores it).
# Concurrent hunts each set their own (they run in their own call), keyed by hunt_id, so
# they never share a thread. `None` => stateless (the legacy #73-retry `invoke_role`).
_hunt_session_ctx: "ContextVar" = None


def _hunt_ctx():
    global _hunt_session_ctx
    if _hunt_session_ctx is None:
        from contextvars import ContextVar
        _hunt_session_ctx = ContextVar("hunt_session_ctx", default=None)
    return _hunt_session_ctx


def hunt_session(run_id: str, hunt_id: str, project_id: str | None = None):
    """Context manager the hunting agent wraps a hunt's author/judge calls in, so those
    turns run STATEFUL on ONE per-hunt thread (`HuntSession(run_id, hunt_id)`).
    `project_id` (default None) is carried on the binding so the stateful turns
    attribute their token usage to the project; a caller that does not know it leaves
    it None (unscoped)."""
    from contextlib import contextmanager

    from polymerhus.app.llm.checkpoints import get_session_checkpointer
    from polymerhus.app.llm.session_address import HuntSession, SessionContext

    @contextmanager
    def _cm():
        ctx = SessionContext(HuntSession(run_id, hunt_id), get_session_checkpointer(),
                             project_id=project_id)
        token = _hunt_ctx().set(ctx)
        try:
            yield
        finally:
            _hunt_ctx().reset(token)

    return _cm()


def hunt_session_context():
    """The currently bound hunt-session context (a typed `SessionContext`), or
    None when the turn runs stateless. The pod's session binding (`pod/llm.py`,
    D84-7) reads this to derive the pod run's run_id/hunt_id from an enclosing
    hunt."""
    return _hunt_ctx().get()


def _hunter_turn(text: str) -> dict | None:
    """One hunter LLM turn: STATEFUL on the per-hunt thread when the hunting agent set a
    hunt-session context (author + judge + re-entries then share that thread's memory),
    else the stateless `invoke_role`. Returns the parsed JSON object, or None (degraded),
    which the hunting agent's seams already handle."""
    from langchain_core.messages import HumanMessage

    ctx = _hunt_ctx().get()
    if ctx is not None:
        from polymerhus.app.llm.session import stateful_turn
        from polymerhus.app.auth.seams import auth_capable_binding  # noqa: PLC0415

        binding = auth_capable_binding(
            HUNTER_ROLE, project_id=getattr(ctx, "project_id", "") or None)
        return _parse_json_object(stateful_turn(
            HUNTER_ROLE, ctx.address, [HumanMessage(content=text)],
            checkpointer=ctx.checkpointer, tools=binding.tools,
            middleware=binding.middleware, context=binding.context,
            usage_scope=ctx.project_id))
    from polymerhus.app.llm.roles import invoke_role
    return _parse_json_object(invoke_role(HUNTER_ROLE, [HumanMessage(content=text)]))


def validate_hunting_llm_config() -> None:
    """Fail fast on the hunting model vars, at the HUNTING bootstrap only.

    Delegates to the shared `validate_llm_config(HUNTING_ROLES)` (operator ruling
    2026-08-06): app boot validates `ROLES` and never demands the hunting vars, so
    a bare environment that never launches a hunt boots clean; the first hunt calls
    THIS and gets the same fail-fast the app roles get."""
    from polymerhus.app.llm.providers import HUNTING_ROLES, validate_llm_config

    validate_llm_config(HUNTING_ROLES)


# --- pure prompt/parse helpers ------------------------------------------------

# The L1 ontology primer (memory-system spec 7, ADR G9): the FOURTH phase-
# constant, rendered at the TOP of each pair's frame in the USER prompt (never
# the system prompt - spec 3.7). It is deliberately NOT an over-specified
# glossary: system kinds and edge types are self-explanatory and the projection
# render already carries them self-describingly. The primer is the fundamental
# knowledge that makes every other part of the graph readable - what a Service,
# a System, and a DataItem are conceived FOR, plus the philosophy of the domain
# model (the L1 is a judged abstraction over the L0 graph; the projection is the
# typed facet surface the gate reasons over; typed facets are proxies, never
# authoritative classification). Single-sourced here and shared by the gate /
# ratify / note composers; never duplicated in the skill or the fallback.
L1_ONTOLOGY_PRIMER = (
    "L1 ontology primer (the domain model every part of this graph reads "
    "through): a Service is the business-function abstraction - the "
    "operator-facing capability a hunt anchors on, kind-qualified as "
    "'<kind>:<key>'. A System is the technological/mechanism abstraction that "
    "capability rides - the typed locus where the fault may bite, identified "
    "by kind and discriminator. A DataItem is the logical data-flow "
    "abstraction - the data a Service produces or consumes, carrying its "
    "name, type, and sensitivity. An L0 Endpoint is the observed reachability "
    "fact - a path that responded - and a Service AGGREGATES the Endpoints "
    "that serve its business function; those aggregated endpoints are part of "
    "the Service's surface (a System's surface includes the Endpoints its "
    "linked services aggregate). The L1 is a judged abstraction over the "
    "observed L0 graph: every node here is an inference licensed by "
    "observations, never direct evidence. The projection is the typed facet surface "
    "you reason over - a proxy for the full characterisation, not an "
    "authoritative classification - so an absent or unknown facet is missing "
    "evidence, never evidence of absence."
)

# The threat modeller's role prompt, memoized on first call (no import-time
# I/O, CODING STANDARD section 6). A missing prompt file is a defect:
# FAIL-CLOSED (raise), so the modeller never reasons without its method.
_MODELLER_SKILL: str | None = None


def _modeller_skill() -> str:
    """The threat modeller's system prompt, read directly from this module's
    `prompts/` dir. Memoized on first call; FAIL-CLOSED."""
    global _MODELLER_SKILL
    if _MODELLER_SKILL is None:
        from pathlib import Path  # noqa: PLC0415

        from polymerhus.attack.hunting.cortex import with_cortex  # noqa: PLC0415

        _MODELLER_SKILL = with_cortex(
            (Path(__file__).resolve().parent / "prompts" / "threat-modeller.md")
            .read_text(encoding="utf-8")
        )
    return _MODELLER_SKILL


def _compose_modeller_prompt(turn) -> str:
    """Render one gate-state reasoning turn (S1 8): the current unit, the
    current state, the section names that gate carries, the input data (the
    persisted model, read fresh so an evicted context is re-queried - S1 6.2),
    and the gate instruction. The next-state hints are NOT here: they ride the
    gate write's tool response (`threat_modeller.GATE_HINTS`).

    Every slot degrades independently: a model that cannot be read renders as
    "(not written yet)", never as an empty claim."""
    state = getattr(turn, "state", None)
    state_value = getattr(state, "value", state) or "UNIT_TECHNICAL_SHARP"
    sections = list(getattr(turn, "sections", ()) or ())
    model = getattr(turn, "model", None)
    lines = [
        f"Unit under analysis: {getattr(turn, 'unit_id', '(unbound)')}",
        f"Current workflow state: {state_value}",
        f"Gate sections to write: {', '.join(sections)}",
        "",
        str(getattr(turn, "instruction", "") or ""),
        "",
        "Grounding inputs:",
        "  Unit projection: " + (
            _render_grounding(getattr(turn, "projection", None)) or "(unavailable)"),
        "  Application-surface overview: " + (
            _render_grounding(getattr(turn, "surface_overview", None))
            or "(unavailable)"),
    ]
    for gap in getattr(turn, "context_gaps", ()) or ():
        lines.append(f"  Grounding gap: {gap}")
    lines += [
        "",
        "The persisted model at this turn's start:",
    ]
    if not isinstance(model, dict):
        lines.append("  (not written yet)")
    else:
        from polymerhus.attack.hunting.threat_modeller_tools import (  # noqa: PLC0415
            MODEL_SECTIONS,
        )

        lines.append(f"  state: {model.get('state')}")
        written = [name for name in MODEL_SECTIONS if model.get(name)]
        lines.append(f"  sections written: {', '.join(written) or '(none)'}")
        if model.get("risk_profile"):
            lines.append(f"  risk profile: {model['risk_profile']}")
        if model.get("validation"):
            lines.append(f"  completion validation: {model['validation']}")
    lines += [
        "",
        "Write the gate with ONE `hunts_store` write carrying this state and its "
        "sections. Then end the reasoning phase with ONE episodic note through "
        "`notes`: the decision nodes and the rationales of the branches you took.",
    ]
    return "\n".join(lines)


def _render_grounding(value, limit: int = 4000) -> str:
    """One grounding input rendered for the turn: a mapping as its JSON, a
    string as itself, an object as its `model_dump` when it has one. Bounded by
    `limit` characters so one oversized read cannot flood the turn; an absent
    value renders "" (the caller names the gap)."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value[:limit]
    if hasattr(value, "model_dump"):
        try:
            value = value.model_dump(mode="json")
        except Exception:  # noqa: BLE001 - a render failure is a denoted gap
            return ""
    try:
        return json.dumps(value, ensure_ascii=False, default=str)[:limit]
    except Exception:  # noqa: BLE001 - a render failure is a denoted gap
        return ""


def _parse_json_object(text) -> dict | None:
    """Best-effort parse of a free-text LLM reply into a JSON object, tolerating a
    ```json fenced block anywhere in the reply (a live D4 reply may open with
    prose and then carry the fenced spec). Returns None on anything unparseable
    (the hunting agent's authoring/judging seams already treat None as a
    degraded turn, fail-open)."""
    if isinstance(text, dict):
        return text
    if not isinstance(text, str) or not text.strip():
        return None
    body = text.strip()
    if body.startswith("```"):
        body = body.split("```", 2)[1] if "```" in body[3:] else body[3:]
        if body.lstrip().lower().startswith("json"):
            body = body.lstrip()[4:]
    elif not body.startswith("{"):
        marker = "```"
        fence_start = body.find(marker)
        if fence_start != -1:
            fenced = body[fence_start + len(marker):]
            fenced = fenced.split(marker, 1)[0] if marker in fenced else fenced
            fenced = fenced.strip()
            if fenced.lower().startswith("json"):
                fenced = fenced[4:].lstrip()
            if fenced.startswith("{"):
                body = fenced
    try:
        obj = json.loads(body)
    except (ValueError, TypeError):
        return None
    return obj if isinstance(obj, dict) else None


def build_author_fn() -> Callable[[str], dict | None]:
    """The hunting agent's `author` seam: the D4 spec-authoring turn on the
    `hunting_hunter` role. The hunting agent composes the FULL prompt (the stable
    decision-tree skill already embedded via `_with_stable_skill`) and passes it as one
    string, so this invokes the hunter with that single message and parses the JSON spec
    back. STATEFUL on the per-hunt thread when the agent set a hunt-session (so the
    re-authoring pass and the judge continue the same session); free-text-then-parse
    rather than a pydantic schema because the D4 typed base is #83/#84's to ratify; a
    None return is the degraded signal the agent already handles."""
    return _hunter_turn


def build_judge_fn() -> Callable[[str], dict | None]:
    """The hunting agent's `judge` seam: the D5 continuation-judgment turn on the
    `hunting_hunter` role (consulted only on an insufficient-evidence derivation). Same
    single-message + JSON-parse contract as `author`, and STATEFUL on the SAME per-hunt
    thread - so the judgment resumes the author's reasoning; a None return degrades the
    judgment, which the agent treats as no-meaningful-insight (fail-open)."""
    return _hunter_turn


# --- the actor-backed SYNC-free lane is composed from `attack/hunting/actors.py` ---


def build_actor_author_fn(registry):
    """The async `author` seam bound to the run's `HuntingActorRegistry`.

    The harness always wraps each dispatch in `hunt_session(run_id, hunt_id)`
    (see `hunting_agent.build_hunting_agent`), so the in-flight hunt id is read
    out-of-band from that context and routed to its per-hunt
    `HuntingHunterActor` - the seam contract `author(text)` stays unchanged."""
    async def author(text: str) -> dict | None:
        ctx = _hunt_ctx().get()
        if ctx is None or getattr(ctx, "address", None) is None:
            return None
        hunt_id = getattr(ctx.address, "hunt_id", None)
        if not hunt_id:
            return None
        return await registry.actor_for(hunt_id).author(text)
    return author


def build_actor_judge_fn(registry):
    """The async `judge` seam bound to the run's `HuntingActorRegistry` - the D5
    continuation judgment resumes the SAME per-hunt actor thread as `author`."""
    async def judge(text: str) -> dict | None:
        ctx = _hunt_ctx().get()
        if ctx is None or getattr(ctx, "address", None) is None:
            return None
        hunt_id = getattr(ctx.address, "hunt_id", None)
        if not hunt_id:
            return None
        return await registry.actor_for(hunt_id).judge(text)
    return judge


def build_actor_hunting_agent(*, run_id, project_id="", memory_store=None,
                              graph_view_fn=None, kb_fn=None,
                              exec_fn=None, checkpointer=None, model_factory=None,
                              observe: bool = True,
                              http_search_fn=None, http_get_fn=None,
                              suite_classes=None, suite_read_fn=None,
                              overview_fn=None):
    """Compose the production hunting-agent dispatch seam (as of #164 W5).

    As of W5 the harness (`hunting_agent.build_hunting_agent`) is the turn-by-turn
    ReAct host: it drives `arun_session_turn` DIRECTLY on the per-hunt
    `HuntSession(run_id, hunt_id)` thread with the bound tool surface, so the
    per-hunt `author`/`judge` actor lane is no longer its mechanism (R1 retired
    the `kb`/`pod`/`author`/`judge` seams). A `HuntingActorRegistry` is still
    built and returned so the run's actor lifecycle bookkeeping (`stop_all`)
    keeps its contract; the harness itself spawns no actor turns.

    Returns `(dispatch_fn, registry)`: the harness `dispatch_fn` is async-native
    (see `hunting_agent.build_hunting_agent`); the run's surfer dispatches with
    it and reaps the registry (`stop_all`) when the hunt session settles.
    Construction performs no imports."""
    from polymerhus.attack.hunting.actors import HuntingActorRegistry  # noqa: PLC0415
    from polymerhus.attack.hunting.hunting_agent import build_hunting_agent  # noqa: PLC0415

    if suite_classes is None or suite_read_fn is None:
        from polymerhus.app.llm.skills import (  # noqa: PLC0415
            list_suite_leaves,
            read_suite_raw,
        )

        suite_classes = list_suite_leaves() if suite_classes is None else suite_classes
        suite_read_fn = read_suite_raw if suite_read_fn is None else suite_read_fn
    registry = HuntingActorRegistry(run_id, checkpointer=checkpointer,
                                    model_factory=model_factory, observe=observe,
                                    project_id=project_id)
    dispatch_fn = build_hunting_agent(
        run_id=run_id, project_id=project_id,
        memory_store=memory_store,
        graph_view_fn=graph_view_fn, kb_fn=kb_fn, exec_fn=exec_fn,
        http_search_fn=http_search_fn, http_get_fn=http_get_fn,
        suite_classes=suite_classes, suite_read_fn=suite_read_fn,
        overview_fn=overview_fn,
        checkpointer=checkpointer, model_factory=model_factory, observe=observe,
    )
    return dispatch_fn, registry


# --- the hunting-side context-window compaction (#95 D9) -----------------------

def build_hunter_compaction_middleware(*, window=None, threshold=None, store=None):
    """Build the hunting-side compaction middleware (#95 D9) for the per-hunt
    async lane: the hunter's OWN model as the running-summary engine (D5), its
    fail-open D7 reasoning profile, and its resolved window - so out-of-band
    passes can spawn on the per-hunt thread. `window` is explicit for tests; the
    shared `app.llm.compaction` builder owns the role wiring, and a raising
    capability reader degrades the profile and the window, never the actor."""
    from polymerhus.app.llm import compaction as C  # noqa: PLC0415

    return C.build_role_compaction_middleware(
        HUNTER_ROLE, window=window, threshold=threshold, store=store)
