"""FR-CURATE - the post-recon curation pass + FR-TYPESEP-b re-homing backstop.

A driver-invoked terminal pass (deliberately NOT wired into `run_pipeline`, plan
§Global Constraints) that reconciles the accumulated Layer-1 graph once recon has
stabilised it: it reads the whole L1 (index-cards + inventory + stale pool),
asks a curation LLM pass to propose typed reconciliation (dedup merges, noise
deletes, mis-type relabels, journey groupings, and prop re-homing), executes them
through the `l1_curator` sole-writer, re-homes any System fact stranded as a
Service prop, runs the webpage-anatomy skill + the end-of-phase sweeps, and
returns a `CurationReport`.

Sole-writer discipline: every `:L1*` write here goes through `l1_curator`
(`reconcile` / `l1_curate` / `enrich` / `strip_props`); this module never emits
Cypher. Provenance is stamped on every write. Each stage is FAIL-OPEN: a stage
that raises degrades to its default and records the error, and LATER stages still
run (mirrors the analyser pod's degrade-to-empty discipline). `propose_fn` and
`read_fn` are injectable so the pass is unit-testable without a live LLM/DB.
"""
from __future__ import annotations

import logging

from agent.recon.analysis import anatomy, index_card, l1_curator, l1_inventory, sweep
from agent.recon.analysis.curation_types import (
    CurationBatch,
    CurationReport,
    curation_proposals_to_ops,
)
from agent.recon.analysis.l1_types import (
    Provenance,
    ServiceDelta,
    StripPropsOp,
    SystemDelta,
    SystemEdgeDelta,
)

logger = logging.getLogger(__name__)

# Cap the stale-pool slice rendered into the curation prompt so a huge unassigned
# pool cannot blow the model's context window (mirrors pod._MAX_L0_NODES).
_MAX_STALE_IN_PROMPT = 200


# --- FR-TYPESEP-b / FR-MODELFIX: the deterministic prop -> System re-homing table
# A mechanism classification wrongly set on a Service is re-homed to the correct
# System reached by a typed edge (so the Stage-3 DFS over a service's System edges
# can find it), then the stale Service prop is stripped. Every rel is in
# `SYSTEM_EDGE_RELS` and every target `system_kind` is a known `SystemKind`
# (l1_curator validates both).
#
# Each rule returns (rel, system_kind, edge_kwargs, system_props):
#   * `rel` / `system_kind` - the typed edge and its target System kind;
#   * `edge_kwargs` - extra edge props (e.g. `realm`) folded onto the SystemEdge;
#   * `system_props` - props to write ON the target System (the classification
#     VALUE itself, so it is not lost when the stale Service prop is stripped).
#
# The web-presentation dimensions (rendering_model, navigation_model) both re-home
# to INDEPENDENT props on ONE `WebPresentation` System reached by `EXPOSED_VIA`
# (the mechanism-as-System correction); neither is inferred from the other
# (L1D-31a - the old SPA->CSR inference is deleted).
_WEB_PRESENTATION = "WebPresentation"


def _rendering_target(value) -> tuple[str, str, dict, dict]:
    """rendering_model -> a `rendering_model` PROP on the WebPresentation System,
    reached by EXPOSED_VIA. The value is stored as-is, independent of navigation."""
    return "EXPOSED_VIA", _WEB_PRESENTATION, {}, {"rendering_model": value}


def _navigation_target(value) -> tuple[str, str, dict, dict]:
    """navigation_model -> a `navigation_model` PROP on the WebPresentation System,
    reached by EXPOSED_VIA. Independent of rendering - no SPA->CSR inference."""
    return "EXPOSED_VIA", _WEB_PRESENTATION, {}, {"navigation_model": value}


def _paradigm_target(value) -> tuple[str, str, dict, dict]:
    """api_paradigm -> EXPOSED_VIA a REST / GraphQL API System (the paradigm IS the
    System kind, so it needs no extra prop)."""
    v = str(value or "").upper()
    kind = "GraphQLApi" if "GRAPH" in v else "RESTApi"
    return "EXPOSED_VIA", kind, {}, {}


