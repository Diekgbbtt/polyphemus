"""The DataPlane Analyser (agent spec #10, ratified `docs/design/dataplane-A1-decisions.md`
2026-07-30, realised by #48), the `data_modeller` A.1 proposer.

Sole owner of the Tier-1 data substrate. Its analysis object is the L1 UNIT (the
Service): it reasons DOWN from the unit - the slug, the `service_contract` and the
Endpoints the Service already aggregates - and DISCOVERS the unit's surface
through `graph_view` and the HTTP-history tools. From that discovered surface it
lifts the logical `DataItem`s it evidences, binds each to the concrete L0 sites
where it appears via `SURFACES_AT`, and maps the `PRODUCES`/`CONSUMES` flows that
connect those items to the settled Service model, plus the baseline
surface-observable DataItem-to-DataItem dependencies. No whole-surface asset
stream is pre-fed. It emits `L1DeltaBatch{data_items, surfaces_at, data_flows,
data_relationships}` and nothing else - it does not assign Endpoints (the
Assigner), type mechanisms (the mechanism-typist), or mint Services.

There is NO per-unit `service_slug` write scope on `data_flows`: a flow may name
ANY live Service as producer or consumer. The only surviving gate is the GLOBAL
inventory validation (`drop_out_of_inventory_services`): a slug that names no live
Service is still dropped.

It never emits Cypher and never sets provenance or identity keys (C17):
`enrichment_proposals_to_deltas` stamps provenance at the curate boundary, and
every write reaches the graph through `l1_curator` (the sole-writer).

The four data proposal shapes carry no `confidence` field (the deliberate
envelope asymmetry, `CONTEXT.md` *Judgment envelope*), so there is no withholding
bar to calibrate here. GROUNDEDNESS is this agent's substitute for the
Assigner's WITHHOLD: an ungrounded lift is dropped by code (`enforce_groundedness`),
never merely discouraged by prompt.

A.2 (the completeness sweep) is `designed-not-built` (DPL-DEC-23): the phase
guard in `make_data_modeller_body` returns `None` for any phase but `"A1"`, an
inert dormant seam per `CODING_STANDARD.md` section 12 - never a silent
half-implementation.
"""
from __future__ import annotations

import logging
import os
from collections import defaultdict
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from polymerhus.analysis.analyser_types import L1DeltaBatch
from polymerhus.analysis.chunking import Chunk, admit_for_role
from polymerhus.analysis.l1_curator import DATA_RELATIONSHIP_KINDS
from polymerhus.analysis.l1_types import L0Ref
from polymerhus.analysis.prompt_variant import prompt_path, resolve_prompt_variant
from polymerhus.analysis.proposer_reasoning import cot_scaffold, role_header
from polymerhus.analysis.reasoning_workflow import ReasoningWorkflow, SubProblem

if TYPE_CHECKING:
    from polymerhus.analysis.memory import AnalysisMemoryStore

logger = logging.getLogger(__name__)

ROLE = "data_modeller"

# The L0 labels this role may reference in a `surfaces_at.l0` (DPL-DEC-10):
# never an Endpoint - a path noun alone never grounds a lift.
_SURFACE_LABELS: tuple[str, ...] = ("Parameter", "Header", "Secret")
_LABEL_ALIASES: dict[str, str] = {
    "parameter": "Parameter", "param": "Parameter",
    "header": "Header", "secret": "Secret",
}


class DataPlaneStats(BaseModel):
    """Per-chunk gate census - the direct analogue of `assigner.AssignmentStats`,
    whose docstring states the rationale this one shares: "a run proposed 114
    sound assignments and wrote zero, and NOTHING in the system said so". Every
    gate in `shape_proposal` is fail-open, so every one of them gets its own
    counter, so a zero-kept step names its cause instead of looking identical to
    a model that found nothing.

    NOTE: the design doc's draft `flagged_chunk` field is deliberately ABSENT.
    Section 6 (ratified 2026-07-30) removes the whole httpx-profile-gate
    apparatus - including `Chunk.flagged` itself - so there is nothing left for
    that counter to observe; carrying a dead field forward would be exactly the
    "no-op checker that rots undetected" `CODING_STANDARD.md` section 12 warns
    against."""

    model_config = ConfigDict(frozen=True)

    # input side - what this role was given
    admitted_parameters: int = 0
    admitted_headers: int = 0
    admitted_secrets: int = 0
    observations_attached: int = 0

    # generation side
    reflection_exhausted: bool = False
    extraction_exhausted: bool = False
    proposed_items: int = 0
    proposed_surfaces: int = 0
    proposed_flows: int = 0
    proposed_relationships: int = 0

    # gate side - one counter per fail-open drop
    unknown_kind_dropped: int = 0            # gate 2
    unresolvable_surfaces: int = 0           # gate 3
    out_of_inventory_flows: int = 0          # gate 4
    fields_proposed: int = 0                 # gate 5
    fields_unobserved_dropped: int = 0       # gate 5
    fields_carried_forward: int = 0          # gate 5
    ungrounded_items_dropped: int = 0        # gate 6
    orphan_relationships_dropped: int = 0    # gate 6

    # output side
    kept_items: int = 0
    kept_surfaces: int = 0
    kept_flows: int = 0
    kept_relationships: int = 0
    reused_item_keys: int = 0
    new_item_keys: int = 0


class DataPlaneOutcome(BaseModel):
    """What one DataPlane Analyser pass produced: the shaped `batch` the curator
    may write, the `backlog` of surface it could not place, and the gate census.

    The backlog is carried but NOT transported (DPL-DEC-22, mirrors #34 D6): no
    envelope field exists to carry it upward yet."""

    model_config = ConfigDict(frozen=True)

    batch: L1DeltaBatch = Field(default_factory=L1DeltaBatch)
    backlog: tuple[str, ...] = ()
    stats: DataPlaneStats = Field(default_factory=DataPlaneStats)


# --- pure shaping (input value in, narrowed/validated batch out; no I/O) -------

def narrow_to_data(batch: L1DeltaBatch) -> L1DeltaBatch:
    """GATE 1, FIRST (section 5): the data_modeller owns ONLY the four data lists.
    Drop `services` (-> Bootstrapper), `systems`/`system_edges` (-> TechnicalSystem)
    and `aggregates` (-> Assigner). Must run first: every count downstream is a
    count of data deltas, and a stray `services`/`aggregates` list reaching the
    curator would restore Service minting (#34 D4) and double-write assignment."""
    return batch.model_copy(update={
        "services": [], "systems": [], "aggregates": [], "system_edges": [],
    })


def _known_data_rel_kinds() -> frozenset[str]:
    from polymerhus.analysis.l1_curator import DATA_RELATIONSHIP_KINDS
    return frozenset(k for k, _desc in DATA_RELATIONSHIP_KINDS)


