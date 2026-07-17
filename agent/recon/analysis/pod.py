"""The analyser pod — a compiled LangGraph subgraph implementing the analyser as
a pure function `f(L0-slice + observations) -> L1-deltas`, written by idempotent
MERGE through `l1_curator` (L1D-22). Mirrors the STYLE of `build_pod_graph`
(agent/recon/pod.py): typed state, node functions, and three injected
side-effecting collaborators so the graph is unit/integration testable without a
live LLM.

The recon pod's `configurator/execute/gate/parser` tool-invocation machinery has
no analog here (the analyser runs no external tool — its "execute" is a read of
the L0 slice), so the graph is the focused `read -> analyse -> curate` flow the
pure-function contract implies. Phase-B reflection and backward-recon requests
(interface B) slot in later as additional edges without re-cutting this.

Fail-open throughout (mirrors orchestrator_agent / steel_client degrade): a read,
LLM, or curate error degrades that node to an empty result and never crashes the
caller — an LLM error yields an empty delta batch, so nothing is written but the
run still completes.
"""
from __future__ import annotations

import logging
from typing import TypedDict

from langgraph.graph import StateGraph, START, END
from pydantic import BaseModel

from agent.recon.analysis.analyser_types import L1DeltaBatch
from agent.recon.analysis.l1_types import Provenance

logger = logging.getLogger(__name__)

# Cap on L0 nodes serialized into the analyser prompt, mirroring pod._MAX_TRIAGE_ASSETS:
# a huge project graph would otherwise blow the model's context window.
import os
_MAX_L0_NODES = int(os.environ.get("MAX_ANALYSER_L0_NODES", "400"))


class AnalyserExport(BaseModel):
    """The analyser pod's result: how many L1 deltas were written, plus an error
    string when a node degraded (fail-open). `enrichment` carries the per-category
    FR-ENRICH counts when the analyser proposed enrichment deltas."""

    services_written: int = 0
    systems_written: int = 0
    aggregates_written: int = 0
    enrichment: dict | None = None
    error: str | None = None


class AnalyserState(TypedDict, total=False):
    project_id: str
    run_id: str
    observations: list[dict]
    l0_slice: dict
    model: str | None
    batch: L1DeltaBatch
    export: AnalyserExport


def _provenance(state: AnalyserState) -> Provenance:
    """System-supplied provenance for every L1 write of this run (the LLM never
    sets it). `job` names the analyser + its run; `model` is the resolved
    analyser model when known."""
    return Provenance(job=f"analyser:{state.get('run_id', '')}", model=state.get("model"), prompt_id=None)


def build_analyser_graph(*, read_fn, analyse_fn, curate_fn):
    """Compile the analyser subgraph, injecting the three collaborators:
      read_fn(project_id) -> l0_slice dict,
      analyse_fn(l0_slice, observations) -> L1DeltaBatch,
      curate_fn(batch, project_id, provenance) -> AnalyserExport.
    The curate collaborator receives the whole proposal `batch` + the system
    `provenance`, so it maps + writes the core deltas AND the enrichment deltas in
    one place (the LLM never sets provenance). Each node is fail-open: an
    exception degrades to an empty result carrying the error, never propagating
    out of the compiled graph.
    """

    def read(state: AnalyserState) -> dict:
        try:
            l0_slice = read_fn(state["project_id"])
        except Exception as exc:  # degrade: analyse an empty slice rather than crash
            logger.warning("analyser.read failed for project=%s", state.get("project_id"), exc_info=True)
            return {"l0_slice": {"nodes": [], "links": []}, "export": AnalyserExport(error=f"read: {exc}")}
        return {"l0_slice": l0_slice}

    def analyse(state: AnalyserState) -> dict:
        try:
            batch = analyse_fn(state.get("l0_slice") or {}, state.get("observations") or [])
        except Exception as exc:  # the key fail-open: an LLM error -> empty batch -> no L1 write
            logger.warning("analyser.analyse (LLM) failed; degrading to empty deltas", exc_info=True)
            return {"batch": L1DeltaBatch(), "export": AnalyserExport(error=f"analyse: {exc}")}
        return {"batch": batch}

    def curate(state: AnalyserState) -> dict:
        batch = state.get("batch") or L1DeltaBatch()
        try:
            export = curate_fn(batch, state["project_id"], _provenance(state))
        except Exception as exc:  # degrade: a write failure never crashes the run
            logger.warning("analyser.curate failed for project=%s", state.get("project_id"), exc_info=True)
            return {"export": AnalyserExport(error=f"curate: {exc}")}
        # preserve an upstream (read/analyse) error note if one was set
        prior = state.get("export")
        if prior is not None and prior.error and not export.error:
            export = export.model_copy(update={"error": prior.error})
        return {"export": export}

    g = StateGraph(AnalyserState)
    g.add_node("read", read)
    g.add_node("analyse", analyse)
    g.add_node("curate", curate)
    g.add_edge(START, "read")
    g.add_edge("read", "analyse")
    g.add_edge("analyse", "curate")
    g.add_edge("curate", END)
    return g.compile()