def _auth_target(value) -> tuple[str, str, dict, dict]:
    """auth_methods -> AUTHENTICATED_BY the AuthenticationMechanism System, the
    method(s) carried as the edge `realm` (mechanism = System, L1D-5)."""
    if isinstance(value, (list, tuple, set)):
        realm = ",".join(str(v) for v in value if v) or None
    else:
        realm = str(value) if value not in (None, "") else None
    return "AUTHENTICATED_BY", "AuthenticationMechanism", {"realm": realm}, {}


def _perimeter_target(value) -> tuple[str, str, dict, dict]:
    """perimeter -> the matching perimeter System edge (WAF / CDN / gateway /
    reverse proxy)."""
    v = str(value or "").upper()
    if "WAF" in v:
        return "FRONTED_BY", "WAF", {}, {}
    if "CDN" in v:
        return "FRONTED_BY", "CDN", {}, {}
    if "GATEWAY" in v:
        return "ROUTED_BY", "APIGateway", {}, {}
    return "FRONTED_BY", "ReverseProxy", {}, {}


# The mechanism-classification props that belong on a System, keyed by Service prop.
_REHOME_RULES = {
    "rendering_model": _rendering_target,
    "navigation_model": _navigation_target,
    "api_paradigm": _paradigm_target,
    "auth_methods": _auth_target,
    "perimeter": _perimeter_target,
}


def _note_error(report: CurationReport, msg: str) -> None:
    report.error = f"{report.error}; {msg}" if report.error else msg


# --- Stage 1: read the L1 context (fail-open per sub-read) ---------------------

def _read_context(project_id: str, read_fn, report: CurationReport) -> dict:
    """Read the index-cards + inventory + stale pool. Each sub-read is guarded so
    a failure in one still yields the others (partial context survives)."""
    context: dict = {
        "cards": [],
        "inventory": {"services": [], "systems": [], "data_items": []},
        "stale_pool": [],
    }
    try:
        context["cards"] = index_card.index_cards(project_id, read_fn=read_fn)
    except Exception as exc:
        logger.warning("curation.read: index_cards failed", exc_info=True)
        _note_error(report, f"read_cards: {exc}")
    try:
        context["inventory"] = l1_inventory.read_l1_inventory(project_id, read_fn=read_fn)
    except Exception as exc:
        logger.warning("curation.read: inventory failed", exc_info=True)
        _note_error(report, f"read_inventory: {exc}")
    try:
        context["stale_pool"] = sweep.stale_pool(project_id, read_fn=read_fn)
    except Exception as exc:
        logger.warning("curation.read: stale_pool failed", exc_info=True)
        _note_error(report, f"read_stale: {exc}")
    return context


# --- Stage 2: the curation LLM proposal pass (real collaborator) ---------------

_CURATION_FALLBACK = (
    "You are the post-recon curation pass. Reconcile the accumulated Layer-1 "
    "graph: propose merges (duplicate services/systems keyed by "
    "business_function_slug / system_kind:discriminator), deletes (off-role/noise "
    "nodes), relabels (mis-typed nodes), journeys ({journey_slug: [service_slug]}), "
    "and rehome (a Service prop that is really a System fact). Ground every "
    "proposal in the provided cards; propose nothing not present. Empty proposals "
    "are a valid honest result."
)


def _load_curation_skill() -> str:
    """The curation system prompt COMPOSED with the analyser reasoning skill (the
    curation pass reasons the same way, then applies the reconciliation rules).
    Both are loaded via the shared `skill_for`, degrading to the inline fallbacks
    if the mount is unavailable (a missing mount never crashes the pass)."""
    from agent.recon.skills import skill_for

    analyser = skill_for("analysis/analyser", fallback="")
    curation = skill_for("analysis/curation", fallback=_CURATION_FALLBACK)
    return f"{analyser}\n\n{curation}" if analyser else curation