def drop_unknown_relationship_kinds(
    batch: L1DeltaBatch, *, kinds: frozenset[str] | None = None
) -> tuple[L1DeltaBatch, int]:
    """GATE 2 (section 5): keep only `data_relationships` whose `kind` is in the
    allowlist. Runs before any per-kind accounting; the writer hard-rejects an
    unknown kind anyway (`l1_curator.build_data_relationship_cypher`), so shaping
    it out here means the proposer emits only what the writer accepts rather than
    relying on the guard (the `mechanism_typist.drop_unknown_vocabulary` discipline)."""
    kinds = kinds if kinds is not None else _known_data_rel_kinds()
    kept = [r for r in batch.data_relationships if r.kind in kinds]
    dropped = len(batch.data_relationships) - len(kept)
    return batch.model_copy(update={"data_relationships": kept}), dropped


def _canonical_label(raw) -> str | None:
    if not isinstance(raw, str):
        return None
    if raw in _SURFACE_LABELS:
        return raw
    return _LABEL_ALIASES.get(raw.strip().lower())


def site_index(sites) -> dict[tuple[str, str], dict]:
    """Index the Parameter/Header/Secret sites the reference gate resolves against
    by `(label, the-part-a-model-reliably-gets-right)`. `sites` is the UNION of the
    unit's admitted chunk and the live graph-discovered sites (C-M1). Parameter and
    Header key on `name`; Secret keys on `value_hash` (its whole identity). First
    match wins on a name collision; the reflection scaffold's HYPOTHESISE step is
    where ambiguity is meant to be resolved, not this index."""
    index: dict[tuple[str, str], dict] = {}
    for a in sites:
        ident = a.identity or {}
        if a.type == "Parameter" or a.type == "Header":
            name = ident.get("name")
            if name is None:
                continue
            key = (a.type, str(name))
        elif a.type == "Secret":
            vh = ident.get("value_hash")
            if vh is None:
                continue
            key = ("Secret", str(vh))
        else:
            continue
        index.setdefault(key, dict(ident))
    return index


def _resolve_ref(l0: L0Ref, sites: dict) -> L0Ref | None:
    label = _canonical_label(l0.label)
    identity = l0.identity if isinstance(l0.identity, dict) else {}
    candidates = [label] if label else list(_SURFACE_LABELS)
    for lbl in candidates:
        name = identity.get("value_hash") if lbl == "Secret" else identity.get("name")
        if name is None:
            continue
        canonical = sites.get((lbl, str(name)))
        if canonical is not None:
            return L0Ref(label=lbl, identity=canonical)
    return None


def resolve_surface_refs(batch: L1DeltaBatch, *, sites: dict) -> tuple[L1DeltaBatch, int]:
    """GATE 3, THE REFERENCE GATE (section 5.1): rewrite every `surfaces_at.l0`
    into the exact `Parameter{name,position,endpoint_path,baseurl}` /
    `Header{name,value,baseurl}` / `Secret{value_hash}` shape, and DROP any that
    names no site the gate could resolve against (the admitted chunk UNION the
    live graph-discovered sites, C-M1).

    `_l0_match_clause` MATCHes on exact label + identity and does not distinguish
    a zero-row match from a write (`l1_curator._write_each` counts it as written
    regardless), so a ref the model formatted its own way would be silently
    discarded - the same defect class as the `l0.label` failure that wrote zero
    of 114 sound Assigner proposals (assigner.py `resolve_l0_refs`). Correctness
    must not depend on the model's formatting, so it is repaired here rather than
    instructed and hoped for. Must run BEFORE gate 6: a surviving `surfaces_at` is
    what makes an item grounded, and gate 6 tests for exactly that survival."""
    kept, dropped = [], 0
    for s in batch.surfaces_at:
        canonical = _resolve_ref(s.l0, sites)
        if canonical is None:
            dropped += 1
            continue
        kept.append(s.model_copy(update={"l0": canonical}))
    return batch.model_copy(update={"surfaces_at": kept}), dropped


def drop_out_of_inventory_services(
    batch: L1DeltaBatch, *, existing_slugs: frozenset[str]
) -> tuple[L1DeltaBatch, tuple[str, ...], int]:
    """GATE 4, THE VALIDATION GATE (section 5.2): drop every `data_flow` whose
    `service_slug` is not a live L1 Service, collecting one backlog description
    per missing slug.

    `existing_slugs` is the FULL live Service inventory, never the unit's own slug
    alone (T3, L1-unit-first): a flow may name ANY live Service as producer or
    consumer. Only a slug that names no live Service is dropped - the global gate,
    which is what stops a hallucinated owner.

    `build_data_flow_cypher` merges the Service with provenance-on-mint, so an
    unvalidated `data_flow` naming a slug that does not exist would CREATE a
    Service through the data path - exactly the chunk-local minting #34 D4
    retired from the Assigner (AMV-12 identity drift). This gate is what keeps
    #34 D4 true on this path too. Mirrors `assigner.drop_out_of_inventory`
    verbatim in shape."""
    kept, missing = [], []
    for flow in batch.data_flows:
        if flow.service_slug in existing_slugs:
            kept.append(flow)
        elif flow.service_slug not in missing:
            missing.append(flow.service_slug)
    backlog = tuple(
        f"{slug}: a data flow named this Service but it is not in the live L1 "
        f"inventory; it may be missing."
        for slug in missing
    )
    dropped = len(batch.data_flows) - len(kept)
    return batch.model_copy(update={"data_flows": kept}), backlog, dropped


def bind_fields_to_observed(
    batch: L1DeltaBatch, *, observed_names: frozenset[str],
    existing_fields: dict[str, list[str]] | None = None,
) -> tuple[L1DeltaBatch, dict]:
    """GATE 5, THE OBSERVED-ONLY FIELDS GATE (section 5.3): intersect each
    proposed `fields` list with the vocabulary this chunk could actually have
    observed, then UNION the survivors with the item's already-persisted
    `fields`, omitting the key entirely when nothing survives.

    The union is not defensive, it is REQUIRED: `build_dataitem_cypher` writes
    `SET d += $props`, which replaces `fields` wholesale, so a re-proposal from a
    later chunk that observed a different subset would otherwise LOSE what an
    earlier chunk observed (DPL-DEC-07). Reading the persisted set live and
    emitting the superset compounds; an item with no `fields` key in its proposal
    is left untouched here (`SET n += map` only touches keys the map carries, so
    omitting the key already preserves whatever is on the node)."""
    existing_fields = existing_fields or {}
    proposed_total = 0
    unobserved_dropped = 0
    carried_forward = 0
    items = []
    for item in batch.data_items:
        props = dict(item.props or {})
        if "fields" not in props:
            items.append(item)
            continue
        proposed = list(props.get("fields") or [])
        proposed_total += len(proposed)
        observed = [f for f in proposed if f in observed_names]
        unobserved_dropped += len(proposed) - len(observed)
        persisted = list(existing_fields.get(item.item_key) or [])
        merged = list(dict.fromkeys(persisted + observed))  # union, stable order
        carried_forward += sum(1 for f in persisted if f not in observed)
        new_props = dict(props)
        if merged:
            new_props["fields"] = merged
        else:
            new_props.pop("fields", None)
        items.append(item.model_copy(update={"props": new_props}))
    stats = {
        "fields_proposed": proposed_total,
        "fields_unobserved_dropped": unobserved_dropped,
        "fields_carried_forward": carried_forward,
    }
    return batch.model_copy(update={"data_items": items}), stats


