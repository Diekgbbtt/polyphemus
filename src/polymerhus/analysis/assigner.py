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
from polymerhus.analysis.l1_types import L0Ref
from polymerhus.analysis.prompt_variant import prompt_path, resolve_prompt_variant
from polymerhus.analysis.reasoning_workflow import ReasoningWorkflow, SubProblem

logger = logging.getLogger(__name__)

ROLE = "assigner"

# The withholding bar (#8 DP-1): 0.75 is an EMPIRICAL PLACEHOLDER, not a reasoned
# number (#34). It is an OUTPUT of the assertion suite - a run sweeps it and the
# measured assignment quality picks the value - and stays env-tunable for that
# purpose. Prior evidence only bounds it: 0.80 starves coverage before A.2 exists,
# 0.70 is too permissive given the ~31-38% over-assignment prior.
ASSIGN_CONFIDENCE_BAR = float(os.environ.get("ANALYSER_ASSIGN_BAR", "0.75"))


class AssignmentStats(BaseModel):
    """Per-chunk gate census - what the Assigner was handed and where each judgment
    died. The reason this exists: a run proposed 114 sound assignments and wrote
    zero, and NOTHING in the system said so. Every gate here is fail-open by design,
    so without a count per gate an empty result is indistinguishable between "the
    model found nothing" and "every judgment was discarded on the way out"."""

    model_config = ConfigDict(frozen=True)

    admitted: int = 0        # Endpoints this role was given
    proposed: int = 0        # aggregates the model returned
    unresolvable: int = 0    # dropped: named no Endpoint in the chunk
    out_of_inventory: int = 0  # dropped: named no live Service
    rescaled: int = 0        # repaired: confidence was a percentage, not a 0..1 value
    withheld: int = 0        # dropped: below the confidence bar
    kept: int = 0            # aggregates handed to the curator


class AssignmentOutcome(BaseModel):
    """What one Assigner pass produced: the shaped `batch` the curator may write,
    the `backlog` of surface it could not place, and the gate census.

    The backlog is carried but NOT transported (#34 D6): no envelope field exists to
    carry it upward yet, so it is returned for inspection and deliberately goes no
    further. Each entry is ONE short sentence with the candidate slug embedded inline
    rather than held in a separate field."""

    model_config = ConfigDict(frozen=True)

    batch: L1DeltaBatch = Field(default_factory=L1DeltaBatch)
    backlog: tuple[str, ...] = ()
    stats: AssignmentStats = Field(default_factory=AssignmentStats)
    # The absent-surface degradation: the bounded harvest found nothing relevant
    # to the contract, so the chain halted before `candidate_owners`. This is a
    # finding (the Service's surface is not mapped), never a failure to search
    # hard enough - it is what stops the escalation to the HTTP firehose.
    no_surface: bool = False


class AssignmentCensus(BaseModel):
    """What the GLOBAL assign pass observed over the whole SETTLED surface (T4,
    ADR D10/D11).

    `AssignmentStats` counts the gates for one chunk; the census counts the same
    five gates across the one global pass and adds the residual `stale` pool - the
    admitted Endpoints that ended with no kept owner. It is returned AND persisted
    to `analysis_runs.stats`, so coverage and withholding stay answerable after the
    run (the signal `AssignmentStats` had no home for)."""

    model_config = ConfigDict(frozen=True)

    admitted: int = 0          # Endpoints on the settled L0 surface
    proposed: int = 0          # aggregates the model returned
    unresolvable: int = 0      # dropped: named no Endpoint on the surface
    out_of_inventory: int = 0  # dropped: named no live Service
    rescaled: int = 0          # repaired: confidence was a percentage
    withheld: int = 0          # dropped: below the confidence bar
    kept: int = 0              # aggregates handed to the writer
    written: int = 0           # aggregates the writer actually wrote
    stale: int = 0             # admitted Endpoints left with no owner


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


def _endpoint_index(endpoints) -> tuple[dict, dict]:
    """Index the chunk's admitted Endpoints by (method, path) and by path alone."""
    by_pair, by_path = {}, {}
    for asset in endpoints:
        ident = asset.identity or {}
        path = ident.get("path")
        if not isinstance(path, str):
            continue
        canonical = {k: ident[k] for k in ("path", "method", "baseurl") if k in ident}
        method = str(ident.get("method") or "").upper()
        by_pair[(method, path)] = canonical
        by_path.setdefault(path, canonical)
    return by_pair, by_path


def _candidate_path(l0) -> tuple[str | None, str]:
    """Recover (path, method) from whatever the model put in an `l0` reference.

    Models reliably name the Endpoint but not the SHAPE: `label` comes back as
    `'GET /rest/user/whoami'` about as often as `'Endpoint'`. The path is the part
    they always get right, so it is what we key on."""
    identity = l0.identity if isinstance(l0.identity, dict) else {}
    method = str(identity.get("method") or "").upper()
    path = identity.get("path")
    if isinstance(path, str) and path.startswith("/"):
        return path, method
    # fall back to the label, which may be "GET /path" or a bare "/path"
    label = l0.label if isinstance(l0.label, str) else ""
    parts = label.split()
    if len(parts) == 2 and parts[1].startswith("/"):
        return parts[1], parts[0].upper()
    if len(parts) == 1 and parts[0].startswith("/"):
        return parts[0], method
    # last resort: any identity value that looks like a path
    for value in identity.values():
        if isinstance(value, str) and value.startswith("/"):
            return value, method
    return None, method


def resolve_l0_refs(batch: L1DeltaBatch, *, endpoints) -> L1DeltaBatch:
    """THE REFERENCE GATE: rewrite every aggregate's `l0` into the canonical
    `Endpoint{path, method, baseurl}` form, and DROP any that names no Endpoint in
    this chunk.

    The sole-writer MATCHes an L0 node by exact label + identity and refuses an
    unsafe label, so a reference the model formatted its own way is silently
    skipped and the whole judgment is lost - a live run proposed 114 sound
    assignments and wrote zero, because `l0.label` came back as `'GET /api/Users'`.
    Correctness must not depend on the model's formatting: the Assigner already
    knows the label is `Endpoint` and holds the exact identities it streamed, so it
    repairs the reference here rather than instructing and hoping.

    Dropping an unmatchable reference is the same discipline as the out-of-inventory
    gate: a reference to surface that was never in the chunk is a reference to
    nothing, not a weak judgment."""
    by_pair, by_path = _endpoint_index(endpoints)
    kept = []
    for agg in batch.aggregates:
        path, method = _candidate_path(agg.l0)
        if path is None:
            continue
        canonical = by_pair.get((method, path)) or by_path.get(path)
        if canonical is None:  # names no Endpoint this chunk carried
            continue
        kept.append(agg.model_copy(update={"l0": L0Ref(label="Endpoint", identity=canonical)}))
    return batch.model_copy(update={"aggregates": kept})