def _curation_prompt(context: dict) -> str:
    """Ground the curation proposal in the CURRENT inventory (so merges/relabels
    reference real keys) + the index-cards (so proposals cite real evidence) + the
    stale/unassigned L0 pool (the prune/reclass candidates)."""
    inv = context.get("inventory") or {}
    cards = context.get("cards") or []
    stale = context.get("stale_pool") or []
    return (
        "CURATION PASS. Reconcile the accumulated Layer-1 graph below. Dedup is "
        "identity reuse: two services are the same iff they share a "
        "business_function_slug intent; two systems iff the same "
        "system_kind:discriminator. Propose ONLY against the keys present here; "
        "invent no node not present. An empty proposal set is a valid honest "
        "result.\n\n"
        "CURRENT L1 INVENTORY (propose merges / relabels against THESE exact keys):\n"
        f"  Services (business_function_slug): {inv.get('services')}\n"
        f"  Systems (system_kind[:discriminator]): {inv.get('systems')}\n"
        f"  DataItems (item_key): {inv.get('data_items')}\n\n"
        f"INDEX CARDS ({len(cards)}): {cards}\n\n"
        f"STALE / UNASSIGNED L0 ELEMENTS ({len(stale)} total, showing "
        f"{min(len(stale), _MAX_STALE_IN_PROMPT)}): {stale[:_MAX_STALE_IN_PROMPT]}\n\n"
        "Propose `merges`, `deletes`, `relabels`, `journeys`, and `rehome`."
    )


def default_propose_fn(context: dict) -> CurationBatch:
    """Real collaborator: ask the analyser-role LLM to propose the curation batch,
    structured output via function_calling (tolerates the open-ended dict/journeys
    fields), wrapped in the analyser's bounded retry. Degrades to an empty batch
    if the model returns no parseable tool call (fail-open)."""
    from langchain_core.messages import HumanMessage, SystemMessage

    from agent.app.llm.roles import chat_model_for
    from agent.recon.analysis.pod import _invoke_with_retry

    llm = chat_model_for("analyser")
    structured = llm.with_structured_output(CurationBatch, method="function_calling")
    result = _invoke_with_retry(structured.invoke, [
        SystemMessage(content=_load_curation_skill()),
        HumanMessage(content=_curation_prompt(context)),
    ])
    return result or CurationBatch()


# --- Stage 4: light journey membership (append-not-clobber) --------------------

def _write_journeys(project_id: str, batch: CurationBatch, cards: list, provenance: Provenance) -> int:
    """Write each proposed journey grouping onto its member Services as a
    `journeys: list[str]` prop via `l1_curator.l1_curate`. Props are open and
    `identity ⊥ membership`, so this never churns Service identity. Existing
    journeys (read off the index-cards) are UNIONed in, so we append, never
    clobber. Returns the number of member Services written."""
    journeys = batch.journeys or {}
    proposed: dict[str, set] = {}
    for journey_slug, members in journeys.items():
        if not journey_slug:
            continue
        for slug in (members or []):
            if slug:
                proposed.setdefault(slug, set()).add(journey_slug)
    if not proposed:
        return 0

    existing: dict[str, set] = {}
    for card in cards or []:
        if card.get("kind") != "Service":
            continue
        slug = (card.get("key") or {}).get("business_function_slug")
        if not slug:
            continue
        cur = (card.get("nl_handles") or {}).get("journeys")
        if isinstance(cur, list):
            existing[slug] = set(cur)

    deltas = [
        ServiceDelta(
            business_function_slug=slug,
            props={"journeys": sorted(existing.get(slug, set()) | new_journeys)},
            provenance=provenance,
        )
        for slug, new_journeys in sorted(proposed.items())
    ]
    if not deltas:
        return 0
    l1_curator.l1_curate(deltas, [], project_id)
    return len(deltas)


# --- Stage 5: webpage anatomy (self-contained; authz deferred) ----------------

def _card_signals(card: dict) -> dict:
    """Assemble the signal bag the webpage-profile skill classifies from - the
    card's spine + NL handles (+ a base_url handle when present)."""
    handles = card.get("nl_handles") or {}
    signals = {
        "service_slug": (card.get("key") or {}).get("business_function_slug"),
        "spine": card.get("spine") or {},
        "handles": handles,
    }
    if handles.get("base_url"):
        signals["base_url"] = handles["base_url"]
    return signals