def enforce_groundedness(
    batch: L1DeltaBatch, *, known_items: frozenset[str] = frozenset(),
) -> tuple[L1DeltaBatch, int, int]:
    """GATE 6, LAST (section 5.4, DPL-DEC-13, ratified 2026-07-30): drop every NEW
    `data_item` with no surviving `surfaces_at` - a path noun alone never grounds
    a lift, so a `data_flow` cannot substitute for an observed surface site. An
    item already in the live inventory is not re-tested (it was grounded when it
    was written). Also drops every `data_relationship` whose endpoints are not
    among (surviving items UNION the live inventory) - `build_data_relationship_cypher`
    merges both DataItems, so an orphan endpoint is a reference to nothing.

    MUST run last: it is a function of what survived every earlier gate. Run
    before gate 3 and it would certify an item grounded by a reference to a site
    the chunk never carried - a gate that is vacuous because a prior
    normalisation did not run yet."""
    known_items = frozenset(known_items)
    grounded_keys = {s.item_key for s in batch.surfaces_at}
    kept_items, dropped_items = [], 0
    for item in batch.data_items:
        if item.item_key in grounded_keys or item.item_key in known_items:
            kept_items.append(item)
        else:
            dropped_items += 1
    valid_keys = {i.item_key for i in kept_items} | known_items
    kept_rels, dropped_rels = [], 0
    for rel in batch.data_relationships:
        if rel.from_item_key in valid_keys and rel.to_item_key in valid_keys:
            kept_rels.append(rel)
        else:
            dropped_rels += 1
    return (
        batch.model_copy(update={"data_items": kept_items, "data_relationships": kept_rels}),
        dropped_items, dropped_rels,
    )


def shape_proposal(
    raw: L1DeltaBatch, *, sites: dict, existing_slugs: frozenset[str] = frozenset(),
    known_items: frozenset[str] = frozenset(), observed_names: frozenset[str] = frozenset(),
    existing_fields: dict[str, list[str]] | None = None,
) -> DataPlaneOutcome:
    """Apply the six ordered shaping gates of section 5 to a raw LLM proposal.

    ORDER IS LOAD-BEARING (section 5, "why the order is load-bearing"): narrow
    first (so the denominator is data deltas only), the reference gate (3) and the
    validation gate (4) before groundedness (6) - they are what REMOVE the
    anchors gate 6 tests for - and groundedness last because it is a function of
    every earlier gate's survivors."""
    known_items = frozenset(known_items)
    batch = narrow_to_data(raw)
    proposed_items = len(batch.data_items)
    proposed_surfaces = len(batch.surfaces_at)
    proposed_flows = len(batch.data_flows)
    proposed_relationships = len(batch.data_relationships)

    batch, unknown_kind_dropped = drop_unknown_relationship_kinds(batch)
    batch, unresolvable_surfaces = resolve_surface_refs(batch, sites=sites)
    batch, backlog, out_of_inventory_flows = drop_out_of_inventory_services(
        batch, existing_slugs=existing_slugs,
    )
    batch, field_stats = bind_fields_to_observed(
        batch, observed_names=observed_names, existing_fields=existing_fields,
    )
    batch, ungrounded_items_dropped, orphan_relationships_dropped = enforce_groundedness(
        batch, known_items=known_items,
    )

    kept_keys = {i.item_key for i in batch.data_items}
    reused_item_keys = len(kept_keys & known_items)
    new_item_keys = len(kept_keys - known_items)

    stats = DataPlaneStats(
        proposed_items=proposed_items, proposed_surfaces=proposed_surfaces,
        proposed_flows=proposed_flows, proposed_relationships=proposed_relationships,
        unknown_kind_dropped=unknown_kind_dropped,
        unresolvable_surfaces=unresolvable_surfaces,
        out_of_inventory_flows=out_of_inventory_flows,
        fields_proposed=field_stats["fields_proposed"],
        fields_unobserved_dropped=field_stats["fields_unobserved_dropped"],
        fields_carried_forward=field_stats["fields_carried_forward"],
        ungrounded_items_dropped=ungrounded_items_dropped,
        orphan_relationships_dropped=orphan_relationships_dropped,
        kept_items=len(batch.data_items), kept_surfaces=len(batch.surfaces_at),
        kept_flows=len(batch.data_flows), kept_relationships=len(batch.data_relationships),
        reused_item_keys=reused_item_keys, new_item_keys=new_item_keys,
    )
    return DataPlaneOutcome(batch=batch, backlog=backlog, stats=stats)


# --- observed vocabulary (section 5.3) -----------------------------------------

def observed_vocabulary(sites) -> frozenset[str]:
    """The names the observed-only gate may keep (section 5.3): the `name` of every
    Parameter/Header site, plus any non-identity keys those (and Secret) assets
    carry in `props`. The `sites` list is the UNION of the unit's admitted chunk
    and the live graph-discovered sites (C-M1), so a field seen only through
    `graph_view` is still groundable."""
    names: set[str] = set()
    for a in sites:
        ident = a.identity or {}
        if a.type in ("Parameter", "Header") and ident.get("name") is not None:
            names.add(str(ident["name"]))
        for k in (a.props or {}):
            names.add(str(k))
    return frozenset(names)


# --- the hypothesis-driven reflection scaffold (section 7.3) -------------------

