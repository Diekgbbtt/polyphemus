"""The hunting module's own LLM bootstrap and role wiring (#94/#93).

Two things live here, both keyed off the hunting role records in
`app/llm/providers.py::HUNTING_ROLES` (`hunting_orchestrator`, `hunting_hunter`):

1. `validate_hunting_llm_config()` - the hunting module's OWN fail-fast, run at
   the HUNTING bootstrap, NEVER at app boot (operator ruling 2026-08-06). A bare
   environment that never launches a hunt must not be forced to configure the
   hunting model vars, so app boot validates only `ROLES` and this validates
   `HUNTING_ROLES` on the first hunt.

2. The production seam factories that bind the orchestrator's and the hunting agent's
   injected LLM seams (`hunt_orchestrator.run_orchestration`'s `reason_fn` /
   `rematch_fn`; `hunting_agent.build_hunting_agent`'s `author` / `judge`) to a
   real model through `roles.invoke_role`.

Statefulness now lives in the MAILBOX ACTORS (`attack/hunting/actors.py`,
feat/async-actor-agents): `arun_orchestration` drives the gate turn and the
re-match judge as turns of ONE `HuntOrchestratorActor` per run on the
`hunting_orchestrator` session thread - purely stateful, exactly like the
recon-orchestrator - and the per-hunt `HuntingHunterActor` (registered per run
by `HuntingActorRegistry`) owns the author/judge turns of each hunt on its
`HuntSession` thread. The factories below remain the thin SYNC lane: explicit
stateless rollback / test seams (`invoke_role` offers the #73 escalating-timeout
retry these degrade-prone turns want), injectable through every harness seam.
DECISION OF RECORD (2026-08-10): the async actor lane is the production default;
the sync factories above/existing `build_gate_reason_fn`-style seams are the
test/rollback lane only - no production wiring uses them.

The composed turns are single-sourced from hunting skills when mounted
(`skills/hunting/hunt-orchestrator/SKILL.md`, authored by #82) and degrade to
the terse fallbacks below otherwise - the same skill-as-system-prompt pattern
the hunting agent uses; the actors reuse the SAME composers (`_gate_skill`,
`_rematch_skill`, `_compose_gate_prompt`, `_compose_rematch_prompt`) and the
SAME free-text-then-parse (`_parse_json_object`) as these factories, so the two
lanes can never drift.

This module imports no driver and performs no I/O at import (CODING_STANDARD
section 6): `invoke_role`, the message classes, and the skill read all resolve
lazily on call.
"""
from __future__ import annotations

import json
import logging
from typing import Callable

from polymerhus.attack.hunting.hunt_orchestrator import (
    GateDecision,
    GateInput,
    MatchVerdict,
)
from polymerhus.recon.control.targeted import TargetedReconResult

logger = logging.getLogger(__name__)

# The orchestrator's gate-reasoning role and the hunting agent's authoring/judging
# role. Single point of truth so a caller never hard-codes a role_id string.
GATE_ROLE = "hunting_orchestrator"
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


def hunt_session(run_id: str, hunt_id: str):
    """Context manager the hunting agent wraps a hunt's author/judge calls in, so those
    turns run STATEFUL on ONE per-hunt thread (`HuntSession(run_id, hunt_id)`)."""
    from contextlib import contextmanager

    from polymerhus.app.llm.checkpoints import get_session_checkpointer
    from polymerhus.app.llm.session_address import HuntSession, SessionContext

    @contextmanager
    def _cm():
        ctx = SessionContext(HuntSession(run_id, hunt_id), get_session_checkpointer())
        token = _hunt_ctx().set(ctx)
        try:
            yield
        finally:
            _hunt_ctx().reset(token)

    return _cm()


def _hunter_turn(text: str) -> dict | None:
    """One hunter LLM turn: STATEFUL on the per-hunt thread when the hunting agent set a
    hunt-session context (author + judge + re-entries then share that thread's memory),
    else the stateless `invoke_role`. Returns the parsed JSON object, or None (degraded),
    which the hunting agent's seams already handle."""
    from langchain_core.messages import HumanMessage

    ctx = _hunt_ctx().get()
    if ctx is not None:
        from polymerhus.app.llm.session import stateful_turn

        return _parse_json_object(stateful_turn(
            HUNTER_ROLE, ctx.address, [HumanMessage(content=text)],
            checkpointer=ctx.checkpointer))
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

_GATE_SKILL_FALLBACK = (
    "You are the hunt-orchestrator's gate: the single embedded reasoning turn (Q8) "
    "that decides which delivered (testable-unit, fault-class) candidates become "
    "carried hunt directions. For each candidate you receive its applies-witnesses "
    "and three-valued match verdict, the symptom-technique KB evidence for its fault "
    "class, and the read-only graph surface. Carry a direction when the fault "
    "plausibly applies and seed it with a fault-matching rationale, the "
    "adversarial-capability/environmental assumptions, the envisioned test "
    "primitives, and the supposed payload vectors that stub the hunting agent's later "
    "concrete hypothesis; prune a direction only on positive grounds (the fault "
    "cannot apply). NEVER prune on degraded grounds: when the KB is unavailable "
    "(kb_degraded), reason from the candidate and surface alone and carry rather than "
    "prune. Return the directions, each marked carried or pruned."
)

_REMATCH_SKILL_FALLBACK = (
    "You are the hunt-orchestrator's re-match judge. A yellow "
    "(insufficient-evidence) candidate raised a park/resume back-edge; you now "
    "re-evaluate whether the fault class applies to the unit GIVEN the recon "
    "evidence the back-edge returned. Return the three-valued verdict: 'applies' "
    "when the returned evidence establishes the fault is present-shaped, "
    "'does-not-apply' when it refutes it, 'insufficient-evidence' when the evidence "
    "still cannot decide (the hard depth-1 cap then lands the direction unresolved)."
)


