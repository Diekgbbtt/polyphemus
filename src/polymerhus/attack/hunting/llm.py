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
    PhaseTurnInput,
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
    "name, type, and sensitivity. The L1 is a judged abstraction over the "
    "observed L0 graph: every node here is an inference licensed by "
    "observations, never direct evidence. The projection is the typed facet surface "
    "you reason over - a proxy for the full characterisation, not an "
    "authoritative classification - so an absent or unknown facet is missing "
    "evidence, never evidence of absence."
)

_GATE_SKILL_FALLBACK = (
    "You are the hunt-orchestrator: the node-per-phase REASON body "
    "(candidates-rewrite spec 3.2/3.3, amended by the memory + workflow-graph "
    "rework) that takes ONE (unit, fault) pair through the hypothesise -> "
    "ratify -> note phases. The phase-transition verbatims are injected in the "
    "tool-call responses (never here); this skill carries the reasoning "
    "discipline. "
    "Hypothesise phase: read the unit's applies-witnesses and three-valued "
    "match verdict, the fault's materialisation and fold family, the read-only "
    "graph surface, and the rich typed projection (including cooperating "
    "systems adjacency). Elicit one or more vulnerability classes - at the "
    "grain of a web-vulnerability CLASS with a research-direction rationale "
    "(e.g. CSRF, IDOR) - never narrowed to a surface locale, payload profile, "
    "vector, or symptom; the narrowing belongs to the hunting agent at "
    "spec-writing. Prune only on positive grounds; NEVER prune on degraded "
    "grounds: when the KB is unavailable (kb_degraded), reason from the "
    "candidate and surface alone and carry rather than prune. "
    "Prior-hunt reflection (Q11): prior minted-config keys are listed in the "
    "prompt; you NEVER write a config that duplicates a prior one; you MAY "
    "call hunts_store(read) to inspect a prior key before writing. "
    "Knowledge-sufficiency decision point (Q9): given this fault class and "
    "unit type, do I have sufficient knowledge of the previous dispatched "
    "hunts and all potentially useful insights collected? If not, loop "
    "hunts_store(read) / notes(read). Target-knowledge loop (Q9): do I have "
    "enough technical knowledge of this unit to concretise the abstract fault "
    "at this locus? If not, query via graph_view iterating until sufficient. "
    "Same-class merge (Q16): if multiple elicited vulnerability classes at one "
    "locus are the same web-vulnerability class, merge them into one; only "
    "fundamentally discriminable classes survive as distinct configs. Pure LLM "
    "reflection - no module-side parsing. The hypothesise write: "
    "hunts_store(write, config, status='hypothesised'), one draft per "
    "surviving class with only rationale + research_direction filled - the "
    "capabilities / assumptions / technique-primitives analysis is the "
    "RATIFICATION phase's work. Consider cooperating systems when creating a "
    "HuntConfig targeting a system. Tools are exactly three: hunts_store, "
    "notes, graph_view (no back-edge-to-recon tool, no budget tool). Return "
    "the directions, each marked carried or pruned; the deterministic mint "
    "fans out N hypothesised drafts per distinct class at this phase."
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


def _system_render(info) -> str:
    """Deterministic one-line render of a SystemInfo (an unpacked edge target
    or a D3 cooperating neighbour): the typed attributes (kind, discriminator,
    exposure, description) plus the sorted raw non-identity props. An absent or
    empty info renders a marker, never a raise."""
    if info is None:
        return "(absent)"
    kind = getattr(info, "kind", None) or "UNKNOWN"
    parts = [f"kind={kind}"]
    for attr in ("discriminator", "exposure", "description"):
        val = getattr(info, attr, None)
        if val is not None:
            parts.append(f"{attr}={val}")
    props = getattr(info, "props", None) or {}
    prop_items = sorted(f"{k}={v}" for k, v in props.items() if v is not None
                        if k not in ("kind", "discriminator", "exposure",
                                     "description"))
    if prop_items:
        parts.append("props={" + ", ".join(prop_items) + "}")
    return "; ".join(parts)


def _data_item_render(item) -> str:
    """Deterministic one-line render of a DataItem (a data-flow edge's full
    node): the named trust slots (name/type/sensitivity, fields, notes). An
    absent or empty item renders a marker, never a raise."""
    if item is None:
        return "(absent)"
    parts = []
    for attr in ("name", "type", "sensitivity"):
        val = getattr(item, attr, None)
        if val is not None:
            parts.append(f"{attr}={val}")
    if getattr(item, "fields", None):
        parts.append("fields=" + ",".join(sorted(map(str, item.fields))))
    if getattr(item, "notes", None):
        parts.append(f"notes={item.notes}")
    return "; ".join(parts) or "(data item without typed slots)"


def _render_projection(projection) -> str:
    """Deterministic render of the unit's typed projection (spec 3.1/3.7): the
    typed spine keys present, per-family outgoing Service->System edges (target
    kind + role presence + the fully-unpacked target System), the data-edge
    counts, the DataRelationship kinds among the unit's items - and, as of T5,
    the RICH slots the T2 projection carries: the exploded DataItems (family ->
    name/type/sensitivity), the DataRelationship kind chains, and the D3
    cooperating-systems adjacency. The compat facets are never removed; each
    slot is read via getattr and a missing facet degrades that slot only -
    absence renders as UNKNOWN/(none) (never FALSE, never a prune signal -
    C16)."""
    if projection is None:
        return "UNKNOWN (projection read failed or absent)"
    kind = getattr(projection, "kind", None) or "UNKNOWN"
    spine = getattr(projection, "spine", None) or {}
    edges = getattr(projection, "edges", None) or {}
    data_edges = getattr(projection, "data_edges", None) or {}
    data_rel = getattr(projection, "data_rel_kinds", None) or frozenset()
    data_items = getattr(projection, "data_items", None) or {}
    data_relationships = getattr(projection, "data_relationships", None) or ()
    cooperating_systems = getattr(projection, "cooperating_systems", None) or {}

    out = [f"unit kind: {kind}"]
    spine_keys = sorted(k for k in spine if k)
    out.append(f"spine (present keys): {spine_keys or '(none present)'}")
    if edges:
        families = []
        for family in sorted(edges):
            infos = edges.get(family) or ()
            rendered = []
            for e in infos:
                target = getattr(e, "target_kind", None) or "UNKNOWN"
                role = getattr(e, "role", None)
                line = f"{target}{' (role present)' if role is not None else ''}"
                sys_info = getattr(e, "target", None)
                if sys_info is not None and getattr(sys_info, "kind", None):
                    line += f" -> {_system_render(sys_info)}"
                rendered.append(line)
            families.append(f"{family}: {sorted(rendered) or '(no edges)'}")
        out.append("outgoing edges:")
        out += [f"  - {line}" for line in families]
    else:
        out.append("outgoing edges: (none)")
    if data_edges:
        out.append("data edges: " + ", ".join(
            f"{fam}={data_edges[fam]}" for fam in sorted(data_edges)))
    else:
        out.append("data edges: (none)")
    out.append("data-relationship kinds: " +
               ("; ".join(sorted(data_rel)) if data_rel else "(none)"))
    if data_items:
        out.append("data items:")
        for family in sorted(data_items):
            items = data_items.get(family) or ()
            rendered = sorted(_data_item_render(i) for i in items)
            out.append(f"  - {family}: {', '.join(rendered) or '(none)'}")
    else:
        out.append("data items: (none)")
    if data_relationships:
        out.append("data relationships:")
        chains = []
        for r in data_relationships:
            family = getattr(r, "family", None) or "?"
            from_key = getattr(r, "from_item_key", None)
            to_key = getattr(r, "to_item_key", None)
            line = f"{family}: {from_key or '?'} -> {to_key or '?'}"
            predicate = getattr(r, "predicate", None)
            if predicate:
                line += f" (predicate: {predicate})"
            chains.append(line)
        out += [f"  - {line}" for line in sorted(chains)]
    else:
        out.append("data relationships: (none)")
    if cooperating_systems:
        out.append("cooperating systems:")
        for family in sorted(cooperating_systems):
            infos = cooperating_systems.get(family) or ()
            rendered = sorted(_system_render(i) for i in infos)
            out.append(f"  - {family}: {', '.join(rendered) or '(none)'}")
    else:
        out.append("cooperating systems: (none)")
    return "\n".join(out)


def _render_materialisation(entry) -> str:
    """Deterministic render of a fault's materialisation-facet content (the CWE
    NL evidence, spec 3.1): name, description, extended description, alternate
    terms, related attack patterns, likelihood, common consequences,
    potential mitigations, functional areas - each facet sorted where it is a
    sequence; an absent entry renders UNKNOWN (never a prune signal - C16).
    Accepts the `FaultMaterialisation` dataclass or a plain dict (both shapes
    occur on the `GateInput` surface)."""
    if entry is None:
        return "UNKNOWN (materialisation unavailable for this fault_class)"

    def _f(name):
        if isinstance(entry, dict):
            return entry.get(name)
        return getattr(entry, name, None)

    name = _f("name")
    description = _f("description")
    extended = _f("extended_description")
    alt_terms = _f("alternate_terms") or []
    patterns = _f("related_attack_patterns") or []
    likelihood = _f("likelihood")
    consequences = _f("common_consequences") or []
    mitigations = _f("potential_mitigations") or []
    areas = _f("functional_areas") or []

    out = []
    if name:
        out.append(f"fault: {name}")
    if description:
        out.append(f"description: {description}")
    if extended:
        out.append(f"extended description: {extended}")
    if alt_terms:
        out.append("alternate terms: " + "; ".join(sorted(map(str, alt_terms))))
    if patterns:
        out.append("related attack patterns: " + "; ".join(sorted(map(str, patterns))))
    if likelihood:
        out.append(f"likelihood: {likelihood}")
    if consequences:
        out.append("common consequences: " + "; ".join(sorted(map(str, consequences))))
    if mitigations:
        out.append("potential mitigations: " + "; ".join(sorted(map(str, mitigations))))
    if areas:
        out.append("functional areas: " + "; ".join(sorted(map(str, areas))))
    return "\n".join(out) or "(materialisation entry empty)"


def _render_fold_family(ids) -> str:
    """Deterministic render of the folded sub-fault family (spec 3.1): the
    sorted tuple of folded fault_ids captured under the parent fault class -
    consideration material, never a prune signal. An absent key renders
    UNKNOWN (C16)."""
    if not ids:
        return "UNKNOWN (no sub-fault fold family captured under this fault)"
    return ", ".join(sorted(map(str, ids)))


def _render_unit_block(units, unit_projection, compat_projection, kb_evidences) -> str:
    """Deterministic render of one matched-unit block (spec 3.7 Q4): each unit's
    identity + witness line followed by ITS OWN rich projection render. The
    projection resolves from the per-unit slot first; the single-unit compat
    slot (`compat_projection`) is the fallback, so a legacy hand-built `GateInput`
    still renders. Every facet degrades independently (C16)."""
    out = []
    for c in units:
        w = c.applies_witnesses
        proj = (unit_projection or {}).get(c.unit_id)
        if proj is None:
            proj = compat_projection
        out.append(
            f"- unit={c.unit_id} fault_class={c.fault_class} "
            f"match_verdict={c.match_verdict} "
            f"witness_deterministic={w.deterministic!r} "
            f"witness_llm={w.llm!r} "
            f"kb_evidence={(kb_evidences or {}).get(c.fault_class) or '(none)'}"
        )
        out += ["    Unit projection (typed facet surface):"]
        out += [f"      {line}" for line in _render_projection(proj).split("\n")]
    return "\n".join(out)


def _compose_gate_prompt(inp: GateInput) -> str:
    """Render the HYPOTHESISE-phase input (spec 3.7, re-scoped by #167/#168) into
    the phase turn's user prompt. The frame OPENS with the L1 ontology primer
    constant (G9, the conceptions of Service / System / DataItem + the domain-
    model philosophy - a user-prompt constant, never the system prompt, spec
    3.7), then the pair header renders the fault class, the KB-grounding line,
    the read-only graph surface, the materialisation and the fold family; the
    matched units split into a Services section and a Systems section, each
    with its own adversarial-reasoning intro (Q4) and each unit's OWN rich
    projection render; then the hypothesise-phase discipline block (Q11 prior-
    hunt reflection on `prior_minted_keys`, Q9 knowledge-sufficiency +
    target-knowledge loops, Q8 hypothesis elicitation, Q16 same-class merge,
    and the hypothesise write). The phase-TRANSITION verbatims are NOT part of
    this prompt - they ride the tool-call responses from the constants (G1/G3).
    Deterministic sorted rendering throughout; every slot degrades
    independently (never FALSE, never a prune signal - C16)."""
    fault_class = inp.candidates[0].fault_class if inp.candidates else None

    # The section split is on the kind-qualified identity, never on the
    # projection kind: "Service:<slug>" lands in Services, "<kind>:<key>" in
    # Systems - so a degraded projection still reaches the right section.
    def _section(unit_id: str) -> str:
        return "Service" if str(unit_id).startswith("Service:") else "System"

    services = sorted((c for c in inp.candidates if _section(c.unit_id) == "Service"),
                      key=lambda c: c.unit_id)
    systems = sorted((c for c in inp.candidates if _section(c.unit_id) == "System"),
                     key=lambda c: c.unit_id)

    lines = [L1_ONTOLOGY_PRIMER, ""]
    lines += [
        f"KB grounding: {'DEGRADED (KB unavailable; do not prune on this)' if inp.kb_degraded else 'available'}",
        f"Read-only graph surface (index cards): {inp.surface or '(none)'}",
    ]
    if fault_class is not None:
        lines += [
            f"Fault class (schedule unit): {fault_class}",
            f"Fault materialisation ({fault_class}):",
            _render_materialisation((inp.materialisation or {}).get(fault_class)),
            f"Sub-fault fold family (consideration material):",
            _render_fold_family((inp.fold_family or {}).get(fault_class)),
        ]

    unit_projection = inp.unit_projection or {}
    lines += ["", "Services:"]
    if services:
        lines += [
            "Adversarial reasoning over each Service: spell its surface - its "
            "edged DataItems and Systems - and where the fault could bite.",
            _render_unit_block(services, unit_projection, inp.projection, inp.kb_evidences),
        ]
    else:
        lines.append("(no matched Service units)")
    lines += ["", "Systems:"]
    if systems:
        lines += [
            "Adversarial reasoning over each System: outline the System "
            "distinctly - its kind, exposure, and props - and where the fault "
            "could bite it.",
            _render_unit_block(systems, unit_projection, inp.projection, inp.kb_evidences),
        ]
    else:
        lines.append("(no matched System units)")

    prior_keys = sorted(str(k) for k in (inp.prior_minted_keys or []))
    lines += [
        "",
        "Hypothesise-phase discipline (per pair):",
        "  Prior-hunt reflection (Q11): Prior minted-config keys to reflect on: "
        f"{', '.join(prior_keys) if prior_keys else '(none)'}",
        "    - You NEVER write a config that duplicates a prior one. Before "
        "writing you MAY call hunts_store(read) to inspect a prior key's config "
        "and assess overlap; a config you assert as a duplicate is never written.",
        "  Knowledge-sufficiency decision point (Q9): given this fault class and "
        "unit type, decide whether you have sufficient knowledge of the previous "
        "dispatched hunts and all potentially useful insights collected; if not, "
        "loop the memory reads (hunts_store(read) / notes(read)).",
        "  Target-knowledge loop (Q9): against the materialised unit (projection "
        "+ surface), if you lack enough technical knowledge of this unit to "
        "concretise the abstract fault at this locus, query the attack-surface / "
        "L1 graph via graph_view, iterating until sufficient.",
        "  Hypothesis elicitation (Q8): for each unit above, elicit one or more "
        "vulnerability classes - at the grain of a web-vulnerability CLASS with "
        "a research-direction rationale (e.g. CSRF, IDOR) - never narrowed to a "
        "surface locale, payload profile, vector, or symptom; the narrowing "
        "belongs to the hunting agent at spec-writing.",
        "  Same-class merge (Q16): if multiple elicited vulnerability classes at "
        "one locus are the SAME web-vulnerability class, merge them into one; "
        "only fundamentally discriminable classes survive as distinct configs. "
        "Pure LLM reflection - no module-side parsing.",
        "  The hypothesise write (spec 3.3): call hunts_store(write, config, "
        "status='hypothesised') with ONE draft per surviving class, carrying "
        "rationale + research_direction ONLY. The capability/assumption/"
        "technique-primitive analysis is the RATIFICATION phase's work (the next "
        "phase) - never filled at this hypothesise turn.",
        "",
        "Return one direction per candidate: set carried true/false, and for a "
        "carried direction fill rationale, research_direction, and "
        "vulnerability_classes ONLY. The capabilities / assumptions / "
        "technique-primitives are the RATIFICATION phase's work (a later "
        "phase) - never a seed you fill at this hypothesise turn.",
    ]
    return "\n".join(lines)


def _compose_ratify_prompt(inp: PhaseTurnInput) -> str:
    """Render the RATIFY-phase input (spec 3.2, re-scoped by #167/#168): the
    frame OPENS with the L1 ontology primer constant (G9, shared with the gate
    and note frames), then the pair and the hypothesised drafts it may
    update/delete/create. The phase transitions ride the tool-call responses
    (NEXT_RATIFY_HINT on the hypothesised write, ONLY NEXT_NOTE_HINT on the
    ratified write - G1), never this prompt: the prompt carries the pair data
    and the ratification contract (must END with a status='ratified' write
    carrying the filled capabilities / assumptions / technique-primitives)."""
    pair = inp.pair
    lines = [L1_ONTOLOGY_PRIMER, ""]
    lines += [
        f"RATIFICATION phase (pair {pair.unit_id}::{pair.fault_class}):",
        f"Hypothesised drafts to ratify: {len(inp.configs)}",
    ]
    for config in inp.configs:
        template = config.prompt_template
        lines += [
            f"  - config {config.hunt_id} "
            f"[vulnerability_class={config.vulnerability_class!r}, "
            f"status={config.status!r}]",
            f"    rationale: {template.rationale or '(none)'}",
            f"    research_direction: {template.research_direction or '(none)'}",
        ]
    lines += [
        "",
        "Ratification contract: you may call hunts_store(write, config) "
        "multiple times to update/delete/create configs. End ratification by a "
        "hunts_store write carrying status='ratified' and, very likely, the "
        "filled adversarial_capabilities / assumptions / technique_primitives. "
        "A config you delete during ratification is written status='dropped' "
        "(it stays on disk, G6).",
        "",
        "Return the pair's configs at their final status.",
    ]
    return "\n".join(lines)


def _compose_note_prompt(inp: PhaseTurnInput) -> str:
    """Render the NOTE-phase input (spec 3.2/G8, re-scoped by #167/#168): the
    frame OPENS with the L1 ontology primer constant (G9, shared with the gate
    and ratify frames), then the pair and its ratified configs. The note-taking
    verbatim rides the ratified write's tool-call response (NEXT_NOTE_HINT, G1)
    and the pair-end verbatim rides the notes tool's response (NEXT_PAIR_HINT +
    next pair) - this prompt carries the pair data and the G8 note contract
    only."""
    pair = inp.pair
    lines = [L1_ONTOLOGY_PRIMER, ""]
    lines += [
        f"NOTE phase (pair {pair.unit_id}::{pair.fault_class}):",
        f"Ratified configs to note: {len(inp.configs)}",
    ]
    for config in inp.configs:
        template = config.prompt_template
        lines += [
            f"  - config {config.hunt_id} "
            f"[vulnerability_class={config.vulnerability_class!r}]",
            f"    rationale: {template.rationale or '(none)'}",
            f"    research_direction: {template.research_direction or '(none)'}",
        ]
    lines += [
        "",
        "Note contract (G8): write ONE note per config covering ALL the "
        "decisions that concern it - the observations drawn from your tool "
        "calls (graph_view or memory reads) that drove the rationale on all "
        "choices - more detailed than the config's rationale and walking the "
        "reasoning that yielded it.",
        "",
        "Return the notes, each keyed to its config.",
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
