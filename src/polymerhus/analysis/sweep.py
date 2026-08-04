"""FR-SWEEP: the end-of-phase sweeps (L1D-24).

Two DERIVED reads once the recon phase-barrier clears (spec §7.2 step 6); neither
is a stored table, both are computed from the sole-writer + MERGE guarantees:

  * stale_pool: assignable L0 assets with **no inbound AGGREGATES edge** - the
    assets the analyser did not confidently assign to any Service (the §15
    `/healthz` case). A derived query, not a structure (L1D-24).
  * resolve_stale_owners: the REDESIGNED missing-systems sweep (operator
    correction 2026-07-20). The old `missing_system_kinds` enumerated `:SystemKind`
    catalogue rows with no instance - which the model correction removed (the kind
    is a plain `kind` attribute, no catalogue nodes). It is replaced by a
    **stale-L0-asset-driven** pass: for each stale asset, an injected LLM proposes
    which System kind and/or Service it could belong to, grounded PRIMARILY in the
    existing L1 inventory (what has already been defined for this project) and
    SECONDARILY in the fixed known-system-kinds enumeration. This is a fail-open
    SEAM (read + prompt-construction + typed result); `propose_fn` is injectable so
    it is unit-testable without a live LLM (mirrors `curation.py`).

Read-only reads; the write counterpart is `l1_curator`. `read_fn` defaults to
`polymerhus.app.clients.neo4j_client.read`, resolved lazily so importing this module
never constructs a live driver.
"""
from __future__ import annotations

import logging
import re

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Interpolated into Cypher (Neo4j cannot parameterise a label), so validate as a
# strict identifier first - defence in depth, mirroring l1_curator._SAFE_IDENT.
# `\Z` (absolute end) not `$`, so a trailing newline cannot slip past the guard.
_SAFE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\Z")

# The L0 labels a Service can aggregate. `Endpoint` is the primary assignable
# asset (the §15 walkthrough assigns endpoints; a stray `/healthz` falls to the
# stale pool). Headers/Technologies/Certificates are System EVIDENCED_BY evidence,
# not Service members, so they are excluded from the stale pool by default. The
# caller may widen the set for a project whose surface aggregates other labels.
DEFAULT_ASSIGNABLE_LABELS: tuple[str, ...] = ("Endpoint",)

# Cap the stale slice rendered into the ownership prompt so a huge unassigned pool
# cannot blow the model's context window (mirrors curation._MAX_STALE_IN_PROMPT).
_MAX_STALE_IN_PROMPT = 200


def _resolve_read_fn(read_fn):
    if read_fn is None:
        from polymerhus.app.clients import neo4j_client
        read_fn = neo4j_client.read
    return read_fn


def known_system_kind_ids() -> list[str]:
    """The fixed known-system-kinds enumeration, drawn from the SAME constant the
    curator validates against (`l1_curator.SYSTEM_KINDS`) - single source of truth.
    Now that the `:SystemKind` catalogue nodes are gone (operator correction
    2026-07-20), this Python constant is the enumeration the sweep prompt uses (the
    operator called the kinds list "second order")."""
    from polymerhus.analysis.l1_curator import SYSTEM_KINDS
    return [kind_id for kind_id, _desc in SYSTEM_KINDS]


def stale_pool(
    project_id: str,
    *,
    labels: tuple[str, ...] = DEFAULT_ASSIGNABLE_LABELS,
    read_fn=None,
) -> list[dict]:
    """Return the assignable L0 nodes of `labels` with no inbound AGGREGATES edge
    (the derived stale set). Each row is the L0 node's property map plus a
    `_label` key naming its L0 label. Raises ValueError on an unsafe label."""
    read_fn = _resolve_read_fn(read_fn)
    out: list[dict] = []
    for label in labels:
        if not isinstance(label, str) or not _SAFE_IDENT.match(label):
            raise ValueError(f"stale_pool: unsafe L0 label {label!r}")
        rows = read_fn(
            f"MATCH (n:{label}) WHERE n.project_id = $project_id "
            "AND NOT ( (:L1Service)-[:AGGREGATES]->(n) ) "
            "RETURN n {.*} AS props",
            {"project_id": project_id},
        )
        for r in rows:
            props = dict(r.get("props") or {})
            props["_label"] = label
            out.append(props)
    return out


def stale_pool_count(
    project_id: str,
    *,
    labels: tuple[str, ...] = DEFAULT_ASSIGNABLE_LABELS,
    read_fn=None,
) -> int:
    """Count of the stale set (cheaper than materialising it for a summary)."""
    read_fn = _resolve_read_fn(read_fn)
    total = 0
    for label in labels:
        if not isinstance(label, str) or not _SAFE_IDENT.match(label):
            raise ValueError(f"stale_pool_count: unsafe L0 label {label!r}")
        rows = read_fn(
            f"MATCH (n:{label}) WHERE n.project_id = $project_id "
            "AND NOT ( (:L1Service)-[:AGGREGATES]->(n) ) "
            "RETURN count(n) AS c",
            {"project_id": project_id},
        )
        total += rows[0]["c"] if rows else 0
    return total


# --- the redesigned stale-asset-driven ownership sweep -------------------------

