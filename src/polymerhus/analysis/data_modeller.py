"""The DataPlane Analyser (agent spec #10, ratified `docs/design/dataplane-A1-decisions.md`
2026-07-30, realised by #48), the `data_modeller` A.1 proposer.

Sole owner of the Tier-1 data substrate: given a chunk of streamed surface, it
lifts the logical `DataItem`s that surface evidences, binds each to the concrete
L0 sites where it appears via `SURFACES_AT`, and maps the `PRODUCES`/`CONSUMES`
flows that connect those items to the settled Service model, plus the baseline
surface-observable DataItem-to-DataItem dependencies. It emits
`L1DeltaBatch{data_items, surfaces_at, data_flows, data_relationships}` and
nothing else - it does not assign Endpoints (the Assigner), type mechanisms (the
mechanism-typist), or mint Services.

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

from pydantic import BaseModel, ConfigDict, Field

from polymerhus.analysis.analyser_types import L1DeltaBatch
from polymerhus.analysis.chunking import Chunk, admit_for_role
from polymerhus.analysis.l1_types import L0Ref
from polymerhus.analysis.proposer_reasoning import cot_scaffold, role_header

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
    candidate_services: int = 0

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


def site_index(admitted) -> dict[tuple[str, str], dict]:
    """Index this chunk's admitted Parameter/Header/Secret assets by
    `(label, the-part-a-model-reliably-gets-right)`, for `resolve_surface_refs` to
    canonicalise against. Parameter/Header key on `name`; Secret keys on
    `value_hash` (its whole identity). First match wins on a name collision -
    ambiguity here is bounded by the chunk (<=100 assets), and the reflection
    scaffold's HYPOTHESISE step is where ambiguity is meant to be resolved, not
    this index."""
    index: dict[tuple[str, str], dict] = {}
    for a in admitted:
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
    names no site this chunk actually streamed.

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


# --- candidate owning Services (section 6) -------------------------------------

def _asset_ref(asset) -> str:
    ident = asset.identity or {}
    if asset.type == "Parameter":
        return f"Parameter:{ident.get('name')}@{ident.get('endpoint_path')}"
    if asset.type == "Header":
        return f"Header:{ident.get('name')}@{ident.get('baseurl')}"
    if asset.type == "Secret":
        return f"Secret:{ident.get('value_hash')}"
    return f"{asset.type}:{ident}"


def owning_services(admitted, aggregations: list[dict]) -> dict[str, list[str]]:
    """The candidate-owning-Service join (section 6): a Parameter joins on
    `endpoint_path` + `baseurl` against the live Service->Endpoint aggregation
    view; a Header/Secret has no endpoint in its identity, so it joins on
    `baseurl` alone (deliberately coarser - a response header is origin-scoped
    rather than endpoint-scoped, and pretending otherwise would manufacture
    precision the surface does not carry). `aggregations` is
    `l1_read.read_service_aggregations`'s live view; only rows whose L0 labels
    include `Endpoint` participate."""
    by_endpoint: dict[tuple, set[str]] = defaultdict(set)
    by_baseurl: dict[str, set[str]] = defaultdict(set)
    for row in aggregations:
        slug = row.get("slug")
        labels = row.get("labels") or []
        if not slug or "Endpoint" not in labels:
            continue
        props = row.get("props") or {}
        path, baseurl = props.get("path"), props.get("baseurl")
        if path and baseurl:
            by_endpoint[(path, baseurl)].add(slug)
        if baseurl:
            by_baseurl[baseurl].add(slug)

    out: dict[str, list[str]] = {}
    for a in admitted:
        ident = a.identity or {}
        ref = _asset_ref(a)
        if a.type == "Parameter":
            key = (ident.get("endpoint_path"), ident.get("baseurl"))
            out[ref] = sorted(by_endpoint.get(key, ()))
        elif a.type in ("Header", "Secret"):
            out[ref] = sorted(by_baseurl.get(ident.get("baseurl"), ()))
    return out


def observed_vocabulary(admitted) -> frozenset[str]:
    """The names this chunk could actually have observed (section 5.3): the
    `name` of every admitted Parameter/Header, plus any non-identity keys those
    (and Secret) assets carry in `props`."""
    names: set[str] = set()
    for a in admitted:
        ident = a.identity or {}
        if a.type in ("Parameter", "Header") and ident.get("name") is not None:
            names.add(str(ident["name"]))
        for k in (a.props or {}):
            names.add(str(k))
    return frozenset(names)


# --- the hypothesis-driven reflection scaffold (section 7.3) -------------------

_REFLECTION_STEPS = [
    "ORIENT: read each admitted Parameter/Header/Secret together with the endpoint "
    "path it hangs off (where it has one) and the origin-scoped adversarial insight; "
    "say what the surface alone tells you before you look at the known DataItems.",
    "HYPOTHESISE (define-hypothesis): for each admitted name, state candidate "
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
    "service slugs ONLY from the candidate list you were given), Trust (for a "
    "consumes whose producing Service differs from the consumer, state the "
    "falsifiable predicate the consumer holds about that data, in one surface-"
    "readable sentence), Relate (only where the surface itself shows it, state a "
    "record-to-record dependency using one of the allowed kinds, with a shallow "
    "predicate).",
    "EMIT / WITHHOLD: report the verified records. Name what you FALSIFIED and why "
    "- a pagination cursor, a CSRF token, a framework header - so withholding is the "
    "loop's demonstrated conclusion, not an assumed default.",
]


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


def _candidates_render(candidates: dict[str, list[str]]) -> str:
    if not candidates:
        return "  (no admitted surface)"
    lines = []
    for ref, slugs in candidates.items():
        lines.append(f"  - {ref}: {slugs if slugs else '(no candidate owner)'}")
    return "\n".join(lines)


def _admitted_render(admitted) -> str:
    lines = []
    for a in admitted:
        line = f"- {a.type} {dict(a.identity or {})}"
        if a.props:
            line += f" props={dict(a.props)}"
        lines.append(line)
    return "\n".join(lines) or "(none)"


def _origin_observations_block(chunk: Chunk) -> str:
    """Origin-scoped adversarial insight (DPL-DEC-15): observations attach by
    ORIGIN, never per-asset - no Observation is ever anchored to a Parameter or a
    Header (the triager re-anchors up to the owning broad asset by design), so a
    per-asset pairing render would be vacuous by construction. Uniform, no
    text-matching refinement (operator-rejected, question 16)."""
    if not chunk.observations:
        return "ORIGIN-SCOPED ADVERSARIAL INSIGHT: (none)"
    lines = ["ORIGIN-SCOPED ADVERSARIAL INSIGHT (context for every admitted asset on that origin):"]
    for o in chunk.observations:
        anchor = o.anchor or {}
        lines.append(
            f"- [{anchor.get('type')} {anchor.get('identity')}] "
            f"{o.rationale or ''} ({o.evidence or ''})".strip()
        )
    return "\n".join(lines)


def _reflection_prompt(chunk: Chunk, inventory: dict | None, candidates: dict) -> str:
    admitted = admit_for_role(chunk, ROLE)
    return (
        f"{role_header('the DataPlane Analyser (data_modeller)', 'lift the Tier-1 logical DataItems this streamed surface evidences, bind them to the surface, and ground their flows onto the settled Service model')}\n\n"
        f"{_known_items_block(inventory)}\n\n"
        "CANDIDATE OWNING SERVICES (the only valid data_flows.service_slug values; a "
        "Header/Secret join is origin-coarse, stated for that reason):\n"
        f"{_candidates_render(candidates)}\n\n"
        "STREAMED SURFACE (Parameter/Header/Secret only - never an Endpoint, a path is "
        "an address, not a place data appears):\n"
        f"{_admitted_render(admitted)}\n\n"
        f"{_origin_observations_block(chunk)}\n\n"
        f"{cot_scaffold(_REFLECTION_STEPS)}\n\n"
        "Write your reasoning as prose. Do not emit JSON or a tool call in this step."
    )


def _extraction_prompt(prose: str, inventory: dict | None, candidates: dict) -> str:
    return (
        f"{_known_items_block(inventory)}\n\n"
        "CANDIDATE OWNING SERVICES (copy `data_flows.service_slug` VERBATIM from these):\n"
        f"{_candidates_render(candidates)}\n\n"
        "Your reflection:\n"
        f"{prose}\n\n"
        # POSITIVE framing (DPL-DEC-18): the legacy single data call returned ZERO
        # data_items under a "leave the other lists EMPTY" litany; state what to
        # FILL and that empty is wrong when a record was verified.
        "TASK - EXTRACT THE DATA PLANE. Your reflection above verified specific "
        "business records, their surface sites, and their flows. Fill FOUR lists: "
        "`data_items`, `surfaces_at`, `data_flows`, `data_relationships` for every "
        "record your reflection verified - an empty result here is wrong whenever "
        "your reflection named a record. For a record already listed above, REUSE "
        "its exact item_key and output the COMPOUNDED fields/notes (fold new insight "
        "in, never blank or merely restate); coin a new item_key only for a record no "
        "existing key covers. Reference a surface site as "
        '{"label": "Parameter"|"Header"|"Secret", "identity": {...the exact fields shown '
        "above...}}. `fields` names ONLY fields you actually observed on the surface "
        "above - never a speculative attribute. Fold the adversarial insight into each "
        "item's `notes` as an adversarial CHARACTERISATION only - never a named "
        "payload, technique, or vector."
    )


# --- system message: two layers (section 7.2) -----------------------------------

_ROLE_VERBATIM = (
    "You are the DataPlane Analyser (data_modeller) in an attack-surface analyser.\n"
    "ROLE - DATA MODELLING. You judge which logical business records (DataItems) the "
    "streamed Parameter/Header/Secret surface evidences, where each one appears "
    "(`surfaces_at`), which Service produces/consumes it (`data_flows`), and shallow "
    "record-to-record dependencies (`data_relationships`). You emit these four lists "
    "and nothing else - never `services`, `systems`, `aggregates`, or `system_edges`.\n"
    "A DataItem is a business record BEHIND the surface (customer account, product "
    "listing, shopping basket, order, delivery address, payment method, coupon), NOT "
    "an endpoint or a parameter itself. A parameter that witnesses no business record "
    "(a pagination cursor, a CSRF token, a framework header) is correctly left alone.\n"
    "REFERENCING A SURFACE SITE: put the site in `surfaces_at.l0` as "
    '{"label": "Parameter"|"Header"|"Secret", "identity": {...exact fields shown to '
    'you...}}. NEVER reference an Endpoint - a path is the address you interrogate, '
    "never a place data appears.\n"
    "`fields` on a DataItem name ONLY fields you actually OBSERVED on the surface "
    "shown to you; never a speculative or merely-plausible field.\n"
    "`data_flows.service_slug` is copied VERBATIM from the candidate owning-Services "
    "list you are given - never a slug you invent.\n"
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

_DATA_PLANE_SKILL_FALLBACK = (
    "Begin every judgment from NO RECORD and make the evidence overturn it. For each "
    "admitted name hold more than one candidate business record before committing, "
    "and always state the null hypothesis - 'this witnesses no business record' - "
    "explicitly. A name that merely sounds like a record with no path or field "
    "corroboration is topical proximity, not evidence. Reuse an existing item_key "
    "before coining a new one. `fields` name ONLY what you observed; never a "
    "plausible-but-unseen attribute. A `surfaces_at` reference is REQUIRED for every "
    "new item - a data_flow alone never grounds a lift, because a path is an address, "
    "never a place data appears. Fold adversarial insight into `notes` as a "
    "characterisation only - no named payload, technique, or vector."
)


def _load_skill() -> str:
    """The data_modeller's HOW, single-sourced from
    `skills/analysis/data-plane/SKILL.md` (DPL-DEC-16), degraded to the terse
    fallback above when the mount is unavailable (`loop-constraints.md`: a skill
    error degrades, never crashes). Every HARD invariant survives a missing mount
    regardless, because narrow/resolve/validate/bind/ground are code."""
    from polymerhus.recon.domain.skills import skill_for

    return skill_for("analysis/data-plane", fallback=_DATA_PLANE_SKILL_FALLBACK)


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

def _default_invoke_fn(messages, *, schema=None):
    """Real collaborator: the analyser-role model behind the single coherent
    escalating retry (#73). `schema=None` returns free-text content (the reflection
    call); a pydantic `schema` returns structured output via function_calling (the
    extraction call). Same model as the assigner/typist."""
    from polymerhus.app.llm.roles import invoke_role

    return invoke_role("analyser", messages, schema=schema)


# --- the two-call proposer body (section 3/7.1) ---------------------------------

def model_data(
    chunk: Chunk, *, invoke_fn=None, inventory: dict | None = None,
    aggregations: list[dict] | None = None,
) -> DataPlaneOutcome:
    """The A.1 data_modeller body: reflection (free prose) -> ONE structured
    extraction call -> the six ordered shaping gates, over one chunk.

    `invoke_fn(messages, *, schema) -> str | L1DeltaBatch | None` is injected
    (unit-testable, no live LLM). FAIL-CLOSED on reflection exhaustion (empty
    outcome, `stats.reflection_exhausted=True`); empty on extraction exhaustion.
    Fail-open on any exception - never crashes the caller. An empty admission is a
    VALID empty result with NO LLM call (DPL-DEC precision-first: nothing to model
    is not a judgment to make)."""
    from langchain_core.messages import HumanMessage, SystemMessage

    admitted = admit_for_role(chunk, ROLE)
    if not admitted:
        return DataPlaneOutcome()

    invoke_fn = invoke_fn or _default_invoke_fn
    system_prompt = _system_prompt()
    candidates = owning_services(admitted, aggregations or [])

    prose = invoke_fn(
        [SystemMessage(content=system_prompt),
         HumanMessage(content=_reflection_prompt(chunk, inventory, candidates))],
        schema=None,
    )
    admitted_counts: dict[str, int] = defaultdict(int)
    for a in admitted:
        admitted_counts[a.type] += 1
    candidate_slugs = {slug for slugs in candidates.values() for slug in slugs}

    if not prose:
        logger.warning("data_modeller: reflection exhausted; fail-closed to empty outcome")
        return DataPlaneOutcome(stats=DataPlaneStats(
            admitted_parameters=admitted_counts.get("Parameter", 0),
            admitted_headers=admitted_counts.get("Header", 0),
            admitted_secrets=admitted_counts.get("Secret", 0),
            observations_attached=len(chunk.observations),
            candidate_services=len(candidate_slugs),
            reflection_exhausted=True,
        ))

    raw = invoke_fn(
        [SystemMessage(content=system_prompt),
         HumanMessage(content=_extraction_prompt(prose, inventory, candidates))],
        schema=L1DeltaBatch,
    )
    extraction_exhausted = raw is None
    raw = raw or L1DeltaBatch()

    inv = inventory or {}
    outcome = shape_proposal(
        raw,
        sites=site_index(admitted),
        existing_slugs=frozenset(inv.get("services") or ()),
        known_items=frozenset(inv.get("data_items") or ()),
        observed_names=observed_vocabulary(admitted),
        existing_fields=inv.get("data_item_fields") or {},
    )
    stats = outcome.stats.model_copy(update={
        "admitted_parameters": admitted_counts.get("Parameter", 0),
        "admitted_headers": admitted_counts.get("Header", 0),
        "admitted_secrets": admitted_counts.get("Secret", 0),
        "observations_attached": len(chunk.observations),
        "candidate_services": len(candidate_slugs),
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


def make_data_modeller_body(*, invoke_fn=None, inventory_fn=None, aggregations_fn=None):
    """Adapt `model_data` to the supervisor's `ProposerBody` signature
    (`(dispatch, state) -> L1DeltaBatch | None`), a FACTORY binding every
    collaborator once (DPL-DEC-02, the Assigner's precedent - not the typist's
    `functools.partial` shape, so the dispatch-time reads stay explicit here).

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
            logger.warning("data_modeller: aggregation read failed; no candidate owners", exc_info=True)
            aggregations = []
        outcome = model_data(chunk, invoke_fn=invoke_fn, inventory=inventory, aggregations=aggregations)
        if outcome.backlog:
            logger.info("data_modeller: %d backlog description(s) not transported (DPL-DEC-22)", len(outcome.backlog))
        return outcome.batch

    return body