def normalise_confidence(batch: L1DeltaBatch) -> tuple[L1DeltaBatch, int]:
    """THE SCALE GATE: rewrite any confidence expressed as a PERCENTAGE into 0..1,
    and clamp what remains into range. Returns the batch and the count rescaled.

    Found live, in the graph, by the eval harness: 213 of 675 `AGGREGATES` edges
    carried confidences between 30.0 and 95.0. `AggregatesProposal.confidence` is a
    bare `float` with no bound, so a model that answers `85` instead of `0.85` is
    accepted verbatim - and then `withhold_below_bar` keeps it, because 85.0 >= 0.75.

    That is the whole withholding gate silently bypassed: the ONE mechanism defending
    against the measured 31-38% over-assignment stops rejecting anything at all, and
    nothing anywhere says so. It is the same defect class as the `l0.label` failure
    that wrote zero of 114 sound assignments - correctness must not depend on the
    model's formatting - so it gets the same treatment: repaired in the shaping seam
    rather than instructed in the prompt and hoped for.

    1.0 is left alone: it is a legitimate maximum, not an ambiguous percentage."""
    rescaled = 0
    fixed = []
    for agg in batch.aggregates:
        c = agg.confidence
        if c > 1.0:
            c = c / 100.0 if c <= 100.0 else 1.0
            rescaled += 1
        elif c < 0.0:
            c = 0.0
            rescaled += 1
        fixed.append(agg if c == agg.confidence else agg.model_copy(update={"confidence": c}))
    return batch.model_copy(update={"aggregates": fixed}), rescaled


def withhold_below_bar(batch: L1DeltaBatch, bar: float = ASSIGN_CONFIDENCE_BAR) -> L1DeltaBatch:
    """THE WITHHOLDING GATE (#8 crux): drop every aggregate whose `confidence < bar`
    so it never reaches `write_aggregates`; the L0 element stays in the stale pool.
    A SHAPING rule - a below-bar element yields no aggregates entry (no "withheld"
    edge exists, AMV-14). Placed in the Assigner seam, NEVER in the shared
    `l1_curator` (the sole-writer stays policy-free)."""
    kept = [a for a in batch.aggregates if a.confidence >= bar]
    return batch.model_copy(update={"aggregates": kept})


def shape_proposal(
    raw: L1DeltaBatch, *, existing_slugs: frozenset[str], endpoints=(),
    bar: float = ASSIGN_CONFIDENCE_BAR,
) -> AssignmentOutcome:
    """Apply the Assigner's ordered shaping to a raw LLM proposal: narrow to
    assignment-only, canonicalise the L0 references against the surface actually
    streamed, drop owners that do not exist (collecting the backlog), put every
    confidence onto the 0..1 scale, then self-withhold below the bar.

    ORDER IS LOAD-BEARING. Normalisation must precede withholding: a percentage-scale
    confidence clears any bar in 0..1, so withholding a batch that has not been
    normalised is a no-op wearing the appearance of a gate."""
    batch = narrow_to_assignment(raw)
    proposed = len(batch.aggregates)
    batch = resolve_l0_refs(batch, endpoints=endpoints)
    resolved = len(batch.aggregates)
    batch, backlog = drop_out_of_inventory(batch, existing_slugs=existing_slugs)
    in_inventory = len(batch.aggregates)
    batch, rescaled = normalise_confidence(batch)
    batch = withhold_below_bar(batch, bar)
    stats = AssignmentStats(
        admitted=len(tuple(endpoints)), proposed=proposed,
        unresolvable=proposed - resolved,
        out_of_inventory=resolved - in_inventory,
        rescaled=rescaled,
        withheld=in_inventory - len(batch.aggregates),
        kept=len(batch.aggregates),
    )
    return AssignmentOutcome(batch=batch, backlog=backlog, stats=stats)


def _chunk_slice(chunk: Chunk) -> dict:
    """Build the admitted-Endpoint view (`{nodes, links}`) this role narrows the
    chunk to (#34 D2/D7) - for the Assigner, Endpoints alone.

    Solely the "nothing to act on" gate: when it is empty the pass is a valid
    empty with no LLM call. The prompt no longer renders a surface slice, so this
    view exists only for that gate and for `shape_proposal`'s deterministic checks."""
    nodes = [
        {"type": a.type, "identity": a.identity, "properties": dict(a.props or {})}
        for a in admit_for_role(chunk, ROLE)
    ]
    return {"nodes": nodes, "links": []}


def _owned_endpoints_repr(endpoints) -> str:
    """Render the Service's OWN already-aggregated endpoints, one
    `METHOD /path (baseurl)` per entry; `(none)` when it aggregates nothing yet."""
    lines = []
    for asset in endpoints or ():
        ident = getattr(asset, "identity", None) or {}
        path = ident.get("path")
        if not isinstance(path, str):
            continue
        method = str(ident.get("method") or "").upper()
        baseurl = ident.get("baseurl")
        line = " ".join(part for part in (method, path) if part)
        if baseurl:
            line = f"{line} ({baseurl})"
        lines.append(line)
    return "; ".join(lines) if lines else "(none)"


def _unit_context_block(chunk: Chunk, inventory: dict | None, owned_endpoints=()) -> str:
    """The ONLY per-unit context the assigner is fed (L1-unit-first): the Service's
    slug, its `service_contract` (the primary routing evidence) and the endpoints it
    ALREADY aggregates, if any.

    The whole settled surface is deliberately ABSENT: the model discovers its own
    surface by querying the tools, driven by the contract (`harvest_surface`). A thin
    KB gets a thin honest contract, and an orphan Service gets an empty owned list;
    both render explicitly rather than as a silently empty prompt."""
    slug = str(getattr(chunk, "source_job", "") or "").removeprefix("service:") or chunk.chunk_id
    contracts = (inventory or {}).get("service_contracts") or {}
    contract = contracts.get(slug, "") if isinstance(contracts, dict) else ""
    overview = (inventory or {}).get("application_overview") or ""
    framing = f"APPLICATION OVERVIEW: {overview}\n\n" if overview else ""
    return (
        f"{framing}"
        f"SERVICE UNIT: {slug}\n"
        f"contract: {contract or '(none)'}\n"
        f"already aggregated endpoints: {_owned_endpoints_repr(owned_endpoints)}"
    )