_REFLECTION_STEPS = [
    "ORIENT: read the Service unit first - its contract and the Endpoints it already "
    "aggregates - then each Parameter/Header/Secret the survey DISCOVERED, together "
    "with the endpoint path it hangs off (where it has one) and the origin-scoped "
    "adversarial insight; say what the surface alone tells you before you look at the "
    "known DataItems.",
    "HYPOTHESISE (define-hypothesis): for each discovered name, state candidate "
    "hypotheses of the form 'this name witnesses business record R'. For an "
    "ambiguous name (id, token, ref) hold MORE THAN ONE candidate record, and state "
    "'this witnesses no business record' as an explicit candidate among them - never "
    "an unstated default reached only if nothing else fits.",
    "VERIFY / FALSIFY (debug-hypothesis + critical-thinking): test each hypothesis "
    "against the evidence actually present. Separate the claim from its support (the "
    "exact name, the exact path, the exact endpoint it hangs off) - a name that "
    "merely sounds like a record with no path or field corroboration is topical "
    "proximity, not evidence. Decide REUSE-vs-COIN here, against the currently-known "
    "DataItems and their notes/fields: an existing item_key with matching notes/fields "
    "wins over minting a synonym.",
    "INTEGRATE: fold the origin's adversarial insight into the surviving record's "
    "notes - what it is, whose trust it carries, what breaks. No named payload, no "
    "named technique, no named vector - an adversarial CHARACTERISATION only.",
    "SHAPE: for each verified record, three low-risk transcriptions of what "
    "verification already settled - Ground (name the exact surface site(s) it "
    "appears at, and which Service produces it and which consumes it, choosing "
    "service slugs from the LIVE Service inventory you were given - any live Service "
    "may be named, not only this unit), Trust (for a consumes whose producing Service "
    "differs from the consumer, state the falsifiable predicate the consumer holds "
    "about that data, in one surface-readable sentence), Relate (only where the "
    "surface itself shows it, state a record-to-record dependency using one of the "
    "allowed kinds, with a shallow predicate).",
    "EMIT / WITHHOLD: report the verified records. Name what you FALSIFIED and why "
    "- a pagination cursor, a CSRF token, a framework header - so withholding is the "
    "loop's demonstrated conclusion, not an assumed default.",
]


# The data_modeller's eight sub-problems (T3, L1-unit-first): three SURVEY turns
# (surface_survey discovers the unit's surface, request_shapes reads the recorded
# requests, insight_recall reads the notes store), the reasoning/extraction turns
# (record_hypotheses, data_extract, flow_shape, flow_extract), and closure_note.
# Each maps onto a run of the `_REFLECTION_STEPS` stages: ORIENT+HYPOTHESISE+
# VERIFY-FALSIFY, INTEGRATE, SHAPE, EMIT-WITHHOLD. The reasoning turns emit
# `claims`; the extraction turns emit `{data_items, surfaces_at}` and
# `{data_flows, data_relationships}`. Every turn speaks `AnalysisTurn`, so the tool
# set never toggles. No turn is fed a whole streamed asset list: the model discovers
# the surface through `graph_view` and the HTTP-history pair, driven by the unit.
_ROLE_HEADER = role_header(
    "the DataPlane Analyser (data_modeller)",
    "work down from the L1 Service unit to the surface it exposes, lift the Tier-1 "
    "logical DataItems that surface evidences, bind them to the surface, and ground "
    "their flows onto the settled Service model",
)

_RECORD_HYPOTHESES_TASK = (
    "Emit one Claim per discovered name: `subject` the name, `assertion` the candidate "
    "business record it witnesses (or 'no record' explicitly), `evidence` the exact "
    "name/path/endpoint corroboration, `verdict` reuse-vs-coin against the known "
    "DataItems. Emit `claims` only; do not emit deltas yet."
)

_DATA_EXTRACT_TASK = (
    "TASK - EXTRACT THE DATA ITEMS. From the reasoning above, fill `data_items` and "
    "`surfaces_at` for every record it verified. For a record already listed above, "
    "REUSE its exact item_key and output the COMPOUNDED fields/notes (fold new insight "
    "in, never blank or merely restate); coin a new item_key only for a record no "
    "existing key covers. Reference a surface site as "
    '{"label": "Parameter"|"Header"|"Secret", "identity": {...the exact fields you '
    "discovered...}}. `fields` names ONLY fields you actually observed on the "
    "discovered surface - never a speculative attribute. Fold the adversarial insight "
    "into each item's `notes` as an adversarial CHARACTERISATION only - never a named "
    "payload, technique, or vector."
)

_FLOW_SHAPE_TASK = (
    "Emit one Claim per verified record's flow shape: `subject` the record, "
    "`assertion` the Surface site(s) and the producing/consuming Service, `evidence` "
    "the live Service inventory you chose the slugs from and the shared-surface "
    "relation, `verdict` the trust assumption predicate and any record-to-record "
    "relation. Emit `claims` only; do not emit deltas yet."
)

_FLOW_EXTRACT_TASK = (
    "TASK - EXTRACT THE FLOWS. From the shape above, fill `data_flows` "
    "(`service_slug` copied VERBATIM from the live Service inventory - any live "
    "Service may be named as producer or consumer) and `data_relationships` "
    "(the fixed allowlist `kind`, one of: "
    + ", ".join(k for k, _desc in DATA_RELATIONSHIP_KINDS)
    + ") for every relation the surface itself shows. Name what "
    "you WITHHELD and why, so withholding is the demonstrated conclusion."
)