# --- default collaborators (real wiring) --------------------------------------

def default_read_fn(project_id: str) -> dict:
    """Read the project's L0 asset slice (the attack-surface graph). Reuses
    graph_read.fetch_project_graph (traversal-then-fetch is the analyser's job,
    not this coarse read; the MVP reads the project slice and lets the LLM focus
    it).

    FR-PODSTREAM: `Observation` nodes are EXCLUDED here - they reach the analyser
    on the dedicated `observations` channel (delivery.collect_observations), so
    delivering them in the slice too would double-deliver each one. Their anchor
    edges (whose other endpoint is dropped) fall away with them."""
    from agent.recon.graph_read import fetch_project_graph
    slice_ = fetch_project_graph(project_id)
    nodes = [n for n in slice_.get("nodes", []) if n.get("type") != "Observation"]
    keep = {n.get("id") for n in nodes}
    links = [l for l in slice_.get("links", []) if l.get("source") in keep and l.get("target") in keep]
    return {"nodes": nodes, "links": links}


# Fallback analyser system prompt, used only if the skill file is unavailable
# (graceful degrade, mirroring _load_triager_skill's "" fallback).
_ANALYSER_SYSTEM_PROMPT = (
    "You are the attack-surface analyser. Given a Layer-0 slice (endpoints, "
    "parameters, headers, technologies, observations), propose Layer-1 service/"
    "system deltas: business-function Services, cross-cutting Systems, and "
    "AGGREGATES assignments (which Service owns which L0 element) with a "
    "confidence and verbatim evidence. Propose nothing you cannot evidence. "
    "Return empty lists if the slice supports no confident judgment."
)

# How to reference an L0 element in an `aggregates` / `surfaces_at` proposal. The
# analyser LLM must set `l0.label` to the node's TYPE and `l0.identity` to its key
# fields (both read straight off the provided slice nodes), NOT put a value in the
# label. Injected into the analyser prompt because the LLM otherwise mislabels
# (observed live: it put a URL in `label`, and the safe-label guard dropped the
# whole assignment).
_L0_REFERENCE_GUIDE = (
    "REFERENCING L0 ELEMENTS (for `aggregates` and `surfaces_at`):\n"
    "Each slice node has a `type` (its L0 label) and `properties` (its fields). "
    "To reference it, set `l0.label` = that node's `type` (e.g. 'Endpoint'), and "
    "`l0.identity` = ONLY the node's identity key fields (omit project_id). The L0 "
    "identity keys per label are:\n"
    "- BaseURL: {url}\n"
    "- Endpoint: {path, method, baseurl}\n"
    "- Parameter: {name, position, endpoint_path, baseurl}\n"
    "- Header: {name, value, baseurl}\n"
    "- Technology: {name, version}\n"
    "- Certificate: {subject_cn}\n"
    "NEVER put a value (like a URL string) in `l0.label`; the label is the node "
    "TYPE. Only reference L0 elements that actually appear in the provided slice."
)

def _load_analyser_skill() -> str:
    """The analyser system prompt = the analyser-service-system-reasoning skill,
    which synthesises the `overthink` + `critical-thinking-logical-reasoning`
    disciplines for proposing L1 deltas. Loaded via the shared `skill_for`
    (FR-SKILLIF): single-sourced from skills/analysis/analyser/SKILL.md, YAML
    frontmatter stripped, cached, and degraded to the inline
    _ANALYSER_SYSTEM_PROMPT fallback if the mount is unavailable, so a missing
    mount never crashes the analyser."""
    from agent.recon.skills import skill_for
    return skill_for("analysis/analyser", fallback=_ANALYSER_SYSTEM_PROMPT)


