"""The cross-layer Assigner (agent spec #8), realising #20 increment 2b's first
proposer slice.

Sole owner of the `AGGREGATES` hinge: HIGH-PRECISION assignment of L0 elements to
their owning Service. The load-bearing NEW piece is the WITHHOLDING GATE - a
below-bar ownership judgment yields NO aggregates entry and the element stays in
the stale pool (absence IS the withholding; no "withheld" edge exists, AMV-14).
Today the assignment pass commits EVERY aggregate (`proposals_to_deltas` writes
`status="committed"` with no confidence filter anywhere); this gate is what stops
the measured over-assignment from becoming permanent edges.

Standalone + injected `invoke_fn` (unit-testable, no live LLM); NOT yet wired into
the supervisor - the schedule wiring + `_two_pass_analyse` dissolution is a later
2b slice. Maker/checker division (#8 DP-5, for #12): the Assigner SELF-withholds on
its own confidence; it does NOT hard-reject empty-evidence proposals (that rung is
the Auditor's, increment 3).
"""
from __future__ import annotations

import logging
import os

from polymerhus.analysis.analyser_types import L1DeltaBatch
from polymerhus.analysis.chunking import Chunk

logger = logging.getLogger(__name__)

# The withholding bar (#8 DP-1): PROVISIONAL 0.75, env-tunable, pending AMV-8 - the
# one genuinely tunable operator number. 0.80 starves coverage before A.2 exists;
# 0.70 is too permissive given the ~31-38% over-assignment prior.
ASSIGN_CONFIDENCE_BAR = float(os.environ.get("ANALYSER_ASSIGN_BAR", "0.75"))

# Exposure-only baseline (mirrors #7's bootstrap allowlist): a MINTED Service may
# carry ONLY a validated `exposure` prop - label / salience / anything else the LLM
# strays into is dropped at creation.
_ALLOWED_SERVICE_PROPS = frozenset({"exposure"})
_EXPOSURE_VALUES = frozenset({"public", "authenticated"})


def narrow_to_assignment(batch: L1DeltaBatch) -> L1DeltaBatch:
    """Leg 4 (#8): the Assigner owns ONLY `{services, aggregates}`. Drop `systems`
    / `system_edges` (-> TechnicalSystem) and every data list (-> DataPlane)."""
    return batch.model_copy(update={
        "systems": [], "system_edges": [],
        "data_items": [], "surfaces_at": [], "data_flows": [], "data_relationships": [],
    })


def withhold_below_bar(batch: L1DeltaBatch, bar: float = ASSIGN_CONFIDENCE_BAR) -> L1DeltaBatch:
    """THE WITHHOLDING GATE (#8 crux): drop every aggregate whose `confidence < bar`
    so it never reaches `write_aggregates`; the L0 element stays in the stale pool.
    A SHAPING rule - a below-bar element yields no aggregates entry (no "withheld"
    edge exists, AMV-14). Placed in the Assigner seam, NEVER in the shared
    `l1_curator` (the sole-writer stays policy-free). Services are untouched."""
    kept = [a for a in batch.aggregates if a.confidence >= bar]
    return batch.model_copy(update={"aggregates": kept})


def apply_exposure_baseline(batch: L1DeltaBatch, *, minted_slugs: frozenset[str]) -> L1DeltaBatch:
    """Exposure-only baseline (#8 leg 2, mirrors #7): a MINTED Service keeps only a
    validated `exposure` prop; a REUSED Service is emitted with EMPTY props so the
    idempotent MERGE never clobbers the Bootstrapper's exposure (no synonym drift,
    AMV-12)."""
    out = []
    for s in batch.services:
        if s.business_function_slug in minted_slugs:
            exposure = (s.props or {}).get("exposure")
            props = {"exposure": exposure} if exposure in _EXPOSURE_VALUES else {}
        else:
            props = {}  # reused -> empty props (never clobber existing exposure)
        out.append(s.model_copy(update={"props": props}))
    return batch.model_copy(update={"services": out})


