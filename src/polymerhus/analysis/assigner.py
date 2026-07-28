"""The cross-layer Assigner (agent spec #8), realising #20 increment 2b's first
proposer slice, reshaped to classification-only by #34.

Sole owner of the `AGGREGATES` hinge and of exactly ONE judgment: given an Endpoint
recon streamed into a chunk, which EXISTING Service owns it, with what confidence,
on what evidence. Three shaping rules realise that:

  - NARROW (#34 D4): the emitted batch carries `aggregates` and nothing else.
    Minting is NOT the Assigner's responsibility - the Bootstrapper read the whole
    architecture to write the Service population, while the Assigner sees one chunk
    of surface, so a chunk-local mint competes with a far better-informed source and
    is the measured origin of cross-run identity drift (AMV-12).
  - VALIDATE (#34 D9): a proposed `service_slug` outside the live inventory is
    dropped BEFORE the confidence gate, so a high confidence cannot rescue a
    hallucinated owner, and the reach is retained as a backlog description naming
    the Service that may be missing.
  - WITHHOLD (#8 crux): a below-bar ownership judgment yields NO aggregates entry and
    the element stays in the stale pool (absence IS the withholding; no "withheld"
    edge exists, AMV-14). This is what stops the measured over-assignment from
    becoming permanent edges.

Several Services may legitimately own the same Endpoint (#34 D3): there is no
single-owner invariant, so each genuine owner is emitted with its own independent
confidence and the bar filters each edge separately.

Standalone + injected `invoke_fn` (unit-testable, no live LLM). Maker/checker
division (#8 DP-5, for #12): the Assigner SELF-withholds on its own confidence; it
does NOT hard-reject empty-evidence proposals (that rung is the Auditor's,
increment 3).
"""
from __future__ import annotations

import logging
import os

from pydantic import BaseModel, ConfigDict, Field

from polymerhus.analysis.analyser_types import L1DeltaBatch
from polymerhus.analysis.chunking import Chunk, admit_for_role

logger = logging.getLogger(__name__)

ROLE = "assigner"

# The withholding bar (#8 DP-1): 0.75 is an EMPIRICAL PLACEHOLDER, not a reasoned
# number (#34). It is an OUTPUT of the assertion suite - a run sweeps it and the
# measured assignment quality picks the value - and stays env-tunable for that
# purpose. Prior evidence only bounds it: 0.80 starves coverage before A.2 exists,
# 0.70 is too permissive given the ~31-38% over-assignment prior.
ASSIGN_CONFIDENCE_BAR = float(os.environ.get("ANALYSER_ASSIGN_BAR", "0.75"))


class AssignmentOutcome(BaseModel):
    """What one Assigner pass produced: the shaped `batch` the curator may write,
    and the `backlog` of surface it could not place.

    The backlog is carried but NOT transported (#34 D6): no envelope field exists to
    carry it upward yet, so it is returned for inspection and deliberately goes no
    further. Each entry is ONE short sentence with the candidate slug embedded inline
    rather than held in a separate field."""

    model_config = ConfigDict(frozen=True)

    batch: L1DeltaBatch = Field(default_factory=L1DeltaBatch)
    backlog: tuple[str, ...] = ()


def narrow_to_assignment(batch: L1DeltaBatch) -> L1DeltaBatch:
    """Leg 4 (#8, tightened by #34 D4): the Assigner owns ONLY `aggregates`. Drop
    `services` (-> Bootstrapper), `systems` / `system_edges` (-> TechnicalSystem)
    and every data list (-> DataPlane)."""
    return batch.model_copy(update={
        "services": [], "systems": [], "system_edges": [],
        "data_items": [], "surfaces_at": [], "data_flows": [], "data_relationships": [],
    })