def _slice_repr(l0_slice: dict) -> str:
    """Token-bounded textual rendering of the L0 slice for the analyser prompt
    (caps at _MAX_L0_NODES, mirroring pod._MAX_TRIAGE_ASSETS)."""
    nodes = (l0_slice or {}).get("nodes", [])
    shown = nodes[:_MAX_L0_NODES]
    omitted = len(nodes) - len(shown)
    return (
        f"L0 slice ({len(nodes)} nodes"
        + (f", showing first {len(shown)}, {omitted} omitted" if omitted else "")
        + f"): {shown}"
    )


def _assignment_prompt(l0_slice: dict, observations: list[dict]) -> str:
    """Pass-1 prompt: the service/system model + surface assignment + topology."""
    from agent.recon.analysis.l1_curator import vocabulary_prompt

    return (
        f"{vocabulary_prompt()}\n\n{_L0_REFERENCE_GUIDE}\n\n{_slice_repr(l0_slice)}\n"
        f"Observations: {observations}\n"
        "TASK 1 of 2 - SERVICE MODEL & SURFACE ASSIGNMENT. Propose ONLY: `services` "
        "(business-function Services - REUSE the exact business_function_slug of any "
        "Service already present in the slice rather than coining a synonym; add a "
        "new Service only for surface no existing one covers), `systems`, "
        "`aggregates` (which Service owns each L0 element), and `system_edges`. "
        "Leave the data-modelling lists (data_items, surfaces_at, data_flows, "
        "data_relationships) EMPTY - a dedicated second pass produces those."
    )


def _compact_l0_for_data(l0_slice: dict) -> tuple[list[dict], list[dict]]:
    """Identity-only view of the surface for the data-modelling pass: enough to
    place SURFACES_AT refs (Endpoint {path,method,baseurl}, Parameter
    {name,position,endpoint_path,baseurl}) WITHOUT the full node property dump that
    balloons the prompt to ~123k chars and makes the call slow/unreliable."""
    endpoints: list[dict] = []
    parameters: list[dict] = []
    for n in (l0_slice or {}).get("nodes", []):
        t = n.get("type")
        p = n.get("properties") or {}
        if t == "Endpoint":
            endpoints.append({"path": p.get("path"), "method": p.get("method"), "baseurl": p.get("baseurl")})
        elif t == "Parameter":
            parameters.append({"name": p.get("name"), "position": p.get("position"),
                               "endpoint_path": p.get("endpoint_path"), "baseurl": p.get("baseurl")})
    return endpoints, parameters


