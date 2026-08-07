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
#
# NOT REACHED IN PRODUCTION, deliberately (operator-ratified 2026-07-28). `Mode` is
# declared at `analysis/messages.py:36` and read only by `_system_prompt`; no
# dispatcher ever sets `"reflect"`. Like the curation pass, reflection is legacy
# under the analysis rewrite and degrades ORGANICALLY as the pipeline completes - it
# is neither wired up nor deleted here. It stays TESTED (C25, C40b on both prompt
# arms) so that whoever does wire it inherits a pinned contract rather than a guess,
# and so its cost is visible: it is dead weight until then, not a working feature.
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
    """The STABLE half of the prompt (#34): the role verbatim, the judgment
    discipline, and under `reflect` the reflection protocol. Everything here is
    invariant across a run so the provider prompt-cache prefix survives it; the
    volatile inventory and chunk ride the user message instead.

    It deliberately does NOT load the shared legacy analyser skill. That skill is
    L0-oriented and addresses a generalist proposer: it instructs System modelling,
    data relationships and Service props, all of which #34 D4/D18 forbid this role
    from emitting. Carrying it here would put "emit aggregates only" and a
    WebPresentation worked example in one system message and let the model choose.
    Retiring it per-role is ticket #30; the ROLE-SPECIFIC skill that replaces it for
    the Assigner is `skills/analysis/assigner/SKILL.md`, selected by
    `ASSIGNER_PROMPT_CONFIG=skill`."""
    base = (
        f"{_ROLE_VERBATIM}\n\n{_load_assigner_skill()}"
        if _assigner_prompt_config() == "skill"
        else f"{_ROLE_VERBATIM}\n\n{_FEW_SHOTS}"
    )
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
    # The scolding half of this rule ("it is the node TYPE, never a path and never a
    # method") was deleted once `resolve_l0_refs` began overwriting `l0.label`
    # unconditionally: an instruction the code no longer depends on is not a safety
    # net, it is tokens spent naming the elephant. What survives is the IDENTITY
    # shape, which is still load-bearing - it is what makes the repair's happy path
    # fire, because `_candidate_path` reads `identity["path"]` first.
    "REFERENCING AN ENDPOINT: put the endpoint in `l0.identity` as "
    "`{\"path\": \"/api/Users\", \"method\": \"GET\", "
    "\"baseurl\": \"<the baseurl shown>\"}`, with `l0.label` set to `Endpoint`. "
    "Only reference endpoints that appear above; one you invent names nothing and "
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
# (identity, the aggregates-only output contract, the reference shape) and must hold
# even with no skills mount, while `skills/analysis/assigner/SKILL.md` is the HOW (the
# ownership-judgment discipline and its worked examples), operator-tunable without a
# code change. This is the per-role retirement of the shared analyser skill promised by
# #30: that skill instructs System modelling and data relationships this role is
# forbidden to emit, so a GENERALIST skill was worse here than none.
#
# The FALLBACK is a degraded stand-in used only when the mount is unavailable
# (`skill_for` logs a warning). Fail-open is required (`loop-constraints.md`: a skill
# error degrades, never crashes), but it must not degrade to SILENCE: withholding is the
# only defence against the measured 31-38% over-assignment, so the fallback carries the
# null-hypothesis, discriminating-evidence and calibration core even though it drops the
# worked examples. Every HARD invariant survives a missing mount regardless, because
# narrow / resolve / inventory / bar are code, not prompt.
_ASSIGNER_SKILL_FALLBACK = (
    "Begin every judgment from NO OWNER and make the evidence overturn it: "
    "assignment is the claim that carries the burden of proof. Read the "
    "Endpoint's own path nouns, method and parameter names BEFORE you read the "
    "inventory, hold every candidate Service whose contract touches them, and "
    "keep only the candidate whose evidence fits THAT contract and not the "
    "others - evidence that fits three Services equally is evidence for none. "
    "Where two contracts genuinely both reach the Endpoint, emit both. "
    "Confidence tracks discriminating evidence: ~0.9 when a path noun names a "
    "record the contract owns, ~0.5 when only the business area matches, ~0.2 "
    "when the only link is topical proximity. A below-bar judgment produces no "
    "edge, and that is the correct outcome rather than a failure."
)


def _load_assigner_skill() -> str:
    """The Assigner's ownership-judgment discipline, single-sourced from
    `skills/analysis/assigner/SKILL.md` through the shared `skill_for` (FR-SKILLIF):
    YAML frontmatter stripped, cached in-process, and degraded to the terse fallback
    above if the mount is unavailable.

    That cache is what preserves the provider prompt-cache prefix: the file is read
    ONCE per process, so `_system_prompt` returns byte-identical content for every
    chunk of a run (the only invalidation is `skills.clear_cache()`, a test seam)."""
    from polymerhus.recon.domain.skills import skill_for

    return skill_for("analysis/assigner", fallback=_ASSIGNER_SKILL_FALLBACK)


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

    admitted = admit_for_role(chunk, ROLE)
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
    outcome = shape_proposal(
        raw, existing_slugs=existing_slugs, endpoints=admitted, bar=bar,
    )
    st = outcome.stats
    # #18/observability: persist the RAW proposals + their confidences (and the bar they were
    # judged against) to Langfuse - otherwise a withheld aggregate leaves no inspectable trace
    # and "did the Assigner withhold on confidence?" is unanswerable post-hoc (moodique cc29fd4a).
    from polymerhus.app.observability import trace_generation
    trace_generation("assigner-aggregates", input={"chunk": chunk.chunk_id, "bar": bar},
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
    seam: the `analyser` role bound to `L1DeltaBatch` via function-calling through the
    #73 escalating retry (`invoke_role`); `None` = no parseable tool call, which
    `assign` treats as a valid empty outcome. Production now uses
    `stateful_invoke_fn` (below)."""
    from polymerhus.app.llm.roles import invoke_role

    def invoke(messages):
        return invoke_role("analyser", messages, schema=L1DeltaBatch)

    return invoke


def stateful_invoke_fn(run_id: str, checkpointer):
    """The STATEFUL Assigner call (#94): the `assigner` role runs as a session whose
    context PROGRESSES across the run's chunks, resuming from its own per-run checkpoint
    (`AnalysisSession(run_id, "assigner")`, distinct from every other agent's
    thread). Structured output is `L1DeltaBatch` via `ToolStrategy` (the
    function_calling-equivalent, #44-safe). Same `(messages) -> batch | None` shape as
    the legacy seam, so `make_assigner_body` is unchanged.

    The Assigner is dispatched sequentially (the supervisor's chunk-major schedule holds
    `ANALYSER_PASS_SEMAPHORE`), so this structurally-sync stateful turn needs no async;
    its statefulness is what lets chunk N+1 reason with what it proposed for chunk N,
    not merely re-read the graph."""
    from polymerhus.app.llm.session import stateful_turn
    from polymerhus.app.llm.session_address import AnalysisSession

    address = AnalysisSession(run_id, "assigner")

    def invoke(messages):
        return stateful_turn("assigner", address, messages,
                             checkpointer=checkpointer, schema=L1DeltaBatch)

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