def _anatomy_stage(project_id: str, cards: list, provenance: Provenance) -> dict:
    """Run the webpage-profile anatomy skill for each Service, committing the triple
    via `commit_anatomy` (which is idempotent: it MERGEs the WebPresentation System
    by identity, so re-profiling an already-settled Service is a harmless no-op).
    We do not skip on an EXPOSED_VIA edge because that edge family is shared with
    the REST/GraphQL API Systems, so the token-light card's edge-degree cannot tell
    a settled web-presentation from an API exposure. Fail-open per service. Authz
    classification needs live per-role probe RESULTS (interface-B), which curation
    does not have, so it is recorded as deferred rather than fabricated."""
    profiled = 0
    committed = 0
    for card in cards or []:
        if card.get("kind") != "Service":
            continue
        slug = (card.get("key") or {}).get("business_function_slug")
        if not slug:
            continue
        try:
            result = anatomy.webpage_profile(_card_signals(card), service_id=slug)
        except Exception:
            logger.warning("curation.anatomy: webpage_profile failed for %s", slug, exc_info=True)
            continue
        profiled += 1
        try:
            anatomy.commit_anatomy(result, project_id, slug, provenance=provenance)
            committed += 1
        except Exception:
            logger.warning("curation.anatomy: commit failed for %s", slug, exc_info=True)
    return {"profiled": profiled, "committed": committed, "authz": "deferred"}


# --- Stage 6: FR-TYPESEP-b re-homing (deterministic backstop + LLM proposals) --

def _rehome_one(project_id: str, slug: str, prop_key: str, value, provenance: Provenance, seen: set) -> bool:
    """Re-home ONE stranded Service prop: write the classification VALUE as a prop
    on the target System (`l1_curator.l1_curate`, when the rule carries system
    props - e.g. the WebPresentation's rendering_model/navigation_model), connect
    the Service to it via a typed edge (`l1_curator.enrich`), then strip the stale
    Service prop (`l1_curator.strip_props`). Deduped on (slug, prop_key). Fail-open."""
    if not slug:
        return False
    key = (slug, prop_key)
    if key in seen:
        return False
    rule = _REHOME_RULES.get(prop_key)
    if rule is None:
        return False
    rel, system_kind, edge_kwargs, system_props = rule(value)
    if not system_kind:
        return False
    seen.add(key)
    try:
        # write the classification VALUE as a prop on the target System so it is not
        # lost when the stale Service prop is stripped (WebPresentation carries the
        # rendering_model / navigation_model value as an independent prop).
        if system_props:
            l1_curator.l1_curate([], [
                SystemDelta(system_kind=system_kind, props=system_props, provenance=provenance),
            ], project_id)
        l1_curator.enrich(project_id, system_edges=[
            SystemEdgeDelta(service_slug=slug, system_kind=system_kind, rel=rel,
                            provenance=provenance, **edge_kwargs),
        ])
        l1_curator.strip_props(project_id, [
            StripPropsOp(label="L1Service", identity={"business_function_slug": slug},
                         prop_keys=[prop_key], provenance=provenance),
        ])
    except Exception:
        logger.warning("curation.rehome: failed for %s/%s", slug, prop_key, exc_info=True)
        return False
    return True


def rehome_service_props(project_id: str, cards: list, provenance: Provenance, *, seen: set | None = None) -> int:
    """DETERMINISTIC (no-LLM) FR-TYPESEP-b / FR-MODELFIX backstop: scan Service
    index-cards for mechanism classifications wrongly set as Service props
    (`rendering_model`, `navigation_model`, `api_paradigm`, `auth_methods`,
    `perimeter`) and re-home each to the correct System via a typed edge, stripping
    the stale Service prop. Returns the count re-homed. Independently testable; also
    invoked as a curation stage."""
    seen = seen if seen is not None else set()
    rehomed = 0
    for card in cards or []:
        if card.get("kind") != "Service":
            continue
        slug = (card.get("key") or {}).get("business_function_slug")
        if not slug:
            continue
        spine = card.get("spine") or {}
        for prop_key in _REHOME_RULES:
            if prop_key in spine and _rehome_one(project_id, slug, prop_key, spine.get(prop_key), provenance, seen):
                rehomed += 1
    return rehomed


