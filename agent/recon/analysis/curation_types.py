"""LLM-facing proposal models for the post-recon curation pass (FR-CURATE) + their
mapping to the `l1_curator` reconciliation ops.

The curation LLM emits *proposals* - its judgment about which accumulated L1 nodes
are duplicates, noise, mis-typed, or carry a System fact stranded
as a Service prop - but it must NOT set provenance: that is system-controlled,
exactly as `analyser_types` omits provenance from its proposals and injects it at
the curate boundary. So the proposal models deliberately omit `provenance`, and
`curation_proposals_to_ops` injects it when it builds the typed reconciliation ops.

`CurationReport` is the pass's returned summary; every stage of `run_curation`
folds its result into it (fail-open, so a degraded stage leaves its field at its
default and records the error).
"""
from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field

from agent.recon.analysis.l1_types import (
    L1_SINGLETON,
    DeleteOp,
    MergeOp,
    Provenance,
    RelabelOp,
)

logger = logging.getLogger(__name__)


# --- LLM-facing proposals (no provenance; system-stamped at the map boundary) --

class MergeProposal(BaseModel):
    """Two units that are the SAME identity: fold `duplicate` into `canonical`.
    `kind` selects the identity shape: a `service` pair is keyed by
    `business_function_slug`; a `system` pair by `kind[:discriminator]`
    (a bare kind is the `__singleton__` System). Dedup is SEMANTIC equivalence:
    two services are the same when they denote the same business function even
    under a different slug or synonym (account == account-management); two systems
    when they are the same cross-cutting mechanism instance. The slug is a label,
    not the identity test."""

    kind: Literal["service", "system"] = "service"
    canonical: str
    duplicate: str


class DeleteProposal(BaseModel):
    """An off-role / noise node to prune. `key` is the unit's identity string
    (a `business_function_slug`, or `kind[:discriminator]`), `kind` its
    type. `reason` is optional NL for the audit trail."""

    kind: Literal["service", "system"] = "service"
    key: str
    reason: str | None = None


class RelabelProposal(BaseModel):
    """A mis-typed node: re-kind `key` (of `from_kind`) to `new_key` (of
    `to_kind`) - e.g. a Service that is really a System. `key`/`new_key` are
    identity strings in the same shape as a merge proposal."""

    from_kind: Literal["service", "system"]
    to_kind: Literal["service", "system"]
    key: str
    new_key: str


class RehomeProposal(BaseModel):
    """A Service prop that is really a System fact (FR-TYPESEP-b): the
    `service_slug` carries `prop_key`=`prop_value` (e.g. rendering_model=CSR) that
    belongs on a System reached by a typed edge, not on the Service. Curation
    creates the System edge and strips the prop. The deterministic scan over the
    index-cards finds most of these; this lets the LLM flag any the scan misses."""

    service_slug: str
    prop_key: str
    prop_value: str | None = None


class CurationBatch(BaseModel):
    """The curation LLM's structured output: the typed reconciliation it proposes
    over the accumulated L1 graph. Every field defaults empty so an honest
    'nothing to reconcile' judgment is a valid, well-typed result (mirrors
    `L1DeltaBatch`)."""

    merges: list[MergeProposal] = Field(default_factory=list)
    deletes: list[DeleteProposal] = Field(default_factory=list)
    relabels: list[RelabelProposal] = Field(default_factory=list)
    rehome: list[RehomeProposal] = Field(default_factory=list)


class CurationReport(BaseModel):
    """The pass summary `run_curation` returns. Counts what each stage did; a
    degraded (fail-open) stage leaves its field at the default and appends to
    `error` (so a partial run is legible, never silent)."""

    merged: int = 0
    deleted: int = 0
    relabelled: int = 0
    rehomed: int = 0
    stale_count: int = 0
    # The redesigned missing-systems sweep (operator correction 2026-07-20): the
    # stale-L0-asset ownership proposals the LLM produced (each an owner grounded in
    # the existing inventory + known-kinds enumeration). Replaces `missing_kinds`.
    stale_owners: list[dict] = Field(default_factory=list)
    anatomy: dict = Field(default_factory=dict)
    error: str | None = None


# --- proposal -> typed reconciliation-op mapping -------------------------------

def _kind_to_label(kind: str) -> str:
    """The L1 unit label for a proposal `kind` ('service' -> L1Service)."""
    return "L1System" if kind == "system" else "L1Service"


def _key_to_identity(kind: str, key: str) -> dict:
    """Parse a proposal identity string into the reconcile-op identity map. A
    service key is a `business_function_slug`; a system key is `kind` or
    `kind:discriminator` (a bare kind is the `__singleton__` System). The System
    identity attribute is `kind` (operator correction 2026-07-20)."""
    if kind == "system":
        if ":" in key:
            system_kind, _, disc = key.partition(":")
            disc = disc.strip() or L1_SINGLETON
        else:
            system_kind, disc = key, L1_SINGLETON
        # System identity attribute is `kind` (operator correction 2026-07-20).
        return {"kind": system_kind.strip(), "discriminator": disc}
    return {"business_function_slug": key.strip()}


def curation_proposals_to_ops(
    batch: CurationBatch, provenance: Provenance
) -> tuple[list[MergeOp], list[DeleteOp], list[RelabelOp]]:
    """Map the LLM's curation proposals to the `l1_curator.reconcile` ops,
    stamping the system-supplied provenance (the LLM never sets it). A proposal
    that cannot be mapped (empty/garbled key) is skipped+logged so one bad
    proposal never aborts the mapping - the sole-writer's per-op fail-open then
    rejects any op with an empty identity too."""
    merges: list[MergeOp] = []
    for m in batch.merges or []:
        try:
            merges.append(MergeOp(
                label=_kind_to_label(m.kind),
                canonical=_key_to_identity(m.kind, m.canonical),
                duplicate=_key_to_identity(m.kind, m.duplicate),
                provenance=provenance,
            ))
        except Exception:
            logger.warning("curation_proposals_to_ops: skipping bad merge proposal", exc_info=True)

    deletes: list[DeleteOp] = []
    for d in batch.deletes or []:
        try:
            deletes.append(DeleteOp(
                label=_kind_to_label(d.kind),
                identity=_key_to_identity(d.kind, d.key),
                provenance=provenance,
            ))
        except Exception:
            logger.warning("curation_proposals_to_ops: skipping bad delete proposal", exc_info=True)

    relabels: list[RelabelOp] = []
    for r in batch.relabels or []:
        try:
            relabels.append(RelabelOp(
                from_label=_kind_to_label(r.from_kind),
                to_label=_kind_to_label(r.to_kind),
                identity=_key_to_identity(r.from_kind, r.key),
                new_identity=_key_to_identity(r.to_kind, r.new_key),
                provenance=provenance,
            ))
        except Exception:
            logger.warning("curation_proposals_to_ops: skipping bad relabel proposal", exc_info=True)

    return merges, deletes, relabels