# The four reflect stages (#34), merging the load-bearing primitives of the
# `overthink` and `critical-thinking-logical-reasoning` disciplines down to what this
# role needs. `candidate_owners` and `assign` each cover a subset of them (spec 3.3).
#
# REVIVED IN PRODUCTION (ADR D25): the 2026-07-28 ratification recorded reflection as
# deliberately unreached. The reasoning workflow now runs the first three stages
# (`candidate_owners`) on every pass and the RESIDUE stage inside `assign`, so the
# reflection is no longer dead weight. The stages stay TESTED on both prompt arms.
#
# RECONCILED (T7): reflection was always carried TWICE - once by the workflow's
# sub-problem prompts (below) and once by a `mode="reflect"` append to the STABLE
# system prompt. Because the workflow now runs the stages on EVERY pass, the
# `mode` append was pure duplication; it is retired and the workflow is the single
# carrier. See `docs/design/assigner-A1-decisions.md` section 5.
_REFLECT_STEPS = (
    "RESTATE AS EVIDENCE: for each aggregate, quote the exact path segment or "
    "parameter name you matched and the clause of the Service's contract it matched "
    "against. An aggregate whose evidence restates the slug instead of the surface is "
    "self-refuting - drop it.",
    "COMPETING OWNER: name the strongest competing Service and say why it lost. If "
    "it genuinely also owns the element, emit it too rather than discarding it. If you "
    "cannot name any competitor, that means the inventory is thin, not that you are "
    "confident.",
    "CALIBRATE: state each confidence, whether it clears the bar, and what specific "
    "evidence would move it.",
    "RESIDUE: list the Endpoints you could not place, one short sentence each.",
)

# The absent-surface degradation (W-b). The harvest is bounded (surgical
# `graph_view` probes, url-path-filtered `search_http_history`), and when it
# finds nothing the chain HALTS before `candidate_owners` rather than running
# the reasoning/assign turns on an empty premise. This is what stops the model
# escalating to the HTTP firehose when a Service's surface is simply not mapped.
def _survivor_count(turn) -> int:
    """The harvested Endpoints that survived falsification (verdict `survive`)."""
    if turn is None:
        return 0
    return sum(1 for c in (getattr(turn, "claims", None) or []) if c.verdict == "survive")


def _halt_without_surface(sub_problem, turn) -> bool:
    """The `halt_when` predicate: stop after `falsify_harvest` when nothing
    survived, so `candidate_owners`/`assign` never run on an absent surface."""
    if sub_problem.id != "falsify_harvest":
        return False
    return _survivor_count(turn) == 0



# unit's surface through the tools, `falsify_harvest` tries to throw the harvest out
# against the contract, `candidate_owners` is the reasoning differential over the
# SURVIVORS, `assign` is the extraction turn, and `closure` writes the note. Each
# turn speaks the ONE envelope `AnalysisTurn`, so the tool set never toggles.
WORKFLOW = ReasoningWorkflow(
    role_id=ROLE,
    sub_problems=(
        SubProblem(
            id="harvest_surface",
            name="harvest the surface",
            prompt=(
                "HARVEST THE SURFACE - the unit is your only anchor. You are given ONE "
                "Service (its slug and `contract`). Derive MULTIPLE candidate strings "
                "from that contract: the nouns it owns, the actions it performs, and "
                "path-word fragments of each. For EVERY candidate string query "
                "`graph_view` with bounded read-only Cypher (always a LIMIT): enumerate "
                "the `:BaseURL`s and their `:Endpoint`s broadly, and run a path-substring "
                "probe per candidate. Where a candidate suggests a path, call "
                "`search_http_history` and then `get_http_artifact` to read a specific "
                "recorded request shape. Query "
                "BROADLY and AGGRESSIVELY; a candidate that returns nothing is a valid "
                "miss, not a failure. Emit one Claim per harvested Endpoint: `subject` "
                "`METHOD /path`; `assertion` the raw surface facts (path segments, "
                "method, trailing segment, parameter names, baseurl) AND which candidate "
                "string found it; `evidence` the Cypher/filter you ran; `verdict` "
                "`harvested`. Do not decide ownership here. Emit `claims` only."
            ),
            inject=("service", "inventory"),
            emit=("claims",),
        ),
        SubProblem(
            id="falsify_harvest",
            name="falsify the harvest",
            prompt=(
                "FALSIFY THE HARVEST - reduce the wrong-aggregation risk before you "
                "decide anything. For EACH harvested Endpoint, try hard to falsify that "
                "it is relevant AND correct for THIS Service's contract: does a noun or "
                "action in the path actually match a clause this contract claims, or is "
                "the match only topical? Is the candidate string that found it one the "
                "contract really names, or a coincidence? Emit one Claim per harvested "
                "Endpoint: `subject` the Endpoint; `assertion` the reason; `evidence` the "
                "path segment or contract clause you tested it against; `verdict` "
                "`survive` or `reject`. An Endpoint whose only link is topical or "
                "technological is `reject`. Lean strict: a rejected real Endpoint costs a "
                "later pass, while an admitted wrong one hangs a false edge that looks "
                "answered. Emit `claims` only."
            ),
            inject=("service", "harvest_surface"),
            emit=("claims",),
            depends_on=("harvest_surface",),
        ),
        SubProblem(
            id="prior_insights",
            name="prior modelling insights",
            prompt=(
                "PRIOR MODELLING INSIGHTS - read before you enrich. Call the `notes` "
                "tool with command=\"read\" to surface what earlier units concluded "
                "about this Service and its neighbours. Read this Service's own notes "
                "(`unit` = the slug), notes whose body mentions the path nouns you "
                "harvested, and any note naming a Service that may be missing. For each "
                "relevant note emit one Claim: `subject` the note key; `assertion` the "
                "recorded insight; `evidence` the note body excerpt; `verdict` `reuse`, "
                "`avoid`, or `competing-owner`. A run with no prior notes is a valid "
                "result - say so. Emit `claims` only."
            ),
            inject=("service", "falsify_harvest"),
            emit=("claims",),
            depends_on=("falsify_harvest",),
        ),
        SubProblem(
            id="candidate_owners",
            name="candidate owners",
            prompt=(
                "REASONING - candidate owners, over the SURVIVORS only. Work through "
                "these stages out loud:\n"
                + "\n".join(f"{i}. {s}" for i, s in enumerate(_REFLECT_STEPS[:3], 1))
                + "\n\nFor each surviving Endpoint (`verdict` `survive`), emit one Claim "
                "per candidate owner: `subject` the Endpoint, `assertion` the matched "
                "evidence and the strongest competing owner, `evidence` the exact path "
                "segment or parameter you matched, `verdict` the owner you would choose "
                "and your confidence. Emit `claims` only; do not propose deltas yet."
            ),
            inject=("inventory", "service", "falsify_harvest", "prior_insights"),
            emit=("claims",),
            depends_on=("falsify_harvest", "prior_insights"),
        ),
        SubProblem(
            id="assign",
            name="assign",
            prompt=(
                "EXTRACTION - assign. " + _REFLECT_STEPS[3] + "\n\nFrom the claims "
                "above, over the survivors only, emit the `aggregates`: one per Endpoint "
                "and owning Service(s), each with `confidence` (0..1) and "
                "`evidence_refs`. Emit one aggregate for EACH genuine owner; a Service "
                "may name ANY live Service as the owner, not only this unit. Use only "
                "`service_slug`s from the inventory; an invented owner names nothing. "
                "Leave services, systems, system_edges and every data-modelling list "
                "EMPTY. Put the residue in `claims`: one Claim per unplaced Endpoint "
                "(`verdict` `residue`)."
            ),
            inject=("inventory", "service", "falsify_harvest", "candidate_owners"),
            emit=("aggregates", "claims"),
            depends_on=("candidate_owners",),
        ),
        SubProblem(
            id="closure",
            name="modelling closure",
            prompt=(
                "CLOSURE - write the modelling-closure note. Summarise what this unit "
                "closed over: the `Endpoint`s you claimed as `AGGREGATES` (slug, "
                "confidence, matched evidence) and EXPLICITLY the `Endpoint`s you did "
                "NOT claim and why each was left in the stale pool. Call the `notes` "
                "tool once: command=\"write\", action=\"append\", unit = the Service "
                "slug, note_name=\"modelling-closure\", kind=\"assignment\", body = the "
                "closure body. Then emit one Claim recording the closure: `subject` the "
                "Service; `assertion` the claimed and unclaimed counts; `evidence` the "
                "note key; `verdict` `closed`. Emit `claims` only."
            ),
            inject=("service", "harvest_surface", "assign"),
            emit=("claims",),
            depends_on=("assign",),
        ),
    ),
)