WORKFLOW = ReasoningWorkflow(
    role_id=ROLE,
    sub_problems=(
        SubProblem(
            id="surface_survey",
            name="surface survey",
            prompt=(
                f"{_ROLE_HEADER}\n\nSURVEY - ORIENT, working DOWNWARD from the Service "
                "unit. Do not assume anything from an asset name, and do not wait for a "
                "pre-fed list: the unit (its slug, contract and already-aggregated "
                "Endpoints) is your only anchor, and you DISCOVER its surface yourself. "
                "Call `graph_view` with read-only Cypher (always a LIMIT): enumerate the "
                "Service's aggregated Endpoints, and for each Endpoint its Parameters, "
                "the Headers and Secrets on the BaseURL it lives on, and any existing "
                "DataItems already flowed to or from this Service. A path is the address "
                "you interrogate, never a place data appears. For each surface sighting, "
                "emit one Claim: `subject` the Service or the endpoint; `assertion` what "
                "the surface alone tells you (the concrete Parameters, Headers and "
                "Secrets you found, and their transport position); `evidence` the exact "
                "Cypher-returned identity; `verdict` whether this is a surface site that "
                "could witness a business record. A name that merely sounds like a record "
                "is not evidence yet; record the sighting, do not judge it here. Emit "
                "`claims` only."
            ),
            inject=("service", "inventory"),
            emit=("claims",),
        ),
        SubProblem(
            id="request_shapes",
            name="request shapes",
            prompt=(
                f"{_ROLE_HEADER}\n\nREAD SHAPES - read the RECORDED REQUEST SHAPES to "
                "the endpoints you surveyed in step 1 (the unit's aggregated Endpoints "
                "and any Endpoint you discovered). The survey names the inputs; the HTTP "
                "history shows how they are actually sent. Call "
                "`search_http_history` with a conjunctive filter over the request side "
                "(filter on `url` containing the endpoint path), then call "
                "`get_http_artifact` on the returned `artifact_id` to inspect one recorded "
                "transaction. Read the `request` object `{method, url, headers, cookies, "
                "query, form}`; body content is never visible and secret-bearing values "
                "are redacted, so the KEYS are what matter. For each request-shape "
                "observation, emit one Claim: `subject` the endpoint; `assertion` the "
                "request keys actually sent and their transport (query, form, header, "
                "cookie); `evidence` the `artifact_id` and the exact key names; `verdict` "
                "which mapped surface site the shape corroborates. A recorded request is a "
                "candidate, never a verification. Emit `claims` only."
            ),
            inject=("service", "surface_survey"),
            emit=("claims",),
            depends_on=("surface_survey",),
        ),
        SubProblem(
            id="insight_recall",
            name="insight recall",
            prompt=(
                f"{_ROLE_HEADER}\n\nRECALL - read the PRIOR MODELLING INSIGHTS from the "
                "notes store before you enrich. Call `notes` with command=\"read\" for "
                "this Service's unit slug, and again with a `body_keyword` for the "
                "modelling closures of other Services that may share a record or a flow. "
                "Reconcile what prior runs concluded against the surface you just "
                "surveyed: a prior `data` item that still fits is a REUSE target; a prior "
                "`open_question` the request shapes now answer is settled here; a prior "
                "insight the survey contradicts is named and set aside. For each prior "
                "insight you carry forward, emit one Claim: `subject` the prior item or "
                "question; `assertion` how the current survey confirms or corrects it; "
                "`evidence` the note key and the surface corroboration; `verdict` reuse, "
                "compound, or set aside. Emit `claims` only."
            ),
            inject=("service", "inventory", "services", "surface_survey", "request_shapes"),
            emit=("claims",),
            depends_on=("surface_survey", "request_shapes"),
        ),
        SubProblem(
            id="record_hypotheses",
            name="record hypotheses",
            prompt=(
                f"{_ROLE_HEADER}\n\n{cot_scaffold(_REFLECTION_STEPS[:3])}\n\n"
                f"{_RECORD_HYPOTHESES_TASK}"
            ),
            inject=(
                "inventory", "services", "observations",
                "surface_survey", "request_shapes", "insight_recall",
            ),
            emit=("claims",),
            depends_on=("surface_survey", "request_shapes", "insight_recall"),
        ),
        SubProblem(
            id="data_extract",
            name="data extract",
            prompt=(
                f"{_ROLE_HEADER}\n\n{cot_scaffold(_REFLECTION_STEPS[3:4])}\n\n"
                f"{_DATA_EXTRACT_TASK}"
            ),
            inject=("inventory", "services", "record_hypotheses"),
            emit=("data_items", "surfaces_at"),
            depends_on=("record_hypotheses",),
        ),
        SubProblem(
            id="flow_shape",
            name="flow shape",
            prompt=(
                f"{_ROLE_HEADER}\n\n{cot_scaffold(_REFLECTION_STEPS[4:5])}\n\n"
                f"{_FLOW_SHAPE_TASK}"
            ),
            inject=("inventory", "services", "record_hypotheses", "data_extract"),
            emit=("claims",),
            depends_on=("data_extract",),
        ),
        SubProblem(
            id="flow_extract",
            name="flow extract",
            prompt=(
                f"{_ROLE_HEADER}\n\n{cot_scaffold(_REFLECTION_STEPS[5:6])}\n\n"
                f"{_FLOW_EXTRACT_TASK}"
            ),
            inject=("inventory", "services", "data_extract", "flow_shape"),
            emit=("data_flows", "data_relationships"),
            depends_on=("flow_shape", "data_extract"),
        ),
        SubProblem(
            id="closure_note",
            name="modelling closure",
            prompt=(
                f"{_ROLE_HEADER}\n\nCLOSE - write the modelling-closure note for this "
                "Service. Call `notes` with command=\"write\", action=\"append\", unit = "
                "the Service slug, note_name=\"modelling-closure\", kind=\"data\", and a "
                "body summarising this enrichment. The body MUST name: the DataItems "
                "lifted and compounded (item_key, fields, anchors, flows); the records "
                "reused; what you WITHHELD or FALSIFIED and why; the recorded request "
                "shapes consulted; and any open question the surface left unresolved. "
                "Then emit one Claim: `subject` the Service; `assertion` the enrichment "
                "result; `evidence` the note key; `verdict` the residual open question or "
                "`resolved`. Emit `claims` only."
            ),
            inject=("service", "record_hypotheses", "data_extract", "flow_extract", "request_shapes"),
            emit=("claims",),
            depends_on=("flow_extract",),
        ),
    ),
)


def _service_slug(chunk: Chunk) -> str:
    """The unit's Service slug: `source_job`'s `service:` suffix, else the chunk id.
    Mirrors the assigner's `_unit_context_block` so both read the same unit key."""
    src = str(getattr(chunk, "source_job", "") or "")
    return src.removeprefix("service:") if src.startswith("service:") else str(chunk.chunk_id)


def _contracted_service(chunk: Chunk, inventory: dict | None) -> str:
    """The unit's non-empty `service_contract` (C-M2): a Service with a contract but
    no PRE-AGGREGATED surface still discovers its own."""
    contracts = (inventory or {}).get("service_contracts") or {}
    return str(contracts.get(_service_slug(chunk), "") or "") if isinstance(contracts, dict) else ""


def _discovered_sites(read_sites_fn, project_id: str | None) -> list:
    """The live graph-discovered sites the reference/observed gates resolve against
    (C-M1), filtered to the surface labels this role may ground on. Fail-open to the
    admitted chunk alone."""
    if read_sites_fn is None or not project_id:
        return []
    try:
        sites = read_sites_fn(project_id) or []
    except Exception:  # noqa: BLE001 - a read blip degrades to the chunk-only index
        logger.warning("data_modeller: discovered-sites read failed; using the chunk only",
                       exc_info=True)
        return []
    return [a for a in sites if a.type in _SURFACE_LABELS]


def _aggregated_endpoints_repr(chunk: Chunk, aggregations: list[dict] | None) -> str:
    """The Service's settled aggregated L0 Endpoints, one `METHOD /path (baseurl)` per
    entry; a hint to enumerate them with `graph_view` when none are settled. A
    starting point, never an asset-name filter."""
    slug = _service_slug(chunk)
    rows = [
        a for a in (aggregations or [])
        if a.get("slug") == slug and "Endpoint" in (a.get("labels") or [])
    ]
    if not rows:
        return "(none settled yet - enumerate them with `graph_view`)"
    lines = []
    for a in rows:
        p = a.get("props") or {}
        line = " ".join(
            part for part in (p.get("method", "?"), p.get("path") or p.get("url") or p)
            if part
        )
        if p.get("baseurl"):
            line = f"{line} ({p['baseurl']})"
        lines.append(line)
    return "; ".join(lines)