def _rehome_stage(project_id: str, batch: CurationBatch, provenance: Provenance, read_fn) -> int:
    """The re-homing stage: re-read the CURRENT cards (so it sees any props the
    anatomy stage just wrote) and run the deterministic backstop, then apply any
    explicit `rehome` proposals the LLM flagged."""
    seen: set = set()
    try:
        cards = index_card.index_cards(project_id, read_fn=read_fn)
    except Exception:
        logger.warning("curation.rehome: card re-read failed", exc_info=True)
        cards = []
    rehomed = rehome_service_props(project_id, cards, provenance, seen=seen)
    for r in (batch.rehome or []):
        if _rehome_one(project_id, r.service_slug, r.prop_key, r.prop_value, provenance, seen):
            rehomed += 1
    return rehomed


# --- the driver-invoked orchestrator ------------------------------------------

def run_curation(project_id: str, run_id: str, *, read_fn=None, propose_fn=None) -> CurationReport:
    """Run the post-recon curation pass over the accumulated L1 graph. Each stage
    is FAIL-OPEN: a stage that raises records the error and later stages still
    run. `read_fn` (threaded to the reads/sweeps) and `propose_fn` (the curation
    LLM pass) are injectable so the pass is unit-testable without a live LLM/DB.
    Returns a `CurationReport` summarising every stage."""
    provenance = Provenance(job=f"curation:{run_id}", model=None, prompt_id=None)
    report = CurationReport()

    # Stage 1: read the L1 context.
    context = _read_context(project_id, read_fn, report)

    # Stage 2: propose the reconciliation batch.
    batch = CurationBatch()
    try:
        batch = (propose_fn or default_propose_fn)(context) or CurationBatch()
    except Exception as exc:
        logger.warning("curation.propose failed; fail-open to empty batch", exc_info=True)
        _note_error(report, f"propose: {exc}")

    # Stage 3: execute the destructive reconciliation via the sole-writer.
    try:
        merges, deletes, relabels = curation_proposals_to_ops(batch, provenance)
        if merges or deletes or relabels:
            counts = l1_curator.reconcile(project_id, merges=merges, deletes=deletes, relabels=relabels)
            report.merged = counts.get("merged", 0)
            report.deleted = counts.get("deleted", 0)
            report.relabelled = counts.get("relabelled", 0)
            # A destructive op changes the IDENTITY SET, so the stage-1 snapshot is
            # now stale. Every later stage consumes `context["cards"]`, and stage 5
            # commits anatomy per card via `commit_anatomy`, which MERGEs the
            # Service by slug - so a merged-away duplicate in the stale list is
            # re-created, silently undoing the dedup and leaving curation to report
            # `merged=1` on every future run while the graph never converges.
            # Re-read so the post-reconcile stages operate on what actually exists.
            if report.merged or report.deleted or report.relabelled:
                context = _read_context(project_id, read_fn, report)
    except Exception as exc:
        logger.warning("curation.reconcile stage failed; fail-open", exc_info=True)
        _note_error(report, f"reconcile: {exc}")

    # Stage 4: write light journey memberships (append-not-clobber).
    try:
        report.journeys_written = _write_journeys(project_id, batch, context.get("cards") or [], provenance)
    except Exception as exc:
        logger.warning("curation.journey stage failed; fail-open", exc_info=True)
        _note_error(report, f"journeys: {exc}")

    # Stage 5: run the webpage-anatomy skill for services that warrant it.
    try:
        report.anatomy = _anatomy_stage(project_id, context.get("cards") or [], provenance)
    except Exception as exc:
        logger.warning("curation.anatomy stage failed; fail-open", exc_info=True)
        _note_error(report, f"anatomy: {exc}")

    # Stage 6: re-home System facts stranded as Service props (FR-TYPESEP-b).
    try:
        report.rehomed = _rehome_stage(project_id, batch, provenance, read_fn)
    except Exception as exc:
        logger.warning("curation.rehome stage failed; fail-open", exc_info=True)
        _note_error(report, f"rehome: {exc}")

    # Stage 7: the end-of-phase sweeps.
    try:
        report.stale_count = sweep.stale_pool_count(project_id, read_fn=read_fn)
    except Exception as exc:
        logger.warning("curation.stale sweep failed; fail-open", exc_info=True)
        _note_error(report, f"stale_sweep: {exc}")
    try:
        report.missing_kinds = sweep.missing_system_kinds(project_id, read_fn=read_fn)
    except Exception as exc:
        logger.warning("curation.missing-kinds sweep failed; fail-open", exc_info=True)
        _note_error(report, f"missing_sweep: {exc}")

    return report