def _gate_skill() -> str:
    from polymerhus.recon.domain.skills import skill_for

    return skill_for("hunting/hunt-orchestrator", fallback=_GATE_SKILL_FALLBACK)


def _rematch_skill() -> str:
    from polymerhus.recon.domain.skills import skill_for

    return skill_for("hunting/hunt-orchestrator-rematch", fallback=_REMATCH_SKILL_FALLBACK)


def _compose_gate_prompt(inp: GateInput) -> str:
    """Render the Q8 gate input (accepted candidates + KB evidence + graph surface)
    into the reasoning turn's user prompt."""
    lines = [
        f"KB grounding: {'DEGRADED (KB unavailable; do not prune on this)' if inp.kb_degraded else 'available'}",
        "",
        "Candidates:",
    ]
    for c in inp.candidates:
        w = c.applies_witnesses
        lines.append(
            f"- unit={c.unit_id} fault_class={c.fault_class} match_verdict={c.match_verdict} "
            f"witness_deterministic={w.deterministic!r} witness_llm={w.llm!r} "
            f"kb_evidence={inp.kb_evidences.get(c.fault_class) or '(none)'}"
        )
    lines += [
        "",
        f"Read-only graph surface (index cards): {inp.surface or '(none)'}",
        "",
        "Return one direction per candidate: set carried true/false, and for a "
        "carried direction fill rationale, assumptions, envisioned_test_primitives, "
        "and supposed_payload_vectors.",
    ]
    return "\n".join(lines)


def _compose_rematch_prompt(unit_id: str, fault_class: str, result: TargetedReconResult) -> str:
    return (
        f"Re-match the fault class {fault_class} against unit {unit_id} on the "
        f"back-edge result.\n"
        f"status: {result.status}\n"
        f"error: {result.error}\n"
        f"pod exports: {[e.model_dump() if hasattr(e, 'model_dump') else e for e in result.pod_exports]}\n\n"
        "Return the three-valued verdict for this (unit_id, fault_class)."
    )


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


# --- production seam factories ------------------------------------------------

def build_gate_reason_fn() -> Callable[[GateInput], GateDecision]:
    """The orchestrator's `reason_fn`: the Q8 embedded gate-reasoning turn, run on
    the `hunting_orchestrator` role with structured `GateDecision` output. Fail-open
    is the orchestrator's responsibility (a raising `reason_fn` carries every
    candidate); here a None/unparseable structured result surfaces as an empty
    decision, which `run_orchestration` treats identically."""
    def reason_fn(inp: GateInput) -> GateDecision:
        from langchain_core.messages import HumanMessage, SystemMessage

        from polymerhus.app.llm.roles import invoke_role

        result = invoke_role(
            GATE_ROLE,
            [SystemMessage(content=_gate_skill()),
             HumanMessage(content=_compose_gate_prompt(inp))],
            schema=GateDecision,
        )
        return result if isinstance(result, GateDecision) else GateDecision()

    return reason_fn


def build_rematch_fn() -> Callable[[str, str, TargetedReconResult], MatchVerdict]:
    """The orchestrator's `rematch_fn`: the D2 three-valued re-match after a
    park/resume back-edge, on the `hunting_orchestrator` role with structured
    `MatchVerdict` output. A None/unparseable result degrades to
    `insufficient-evidence`, which the depth-1 cap lands as unresolved (never a
    false 'applies')."""
    def rematch_fn(unit_id: str, fault_class: str, result: TargetedReconResult) -> MatchVerdict:
        from langchain_core.messages import HumanMessage, SystemMessage

        from polymerhus.app.llm.roles import invoke_role

        verdict = invoke_role(
            GATE_ROLE,
            [SystemMessage(content=_rematch_skill()),
             HumanMessage(content=_compose_rematch_prompt(unit_id, fault_class, result))],
            schema=MatchVerdict,
        )
        if isinstance(verdict, MatchVerdict):
            return verdict
        return MatchVerdict(unit_id=unit_id, fault_class=fault_class,
                            verdict="insufficient-evidence")

    return rematch_fn


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


def build_actor_hunting_agent(*, store, run_id, kb, pod, axis=None,
                              checkpointer=None, model_factory=None,
                              observe: bool = True):
    """Compose the production hunting-agent dispatch seam (feat/async-actor-agents):
    a `build_hunting_agent` harness whose `author`/`judge` are per-hunt
    `HuntingHunterActor` turns, registered per run by a `HuntingActorRegistry`.

    Returns `(dispatch_fn, registry)`: the harness `dispatch_fn` is async-native
    (see `hunting_agent.build_hunting_agent`); the caller passes it to
    `run_orchestration`/`arun_orchestration` and reaps the registry (`stop_all`)
    when the run's orchestration finishes. Construction performs no imports."""
    from polymerhus.attack.hunting.actors import HuntingActorRegistry  # noqa: PLC0415
    from polymerhus.attack.hunting.hunting_agent import build_hunting_agent  # noqa: PLC0415

    registry = HuntingActorRegistry(run_id, checkpointer=checkpointer,
                                    model_factory=model_factory, observe=observe)
    dispatch_fn = build_hunting_agent(
        store=store, run_id=run_id, kb=kb, pod=pod,
        author=build_actor_author_fn(registry),
        judge=build_actor_judge_fn(registry),
        axis=axis,
    )
    return dispatch_fn, registry