def _data_modelling_prompt(l0_slice: dict, assignment: L1DeltaBatch) -> str:
    """Pass-2 prompt: the logical DataItems + flows, grounded in pass-1's
    assignment (each Service + a token-light sample of the endpoints it now owns)
    plus an IDENTITY-ONLY surface digest (not the full node dump - that made the
    prompt ~123k chars and pass-2 timed out / returned no structured output)."""
    from agent.recon.analysis.l1_curator import vocabulary_prompt

    owned: dict[str, list[str]] = {}
    for a in assignment.aggregates:
        ident = a.l0.identity or {}
        ref = ident.get("path") or ident.get("url") or ident.get("name")
        if ref:
            bucket = owned.setdefault(a.service_slug, [])
            if len(bucket) < 8:
                bucket.append(str(ref))
    summary = "\n".join(f"  - {s}: {', '.join(p)}" for s, p in sorted(owned.items())) or "  (none assigned)"
    endpoints, parameters = _compact_l0_for_data(l0_slice)
    endpoints = endpoints[:_MAX_L0_NODES]
    # Positive, example-led recipe: state exactly what to fill and show ONE worked
    # DataItem. A negative framing ("leave the other lists EMPTY") made a weaker
    # analyser model anchor on the empties and return zero data_items (observed
    # live: args={'services':[],...} only). The merge keeps ONLY the four data
    # lists from this pass, so we never mention the others.
    return (
        "TASK: LOGICAL DATA MODELLING. List the principal business records (DataItems) "
        "this application keeps, and how they flow. Fill FOUR lists: `data_items`, "
        "`surfaces_at`, `data_flows`, `data_relationships`. You MUST return at least "
        "one data_item; an empty data_items list is a wrong answer for any real "
        "application.\n\n"
        "A DataItem is a business record BEHIND the surface (customer account, product "
        "listing, shopping basket, order, delivery address, payment method, coupon, "
        "gift card, review, complaint, loyalty points, subscription plan, security "
        "question), NOT an endpoint or a parameter.\n\n"
        "WORKED EXAMPLE (copy this shape):\n"
        '  data_items:   [{"item_key": "shopping_basket"}, {"item_key": "product_listing"}]\n'
        '  surfaces_at:  [{"item_key": "shopping_basket", "l0": {"label": "Endpoint",'
        ' "identity": {"path": "/api/BasketItems", "method": "GET", "baseurl": "<baseurl>"}}}]\n'
        '  data_flows:   [{"service_slug": "cart", "item_key": "shopping_basket", "direction": "produces"},\n'
        '                 {"service_slug": "cart", "item_key": "product_listing", "direction": "consumes",'
        ' "assumption": "basket trusts the price is validated server-side",'
        ' "assumption_rationale": "basket references product by id only"}]\n'
        '  data_relationships: [{"from_item_key": "shopping_basket", "to_item_key": "product_listing",'
        ' "kind": "derived_from", "rationale": "a basket line is derived from a product"}]\n\n'
        "Now do the same for THIS application. Use the services + their endpoints and "
        "the surface below to ground every item_key in real endpoints/parameters. In "
        "`data_flows`, set `service_slug` to a slug COPIED VERBATIM from the services "
        "list below (keep hyphens exactly; do not rename or invent a service).\n\n"
        f"Services and the endpoints they own:\n{summary}\n\n"
        f"Endpoints on the surface (identity only, {len(endpoints)}): {endpoints}\n"
        f"Parameters on the surface ({len(parameters)}): {parameters}\n\n"
        f"{_L0_REFERENCE_GUIDE}\n\n"
        f"Allowed data_relationship kinds:\n{vocabulary_prompt()}"
    )


def _invoke_with_retry(invoke_fn, messages, *, attempts: int = 3):
    """Call a structured-output LLM with a bounded retry. `with_structured_output`
    returns None (no parseable tool call) on a transient provider hiccup - observed
    live: a run where BOTH analyser passes returned None and zeroed the whole
    analysis, though the same call succeeds on retry. Retries on a None return OR an
    exception; returns the first non-None batch, or None if every attempt failed."""
    result = None
    for i in range(attempts):
        try:
            result = invoke_fn(messages)
        except Exception:  # transient provider/parse error: retry, don't crash
            logger.warning("analyser structured call raised (attempt %d/%d)", i + 1, attempts, exc_info=True)
            result = None
        if result is not None:
            return result
        logger.warning("analyser structured call returned no tool call (attempt %d/%d)", i + 1, attempts)
    return result


def _two_pass_analyse(invoke_fn, l0_slice: dict, observations: list[dict]) -> L1DeltaBatch:
    """Two-pass analyse: an assignment pass (services/systems/aggregates/
    system_edges) then a DEDICATED data-modelling pass (data_items/surfaces_at/
    data_flows/data_relationships), merged into one batch.

    The passes are split because ONE combined call reliably drops data modelling
    under assignment load - observed live (finish_reason 'tool_calls', NOT a token
    cutoff: 150 aggregates + 90 system_edges, 0 data_items). Isolating data
    modelling into its own call stops the high-volume assignment work from crowding
    it out. `invoke_fn(messages) -> L1DeltaBatch` is injected so this is
    unit-testable without a live LLM. Fail-open: if the data-modelling pass raises,
    the assignment pass survives (enrichment degrades, assignment is never lost)."""
    from langchain_core.messages import SystemMessage, HumanMessage

    skill = _load_analyser_skill()
    assignment = _invoke_with_retry(invoke_fn, [
        SystemMessage(content=skill),
        HumanMessage(content=_assignment_prompt(l0_slice, observations)),
    ])
    # structured_output returns None when the model emits no parseable tool call;
    # after retries, degrade to an empty batch rather than crash (fail-open).
    if assignment is None:
        assignment = L1DeltaBatch()
    data = _invoke_with_retry(invoke_fn, [
        SystemMessage(content=skill),
        HumanMessage(content=_data_modelling_prompt(l0_slice, assignment)),
    ])
    if data is None:  # data-modelling pass produced no tool call after retries -> assignment-only
        logger.warning("analyser data-modelling pass produced no structured output; assignment-only")
        return assignment
    # merge: assignment's core/topology + the data-modelling pass's data lists
    return assignment.model_copy(update={
        "data_items": data.data_items,
        "surfaces_at": data.surfaces_at,
        "data_flows": data.data_flows,
        "data_relationships": data.data_relationships,
    })