def _service_unit_block(
    chunk: Chunk, inventory: dict | None = None,
    aggregations: list[dict] | None = None,
) -> str:
    """The `service` base source: the ONE Service unit this workflow enriches - its
    slug, its `service_contract`, and the Endpoints it already aggregates.

    The whole settled surface is deliberately ABSENT: the model DISCOVERS its own
    surface through `graph_view` and the HTTP-history pair, driven by the unit
    (L1-unit-first). A thin KB gets a thin honest contract, and an orphan unit gets an
    empty aggregated list; both render explicitly rather than as a silently empty
    prompt."""
    slug = _service_slug(chunk)
    contracts = (inventory or {}).get("service_contracts") or {}
    contract = contracts.get(slug, "") if isinstance(contracts, dict) else ""
    return (
        f"SERVICE UNIT: {slug}\n"
        "This Service - not any asset name - is the reasoning anchor for the data "
        "plane. Its contract states what it does and owns; its already-aggregated "
        "Endpoints are a starting point, never a name filter.\n"
        f"contract: {contract or '(none)'}\n"
        f"aggregated endpoints: {_aggregated_endpoints_repr(chunk, aggregations)}"
    )


def _live_services_block(inventory: dict | None) -> str:
    """The `services` base source: the FULL live Service inventory (slug - contract),
    so a flow may name ANY live Service as producer/consumer - there is NO per-unit
    write scope. A `service_slug` outside this list is still dropped by the global
    validation gate."""
    inv = inventory or {}
    services = list(inv.get("services") or [])
    contracts = inv.get("service_contracts") or {}
    if not services:
        return "LIVE SERVICE INVENTORY: (none yet)"
    lines = [
        "LIVE SERVICE INVENTORY (name ANY of these as a producer/consumer; a slug "
        "not listed here names nothing and its flow is discarded):",
    ]
    for slug in services:
        note = (contracts or {}).get(slug)
        lines.append(f"- {slug} - {note}" if note else f"- {slug}")
    return "\n".join(lines)


def _known_items_block(inventory: dict | None) -> str:
    inv = inventory or {}
    items = inv.get("data_items") or []
    fields = inv.get("data_item_fields") or {}
    notes = inv.get("data_item_notes") or {}
    if not items:
        return "CURRENTLY-KNOWN DATAITEMS: (none yet)"
    lines = [
        "CURRENTLY-KNOWN DATAITEMS (reuse the EXACT item_key rather than coining a "
        "synonym; compound fields/notes on reuse - never blank them):",
    ]
    for key in items:
        extra = []
        f = fields.get(key) or []
        n = (notes.get(key) or "").strip()
        if f:
            extra.append(f"fields={list(f)}")
        if n:
            extra.append(f"notes: {n}")
        lines.append(f"- {key}" + (" :: " + "; ".join(extra) if extra else ""))
    return "\n".join(lines)


def _origin_observations_block(chunk: Chunk) -> str:
    """Origin-scoped adversarial insight (DPL-DEC-15): observations attach by
    ORIGIN, never per-asset - no Observation is ever anchored to a Parameter or a
    Header (the triager re-anchors up to the owning broad asset by design), so a
    per-asset pairing render would be vacuous by construction. Uniform, no
    text-matching refinement (operator-rejected, question 16)."""
    if not chunk.observations:
        return "ORIGIN-SCOPED ADVERSARIAL INSIGHT: (none)"
    lines = ["ORIGIN-SCOPED ADVERSARIAL INSIGHT (context for every surface site on that origin):"]
    for o in chunk.observations:
        anchor = o.anchor or {}
        lines.append(
            f"- [{anchor.get('type')} {anchor.get('identity')}] "
            f"{o.rationale or ''} ({o.evidence or ''})".strip()
        )
    return "\n".join(lines)


# --- system message: two layers (section 7.2) -----------------------------------

_ROLE_VERBATIM = (
    "You are the DataPlane Analyser (data_modeller) in an attack-surface analyser.\n"
    "ROLE - DATA MODELLING. You reason DOWN from the L1 Service unit you are given "
    "and DISCOVER its Parameter/Header/Secret surface through the tools, then judge "
    "which logical business records (DataItems) that surface evidences, where each one "
    "appears (`surfaces_at`), which Service produces/consumes it (`data_flows`), and "
    "shallow record-to-record dependencies (`data_relationships`). You emit these four "
    "lists and nothing else - never `services`, `systems`, `aggregates`, or "
    "`system_edges`.\n"
    "A DataItem is a business record BEHIND the surface (customer account, product "
    "listing, shopping basket, order, delivery address, payment method, coupon), NOT "
    "an endpoint or a parameter itself. A parameter that witnesses no business record "
    "(a pagination cursor, a CSRF token, a framework header) is correctly left alone.\n"
    "REFERENCING A SURFACE SITE: put the site in `surfaces_at.l0` as "
    '{"label": "Parameter"|"Header"|"Secret", "identity": {...exact fields you '
    'discovered...}}. NEVER reference an Endpoint - a path is the address you interrogate, '
    "never a place data appears.\n"
    "`fields` on a DataItem name ONLY fields you actually OBSERVED on the surface "
    "you discovered; never a speculative or merely-plausible field.\n"
    "`data_flows.service_slug` is copied VERBATIM from the live Service inventory you "
    "are given - any live Service may be named as producer or consumer; never a slug "
    "you invent.\n"
    "`data_relationships.kind` is one of the fixed allowlist; anything else is "
    "discarded.\n"
    "You never set provenance or write status; those are stamped by the system."
)

# The `baseline` fallback prompt arm. UNLIKE the Assigner's `baseline` (a
# byte-faithful reproduction of a legacy prompt), THIS ONE IS NOT byte-faithful
# to anything that ever shipped: the legacy `pod._data_modelling_prompt` took a
# whole-slice `assignment: L1DeltaBatch` argument and an Endpoint-target worked
# example the catalogue (section 5.1) now forbids, so no byte-faithful
# reproduction is constructible (DPL-DEC-17's honesty note). This arm
# APPROXIMATES the legacy shape's positive framing + one worked example, kept as
# a rollback lever only - never trust it as a tested prior arrangement.
_BASELINE_FEW_SHOTS = (
    "WORKED EXAMPLE (copy this shape, never the domain):\n"
    '  data_items: [{"item_key": "shopping_basket", "props": {"fields": ["ProductId", "quantity"], '
    '"notes": "client-supplied quantity and product reference"}}]\n'
    '  surfaces_at: [{"item_key": "shopping_basket", "l0": {"label": "Parameter", '
    '"identity": {"name": "quantity", "position": "query", "endpoint_path": "/api/basket", "baseurl": "<baseurl>"}}}]\n'
    '  data_flows: [{"service_slug": "cart", "item_key": "shopping_basket", "direction": "produces"}]\n'
    '  data_relationships: [{"from_item_key": "shopping_basket", "to_item_key": "product_listing", '
    '"kind": "derived_from", "rationale": "a basket line is derived from a listed product"}]'
)