def drop_out_of_inventory(
    batch: L1DeltaBatch, *, existing_slugs: frozenset[str]
) -> tuple[L1DeltaBatch, tuple[str, ...]]:
    """THE VALIDATION GATE (#34 D9): drop every aggregate whose `service_slug` is not
    a live L1 identity, and return one backlog description per dropped slug.

    Runs BEFORE the confidence gate on purpose - an owner that does not exist is not
    a weak judgment to be scored, it is a reference to nothing, and scoring it would
    let a confident hallucination through. The reach is kept as evidence: the model
    saw surface it could not place, which is the signal a Service may be missing."""
    kept, missing = [], []
    for agg in batch.aggregates:
        if agg.service_slug in existing_slugs:
            kept.append(agg)
        elif agg.service_slug not in missing:
            missing.append(agg.service_slug)
    if missing and not existing_slugs:
        # Every proposal dropped because the caller passed no inventory at all. The
        # fail-safe direction is right (nothing is written), but silent, so a caller
        # that forgot to read the inventory would look like a model that found
        # nothing. Say so.
        logger.warning(
            "assigner: validation set is EMPTY - all %d proposed owner(s) dropped; "
            "the caller supplied no live L1 inventory", len(missing),
        )
    backlog = tuple(
        f"{slug}: surface was proposed for this business function but no such Service "
        f"exists in the L1 inventory; it may be missing."
        for slug in missing
    )
    return batch.model_copy(update={"aggregates": kept}), backlog


def withhold_below_bar(batch: L1DeltaBatch, bar: float = ASSIGN_CONFIDENCE_BAR) -> L1DeltaBatch:
    """THE WITHHOLDING GATE (#8 crux): drop every aggregate whose `confidence < bar`
    so it never reaches `write_aggregates`; the L0 element stays in the stale pool.
    A SHAPING rule - a below-bar element yields no aggregates entry (no "withheld"
    edge exists, AMV-14). Placed in the Assigner seam, NEVER in the shared
    `l1_curator` (the sole-writer stays policy-free)."""
    kept = [a for a in batch.aggregates if a.confidence >= bar]
    return batch.model_copy(update={"aggregates": kept})


def shape_proposal(
    raw: L1DeltaBatch, *, existing_slugs: frozenset[str], bar: float = ASSIGN_CONFIDENCE_BAR
) -> AssignmentOutcome:
    """Apply the Assigner's ordered shaping to a raw LLM proposal: narrow to
    assignment-only, drop owners that do not exist (collecting the backlog), then
    self-withhold below the bar."""
    batch = narrow_to_assignment(raw)
    batch, backlog = drop_out_of_inventory(batch, existing_slugs=existing_slugs)
    batch = withhold_below_bar(batch, bar)
    return AssignmentOutcome(batch=batch, backlog=backlog)


def _chunk_slice(chunk: Chunk) -> dict:
    """Adapt a chunk's immutable L0 delta to the prompt slice shape
    (`{nodes, links}`) the assignment verbatim reads, narrowed to the types this
    role admits (#34 D2/D7) - for the Assigner, Endpoints alone."""
    nodes = [
        {"type": a.type, "identity": a.identity, "properties": dict(a.props or {})}
        for a in admit_for_role(chunk, ROLE)
    ]
    return {"nodes": nodes, "links": []}


# The four-step reflect verbatim (#34), merging the load-bearing primitives of the
# `overthink` and `critical-thinking-logical-reasoning` disciplines down to what this
# role needs. Fires ONLY on `mode="reflect"`, so the create-pass system prefix stays
# byte-stable and provider prompt-caching holds across the run.
_REFLECT_VERBATIM = (
    "\n\nREFLECT PASS. Before emitting any revised proposal, write these four steps out:\n"
    "1. RESTATE AS EVIDENCE: for each aggregate, quote the exact path segment or "
    "parameter name you matched and the clause of the Service's contract it matched "
    "against. An aggregate whose evidence restates the slug instead of the surface is "
    "self-refuting - drop it.\n"
    "2. COMPETING OWNER: name the strongest competing Service and say why it lost. If "
    "it genuinely also owns the element, emit it too rather than discarding it. If you "
    "cannot name any competitor, that means the inventory is thin, not that you are "
    "confident.\n"
    "3. CALIBRATE: state each confidence, whether it clears the bar, and what specific "
    "evidence would move it.\n"
    "4. RESIDUE: list the Endpoints you could not place, one short sentence each."
)


def _system_prompt(mode: str = "create") -> str:
    """The STABLE half of the prompt (#34): the role verbatim, the worked examples,
    and under `reflect` the reflection protocol. Everything here is invariant across
    a run so the provider prompt-cache prefix survives it; the volatile inventory and
    chunk ride the user message instead.

    It deliberately does NOT load the shared legacy analyser skill. That skill is
    L0-oriented and addresses a generalist proposer: it instructs System modelling,
    data relationships and Service props, all of which #34 D4/D18 forbid this role
    from emitting. Carrying it here would put "emit aggregates only" and a
    WebPresentation worked example in one system message and let the model choose.
    Retiring it per-role is ticket #30; this is that retirement for the Assigner."""
    base = f"{_ROLE_VERBATIM}\n\n{_FEW_SHOTS}"
    return base + _REFLECT_VERBATIM if mode == "reflect" else base


