"""The analyser's entry point plus shared prompt-render and write helpers.

RETIRED (#48 section 11 step 6, ratified 2026-07-30): this module used to compile
a LangGraph subgraph implementing the legacy analyser as a pure function
`f(L0-slice + observations) -> L1-deltas` (a `read -> analyse -> curate` flow),
running a legacy two-pass prompt behind the `analysis.supervisor_enabled`
coexistence flag. That flag flipped ON by default in the same change (step 5) and
the flag branch, the legacy pass, its prompts, and its skill loader are now fully
dissolved: `run_analyser` is a thin wrapper that always drives the chunk-fed
supervised path (`supervisor.run_analyser_chunked`), the two-role
`assigner -> mechanism_typist` schedule.

What survives here, with its live consumers: `AnalyserExport` (broadly),
`default_read_fn` (`l0_stream`), `_inventory_block` (`bootstrap`),
`l1_graph_block` (`assigner`),
`_slice_repr` (`assigner`),
`default_curate_fn` and `default_curate_with_enrichment_fn`
(`supervisor`), and `run_analyser` itself. The module is coherent without a pod:
the analyser's entry point plus shared prompt-render and write helpers.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class AnalyserExport(BaseModel):
    """The analyser pod's result: how many L1 deltas were written, plus an error
    string when a node degraded (fail-open). `enrichment` carries the per-category
    FR-ENRICH counts when the analyser proposed enrichment deltas."""

    services_written: int = 0
    systems_written: int = 0
    aggregates_written: int = 0
    enrichment: dict | None = None
    error: str | None = None


# --- default collaborators (real wiring) --------------------------------------

def default_read_fn(project_id: str) -> dict:
    """Read the project's L0 asset slice (the attack-surface graph). Reuses
    graph_read.fetch_project_graph (traversal-then-fetch is the analyser's job,
    not this coarse read; the MVP reads the project slice and lets the LLM focus
    it).

    FR-PODSTREAM: `Observation` nodes are EXCLUDED here - they reach the analyser
    on their own dedicated channel (`l0_stream.read_observations`, or
    `delivery.collect_observations` for a dict-shaped pull), so delivering them
    in the slice too would double-deliver each one. Their anchor edges (whose
    other endpoint is dropped) fall away with them."""
    from polymerhus.recon.domain.graph_read import fetch_project_graph
    slice_ = fetch_project_graph(project_id)
    nodes = [n for n in slice_.get("nodes", []) if n.get("type") != "Observation"]
    keep = {n.get("id") for n in nodes}
    links = [l for l in slice_.get("links", []) if l.get("source") in keep and l.get("target") in keep]
    return {"nodes": nodes, "links": links}


def _slice_repr(l0_slice: dict) -> str:
    """Textual rendering of the L0 slice for a prompt.

    UNTRUNCATED since #48 section 11 step 6 (ratified 2026-07-30): the legacy
    400-node cap this helper used to apply is a no-op on the surviving path,
    because every consumer of this helper now renders a single CHUNK, targeted at
    `chunking.CHUNK_MAX_ASSETS = 300` - the per-chunk packing cap. The cap
    is SOFT (2026-10-15): an atomic topology family can exceed it, so the
    truncation branch is unreachable unless one family alone passes 400 nodes."""
    nodes = (l0_slice or {}).get("nodes", [])
    return f"L0 slice ({len(nodes)} nodes): {nodes}"


# FR-INVENTORY: the "reuse these exact keys" duplicate-prevention rule. Rendered
# from the CURRENT L1 identity inventory (read once per run) and injected at the
# TOP of every analyser prompt - never truncated, so it is never dropped the way
# the old "reuse the slug already in the slice" hint was (that hint leaned on L1
# nodes buried in a capped slice the legacy data pass dropped).
def _inventory_block(inventory: dict | None) -> str:
    """Render the CURRENT L1 identities as an explicit, machine-legible reuse
    block (a bullet list of the exact keys) for the TOP of an analyser prompt.
    Never truncated. An empty category renders `(none yet)` so the block shape is
    deterministic on the very first pass.

    A Service that carries a `service_contract` (#29) renders as `slug - contract`.
    The contract is the Bootstrapper's functional profile of the business function,
    and it is what makes this block usable for ASSIGNMENT rather than only for
    identity reuse: a bare slug list tells a proposer which names exist, but nothing
    about what each one owns, so a slug like `byoc` or `agent-tool` is unroutable.
    Fed from the parallel `service_contracts` map, so a contract-less inventory
    renders exactly as before."""
    inv = inventory or {}
    contracts = inv.get("service_contracts") or {}

    def _render(heading: str, keys, *, annotations: dict | None = None) -> str:
        keys = list(keys or [])
        if not keys:
            return f"  {heading}: (none yet)"
        lines = []
        for k in keys:
            note = (annotations or {}).get(k)
            lines.append(f"    - {k} - {note}" if note else f"    - {k}")
        return f"  {heading}:\n" + "\n".join(lines)

    return (
        "EXISTING L1 IDENTITIES - reuse these EXACT keys, do NOT coin a synonym.\n"
        "These identities are already in the graph from earlier passes. Sign-in / "
        "signin / login are ONE identity: pick the key already listed here rather "
        "than minting a near-duplicate. Add a NEW Service / System ONLY "
        "for surface no existing key below covers.\n"
        "Where a Service shows a description after its slug, that is its service "
        "contract: what that business function does and owns.\n"
        f"{_render('Services (business_function_slug)', inv.get('services'), annotations=contracts)}\n"
        f"{_render('Systems (kind[:discriminator])', inv.get('systems'))}"
    )


def _render_l1_graph_sections(inv: dict) -> tuple:
    """Render the three sections of the L1 graph block as (services, systems, edges)
    lines. `(none yet)` for an empty section; stable-sorted; untruncated (the L1
    graph is small). Shared by `l1_graph_block`."""
    contracts = inv.get("service_contracts") or {}
    descriptions = inv.get("system_descriptions") or {}
    details = inv.get("system_details") or {}
    edges = inv.get("edges") or []

    service_keys = sorted(set(inv.get("services") or ()) | set(contracts))
    if not service_keys:
        services = "  Services (business_function_slug - contract): (none yet)"
    else:
        lines = []
        for k in service_keys:
            contract = (contracts.get(k) or "").strip()
            lines.append(f"    - {k} - {contract}" if contract else f"    - {k}")
        services = "  Services (business_function_slug - contract):\n" + "\n".join(lines)

    system_keys = sorted(set(inv.get("systems") or ()) | set(descriptions) | set(details))
    if not system_keys:
        systems = ("  Systems (kind[:discriminator] :: description {attributes}): "
                   "(none yet)")
    else:
        lines = []
        for k in system_keys:
            desc = (descriptions.get(k) or "").strip()
            line = f"    - {k}"
            if desc:
                line += f" :: {desc}"
            attrs = details.get(k) or {}
            if attrs:
                rendered = ", ".join(f"{a}={attrs[a]}" for a in sorted(attrs))
                line += f" {{{rendered}}}"
            lines.append(line)
        systems = ("  Systems (kind[:discriminator] :: description {attributes}):\n"
                   + "\n".join(lines))

    if not edges:
        edges_block = "  Edges (Service -[REL]-> System): (none yet)"
    else:
        lines = []
        for e in sorted(edges, key=_edge_sort_key):
            tail = _edge_tail(e)
            lines.append(
                f"    - {e.get('service_slug')} -[{e.get('rel')}]-> "
                f"{e.get('system_key')}{tail}"
            )
        edges_block = "  Edges (Service -[REL]-> System):\n" + "\n".join(lines)

    return services, systems, edges_block


def _edge_sort_key(edge: dict):
    """Stable sort for edges: (service_slug, rel, system_key, role, realm, order),
    None-tolerant so a missing sub-field never raises on comparison."""
    order = edge.get("order")
    return (
        edge.get("service_slug") or "", edge.get("rel") or "",
        edge.get("system_key") or "", edge.get("role") or "", edge.get("realm") or "",
        "" if order is None else str(order),
    )


def _edge_tail(edge: dict) -> str:
    """` (role=..., realm=..., order=...)` for the sub-granularity that is SET, or
    "" when none is. A `0` order is SET (positional metadata), so the check is
    `is not None`, never truthiness."""
    parts = [
        f"{key}={edge.get(key)}"
        for key in ("role", "realm", "order") if edge.get(key) is not None
    ]
    return f" ({', '.join(parts)})" if parts else ""


def l1_graph_block(inventory: dict | None) -> str:
    """The current L1 GRAPH as an explicit prompt block for the Assigner's volatile
    human message (operator ruling 2026-10-16): each Service with its
    `service_contract`, each System as `kind[:disc] :: description {attributes}`, and
    the typed `Service -[REL]-> System` edges with role/realm/order.

    It folds in the FR-INVENTORY identity-reuse discipline ("reuse these EXACT keys,
    do NOT coin a synonym"), so it REPLACES `_inventory_block` in the Assigner prompt
    rather than sitting beside it (two identity lists would duplicate). `_inventory_block`
    is kept for its other consumers (bootstrap). Built fresh from the per-dispatch
    `read_l1_inventory` read, so it tracks the graph as the run concretises more linked
    systems. Untruncated (L1 is small); stable sort; `(none yet)` for an empty section.

    A previous graph_view-capable Assigner degraded quality and bloated context
    (retained decision), so the graph is POSTED here, never exposed as a tool."""
    inv = inventory or {}
    services, systems, edges = _render_l1_graph_sections(inv)
    return (
        "EXISTING L1 GRAPH - reuse these EXACT keys, do NOT coin a synonym.\n"
        "These identities and the links between them are already in the graph from "
        "earlier passes. Sign-in / signin / login are ONE identity: pick the key "
        "already listed here rather than minting a near-duplicate. Add a NEW Service "
        "/ System ONLY for surface no existing key below covers.\n"
        f"{services}\n"
        f"{systems}\n"
        f"{edges}"
    )
# `_invoke_with_retry` was RETIRED (#73): structured analyser calls now go through
# `roles.invoke_role`, whose single escalating-budget retry
# (`invoke_with_escalating_timeout`) replaces this helper AND the client's own retry
# (they multiplied, #32). A None return is still the fail-closed unmet-generation
# signal the callers treat as a valid empty outcome.


def default_curate_fn(services, systems, aggregates, project_id: str) -> AnalyserExport:
    """Real collaborator: write the deltas through the L1 sole-writer (idempotent
    MERGE). Services/Systems first, then AGGREGATES edges (their MATCHed L0
    targets must already exist from recon)."""
    from polymerhus.analysis import l1_curator

    services_written, systems_written = l1_curator.l1_curate(services, systems, project_id)
    aggregates_written = l1_curator.write_aggregates(aggregates, project_id)
    return AnalyserExport(
        services_written=services_written,
        systems_written=systems_written,
        aggregates_written=aggregates_written,
    )


def default_curate_with_enrichment_fn(batch, project_id: str, provenance) -> AnalyserExport:
    """Full curate: the core deltas (services/systems/aggregates) plus the
    FR-ENRICH deltas (Service->System edges), all mapped from one analyser `batch`
    with system provenance and written through the L1 sole-writer. Used when the
    analyser proposes enrichment alongside assignment."""
    from polymerhus.analysis import l1_curator
    from polymerhus.analysis.analyser_types import (
        enrichment_proposals_to_deltas, proposals_to_deltas,
    )

    services, systems, aggregates = proposals_to_deltas(batch, provenance)
    export = default_curate_fn(services, systems, aggregates, project_id)

    enrich_deltas = enrichment_proposals_to_deltas(batch, provenance)
    if any(enrich_deltas.values()):
        counts = l1_curator.enrich(project_id, **enrich_deltas)
        export = export.model_copy(update={"enrichment": counts})
    return export


def run_analyser(
    project_id: str,
    run_id: str,
    observations: list | None = None,
    *,
    deliver_fn=None,
    run_supervisor_fn=None,
    **collaborators,
) -> AnalyserExport:
    """Convenience: run the analyser for a project and return its export.
    Synchronous (the default wiring has no live collaborator on the caller's own
    event loop); a caller already on the event loop should offload via
    asyncio.to_thread, like run_job.

    THIN WRAPPER (#48 section 11 step 6, ratified 2026-07-30): the legacy
    read->analyse->curate pod and its `analysis.supervisor_enabled` coexistence
    flag are retired. `run_analyser` always drives the chunk-fed supervised path
    (`supervisor.run_analyser_chunked`, the assigner -> mechanism_typist
    schedule). `run_supervisor_fn` is injectable for testing and
    defaults to `run_analyser_chunked`; any extra keyword (`invoke_fn`,
    `assets_fn`, `write_fn`, `checkpointer`, ...) is passed straight through, so a
    test can wire the same collaborator surface `analyse_chunked` exposes.

    FR-PODSTREAM: the delivery-completeness guarantee is independent of which
    graph executes it. When `observations is None` (the default) and the caller
    has not supplied its own `observations_fn` override, the run's triager
    Observations are auto-delivered (fail-open) via `deliver_fn` and threaded
    into the supervised pass as an `observations_fn` override, so a caller that
    already holds a fixed set (a test, or a future streaming caller) does not pay
    for a second live read. An explicit `observations` list (including `[]`) is
    honoured as-is and delivery is NOT invoked. `deliver_fn(project_id) ->
    list[Observation]` is injectable for testing and defaults to
    `l0_stream.read_observations` - the SAME anchored read `analyse_chunked`
    would otherwise perform itself, so the default production behaviour is
    unchanged, just made explicit at this seam."""
    from polymerhus.analysis.supervisor import run_analyser_chunked

    if observations is None and "observations_fn" not in collaborators:
        if deliver_fn is None:
            from polymerhus.analysis.l0_stream import read_observations as deliver_fn
        try:
            observations = deliver_fn(project_id)
        except Exception:  # fail-open: a delivery-read failure must not crash the run
            logger.warning(
                "run_analyser: observation delivery failed for project=%s; "
                "degrading to no observations", project_id, exc_info=True,
            )
            observations = []
    if observations is not None:
        collaborators.setdefault("observations_fn", lambda pid, _obs=observations: _obs)

    run_supervisor_fn = run_supervisor_fn or run_analyser_chunked
    return run_supervisor_fn(project_id, run_id, **collaborators)