# The data_modeller role prompt, selected by the active prompt variant
# (`prompt_variant.prompt_path`: `data-plane.md` for `legacy`,
# `data-plane-batched-l1unit-first.md` for the default), memoized PER VARIANT on
# first call (no import-time I/O, CODING STANDARD section 6). A missing prompt file
# is a defect: FAIL-CLOSED (raise).
_DATA_PLANE_SKILLS: dict[str, str] = {}


def _load_skill() -> str:
    """The data_modeller's HOW, read from the file the active prompt variant selects
    (DPL-DEC-16): memoized in-process PER VARIANT, FAIL-CLOSED on a missing file
    (raise). Every HARD invariant survives regardless, because
    narrow/resolve/validate/bind/ground are code."""
    variant = resolve_prompt_variant()
    cached = _DATA_PLANE_SKILLS.get(variant)
    if cached is None:
        cached = prompt_path("data_modeller", variant).read_text(encoding="utf-8")
        _DATA_PLANE_SKILLS[variant] = cached
    return cached


_DATA_MODELLER_PROMPT_CONFIGS = ("baseline", "skill")
_DEFAULT_DATA_MODELLER_PROMPT_CONFIG = "skill"


def _data_modeller_prompt_config() -> str:
    cfg = (os.environ.get("DATA_MODELLER_PROMPT_CONFIG") or _DEFAULT_DATA_MODELLER_PROMPT_CONFIG).strip()
    if cfg not in _DATA_MODELLER_PROMPT_CONFIGS:
        logger.warning(
            "DATA_MODELLER_PROMPT_CONFIG=%r is unknown (known: %s); using %r",
            cfg, ", ".join(_DATA_MODELLER_PROMPT_CONFIGS), _DEFAULT_DATA_MODELLER_PROMPT_CONFIG,
        )
        return _DEFAULT_DATA_MODELLER_PROMPT_CONFIG
    return cfg


def _system_prompt() -> str:
    if _data_modeller_prompt_config() == "skill":
        return f"{_ROLE_VERBATIM}\n\n{_load_skill()}"
    return f"{_ROLE_VERBATIM}\n\n{_BASELINE_FEW_SHOTS}"


# --- the injected LLM seam (typist's shape: prose | structured) ----------------

def _default_invoke_fn(messages, *, schema=None, system_prompt=None):
    """The legacy stateless call, retained for callers/tests on the one-shot seam: the
    analyser-role model behind the #73 escalating retry. `schema=None` returns free-text
    (the reflection call); a pydantic `schema` returns structured output. The role prompt
    is prepended here, exactly where the stateful seam's `system_prompt=` binding puts
    it. Production now uses `stateful_invoke_fn`."""
    from polymerhus.analysis.proposer_turn import prepend_prompt
    from polymerhus.app.llm.roles import invoke_role

    return invoke_role("analyser", prepend_prompt(messages, system_prompt), schema=schema)


def stateful_invoke_fn(run_id: str, checkpointer, project_id: str | None = None):
    """The STATEFUL data-modeller call (#94): the `data_modeller` role runs as a session
    resuming from its OWN per-run checkpoint (`AnalysisSession(run_id, "data_modeller")`, distinct from every other agent's), so its sub-problem
    chain and every chunk append to ONE growing context. Every turn goes through the
    one `AnalysisTurn` envelope. Same `(messages, *, schema)` shape as
    `_default_invoke_fn`. Structurally sync (sequential dispatch).

    The role prompt is bound ONCE as the agent's ephemeral leading block (the
    converged seam, `proposer_turn.session_invoke_fn`), so it is the stable prefix of
    every request and never accumulates in the checkpointed trail.

    Context-window compaction (#95 H/D9): the run's turns run COMPACTED - the
    analysis-side compaction middleware is built once per run and passed through
    `stateful_turn`, so an over-budget thread spawns out-of-band running-summary
    passes that the next turn's barrier awaits. Built fail-open: a missing role
    config degrades the profile/window, never the session."""
    from polymerhus.analysis.proposer_turn import session_invoke_fn

    return session_invoke_fn("data_modeller", run_id, checkpointer, project_id)


# --- the two-call proposer body (section 3/7.1) ---------------------------------