_ROLE_VERBATIM = (
    "You are the cross-layer Assigner in an attack-surface analyser.\n"
    "ROLE - SURFACE ASSIGNMENT. You judge ONE thing: which EXISTING Service owns each "
    "Endpoint you are shown. You propose `aggregates` and nothing else.\n"
    # The contract is the PRIMARY routing evidence (#29). Before it existed the
    # inventory offered only slugs, so matching fell back to guessing what an opaque
    # slug (`byoc`, `agent-tool`) might mean - the assignment noise the withholding
    # bar then had to absorb.
    "HOW TO JUDGE OWNERSHIP: read each candidate Service's contract - what that "
    "business function DOES and OWNS - and match it against the concrete nouns and "
    "actions in the Endpoint itself: the path segments, the parameter names, the "
    "method. A path noun that names something a contract says the Service owns is "
    "strong evidence; a merely plausible topical association is not. Cite the specific "
    "path or parameter you matched in `evidence_refs`.\n"
    "SHARED OWNERSHIP IS REAL: more than one Service may genuinely own the same "
    "Endpoint. When two contracts both fit, emit an aggregate for EACH, every one "
    "carrying its own honest confidence. Do not pick a winner and do not discount a "
    "confidence merely because ownership is shared.\n"
    "CONFIDENCE: give each aggregate the confidence you actually hold. A judgment you "
    "would not defend belongs low, and a low one simply produces no edge - that is the "
    "correct outcome, not a failure.\n"
    "USE ONLY THE SLUGS LISTED IN THE INVENTORY. You cannot create a Service: a slug "
    "that is not listed names nothing and its aggregate will be discarded. If surface "
    "fits no listed Service, leave it unassigned rather than inventing an owner.\n"
    "Emit `aggregates` only. Leave services, systems, system_edges and every "
    "data-modelling list EMPTY - other proposers own those."
)

# Three worked examples (#34). The WITHHOLDING one is load-bearing: the measured
# 31-38% over-assignment says the model does not withhold unprompted, so the
# behaviour has to be demonstrated rather than only instructed.
#
# The example slugs are deliberately UNLIKE anything a real inventory holds. A worked
# example sharing a slug with a live identity invites the model to echo the example's
# answer as though it were a judgment about the surface in front of it.
_FEW_SHOTS = (
    "WORKED EXAMPLES. These slugs are illustrative and will never appear in a real "
    "inventory; use them for the SHAPE of the judgment, never as an answer.\n"
    "1. CLEAR ASSIGNMENT. Inventory has `invoice-settlement - Takes a draft invoice to "
    "a settled payment; owns invoices and payment intents.` Endpoint "
    "`POST /invoices/42/settle`. -> one aggregate, service_slug `invoice-settlement`, "
    "confidence 0.93, evidence_refs [\"path segment /invoices\", "
    "\"path segment /settle\"]. The path nouns name records the contract says the "
    "Service owns.\n"
    "2. DELIBERATE WITHHOLDING. Inventory has `invoice-settlement` and "
    "`brochure-pages - Presents marketing pages and categories.` Endpoint "
    "`GET /internal/health`. -> one aggregate at MOST, confidence 0.2, or none at all. "
    "Nothing in either contract mentions health or internal probes; topical proximity "
    "to a web app is not evidence. The low confidence is the right answer, and the "
    "element correctly ends up with no owner.\n"
    "3. SHARED OWNERSHIP. Inventory has `invoice-settlement - owns invoices` and "
    "`parcel-dispatch - owns shipments and dispatch of settled invoices.` Endpoint "
    "`GET /invoices/42/shipment`. -> TWO aggregates: `invoice-settlement` at 0.85 "
    "(evidence \"path segment /invoices\") and `parcel-dispatch` at 0.80 (evidence "
    "\"path segment /shipment\"). Both contracts genuinely reach this Endpoint; emit "
    "both rather than choosing."
)