def shape_proposal(
    raw: L1DeltaBatch, *, existing_slugs: frozenset[str], bar: float = ASSIGN_CONFIDENCE_BAR
) -> L1DeltaBatch:
    """Apply the Assigner's ordered shaping to a raw LLM proposal: narrow to
    assignment-only, self-withhold below the bar, then enforce the exposure
    baseline. `minted` = proposed slugs not already in the live inventory."""
    minted = frozenset(s.business_function_slug for s in raw.services) - existing_slugs
    batch = narrow_to_assignment(raw)
    batch = withhold_below_bar(batch, bar)
    batch = apply_exposure_baseline(batch, minted_slugs=minted)
    return batch


def _chunk_slice(chunk: Chunk) -> dict:
    """Adapt a `service`-concern chunk's immutable L0 delta to the prompt slice
    shape (`{nodes, links}`) the assignment verbatim reads."""
    nodes = [
        {"type": a.type, "identity": a.identity, "properties": dict(a.props or {})}
        for a in chunk.assets
    ]
    return {"nodes": nodes, "links": []}


def _assignment_prompt(l0_slice: dict, inventory: dict | None) -> str:
    """The assignment-only verbatim (a focused rewrite of the legacy pass-1 prompt,
    #8): reuse existing identities, judge ownership with confidence + evidence, and
    set `exposure` (public/authenticated) ONLY on a newly-minted Service - never
    label or salience."""
    from polymerhus.analysis.pod import _inventory_block, _slice_repr

    return (
        f"{_inventory_block(inventory)}\n\n{_slice_repr(l0_slice)}\n\n"
        "TASK - SURFACE ASSIGNMENT (assignment ONLY). Propose `services` and "
        "`aggregates` (which Service owns each L0 element), each aggregate carrying "
        "your `confidence` (0..1) and `evidence_refs`. REUSE the exact "
        "business_function_slug of any Service already listed above rather than "
        "coining a synonym; add a NEW Service only for surface no existing one "
        "covers, and on a NEW Service set ONLY `exposure` (public or authenticated) "
        "- never label or salience. Leave systems, system_edges, and all "
        "data-modelling lists EMPTY (dedicated proposers produce those)."
    )


def assign(
    chunk: Chunk,
    *,
    invoke_fn,
    inventory: dict | None = None,
    existing_slugs: frozenset[str] = frozenset(),
    bar: float = ASSIGN_CONFIDENCE_BAR,
) -> L1DeltaBatch:
    """The Assigner proposer body (#8): from a `service`-concern `Chunk` + the LIVE
    inventory, judge ownership, then SELF-WITHHOLD below the bar and enforce the
    exposure baseline, returning a narrowed `L1DeltaBatch{services, aggregates}`.

    `invoke_fn(messages) -> L1DeltaBatch | None` is injected (unit-testable, no live
    LLM). Fail-open: a `None`/raising `invoke_fn` (or an empty chunk) degrades to an
    empty batch. Pure given its inputs (a replayed slice yields the same batch)."""
    from langchain_core.messages import HumanMessage, SystemMessage

    if not chunk.assets:  # empty delta -> nothing to assign (valid empty)
        return L1DeltaBatch()
    try:
        raw = invoke_fn([
            SystemMessage(content=_load_skill()),
            HumanMessage(content=_assignment_prompt(_chunk_slice(chunk), inventory)),
        ])
    except Exception:  # LLM error -> fail-open to no assignment, never crash
        logger.warning("assigner: invoke failed; degrading to empty batch", exc_info=True)
        return L1DeltaBatch()
    if raw is None:  # no parseable tool call after retries -> empty batch
        return L1DeltaBatch()
    return shape_proposal(raw, existing_slugs=existing_slugs, bar=bar)


def _load_skill() -> str:
    """The analyser skill preamble (reused from the legacy pod loader)."""
    from polymerhus.analysis.pod import _load_analyser_skill

    return _load_analyser_skill()