def model_data(
    chunk: Chunk, *, invoke_fn=None, inventory: dict | None = None,
    aggregations: list[dict] | None = None,
    read_sites_fn=None,
    memory: "AnalysisMemoryStore | None" = None, project_id: str | None = None,
    run_id: str | None = None,
) -> DataPlaneOutcome:
    """The A.1 data_modeller body: the `WORKFLOW` sub-problem chain (surface_survey
    -> request_shapes -> insight_recall -> record_hypotheses -> data_extract ->
    flow_shape -> flow_extract -> closure_note) -> the six ordered shaping gates,
    over one chunk.

    The prompt carries only the Service UNIT (its slug, `service_contract` and
    aggregated Endpoints), the known DataItems, the FULL live Service inventory and
    the origin-scoped insight; the model DISCOVERS its own surface through the tools
    (L1-unit-first). `existing_slugs` at the shaping seam is the full live inventory,
    so a flow may name ANY live Service - there is no per-unit write scope.

    The deterministic reference/observed gates resolve against the unit's admitted
    chunk UNION the live graph-discovered sites `read_sites_fn(project_id)` returns
    (C-M1): a site the model found only through `graph_view` can still ground an item.

    `invoke_fn(messages, *, schema, system_prompt) -> AnalysisTurn | None` is injected
    (unit-testable, no live LLM). FAIL-CLOSED on hypotheses exhaustion (empty outcome,
    `stats.reflection_exhausted=True`); empty on extraction exhaustion. Fail-open on
    any exception - never crashes the caller. An empty admission is a VALID empty
    result with NO LLM call - EXCEPT for a contracted Service with no pre-aggregated
    surface, which still DISCOVERS its own (C-M2; DPL-DEC precision-first: nothing to
    model is not a judgment to make, but discovery is the point)."""
    admitted = admit_for_role(chunk, ROLE)
    if not admitted and not _contracted_service(chunk, inventory):
        return DataPlaneOutcome()

    invoke_fn = invoke_fn or _default_invoke_fn
    system_prompt = _system_prompt()
    discovered = _discovered_sites(read_sites_fn, project_id)
    sites = [*admitted, *discovered]
    admitted_counts: dict[str, int] = defaultdict(int)
    for a in admitted:
        admitted_counts[a.type] += 1

    # The volatile base sources the workflow injects verbatim. The whole settled
    # surface is NOT a base source (L1-unit-first): the model DISCOVERS it through
    # the tools. Only the unit context, the known DataItems, the full live Service
    # inventory and the origin-scoped insight travel the prompt. `sites` still
    # feeds the deterministic gates (reference resolution, observed vocabulary).
    base_artifacts = {
        "service": _service_unit_block(chunk, inventory, aggregations),
        "inventory": _known_items_block(inventory),
        "services": _live_services_block(inventory),
        "observations": _origin_observations_block(chunk),
    }

    # Per-batch memory: the whole chain of ONE chunk shares a session (the batch
    # scope), so the reasoning is the extraction's context; the next chunk opens a
    # fresh thread. The scope is inert for the one-shot leg. The fail-closed gate
    # halts the chain when the hypotheses turn exhausts.
    from polymerhus.analysis.proposer_turn import proposer_batch
    from polymerhus.analysis.reasoning_workflow import AnalysisTurn, run_workflow, to_delta_batch

    try:
        with proposer_batch(chunk.chunk_id):
            run = run_workflow(
                WORKFLOW, invoke_fn=invoke_fn, system_prompt=system_prompt,
                base_artifacts=base_artifacts,
                halt_when=lambda sp, turn: sp.id == "record_hypotheses" and turn is None,
                unit_slug=_service_slug(chunk), memory=memory, project_id=project_id,
                run_id=run_id, note_kind="data",
            )
    except Exception:  # fail-open: LLM error -> empty outcome, never crash (DPL-DEC fail-open)
        logger.warning("data_modeller: workflow failed; degrading to empty outcome", exc_info=True)
        return DataPlaneOutcome()

    if run.turns.get("record_hypotheses") is None:
        logger.warning("data_modeller: hypotheses exhausted; fail-closed to empty outcome")
        return DataPlaneOutcome(stats=DataPlaneStats(
            admitted_parameters=admitted_counts.get("Parameter", 0),
            admitted_headers=admitted_counts.get("Header", 0),
            admitted_secrets=admitted_counts.get("Secret", 0),
            observations_attached=len(chunk.observations),
            reflection_exhausted=True,
        ))

    data_turn = run.turns.get("data_extract")
    flow_turn = run.turns.get("flow_extract")
    extraction_exhausted = data_turn is None and flow_turn is None
    raw = to_delta_batch(AnalysisTurn(
        data_items=list(data_turn.data_items) if data_turn is not None else [],
        surfaces_at=list(data_turn.surfaces_at) if data_turn is not None else [],
        data_flows=list(flow_turn.data_flows) if flow_turn is not None else [],
        data_relationships=list(flow_turn.data_relationships) if flow_turn is not None else [],
    ))

    inv = inventory or {}
    outcome = shape_proposal(
        raw,
        sites=site_index(sites),
        existing_slugs=frozenset(inv.get("services") or ()),
        known_items=frozenset(inv.get("data_items") or ()),
        observed_names=observed_vocabulary(sites),
        existing_fields=inv.get("data_item_fields") or {},
    )
    stats = outcome.stats.model_copy(update={
        "admitted_parameters": admitted_counts.get("Parameter", 0),
        "admitted_headers": admitted_counts.get("Header", 0),
        "admitted_secrets": admitted_counts.get("Secret", 0),
        "observations_attached": len(chunk.observations),
        "extraction_exhausted": extraction_exhausted,
    })
    outcome = outcome.model_copy(update={"stats": stats})
    logger.info(
        "data_modeller chunk=%s admitted=%d(p=%d h=%d s=%d) "
        "proposed(items=%d surfaces=%d flows=%d rels=%d) -> "
        "kept(items=%d surfaces=%d flows=%d rels=%d) "
        "(unknown_kind=%d unresolvable=%d out_of_inventory=%d fields_dropped=%d "
        "ungrounded=%d orphan=%d) backlog=%d",
        chunk.chunk_id, len(admitted), stats.admitted_parameters, stats.admitted_headers,
        stats.admitted_secrets, stats.proposed_items, stats.proposed_surfaces,
        stats.proposed_flows, stats.proposed_relationships, stats.kept_items,
        stats.kept_surfaces, stats.kept_flows, stats.kept_relationships,
        stats.unknown_kind_dropped, stats.unresolvable_surfaces, stats.out_of_inventory_flows,
        stats.fields_unobserved_dropped, stats.ungrounded_items_dropped,
        stats.orphan_relationships_dropped, len(outcome.backlog),
    )
    return outcome


# --- supervisor wiring (the proposer_bodies["data_modeller"] seam) -------------

def _default_read_inventory(project_id: str) -> dict:
    from polymerhus.analysis.l1_inventory import read_l1_inventory
    return read_l1_inventory(project_id)


def _default_read_aggregations(project_id: str) -> list[dict]:
    from polymerhus.analysis.l1_read import read_service_aggregations
    return read_service_aggregations(project_id)


def make_data_modeller_body(
    *, invoke_fn=None, inventory_fn=None, aggregations_fn=None, read_sites_fn=None,
    memory=None,
):
    """Adapt `model_data` to the supervisor's `ProposerBody` signature
    (`(dispatch, state) -> L1DeltaBatch | None`), a FACTORY binding every
    collaborator once (DPL-DEC-02, the Assigner's precedent - not the typist's
    `functools.partial` shape, so the dispatch-time reads stay explicit here).

    `memory` threads the per-unit analysis backstop into `run_workflow` (ADR D31);
    it is inert (None) on the streamed default. `read_sites_fn` is the C-M1
    live-identity seam; absent it, the gates resolve against the chunk alone.
    Returns `None` immediately when `dispatch.phase != "A1"` - the inert A.2 seam
    (DPL-DEC-23): A.2 is `designed-not-built`, never a silent half-implementation.
    Every read is guarded, so this body never raises regardless of what its
    collaborators do."""

    def body(dispatch, state) -> L1DeltaBatch | None:
        if getattr(dispatch, "phase", None) != "A1":
            return None
        chunk = getattr(dispatch, "chunk", None)
        if chunk is None:
            return None
        project_id = state.get("project_id", "")
        read_inventory = inventory_fn or _default_read_inventory
        read_aggregations = aggregations_fn or _default_read_aggregations
        try:
            inventory = read_inventory(project_id)
        except Exception:
            logger.warning("data_modeller: inventory read failed; modelling without it", exc_info=True)
            inventory = {}
        try:
            aggregations = read_aggregations(project_id)
        except Exception:
            logger.warning("data_modeller: aggregation read failed; no live Service context", exc_info=True)
            aggregations = []
        outcome = model_data(
            chunk, invoke_fn=invoke_fn, inventory=inventory, aggregations=aggregations,
            read_sites_fn=read_sites_fn,
            memory=memory, project_id=project_id or None,
            run_id=(state.get("run_id") or "").removeprefix("stream-") or None,
        )
        if outcome.backlog:
            logger.info("data_modeller: %d backlog description(s) not transported (DPL-DEC-22)", len(outcome.backlog))
        return outcome.batch

    return body