def _system_prompt() -> str:
    """The STABLE half of the prompt (#34): the role verbatim and the judgment
    discipline. Everything here is invariant across a run so the provider
    prompt-cache prefix survives it; the volatile inventory and the Service unit ride
    the user message instead. The reflection stages are NOT appended here: the
    workflow's sub-problem prompts are their single carrier (T7 reconciliation),
    so the stable prefix is byte-identical on every pass, reflect or create.

    It deliberately does NOT load the shared legacy analyser skill. That skill is
    L0-oriented and addresses a generalist proposer: it instructs System modelling,
    data relationships and Service props, all of which #34 D4/D18 forbid this role
    from emitting. Carrying it here would put "emit aggregates only" and a
    WebPresentation worked example in one system message and let the model choose.
    Retiring it per-role is ticket #30; the ROLE-SPECIFIC prompt that replaces it for
    the Assigner is the file `prompt_variant.prompt_path` selects
    (`ANALYSIS_PROMPT_VARIANT`), gated on `ASSIGNER_PROMPT_CONFIG=skill`."""
    base = (
        f"{_ROLE_VERBATIM}\n\n{_load_assigner_skill()}"
        if _assigner_prompt_config() == "skill"
        else f"{_ROLE_VERBATIM}\n\n{_FEW_SHOTS}"
    )
    return base