def _user_prompt(l0_slice: dict, inventory: dict | None) -> str:
    """The VOLATILE half of the prompt (#34): the un-truncated L1 identities block
    FIRST (the FR-INVENTORY discipline - identity reuse enforced at write time),
    then the rendered chunk.

    The inventory sits here rather than in the system prefix ON PURPOSE: it mutates
    as the run proceeds, so hoisting it into the cacheable prefix would invalidate
    that prefix at every step and buy nothing."""
    from polymerhus.analysis.pod import _inventory_block, _slice_repr

    return (
        f"{_inventory_block(inventory)}\n\n{_slice_repr(l0_slice)}\n\n"
        "TASK: assign each Endpoint above to the Service(s) that own it, each "
        "aggregate carrying your `confidence` (0..1) and `evidence_refs`."
    )


def assign(
    chunk: Chunk,
    *,
    invoke_fn,
    inventory: dict | None = None,
    existing_slugs: frozenset[str] = frozenset(),
    bar: float = ASSIGN_CONFIDENCE_BAR,
    mode: str = "create",
) -> AssignmentOutcome:
    """The Assigner proposer body (#8): from a `Chunk` + the LIVE inventory, judge
    which existing Service owns each admitted Endpoint, then drop unknown owners and
    SELF-WITHHOLD below the bar, returning the narrowed batch plus its backlog.

    `invoke_fn(messages) -> L1DeltaBatch | None` is injected (unit-testable, no live
    LLM). Fail-open: a `None`/raising `invoke_fn` (or a chunk with no Endpoint in it)
    degrades to an empty outcome. Pure given its inputs (a replayed chunk yields the
    same outcome)."""
    from langchain_core.messages import HumanMessage, SystemMessage

    l0_slice = _chunk_slice(chunk)
    if not l0_slice["nodes"]:  # nothing this role can act on -> valid empty
        return AssignmentOutcome()
    try:
        raw = invoke_fn([
            SystemMessage(content=_system_prompt(mode)),
            HumanMessage(content=_user_prompt(l0_slice, inventory)),
        ])
    except Exception:  # LLM error -> fail-open to no assignment, never crash
        logger.warning("assigner: invoke failed; degrading to empty outcome", exc_info=True)
        return AssignmentOutcome()
    if raw is None:  # no parseable tool call after retries -> empty outcome
        return AssignmentOutcome()
    return shape_proposal(raw, existing_slugs=existing_slugs, bar=bar)


def default_invoke_fn():
    """The LIVE structured-output call for the Assigner: the `analyser` role model
    bound to `L1DeltaBatch` via function-calling, behind the pod's bounded retry.

    Reuses the legacy pod's two ingredients rather than introducing a second LLM
    plumbing path; returns `None` when no parseable tool call survives the retries,
    which `assign` already treats as a valid empty outcome."""
    from polymerhus.analysis.pod import _invoke_with_retry
    from polymerhus.app.llm.roles import chat_model_for

    structured = chat_model_for("analyser").with_structured_output(
        L1DeltaBatch, method="function_calling"
    )

    def invoke(messages):
        return _invoke_with_retry(structured.invoke, messages)

    return invoke


def make_assigner_body(*, invoke_fn, inventory_fn, bar: float = ASSIGN_CONFIDENCE_BAR):
    """Adapt `assign` to the supervisor's `ProposerBody` signature
    (`(dispatch, state) -> L1DeltaBatch | None`).

    `inventory_fn(project_id) -> inventory` is called at DISPATCH time, never earlier:
    the chunk is frozen and carries no L1 context, so the inventory must be re-derived
    live or chunk N+1 would not see what chunk N wrote. The identities block and the
    validation set both come from that one read, so they cannot disagree.

    The backlog is dropped here rather than transported (#34 D6): the envelope has no
    field to carry it yet."""

    def body(dispatch, state) -> L1DeltaBatch | None:
        if dispatch.chunk is None:
            return None
        inventory = inventory_fn(state.get("project_id", "")) or {}
        outcome = assign(
            dispatch.chunk,
            invoke_fn=invoke_fn,
            inventory=inventory,
            existing_slugs=frozenset(inventory.get("services") or ()),
            bar=bar,
            mode=getattr(dispatch, "mode", "create"),
        )
        if outcome.backlog:
            logger.info("assigner: %d backlog description(s) not transported (D6)", len(outcome.backlog))
        return outcome.batch

    return body