class StaleAssetOwnership(BaseModel):
    """One LLM proposal: which existing Service and/or known System kind a stale L0
    asset could belong to. Grounded PRIMARILY in the existing L1 inventory
    (`service_slug`, an EXISTING business_function_slug) and SECONDARILY in the
    known-kinds enumeration (`kind`, a known system kind). Both are optional - an
    honest "cannot place it" leaves both None. `asset_ref` echoes the stale asset
    the proposal is about (for the caller to correlate)."""

    asset_ref: dict = Field(default_factory=dict)
    service_slug: str | None = None
    kind: str | None = None
    rationale: str | None = None


class StaleOwnershipBatch(BaseModel):
    """The stale-ownership LLM's structured output: an owner proposal per stale
    asset it could place. Empty is a valid honest result (mirrors CurationBatch)."""

    proposals: list[StaleAssetOwnership] = Field(default_factory=list)


def stale_ownership_prompt(context: dict) -> str:
    """Pure: build the stale-asset ownership prompt. Grounds the reasoning PRIMARILY
    in the existing L1 inventory (rendered FIRST) and SECONDARILY in the known
    system-kinds enumeration (rendered after). Only existing Service slugs and
    known kinds are valid owners; an asset that fits neither is left unplaced."""
    inv = context.get("inventory") or {}
    stale = context.get("stale_pool") or []
    known = context.get("known_kinds") or []
    shown = stale[:_MAX_STALE_IN_PROMPT]
    return (
        "STALE-ASSET OWNERSHIP SWEEP. Each L0 asset below was assigned to no "
        "Service during recon (no inbound AGGREGATES). For each, judge which "
        "System and/or Service it most plausibly belongs to.\n\n"
        "GROUND YOUR JUDGMENT PRIMARILY in what is ALREADY DEFINED for this project "
        "(reuse an existing key; do not coin a new Service):\n"
        f"  Existing Services (business_function_slug): {inv.get('services')}\n"
        f"  Existing Systems (kind[:discriminator]): {inv.get('systems')}\n"
        f"  Existing DataItems (item_key): {inv.get('data_items')}\n\n"
        "SECONDARILY, if no existing unit fits, you MAY name one of the known "
        f"system kinds (second-order fallback): {known}\n\n"
        f"STALE / UNASSIGNED L0 ASSETS ({len(stale)} total, showing {len(shown)}): "
        f"{shown}\n\n"
        "Propose an owner (`service_slug` from the existing Services and/or a "
        "known `kind`) per asset you can place; leave an asset out entirely if it "
        "fits nothing. Invent no Service not listed above."
    )


def default_stale_propose_fn(context: dict) -> StaleOwnershipBatch:
    """Real collaborator (thin LLM wiring): ask the analyser-role LLM for the stale
    ownership batch, structured output via function_calling, wrapped in the
    analyser's bounded retry. Degrades to an empty batch when the model returns no
    parseable tool call (fail-open); `resolve_stale_owners` also guards the call."""
    from langchain_core.messages import HumanMessage, SystemMessage

    from polymerhus.app.llm.roles import invoke_role

    result = invoke_role("analyser", [
        SystemMessage(content=(
            "You place unassigned attack-surface assets onto the Services/Systems "
            "already defined for the project. Reuse existing identities first; only "
            "fall back to a known system kind when nothing existing fits. Propose "
            "nothing you cannot ground - an empty result is a valid honest answer."
        )),
        HumanMessage(content=stale_ownership_prompt(context)),
    ], schema=StaleOwnershipBatch)
    return result or StaleOwnershipBatch()


def resolve_stale_owners(
    project_id: str,
    *,
    labels: tuple[str, ...] = DEFAULT_ASSIGNABLE_LABELS,
    read_fn=None,
    propose_fn=None,
) -> StaleOwnershipBatch:
    """The redesigned missing-systems sweep: read the stale L0 pool + the existing
    L1 inventory, ground a prompt in them (inventory primary, known-kinds
    secondary), and ask the LLM (or an injected `propose_fn`) which System/Service
    each stale asset belongs to. Returns the typed `StaleOwnershipBatch`.

    Fail-open throughout: a read error yields an empty stale pool / inventory, and
    a propose error (or a `propose_fn` returning None) degrades to an empty batch -
    it NEVER raises into the caller (mirrors curation's degrade-to-empty).

    NOTE (seam only): this PROPOSES ownership; it deliberately does NOT write the
    assignments back as AGGREGATES edges. Materialising the accepted proposals via
    the l1_curator sole-writer is the remaining (unbuilt) leg - see the module
    docstring / the refactor report."""
    from polymerhus.analysis.l1_inventory import read_l1_inventory

    read_fn = _resolve_read_fn(read_fn)
    try:
        pool = stale_pool(project_id, labels=labels, read_fn=read_fn)
    except Exception:
        logger.warning("resolve_stale_owners: stale_pool read failed; fail-open", exc_info=True)
        pool = []
    try:
        inventory = read_l1_inventory(project_id, read_fn=read_fn)
    except Exception:
        logger.warning("resolve_stale_owners: inventory read failed; fail-open", exc_info=True)
        inventory = {"services": [], "systems": [], "data_items": []}

    context = {
        "stale_pool": pool,
        "inventory": inventory,
        "known_kinds": known_system_kind_ids(),
    }
    if not pool:  # nothing stale to place - skip the LLM entirely
        return StaleOwnershipBatch()

    try:
        batch = (propose_fn or default_stale_propose_fn)(context)
    except Exception:
        logger.warning("resolve_stale_owners: propose failed; fail-open to empty", exc_info=True)
        return StaleOwnershipBatch()
    return batch or StaleOwnershipBatch()