_ROLE_VERBATIM = (
    "You are the cross-layer Assigner in an attack-surface analyser.\n"
    "ROLE - SURFACE ASSIGNMENT. You judge ONE thing: which EXISTING Service owns each "
    "Endpoint you discover. You propose `aggregates` and nothing else.\n"
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
    # The scolding half of this rule ("it is the node TYPE, never a path and never a
    # method") was deleted once `resolve_l0_refs` began overwriting `l0.label`
    # unconditionally: an instruction the code no longer depends on is not a safety
    # net, it is tokens spent naming the elephant. What survives is the IDENTITY
    # shape, which is still load-bearing - it is what makes the repair's happy path
    # fire, because `_candidate_path` reads `identity["path"]` first.
    "REFERENCING AN ENDPOINT: put the endpoint in `l0.identity` as "
    "`{\"path\": \"/api/Users\", \"method\": \"GET\", "
    "\"baseurl\": \"<the baseurl the tool returned>\"}`, with `l0.label` set to `Endpoint`. "
    "Only reference endpoints you discovered through the tools; one you invent names nothing and "
    "is discarded.\n"
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


# The Assigner's system message is TWO layers, mirroring the Bootstrapper
# (`bootstrap.py::_BOOTSTRAPPER_BASE_SYSTEM`): `_ROLE_VERBATIM` above is the WHAT
# (identity, the aggregates-only output contract, the reference shape) and holds
# unconditionally, while the HOW (the ownership-judgment discipline and its worked
# examples) is the file `prompt_variant.prompt_path` selects - `assigner.md` for the
# `legacy` variant, `assigner-batched-l1unit-first.md` for the default. Either way
# it is operator-tunable without a code change. This is the per-role retirement of
# the shared analyser skill promised by #30: that skill instructs System modelling
# and data relationships this role is forbidden to emit, so a GENERALIST skill was
# worse here than none.
#
# There is no degraded stand-in: a missing prompt file is a defect and the read
# below FAILS CLOSED (raises). Withholding is the only defence against the
# measured 31-38% over-assignment, so the discipline's null-hypothesis,
# discriminating-evidence and calibration core must always be present - and every
# HARD invariant survives regardless, because narrow / resolve / inventory / bar
# are code, not prompt.
_ASSIGNER_SKILLS: dict[str, str] = {}


def _load_assigner_skill() -> str:
    """The Assigner's ownership-judgment discipline, read from the file the active
    prompt variant selects (`prompt_variant.prompt_path`): memoized in-process PER
    VARIANT, FAIL-CLOSED on a missing file (raise).

    The per-variant memoization is what preserves the provider prompt-cache prefix:
    within a variant the file is read ONCE per process, so `_system_prompt`
    returns byte-identical content for every chunk of a run."""
    variant = resolve_prompt_variant()
    cached = _ASSIGNER_SKILLS.get(variant)
    if cached is None:
        cached = prompt_path("assigner", variant).read_text(encoding="utf-8")
        _ASSIGNER_SKILLS[variant] = cached
    return cached


# The assignment prompt is the highest-variance surface in the analyser: the SAME
# surface has drawn 143 aggregates in one run and 11 in another (AMV-9). Which
# arrangement is better is therefore an EMPIRICAL question, and this repo has a settled
# answer to that shape of question - `bootstrap._PROMPT_CONFIGS`, where `skill_in_prompt`
# became the default only after a measured comparative eval, never on argument.
#
# DEFAULT = `skill` (operator-ratified 2026-07-29). The comparison that would normally
# earn that default did NOT: on soupmarket.shop the skill arm scored 55 aggregates /
# 0.366 coverage against baseline's 43 / 0.313, but its run had 23 bootstrapped Services
# against the baseline run's 11 - and an Assigner cannot assign to an owner that does not
# exist, so inventory size, not the prompt arm, is the likeliest explanation of that gap.
# The measured claim is therefore only "no regression"; the flip rests on the operator's
# judgment of the skill's CONTENT (the no-owner null hypothesis, the confidence anchors,
# the differential over candidate owners), not on the numbers.
#
# `baseline` reproduces the pre-skill prompt BYTE-FOR-BYTE and remains the rollback path,
# one env var away, and `_FEW_SHOTS` is retained for it and must not be deleted.
#
# The harness for a proper comparison is `evaluation.evaluate_assigner` - assignment
# volume against the integrity columns that stop volume being read as a score (stale
# pool, withheld rate, out-of-inventory rate), plus the confidence-bar sweep that makes
# `ASSIGN_CONFIDENCE_BAR` an output rather than a guess. It needs a FIXED inventory and
# repeats to settle this, and three of its columns are still unpopulated because
# `AssignmentStats` is persisted nowhere (design doc section 14.1).
_ASSIGNER_PROMPT_CONFIGS = ("baseline", "skill")
_DEFAULT_ASSIGNER_PROMPT_CONFIG = "skill"


def _assigner_prompt_config() -> str:
    cfg = (os.environ.get("ASSIGNER_PROMPT_CONFIG") or _DEFAULT_ASSIGNER_PROMPT_CONFIG).strip()
    if cfg not in _ASSIGNER_PROMPT_CONFIGS:
        logger.warning(
            "ASSIGNER_PROMPT_CONFIG=%r is unknown (known: %s); using %r",
            cfg, ", ".join(_ASSIGNER_PROMPT_CONFIGS), _DEFAULT_ASSIGNER_PROMPT_CONFIG,
        )
        return _DEFAULT_ASSIGNER_PROMPT_CONFIG
    return cfg


def assign(
    chunk: Chunk,
    *,
    invoke_fn,
    inventory: dict | None = None,
    existing_slugs: frozenset[str] = frozenset(),
    owned_endpoints=(),
    bar: float = ASSIGN_CONFIDENCE_BAR,
    run_id: str | None = None,
    tags: list | None = None,
    memory=None,
    project_id: str | None = None,
    note_kind: str = "open_question",
) -> AssignmentOutcome:
    """The Assigner proposer body (#8): from a `Chunk` + the LIVE inventory, judge
    which existing Service owns each admitted Endpoint, then drop unknown owners and
    SELF-WITHHOLD below the bar, returning the narrowed batch plus its backlog.

    The body runs the role's `WORKFLOW` (harvest_surface -> falsify_harvest ->
    prior_insights -> candidate_owners -> assign -> closure) through the injected
    `invoke_fn`, then shapes the extraction turn. The surface is NOT pre-fed: the
    prompt carries the Service unit (`_unit_context_block`) and the inventory, and
    the model discovers the surface through the tools. The full admitted endpoint
    set is still built from the chunk for the deterministic gates (`shape_proposal`),
    so a harvested Endpoint outside the unit context is validated, never assumed.

    `owned_endpoints` is the Service's OWN already-aggregated surface (the per-Service
    unit's `assets`), rendered into the unit card; it is context only, never a write
    scope. `invoke_fn(messages, *, schema, system_prompt) -> AnalysisTurn | None` is
    injected (unit-testable, no live LLM). Fail-open: a `None`/raising `invoke_fn`
    (or a chunk with no Endpoint in it) degrades to an empty outcome. Pure given its
    inputs.

    `memory` / `project_id` / `note_kind` thread the per-unit backstop into
    `run_workflow` (ADR D31): the global assign pass binds them so its turns'
    unit records one note (an `assignment` note); the streamed per-chunk path
    binds none, so it stays inert and byte-unbroken."""
    from polymerhus.analysis.pod import _inventory_block
    from polymerhus.analysis.proposer_turn import proposer_batch
    from polymerhus.analysis.reasoning_workflow import run_workflow, to_delta_batch

    admitted = admit_for_role(chunk, ROLE)
    l0_slice = _chunk_slice(chunk)
    if not l0_slice["nodes"]:  # nothing this role can act on -> valid empty
        return AssignmentOutcome()
    # The STABLE half of the prompt (#34) rides the stateful seam's `system_prompt=`
    # binding as the agent's leading block (the converged seam), so the provider's
    # cache prefix is a byte-identical leading block on every chunk and the prompt
    # never accumulates in the checkpointed trail. The legacy one-shot seam prepends
    # it into its message list instead.
    system_prompt = _system_prompt()
    # The volatile base sources the workflow injects verbatim: the inventory block
    # (identity reuse) and the Service UNIT context. The settled surface is NOT a
    # base source - the model DISCOVERS it through the tools (L1-unit-first), so only
    # the unit travels the prompt. `l0_slice`/`admitted` still feed `shape_proposal`.
    base_artifacts = {
        "inventory": _inventory_block(inventory),
        "service": _unit_context_block(chunk, inventory, owned_endpoints),
    }
    # Per-batch memory: the chunk id scopes the whole chain to its own session (the
    # supervisor dispatches one chunk at a time), so the next chunk starts fresh.
    # The scope is inert for the one-shot legacy seam.
    try:
        with proposer_batch(chunk.chunk_id):
            run = run_workflow(WORKFLOW, invoke_fn=invoke_fn,
                               system_prompt=system_prompt,
                               base_artifacts=base_artifacts,
                               halt_when=_halt_without_surface,
                               unit_slug=chunk.chunk_id, memory=memory,
                               project_id=project_id, run_id=run_id,
                               note_kind=note_kind)
    except Exception:  # LLM error -> fail-open to no assignment, never crash
        logger.warning("assigner: workflow failed; degrading to empty outcome", exc_info=True)
        return AssignmentOutcome()
    turn = run.turns.get("assign")
    if turn is None:
        # The chain halted at `falsify_harvest` because nothing survived: the
        # Service's surface is not mapped. Record it as a finding, not a failure.
        falsify = run.turns.get("falsify_harvest")
        if falsify is not None and _survivor_count(falsify) == 0:
            logger.info(
                "assigner chunk=%s no_surface: bounded harvest found nothing; "
                "halted before candidate_owners", chunk.chunk_id,
            )
            return AssignmentOutcome(no_surface=True)
        # no parseable tool call after retries -> empty outcome
        return AssignmentOutcome()
    raw = to_delta_batch(turn)
    outcome = shape_proposal(
        raw, existing_slugs=existing_slugs, endpoints=admitted, bar=bar,
    )
    st = outcome.stats
    # #18/observability: persist the RAW proposals + their confidences (and the bar they were
    # judged against) to Langfuse - otherwise a withheld aggregate leaves no inspectable trace
    # and "did the Assigner withhold on confidence?" is unanswerable post-hoc (moodique cc29fd4a).
    from polymerhus.app.observability import trace_generation
    trace_generation("assigner-aggregates", input={"chunk": chunk.chunk_id, "bar": bar},
                     run_id=run_id, tags=tags,
                     output={"proposed": [{"service_slug": getattr(a, "service_slug", None),
                                           "confidence": getattr(a, "confidence", None)}
                                          for a in (raw.aggregates or [])],
                             "stats": st.model_dump()})
    # ONE structured line per chunk. A zero-kept step now names its cause instead of
    # looking identical to a model that found nothing.
    logger.info(
        "assigner chunk=%s admitted=%d proposed=%d -> kept=%d "
        "(unresolvable=%d out_of_inventory=%d withheld=%d) backlog=%d",
        chunk.chunk_id, st.admitted, st.proposed, st.kept,
        st.unresolvable, st.out_of_inventory, st.withheld, len(outcome.backlog),
    )
    return outcome


def default_invoke_fn():
    """The legacy stateless call, retained for callers/tests that want the one-shot
    seam: the `analyser` role bound to the `AnalysisTurn` envelope via function-calling
    through the #73 escalating retry (`invoke_role`); `None` = no parseable tool call,
    which `assign` treats as a valid empty outcome. The role prompt is prepended into
    the message list here, exactly where the stateful seam's `system_prompt=` binding
    puts it.

    It is NOT the global assign pass's production seam: that one is notes-bound
    (`stateful_invoke_fn` / the per-Service proposer turn seam) so the
    constant-tool-set contract holds (spec 3.2/5, ADR D26). This one-shot seam binds
    no `notes` and stays for the contract tier."""
    from polymerhus.analysis.proposer_turn import prepend_prompt
    from polymerhus.analysis.reasoning_workflow import AnalysisTurn

    def invoke(messages, *, schema=AnalysisTurn, system_prompt=None):
        from polymerhus.app.llm.roles import invoke_role

        return invoke_role("analyser", prepend_prompt(messages, system_prompt), schema=schema)

    return invoke


def stateful_invoke_fn(run_id: str, checkpointer, project_id: str | None = None):
    """The STATEFUL Assigner call (#94): the `assigner` role runs as a session whose
    context PROGRESSES across the run's chunks, resuming from its own per-run checkpoint
    (`AnalysisSession(run_id, "assigner")`, distinct from every other agent's
    thread). Structured output is the `AnalysisTurn` envelope (#44-safe). Same
    `(messages, *, schema)` shape as the legacy seam, so `make_assigner_body` is
    unchanged.

    The role prompt is bound ONCE as the agent's ephemeral leading block (the
    converged seam, `proposer_turn.session_invoke_fn`), so it is the stable prefix of
    every request and never accumulates in the checkpointed trail.

    The Assigner is dispatched sequentially (the supervisor's chunk-major schedule holds
    `ANALYSER_PASS_SEMAPHORE`), so this structurally-sync stateful turn needs no async;
    its statefulness is what lets chunk N+1 reason with what it proposed for chunk N,
    not merely re-read the graph.

    Context-window compaction (#95 H/D9): the run's turns run COMPACTED - the
    analysis-side compaction middleware is built once per run and passed through
    `stateful_turn`, so an over-budget thread spawns out-of-band running-summary
    passes that the next turn's barrier awaits. Built fail-open: a missing role
    config degrades the profile/window, never the session."""
    from polymerhus.analysis.proposer_turn import session_invoke_fn

    return session_invoke_fn("assigner", run_id, checkpointer, project_id)


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
        # Convergence: the supervisor no longer opens an agent span, so the
        # structured-output record carries its own explicit run correlation.
        run_id = (state.get("run_id") or "").removeprefix("stream-")
        outcome = assign(
            dispatch.chunk,
            invoke_fn=invoke_fn,
            inventory=inventory,
            existing_slugs=frozenset(inventory.get("services") or ()),
            bar=bar,
            run_id=run_id or None,
            tags=["analysis", getattr(dispatch, "role", "assigner")],
        )
        if outcome.backlog:
            logger.info("assigner: %d backlog description(s) not transported (D6)", len(outcome.backlog))
        return outcome.batch

    return body


# --- T4: the global assign pass over the settled surface ----------------------


def _default_write_fn(batch: L1DeltaBatch, project_id: str) -> int:
    """The global pass's curator collaborator: write `AGGREGATES` and nothing else.

    It routes through `proposals_to_deltas` + `l1_curator.write_aggregates`, never
    `l1_curate`: a writer that could create a Service would quietly restore the
    minting path the Bootstrapper owns alone (ADR D37, "the pass no-mints")."""
    from polymerhus.analysis import l1_curator
    from polymerhus.analysis.analyser_types import proposals_to_deltas
    from polymerhus.analysis.l1_types import Provenance

    _, _, aggregates = proposals_to_deltas(batch, Provenance(job="analyser:global"))
    return l1_curator.write_aggregates(aggregates, project_id)


# The analysis run is `draining` for the whole of stage 1: the global pass runs
# first, at the head of the run. Re-stamping that same live status is truthful and
# idempotent (it never stamps `finished_at`), and the census rides the additive
# `stats` JSONB merge (ADR D11).
_CENSUS_STATUS = "draining"


def _persist_census(run_id: str, census: AssignmentCensus) -> None:
    """Merge the census onto the analysis run's `stats` (ADR D11)."""
    from polymerhus.app.clients import pg

    pg.set_analysis_run_status(
        run_id, _CENSUS_STATUS, stats={"assignment_census": census.model_dump()})


def _endpoint_key(identity: dict) -> tuple[str, str, str]:
    """A stable key for an Endpoint identity, method-normalised: `_endpoint_index`
    keys the pair on the UPPERCASED method while the canonical identity keeps the
    original case, so the two must agree here."""
    ident = identity or {}
    return (
        str(ident.get("path") or ""),
        str(ident.get("method") or "").upper(),
        str(ident.get("baseurl") or ""),
    )


def _stale_count(admitted, batch: L1DeltaBatch) -> int:
    """The residual stale pool: the admitted Endpoints that received no kept
    aggregate. Distinct keys, because several Services may own one Endpoint without
    that counting as two covered elements."""
    admitted_keys = {_endpoint_key(a.identity) for a in admitted}
    kept_keys = {_endpoint_key(a.l0.identity) for a in batch.aggregates}
    return len(admitted_keys - kept_keys)


def _global_invoke_fn(run_id: str, project_id: str, checkpointer):
    """The global assign pass's production turn seam: the SAME notes-bound
    `session_invoke_fn` the per-Service proposers use (spec 3.2/5, ADR D26/D34),
    with the `assigner` role, so both sub-problem turns bind `{AnalysisTurn,
    notes}` and the tool set never toggles. Fail-open: an unbuildable seam falls
    back to the legacy one-shot call, so a degraded pass writes nothing rather
    than crashing the run."""
    try:
        return stateful_invoke_fn(run_id, checkpointer, project_id)
    except Exception:  # noqa: BLE001 - fail-open to the notes-less one-shot seam
        logger.warning("assigner: global pass seam unavailable; using the one-shot seam",
                       exc_info=True)
        return default_invoke_fn()


async def assign_global(
    project_id: str,
    run_id: str,
    *,
    read_fn=None,
    invoke_fn=None,
    write_fn=None,
    inventory_fn=None,
    persist_fn=None,
    memory=None,
    checkpointer=None,
    bar: float = ASSIGN_CONFIDENCE_BAR,
) -> AssignmentCensus:
    """THE GLOBAL ASSIGN PASS (T4, spec 4.2, ADR D7-D11): re-read the settled L0
    surface and the Service inventory, run the Assigner's L1-unit-first workflow
    (harvest_surface -> falsify_harvest -> prior_insights -> candidate_owners ->
    assign -> closure) over the WHOLE surface, write `AGGREGATES` through the no-mint
    writer, and return (and persist) the census.

    A plain awaited call, NOT a supervisor dispatch (ADR D9): `AgentDispatch`
    rejects a slice-less non-slice-less role, and the pass is a whole-graph single
    step anyway. It assembles its own input from the graph - there is no pushed
    chunk and no FIFO (ADR D1/D3); the surface is grouped into ONE chunk-shaped
    slice so the SAME prompt and the SAME five shaping gates run unchanged (ADR
    D7).

    Every collaborator is injected, so the pass is unit-testable with no Neo4j and
    no LLM:

    - `read_fn(project_id) -> {nodes, links}`: the pod-shaped L0 read.
    - `inventory_fn(project_id) -> inventory`: the live Service inventory.
    - `invoke_fn(messages, *, schema, system_prompt)`: the Assigner's LLM seam.
    - `write_fn(batch, project_id) -> int`: the no-mint `AGGREGATES` writer.
    - `persist_fn(run_id, census)`: the `analysis_runs.stats` write.
    - `memory` / `checkpointer`: the notes store and session checkpointer the
      notes-bound default seam and the per-unit backstop use. Both are optional:
      absent a `memory` store the backstop is inert, and absent a `checkpointer`
      one is resolved from the session checkpointer.

    The default `invoke_fn` is the SAME notes-bound proposer seam the per-Service
    proposers use (spec 3.2/5, ADR D26), NOT the notes-less one-shot call, so
    both sub-problem turns bind `{AnalysisTurn, notes}`. When a `memory` store is
    bound, the pass's turns carry `unit_slug="global:<run_id>"` so `run_workflow`'s
    backstop records one `assignment` note for the pass (ADR D31) - making the
    `assignment` kind reachable in `service_sourced`.

    Fail-open: a degraded or empty result yields a census with zero writes and
    NEVER raises into the caller. Persistence is best-effort, exactly like the
    lifecycle's own stats write."""
    from polymerhus.analysis.l0_stream import read_l0_assets
    from polymerhus.analysis.l1_inventory import read_l1_inventory

    if invoke_fn is None:
        if checkpointer is None:
            try:
                from polymerhus.app.llm.checkpoints import get_session_checkpointer

                checkpointer = get_session_checkpointer()
            except Exception:  # noqa: BLE001 - a null checkpointer degrades the seam
                checkpointer = None
        invoke_fn = _global_invoke_fn(run_id, project_id, checkpointer)
    if write_fn is None:
        write_fn = _default_write_fn
    if inventory_fn is None:
        inventory_fn = read_l1_inventory
    if persist_fn is None:
        persist_fn = _persist_census

    census = AssignmentCensus()
    try:
        assets = read_l0_assets(project_id, read_fn=read_fn)
        # ONE grouped slice for the whole surface: the session scope is the run's
        # global pass, so the two sub-problems share a single session.
        chunk = Chunk(chunk_id=f"global:{run_id}", assets=tuple(assets))
        admitted = admit_for_role(chunk, ROLE)
        inventory = inventory_fn(project_id) or {}
        outcome = assign(
            chunk,
            invoke_fn=invoke_fn,
            inventory=inventory,
            existing_slugs=frozenset(inventory.get("services") or ()),
            bar=bar,
            run_id=run_id,
            tags=["analysis", "assigner", "service_sourced", "global"],
            memory=memory,
            project_id=project_id,
            note_kind="assignment",
        )
        written = 0
        if outcome.batch.aggregates:  # an empty result writes NOTHING, not a null
            written = int(write_fn(outcome.batch, project_id) or 0)
        st = outcome.stats
        census = AssignmentCensus(
            # `admitted` is the surface READ, not the LLM's view of it: on a degraded
            # turn (`st` all zero) reporting the surface is what says "there was work
            # and none of it was done". The gate counts below stay the LLM's.
            admitted=len(admitted),
            proposed=st.proposed,
            unresolvable=st.unresolvable,
            out_of_inventory=st.out_of_inventory,
            rescaled=st.rescaled,
            withheld=st.withheld,
            kept=st.kept,
            written=written,
            stale=_stale_count(admitted, outcome.batch),
        )
    except Exception:  # noqa: BLE001 - a degraded pass must never crash the run
        logger.warning("assign_global: pass degraded; returning a zero census", exc_info=True)
        census = AssignmentCensus()

    try:
        persist_fn(run_id, census)
    except Exception:  # noqa: BLE001 - persistence is best-effort (mirrors lifecycle)
        logger.warning("assign_global: census persistence failed", exc_info=True)

    logger.info(
        "assign_global run=%s admitted=%d kept=%d written=%d stale=%d "
        "(unresolvable=%d out_of_inventory=%d withheld=%d)",
        run_id, census.admitted, census.kept, census.written, census.stale,
        census.unresolvable, census.out_of_inventory, census.withheld,
    )
    return census


async def assign_services(
    project_id: str,
    run_id: str,
    *,
    read_fn=None,
    invoke_fn=None,
    write_fn=None,
    inventory_fn=None,
    persist_fn=None,
    memory=None,
    checkpointer=None,
    units=None,
    read_slices_fn=None,
    bar: float = ASSIGN_CONFIDENCE_BAR,
) -> AssignmentCensus:
    """THE PER-SERVICE ASSIGN PASS (v2, spec 2.1, ADR D46): one awaited call per
    Service unit.

    The v2 consumption filter for the Assigner is EACH SERVICE (v2 spec section 2):
    the assigner grounds ownership on the L0 surface THROUGH one Service at a time,
    rather than grouping the whole surface into one pass. Each Service unit carries
    the settled L0 surface as the candidate set the deterministic gates validate
    against, and its OWN aggregated endpoints as the unit context; the model
    DISCOVERS its relevant surface through the tools, driven by the contract. A
    Service is judged with the FULL live inventory as `existing_slugs`, so it may
    name ANY live Service as an owner - there is NO per-Service write filter. The
    only surviving gate is the GLOBAL inventory validation: a slug not in the live
    inventory is still dropped by `drop_out_of_inventory`.

    It reuses the SAME `assign` body, prompt and five shaping gates as the global
    pass - only the unit set and the unit context differ - and sums the per-Service
    censuses into one. Fail-open per Service: a unit that raises contributes zero and
    the next unit runs. Persistence mirrors `assign_global` (best-effort)."""
    from polymerhus.analysis.l0_stream import read_l0_assets

    if inventory_fn is None:
        from polymerhus.analysis.l1_inventory import read_l1_inventory

        inventory_fn = read_l1_inventory
    if write_fn is None:
        write_fn = _default_write_fn
    if persist_fn is None:
        persist_fn = _persist_census
    if units is None:
        from polymerhus.analysis.service_slice import (
            RESIDUAL_UNIT,
            build_service_slices,
        )

        all_units = build_service_slices(project_id, read_fn=read_slices_fn)
        units = [u for u in all_units if u.chunk_id != RESIDUAL_UNIT]

    if invoke_fn is None:
        if checkpointer is None:
            try:
                from polymerhus.app.llm.checkpoints import get_session_checkpointer

                checkpointer = get_session_checkpointer()
            except Exception:  # noqa: BLE001 - a null checkpointer degrades the seam
                checkpointer = None
        invoke_fn = _global_invoke_fn(run_id, project_id, checkpointer)

    totals = {
        "admitted": 0, "proposed": 0, "unresolvable": 0, "out_of_inventory": 0,
        "rescaled": 0, "withheld": 0, "kept": 0, "written": 0, "stale": 0,
    }
    try:
        assets = tuple(read_l0_assets(project_id, read_fn=read_fn))
        inventory = inventory_fn(project_id) or {}
        all_slugs = frozenset(inventory.get("services") or ())
    except Exception:  # noqa: BLE001 - a degraded read yields a zero census
        logger.warning("assign_services: read failed; returning a zero census", exc_info=True)
        units, assets, inventory, all_slugs = [], (), {}, frozenset()

    for unit in units:
        slug = str(unit.source_job or "").removeprefix("service:") or unit.chunk_id
        if slug not in all_slugs:
            continue
        # The unit is the prompt anchor; the whole settled surface rides the chunk so
        # the deterministic gates can validate a harvested Endpoint. `unit.assets` is
        # the Service's OWN already-aggregated surface, fed as context. The FULL live
        # inventory is the validation set, so no per-Service write filter remains.
        chunk = Chunk(
            chunk_id=unit.chunk_id, source_job=f"service:{slug}", assets=assets,
        )
        try:
            admitted = admit_for_role(chunk, ROLE)
            outcome = assign(
                chunk,
                invoke_fn=invoke_fn,
                inventory=inventory,
                existing_slugs=all_slugs,
                owned_endpoints=tuple(unit.assets),
                bar=bar,
                run_id=run_id,
                tags=["analysis", "assigner", "service_sourced", "per_service"],
                memory=memory,
                project_id=project_id,
                note_kind="assignment",
            )
            written = 0
            if outcome.batch.aggregates:  # an empty result writes NOTHING
                written = int(write_fn(outcome.batch, project_id) or 0)
            st = outcome.stats
            totals["admitted"] += len(admitted)
            totals["proposed"] += st.proposed
            totals["unresolvable"] += st.unresolvable
            totals["out_of_inventory"] += st.out_of_inventory
            totals["rescaled"] += st.rescaled
            totals["withheld"] += st.withheld
            totals["kept"] += st.kept
            totals["written"] += written
            totals["stale"] += _stale_count(admitted, outcome.batch)
        except Exception:  # noqa: BLE001 - fail-open per Service, the loop continues
            logger.warning("assign_services: unit %s degraded; continuing", unit.chunk_id,
                           exc_info=True)

    census = AssignmentCensus(**totals)
    try:
        persist_fn(run_id, census)
    except Exception:  # noqa: BLE001 - persistence is best-effort (mirrors lifecycle)
        logger.warning("assign_services: census persistence failed", exc_info=True)

    logger.info(
        "assign_services run=%s units=%d kept=%d written=%d stale=%d",
        run_id, len(units), census.kept, census.written, census.stale,
    )
    return census