def default_analyse_fn(l0_slice: dict, observations: list[dict]) -> L1DeltaBatch:
    """Real collaborator: ask the analyser LLM to propose L1 deltas in TWO passes
    (assignment, then a dedicated data-modelling pass - see _two_pass_analyse).
    Mirrors default_triage_fn's structured-output pattern (function_calling
    tolerates the open-ended `dict` props/identity fields json_schema rejects)."""
    from agent.app.llm.roles import chat_model_for

    llm = chat_model_for("analyser")
    structured_llm = llm.with_structured_output(L1DeltaBatch, method="function_calling")
    return _two_pass_analyse(structured_llm.invoke, l0_slice, observations)


def default_curate_fn(services, systems, aggregates, project_id: str) -> AnalyserExport:
    """Real collaborator: write the deltas through the L1 sole-writer (idempotent
    MERGE). Services/Systems first, then AGGREGATES edges (their MATCHed L0
    targets must already exist from recon)."""
    from agent.recon.analysis import l1_curator

    services_written, systems_written = l1_curator.l1_curate(services, systems, project_id)
    aggregates_written = l1_curator.write_aggregates(aggregates, project_id)
    return AnalyserExport(
        services_written=services_written,
        systems_written=systems_written,
        aggregates_written=aggregates_written,
    )


def default_curate_with_enrichment_fn(batch, project_id: str, provenance) -> AnalyserExport:
    """Full curate: the core deltas (services/systems/aggregates) plus the
    FR-ENRICH deltas (DataItems, SURFACES_AT, PRODUCES/CONSUMES, DataRelationships,
    System edges), all mapped from one analyser `batch` with system provenance and
    written through the L1 sole-writer. Used when the analyser proposes enrichment
    alongside assignment. Seeds the DataRelationship catalogue (idempotent)."""
    from agent.recon.analysis import l1_curator
    from agent.recon.analysis.analyser_types import (
        enrichment_proposals_to_deltas, proposals_to_deltas,
    )

    services, systems, aggregates = proposals_to_deltas(batch, provenance)
    export = default_curate_fn(services, systems, aggregates, project_id)

    enrich_deltas = enrichment_proposals_to_deltas(batch, provenance)
    if any(enrich_deltas.values()):
        l1_curator.seed_data_relationship_kinds(project_id)
        counts = l1_curator.enrich(project_id, **enrich_deltas)
        export = export.model_copy(update={"enrichment": counts})
    return export


# The default compiled analyser pod (real collaborators). The curate collaborator
# is the full one: it writes the core deltas AND the FR-ENRICH deltas.
analyser_graph = build_analyser_graph(
    read_fn=default_read_fn, analyse_fn=default_analyse_fn,
    curate_fn=default_curate_with_enrichment_fn,
)


def run_analyser(
    project_id: str,
    run_id: str,
    observations: list[dict] | None = None,
    *,
    graph=None,
    deliver_fn=None,
) -> AnalyserExport:
    """Convenience: invoke the compiled analyser pod for a project and return its
    export. Synchronous (no async collaborators in the default wiring); a caller
    on the event loop should offload via asyncio.to_thread, like run_job.

    FR-PODSTREAM: when `observations is None` (the default), the run's triager
    Observations are auto-delivered from the graph (deduped, fail-open) so the
    batch pull is complete without the caller wiring them. An explicit
    `observations` list (including `[]`) is honoured as-is (e.g. a streaming
    caller pushing its own set). `deliver_fn(project_id) -> list[dict]` is
    injectable for testing."""
    if observations is None:
        if deliver_fn is None:
            from agent.recon.analysis.delivery import deliver_observations as deliver_fn
        observations = deliver_fn(project_id)
    graph = graph or analyser_graph
    result = graph.invoke(
        {"project_id": project_id, "run_id": run_id, "observations": observations}
    )
    return result["export"]
