"""The TechnicalSystem Analyser (agent spec #9), realising #20 increment 2b's
mechanism-typing proposer slice.

Sole owner of MECHANISM TYPING: it defines/extends the cross-cutting `System`s the
target lies on and links them to Services as typed `Service->System` edges - NEVER
as Service props (the mechanism-as-System correction). BREADTH-ONLY (grilled #9):
it emits `L1DeltaBatch{systems, system_edges}`; all System DEEPENING (WebPresentation
rendering/navigation, authz inverse-pyramid, backward-recon probes, the AnatomyResult
triple) is Phase B (epic #39; deepening #41; System under-typing #40).

Algorithm (T2, `batched-l1unit-first-adr.md`) - EIGHT sequential sub-problems over
one unit, a Service OR a System (`service_slice.build_service_slices` appends
both), each turn speaking the ONE `AnalysisTurn` envelope:

  1. `orient_from_catalog` - read the RDF catalog, the bootstrapped Systems, and
     the unit; state the mechanism landscape.
  2. `harvest_surface` - DISCOVER the unit's surface through `graph_view` and the
     bound HTTP-history pair, driven by the unit identifier/description.
  3. `prior_insights` - read the notes store.
  4. `mechanism_hypotheses` - the direction-dependent central question (a Service
     unit asks forward, a System unit in reverse). Exhaustion here fails the step
     CLOSED (the chain halts).
  5. `page_clusters` - group the navigable `text/html` pages by rendered similarity.
  6. `systems_extract` - VERIFY/FALSIFY then emit the `systems` deltas (new/extended,
     each carrying a COMPOUNDED NL `description` prop). Soft pass-through on
     exhaustion.
  7. `link` - EMIT the `system_edges` against any live Service that rides the System.
     Soft pass-through on exhaustion.
  8. `closure` - write the `system` modelling-closure note.

Standalone + injected `invoke_fn` / reads (unit-testable, no live LLM/graph); the body
matches the `supervisor.ProposerBody` protocol EXACTLY (like the Assigner) - it is
register-ready in `proposer_bodies["mechanism_typist"]`. Fail-open throughout.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING

from polymerhus.analysis.analyser_types import L1DeltaBatch
from polymerhus.analysis.chunking import Chunk
from polymerhus.analysis.prompt_variant import prompt_path, resolve_prompt_variant
from polymerhus.analysis.proposer_reasoning import cot_scaffold, role_header
from polymerhus.analysis.reasoning_workflow import ReasoningWorkflow, SubProblem

if TYPE_CHECKING:
    from polymerhus.analysis.memory import AnalysisMemoryStore

logger = logging.getLogger(__name__)

_SINGLETON = "__singleton__"

# The hypothesis-driven reflection scaffold (grilled #9), re-parametrised for the
# L1-unit-first mechanism-typist: the numbered process the reason turns work THROUGH
# out loud, synthesising overthink (staged reasoning), critical-thinking
# (claim/evidence/assumption/fallacy) and define/debug-hypothesis. It reasons FROM
# the unit and the RDF catalog, then discovers and verifies against the graph.
_REFLECTION_STEPS = [
    "ORIENT: read the RDF catalog (the System kinds and the System-edge rels) and the "
    "currently-defined Systems, then read the UNIT subject itself (its identifier, its "
    "kind, and its description). State the mechanism landscape this unit could sit in - "
    "which kinds are even plausible here, and which are ruled out - before touching any "
    "asset.",
    "HYPOTHESISE: from the contract (Service unit) or the overlay (System unit) define "
    "candidate hypotheses of the form 'this unit relies on a System of kind K - "
    "newly-defined, OR extending currently-defined System X' (Service direction), or "
    "'this System overlays Service S via rel R' (System direction). Hold more than one "
    "candidate kind for an ambiguous unit.",
    "CLUSTER PAGES (WebPresentation): among the NAVIGABLE text/html pages only (content_type "
    "text/html; exclude API/XHR/JSON responses and static assets), group them by rendered "
    "similarity (shared title/structure/size) into page CLUSTERS - a templated set (e.g. many "
    "product pages) or a single not-found/error page is ONE cluster, not many. Note which "
    "service each cluster serves; each (service, cluster) is one WebPresentation.",
    "VERIFY / FALSIFY: test each hypothesis against the evidence actually present in the "
    "graph and the recorded HTTP history. A framework fingerprint alone is NOT the "
    "mechanism-in-use; separate the claim from its support; decide new-vs-extend against "
    "the currently-defined Systems listed.",
    "INTEGRATE the adversarial observation insight into the surviving System's "
    "characterisation - what makes that mechanism attackable.",
    "EMIT a prose delta overview: the verified NEW and EXTENDED Systems and their "
    "adversarial characterisations, and the Service->System edges you can ground. Do NOT "
    "deep-profile (no rendering/navigation model, no authorization pyramid) - that is a "
    "later phase.",
]


# --- pure shaping (input value in, narrowed/validated batch out; no I/O) -------

def narrow_to_typing(batch: L1DeltaBatch) -> L1DeltaBatch:
    """The mechanism-typist owns ONLY `{systems, system_edges}` (mirrors
    `assigner.narrow_to_assignment` from the other side of the `service` chunk):
    drop the assignment lists (-> Assigner) and every data list (-> Data-modeller)."""
    return batch.model_copy(update={
        "services": [], "aggregates": [],
        "data_items": [], "surfaces_at": [], "data_flows": [], "data_relationships": [],
    })


def drop_unknown_vocabulary(
    batch: L1DeltaBatch, *, kinds: frozenset[str], rels: frozenset[str]
) -> L1DeltaBatch:
    """Keep only Systems whose `kind` is known and edges whose `rel` AND `kind` are
    known. The sole-writer would reject an unknown value anyway (rel/kind are
    interpolated into Cypher), but shaping it out HERE means the proposer emits only
    values the writer accepts, never relying on the guard."""
    systems = [s for s in batch.systems if s.kind in kinds]
    edges = [e for e in batch.system_edges if e.rel in rels and e.kind in kinds]
    return batch.model_copy(update={"systems": systems, "system_edges": edges})


def _merge_systems(primary, fallback):
    """Merge System proposals from the extraction call (primary - richer descriptions)
    with any the LINKING call CO-PRODUCED (fallback). The model naturally emits
    systems+edges together in the linking step, so a System it names there must be
    CAPTURED, never discarded (observed live: extraction=0 systems, linking co-produced
    5 well-described ones that were being thrown away). Keyed by (kind, discriminator);
    primary wins, but a fallback fills a missing key OR supplies a description the
    primary left blank."""
    out: dict = {}
    for s in primary:
        out[(s.kind, s.discriminator)] = s
    for s in fallback:
        k = (s.kind, s.discriminator)
        if k not in out:
            out[k] = s
        elif not (out[k].props or {}).get("description") and (s.props or {}).get("description"):
            out[k] = s
    return list(out.values())


def _reconcile_webpresentation(systems: list, edges: list) -> tuple[list, list]:
    """Deterministically enforce the two #53 invariants a two-call typist cannot -
    WebPresentation UNIQUENESS and coherent service-LINKING - and return the repaired
    (systems, edges).

    The fault (moodique 6c21005b): the SYSTEMS call emits the ratified per-cluster node
    (`<service>::<cluster>`, with `pages`) while the LINKING call independently re-describes
    the same presentation at the DEFAULT `__singleton__` discriminator and points its edge
    THERE - the 'copy the discriminator VERBATIM' prompt instruction is unreliable across two
    separate structured calls. `_merge_systems` keys on (kind, discriminator), so the singleton
    survives as a DUPLICATE and the real per-cluster node is left ORPHANED (the edge hangs off
    the singleton). Per the #53 model a WebPresentation is ALWAYS per (service, cluster), so a
    `__singleton__` WebPresentation is never a legitimate node when a discriminated one exists.

    Repair (only when >=1 discriminated WebPresentation exists - otherwise the batch under-
    clustered, a separate A.2 concern, and is left untouched):
      * DROP every `__singleton__` WebPresentation system (uniqueness); its description is a
        re-statement of a discriminated node's.
      * SNAP every WebPresentation edge whose discriminator is `__singleton__`/blank/unknown to
        the discriminated node of its OWN service - matched by the `<service_slug>::` prefix the
        discriminator is defined on - but ONLY when exactly one such node exists (an unambiguous
        single-cluster service). A multi-cluster service whose edge already names a real cluster
        is left as the LLM wrote it; an ambiguous singleton edge is left for A.2 rather than
        guessed."""
    disc_wp = [s for s in systems
               if s.kind == "WebPresentation" and (s.discriminator or _SINGLETON) != _SINGLETON]
    if not disc_wp:
        return systems, edges
    known_disc = {s.discriminator for s in disc_wp}
    # by owning service (the discriminator is '<service_slug>::<cluster>')
    by_service: dict[str, list[str]] = defaultdict(list)
    for d in known_disc:
        by_service[d.split("::", 1)[0]].append(d)

    kept_systems = [s for s in systems
                    if not (s.kind == "WebPresentation" and (s.discriminator or _SINGLETON) == _SINGLETON)]

    repaired_edges = []
    for e in edges:
        if e.kind == "WebPresentation":
            update: dict = {}
            # snap a singleton/blank/unknown discriminator onto the real per-cluster node of
            # the SAME service (unambiguous single-cluster service only).
            if (e.discriminator or _SINGLETON) not in known_disc:
                candidates = by_service.get(e.service_slug, [])
                if len(candidates) == 1:
                    update["discriminator"] = candidates[0]
            # a WebPresentation is the channel a service is EXPOSED_VIA, never a perimeter
            # FRONTED_BY / ROUTED_BY / PROTECTED_BY it: the linking call sometimes mislabels the
            # rel (observed live: FRONTED_BY), so coerce it - the node is a presentation surface,
            # not an intermediary. Keeps the edge SEMANTICS robust to the second call's wording.
            if e.rel != "EXPOSED_VIA":
                update["rel"] = "EXPOSED_VIA"
            if update:
                e = e.model_copy(update=update)
        repaired_edges.append(e)
    return kept_systems, repaired_edges


def _system_key(kind: str, discriminator: str | None) -> str:
    """Render a System identity the way `read_l1_inventory._render_system` does:
    `kind` for a singleton, else `kind:disc` - so a key computed here matches the
    inventory's `systems` list (the first-definer test, ADR D19)."""
    from polymerhus.analysis.l1_types import elide_singleton

    disc = elide_singleton(discriminator)
    return f"{kind}:{disc}" if disc else kind


def strip_recompounded_descriptions(
    batch: L1DeltaBatch, *, existing_keys: frozenset[str]
) -> L1DeltaBatch:
    """The first-definer compounding rule (ADR D19): only the Service that FIRST
    defines a System compounds its `description`; later Services never re-compound
    it. A System already present in the live inventory was defined by an earlier
    Service (or an earlier run), so this Service must not overwrite its
    description - the description prop is dropped from the emitted batch, and the
    writer's `SET += props` then leaves the existing description intact. A System
    that is NOT yet defined (this Service is its first definer) keeps its
    description, so the one authorised compounding still happens. Inert on the
    streamed default (`existing_keys` empty)."""
    if not existing_keys:
        return batch
    out = []
    for system in batch.systems:
        key = _system_key(system.kind, system.discriminator)
        if key in existing_keys and (system.props or {}).get("description"):
            props = dict(system.props)
            props.pop("description", None)
            system = system.model_copy(update={"props": props})
        out.append(system)
    return batch.model_copy(update={"systems": out})


def _known_kinds() -> frozenset[str]:
    from polymerhus.analysis.l1_curator import _KNOWN_KINDS
    return _KNOWN_KINDS


def _known_rels() -> frozenset[str]:
    from polymerhus.analysis.l1_curator import SYSTEM_EDGE_RELS
    return SYSTEM_EDGE_RELS


# --- primary/secondary service partition (linking context, grilled #9 Q3) ------

def _identity_matches(asset, agg: dict) -> bool:
    """True when an AGGREGATES row `agg` (an L0 node this Service aggregates) is the
    chunk `asset`: same L0 label AND every identity key/value of the asset present on
    the L0 node's props. A bounded subset-match (no reconstructed L0 key)."""
    if asset.type not in (agg.get("labels") or []):
        return False
    props = agg.get("props") or {}
    return all(str(props.get(k)) == str(v) for k, v in (asset.identity or {}).items())


def partition_services(
    chunk_assets, aggregations: list[dict], all_services: frozenset[str]
) -> tuple[list[str], list[str], dict[str, list[str]]]:
    """Split the linking candidates (grilled #9): PRIMARY = services that aggregate any
    of THIS chunk's assets (with the assets each aggregates, as linking evidence);
    SECONDARY = other services that have >=1 aggregated L0 asset (asset-less services
    are excluded - no surface to hang a System off). `aggregations` is the live
    Service->L0 aggregation view; `all_services` bounds it to known Services."""
    primary: set[str] = set()
    owned: dict[str, list[str]] = defaultdict(list)
    services_with_assets: set[str] = set()
    for agg in aggregations:
        slug = agg.get("slug")
        if not slug:
            continue
        services_with_assets.add(slug)
        for asset in chunk_assets:
            if _identity_matches(asset, agg):
                primary.add(slug)
                ref = _asset_ref(asset)
                if ref not in owned[slug]:
                    owned[slug].append(ref)
                break
    secondary = (services_with_assets & set(all_services)) - primary
    return sorted(primary), sorted(secondary), {k: owned[k] for k in sorted(owned)}


def _asset_ref(asset) -> str:
    ident = asset.identity or {}
    ref = ident.get("path") or ident.get("url") or ident.get("name") or ident.get("baseurl")
    return f"{asset.type}:{ref}" if ref else asset.type


# --- prompt construction ------------------------------------------------------

# Non-identity props that are pipeline plumbing, not adversarial evidence: kept off
# the prompt so the surface stays no-noise. Everything else on the props bag (an
# Endpoint's content_type/title/status_code/server/content_length, a Technology's
# categories, ...) IS discriminative and must reach the typist.
_PROMPT_NOISE_PROPS = frozenset({"profile", "source"})


def _asset_props_summary(props: dict) -> str:
    """The asset's non-identity props that CARRY mechanism-typing signal (grilled #9
    fix): the mechanism a path evidences is discriminated by what it actually SERVES -
    content_type, title, status_code, server - NOT by its path string alone. Rendering
    only the identity made the typist infer a System's kind from path nouns (an
    assumption, not evidence): an API-looking path returning `text/html` is a
    client-routed web-presentation view, indistinguishable from a REST endpoint once
    content_type is dropped. Pipeline plumbing is filtered out to keep the prompt
    no-noise; the keys are sorted for a deterministic prompt."""
    meaningful = {k: v for k, v in (props or {}).items() if k not in _PROMPT_NOISE_PROPS}
    return ", ".join(f"{k}={v}" for k, v in sorted(meaningful.items()))


def _asset_observation_paragraphs(chunk: Chunk) -> str:
    """Render each streamed asset paired with its triager observation INSIGHT as a
    paragraph (grilled #9 Q4): the adversarial NLP layer that drives System typing
    rides beside the asset it anchors to. Observations already travel on the chunk.

    An observation is NEVER anchored to an Endpoint/Header/Parameter: the triager
    re-anchors UP to the owning broad asset and the curator's ANCHOR_ALLOWLIST
    ({Domain, Subdomain, BaseURL, IP, Service}) silently drops any narrow anchor.
    So a narrow asset's insight is looked up on its PARENT broad anchor (via the
    curator's pure `broaden_anchor`, e.g. Endpoint -> its BaseURL) AS WELL AS on the
    asset itself - otherwise the exact (type, identity) match can never connect an
    Endpoint to its BaseURL-anchored insight and the block is silently empty."""
    from polymerhus.recon.domain.curator import broaden_anchor

    by_anchor: dict[tuple, list] = defaultdict(list)
    for o in chunk.observations:
        anchor = o.anchor or {}
        by_anchor[(anchor.get("type"), _idkey(anchor.get("identity") or {}))].append(o)
    paras: list[str] = []
    for a in chunk.assets:
        lookups = [(a.type, _idkey(a.identity or {}))]
        parent = broaden_anchor({"type": a.type, "identity": a.identity or {}})
        if parent:
            lookups.append((parent["type"], _idkey(parent["identity"])))
        seen: set[int] = set()
        insights: list = []
        for k in lookups:
            for o in by_anchor.get(k, []):
                if id(o) not in seen:  # an obs matched by both exact + parent lookup shows once
                    seen.add(id(o))
                    insights.append(o)
        head = f"- {a.type} {dict(a.identity or {})}"
        summary = _asset_props_summary(a.props)
        if summary:
            head = f"{head} [{summary}]"
        if insights:
            joined = "; ".join(f"{o.rationale or ''} ({o.evidence or ''})".strip() for o in insights)
            paras.append(f"{head}\n  adversarial insight: {joined}")
        else:
            paras.append(head)
    return "\n".join(paras) or "(no assets)"


def _idkey(identity: dict) -> tuple:
    return tuple(sorted((k, str(v)) for k, v in (identity or {}).items()))


def _defined_systems_block(inventory: dict | None) -> str:
    """The currently-defined Systems WITH their descriptions (grilled #9 Q3/Q7): the
    discriminative context for the new-vs-extend decision and description compounding.
    `system_descriptions` is the additive map `read_l1_inventory` now returns.

    The LIVE Service inventory is appended (T2): the System direction links an overlay
    to the Services that ride it, so the bootstrapped Service slug list is part of the
    unit-first context, not a separate source."""
    inv = inventory or {}
    systems = inv.get("systems") or []
    descs = inv.get("system_descriptions") or {}
    services = inv.get("services") or []
    if not systems:
        systems_lines = ["CURRENTLY-DEFINED SYSTEMS: (none yet)"]
    else:
        systems_lines = [
            "CURRENTLY-DEFINED SYSTEMS (extend these by their EXACT key; enrich - never blank - a description):"]
        for s in systems:
            d = (descs.get(s) or "").strip()
            systems_lines.append(f"- {s}" + (f" :: {d}" if d else ""))
    services_line = (
        "LIVE SERVICES (link to ANY of these - no per-unit scope): "
        + (", ".join(services) if services else "(none yet)"))
    return "\n".join([*systems_lines, services_line])


_SYSTEMS_TASK = (
    "TASK - EXTRACT SYSTEMS. The orient, harvest and hypotheses above (and the page "
    "clusters) are your reflection: use them. Propose ONE `systems` entry for EACH "
    "mechanism your verified hypotheses named: a known `kind` (+ `discriminator`, "
    "default __singleton__) with a `description` prop in `props` - a brief "
    "adversarially-oriented NL characterisation of that mechanism. You MUST return at "
    "least one system whenever your hypotheses named a mechanism; an empty `systems` "
    "list is a wrong answer here. Read the fed catalog for the legal `kind`s and the "
    "fed bootstrapped Systems: for a System already listed, REUSE its exact key and "
    "output an ENRICHED description (fold your new insight in - never blank it, never "
    "merely restate). "
    # WebPresentation is PER (service, page-cluster), not a singleton (#53): the
    # downstream agent must locate the exact page a service is exposed on.
    "SPECIAL CASE - WebPresentation: emit ONE per (owning service, page cluster) from the "
    "CLUSTER PAGES step - set `discriminator` to '<service_slug>::<cluster>' (a short "
    "stable cluster slug, e.g. 'product-detail', 'category-listing', 'checkout', "
    "'not-found') and put the cluster's member text/html page paths in a `pages` list in "
    "`props`. Never emit a __singleton__ WebPresentation and never one per raw URL. "
    "Do not link edges here."
)


def _linking_context(primary: list[str], secondary: list[str],
                     owned: dict[str, list[str]], all_services=()) -> str:
    """The dynamic service context the LINKING sub-problem injects: PRIMARY services
    (with the assets they own, as linking evidence) and the shared-surface list.

    No per-unit WRITE scope (T2): PRIMARY is a PRIORITY hint, never a restriction,
    so the FULL live inventory is appended and a link to any other live Service is
    valid - a System may overlay Services the unit's chunk does not touch."""
    prim_lines = "\n".join(
        f"  - {slug} (owns: {', '.join(owned.get(slug, [])) or 'surface in this chunk'})"
        for slug in primary) or "  (none)"
    shared = sorted(set(secondary) | {s for s in all_services if s not in set(primary)})
    return (
        "PRIMARY services (they aggregate this unit's assets - link Systems to THESE first,\n"
        "but they are a PRIORITY, not a restriction):\n"
        f"{prim_lines}\n"
        f"ALSO LINKABLE - every other live Service (a System may overlay any of them): "
        f"{shared or '(none)'}"
    )


_LINKING_TASK = (
    "TASK - LINK SERVICES (system_edges ONLY). Connect each System above to EVERY "
    "Service it genuinely overlays, choosing the exact edge label - the full `rel` "
    "catalogue is in the fed `vocabulary` artifact (e.g. "
    "EXPOSED_VIA a REST/GraphQL API OR a WebPresentation page-cluster - copy its "
    "'<service>::<cluster>' discriminator VERBATIM so the edge hits the right node; "
    "FRONTED_BY / PROTECTED_BY / ROUTED_BY a perimeter; "
    "IDENTIFIED_BY / AUTHENTICATED_BY / AUTHORIZED_BY the identity Systems; "
    "SHAPES_DATA_OF / ON_REQUEST_PATH / DEPENDS_ON the remaining catalogue rels). A "
    "Service unit may link its System to ANY live Service; a System unit may link to "
    "any rider. There is NO per-unit write scope - pick the owner that FITS, and copy "
    "each service_slug VERBATIM. Leave every other list EMPTY."
)


# The typist's eight unit-first sub-problems (T2), each mapping onto a run of the
# `_REFLECTION_STEPS` stages: ORIENT, HYPOTHESISE, CLUSTER PAGES, VERIFY-FALSIFY,
# INTEGRATE, EMIT. The reasoning turns emit `claims`; the two extraction turns emit
# `systems` and `system_edges`. Every turn speaks `AnalysisTurn`, so the tool set
# never toggles. The unit kind selects the CENTRAL QUESTION direction: a Service
# unit asks forward (which Systems does this Service rely on); a System unit asks
# the same question in reverse (which Services rely on this overlay). Placed here,
# after the prompt texts it composes.
_ROLE_HEADER = role_header(
    "the TechnicalSystem mechanism-typist",
    "reconstruct, at breadth, the cross-cutting technical Systems a unit relies on "
    "(or overlays) and how they bind to the Services",
)

WORKFLOW = ReasoningWorkflow(
    role_id="mechanism_typist",
    sub_problems=(
        SubProblem(
            id="orient_from_catalog",
            name="orient from the catalog",
            prompt=(
                f"{_ROLE_HEADER}\n\n{cot_scaffold(_REFLECTION_STEPS[:1])}\n\n"
                "ORIENT FROM THE CATALOG. "
                "Use the fed RDF catalog, the currently-defined Systems, and the UNIT "
                "subject to state the mechanism landscape for THIS unit: which System "
                "kinds are plausible for it, and which the catalog rules out. Emit one "
                "Claim per candidate kind: `subject` the unit; `assertion` why that kind "
                "fits (or is ruled out); `evidence` the catalog entry or the unit "
                "description clause; `verdict` `plausible` or `ruled-out`. Emit `claims` "
                "only."
            ),
            inject=("unit", "inventory", "vocabulary"),
            emit=("claims",),
        ),
        SubProblem(
            id="harvest_surface",
            name="harvest the surface",
            prompt=(
                f"{_ROLE_HEADER}\n\nHARVEST THE SURFACE - DISCOVER THE UNIT'S SURFACE, "
                "from the unit and not from a pre-fed inventory. Read the unit's identifier "
                "and description, and, "
                "for a Service unit, its already-aggregated endpoints. Hypothesise the "
                "paths and mechanisms the unit implies FIRST, then call `graph_view` "
                "with bounded read-only Cypher (always a LIMIT) to confirm or refute "
                "each guess and to enumerate broadly: for a Service unit traverse "
                "`AGGREGATES`; for a System unit read its `EVIDENCED_BY` fingerprints "
                "plus the `AGGREGATES` endpoints of every Service that rides it. The "
                "HTTP-history pair is bound: call `search_http_history` on each "
                "hypothesised path, then `get_http_artifact` to read a specific recorded "
                "request shape where it helps. "
                "Read every returned endpoint with the response evidence that "
                "discriminates a mechanism (`content_type`, `title`, `status_code`, "
                "`server`). Emit one Claim per discovered endpoint: `subject` the "
                "endpoint; `assertion` the mechanism evidence you actually read; "
                "`evidence` the Cypher/history query that found it; `verdict` a "
                "tentative mechanism kind or `unknown`. Read what the unit SERVES, not "
                "the names it CARRIES; a guess that returns nothing is a valid miss. "
                "Emit `claims` only."
            ),
            inject=("unit",),
            emit=("claims",),
        ),
        SubProblem(
            id="prior_insights",
            name="prior insights",
            prompt=(
                f"{_ROLE_HEADER}\n\nRECALL PRIOR INSIGHTS - read before you reason. Call "
                "the `notes` tool with command=\"read\" on the unit slug; call it again "
                "with `body_keyword` set to each mechanism noun the harvest surfaced "
                "(for example `auth`, `session`, `api`, `presentation`) so a note another "
                "earlier unit wrote about a shared mechanism is found even when keyed by "
                "a different unit. Do not re-derive a mechanism an earlier unit already "
                "characterised; reuse that characterisation. For each reusable insight "
                "emit one Claim: `subject` the prior unit or note key; `assertion` the "
                "inherited insight; `evidence` the note key; `verdict` `reuse` or "
                "`supersede`. A run with no prior notes is a valid result - say so. Emit "
                "`claims` only."
            ),
            inject=("unit", "harvest_surface"),
            emit=("claims",),
            depends_on=("harvest_surface",),
        ),
        SubProblem(
            id="mechanism_hypotheses",
            name="mechanism hypotheses",
            prompt=(
                f"{_ROLE_HEADER}\n\n{cot_scaffold(_REFLECTION_STEPS[1:2])}\n\n"
                "Answer the CENTRAL QUESTION for THIS unit, in the DIRECTION its kind "
                "selects (the unit block states it): a SERVICE unit asks forward - "
                "given the catalog, which technical Systems could this Service rely on "
                "to offer its contract, and HOW is that contract implemented; which "
                "relied-upon Systems are NOT yet mapped. A SYSTEM unit asks the same "
                "question in reverse - which Services rely on this technical overlay, "
                "and how. Hypothesise from the contract/overlay first, then hold the "
                "candidate against the harvested surface. Emit one Claim per hypothesis: "
                "`subject` the unit or the candidate System/Service; `assertion` the "
                "candidate System kind (or rider Service and rel) and whether it is new "
                "or an extension; `evidence` the contract clause and the harvested "
                "surface that licenses it; `verdict` new-vs-extend with the defined "
                "System key (or the rider slug + rel). Emit `claims` only; do not emit "
                "deltas yet."
            ),
            inject=("unit", "inventory", "vocabulary", "observations",
                    "orient_from_catalog", "harvest_surface", "prior_insights"),
            emit=("claims",),
            depends_on=("orient_from_catalog", "harvest_surface", "prior_insights"),
        ),
        SubProblem(
            id="page_clusters",
            name="page clusters",
            prompt=(
                f"{_ROLE_HEADER}\n\n{cot_scaffold(_REFLECTION_STEPS[2:3])}\n\n"
                "Emit one Claim per (service, cluster): `subject` the service, `assertion` "
                "the cluster and its member page paths, `evidence` the shared "
                "title/structure/size, `verdict` the short cluster slug. Emit `claims` only."
            ),
            inject=("unit", "harvest_surface"),
            emit=("claims",),
            depends_on=("harvest_surface",),
        ),
        SubProblem(
            id="systems_extract",
            name="systems extract",
            prompt=(
                f"{_ROLE_HEADER}\n\n{cot_scaffold(_REFLECTION_STEPS[3:5])}\n\n"
                f"{_SYSTEMS_TASK}"
            ),
            inject=("unit", "inventory", "vocabulary", "mechanism_hypotheses", "page_clusters"),
            emit=("systems",),
            depends_on=("mechanism_hypotheses", "page_clusters"),
        ),
        SubProblem(
            id="link",
            name="link",
            prompt=(
                f"{_ROLE_HEADER}\n\n{cot_scaffold(_REFLECTION_STEPS[5:6])}\n\n"
                f"{_LINKING_TASK}"
            ),
            inject=("unit", "inventory", "vocabulary", "candidates", "systems_extract"),
            emit=("system_edges",),
            depends_on=("systems_extract",),
        ),
        SubProblem(
            id="closure",
            name="closure",
            prompt=(
                f"{_ROLE_HEADER}\n\nCLOSE. Summarise the unit's outcome: which Systems "
                "were DEFINED, which were EXTENDED, and which Service->System edges were "
                "linked, naming the evidence each typing rests on; name each mechanism "
                "you could not decide and why. Call the `notes` tool once: "
                "command=\"write\", action=\"append\", unit = the unit slug, "
                "note_name=\"modelling-closure\", kind=\"system\", body = the closure "
                "body. Write it even when you typed no System, so the unit's coverage "
                "stays auditable. Then emit one Claim: `subject` the unit; `assertion` "
                "the count of Systems defined and extended; `evidence` the note key; "
                "`verdict` `closed`. Emit `claims` only."
            ),
            inject=("unit", "systems_extract", "link"),
            emit=("claims",),
            depends_on=("systems_extract", "link"),
        ),
    ),
)


# --- the injected LLM seam ----------------------------------------------------

def _default_invoke_fn(messages, *, schema=None, system_prompt=None):
    """The legacy stateless call, retained for callers/tests on the one-shot seam: the
    analyser-role model behind the #73 escalating retry. `schema=None` returns free-text
    (the reflection call); a pydantic `schema` returns structured output. Production now
    uses `session_invoke_fn`, which binds the same prompt as the agent's leading block
    instead of a trail message."""
    from polymerhus.analysis.proposer_turn import prepend_prompt
    from polymerhus.app.llm.roles import invoke_role

    return invoke_role("analyser", prepend_prompt(messages, system_prompt), schema=schema)


def stateful_invoke_fn(run_id: str, checkpointer, project_id: str | None = None):
    """The STATEFUL mechanism-typist call (#94): the `mechanism_typist` role runs as a
    session resuming from its OWN per-run checkpoint (`AnalysisSession(run_id, "mechanism_typist")`, distinct from every other agent's), so its
    sub-problem chain and every chunk append to ONE growing context. Every turn goes
    through the one `AnalysisTurn` envelope. Same
    `(messages, *, schema)` shape as `_default_invoke_fn`. Structurally sync (sequential
    dispatch under `ANALYSER_PASS_SEMAPHORE`).

    The role prompt is bound ONCE as the agent's ephemeral leading block (the
    converged seam, `proposer_turn.session_invoke_fn`), so it is the stable prefix of
    every request and never accumulates in the checkpointed trail.

    Context-window compaction (#95 D9): the run's turns run COMPACTED - the
    analysis-side compaction middleware is built once per run and passed through
    `stateful_turn`, so an over-budget thread spawns out-of-band running-summary
    passes that the next turn's barrier awaits. Built fail-open: a missing role
    config degrades the profile/window, never the session."""
    from polymerhus.analysis.proposer_turn import session_invoke_fn

    return session_invoke_fn("mechanism_typist", run_id, checkpointer, project_id)


# The mechanism-typist role prompt, selected by the active prompt variant
# (`prompt_variant.prompt_path`: `technical-system.md` for `legacy`,
# `technical-system-batched-l1unit-first.md` for the default), memoized PER VARIANT
# on first call (no import-time I/O, CODING STANDARD section 6). A missing prompt
# file is a defect: FAIL-CLOSED (raise).
_TECHNICAL_SYSTEM_SKILLS: dict[str, str] = {}


def _load_skill() -> str:
    """The mechanism-typist's OWN prompt (grilled #9): hypothesis-driven
    mechanism-typing discipline + the >=6 breadth exemplars, read from the file the
    active prompt variant selects. Memoized in-process PER VARIANT; FAIL-CLOSED on a
    missing file (raise). NOT the assignment-oriented analyser skill."""
    variant = resolve_prompt_variant()
    cached = _TECHNICAL_SYSTEM_SKILLS.get(variant)
    if cached is None:
        cached = prompt_path("mechanism_typist", variant).read_text(encoding="utf-8")
        _TECHNICAL_SYSTEM_SKILLS[variant] = cached
    return cached


# --- the 8-sub-problem proposer body ------------------------------------------

def _unit_kind(chunk: Chunk) -> str:
    """`System` for a System unit (`source_job` prefixed `system:`), `Residual` for
    the unaggregated-surface unit (`source_job` `residual`), else `Service`."""
    src = str(getattr(chunk, "source_job", "") or "")
    if src.startswith("system:"):
        return "System"
    if src == "residual":
        return "Residual"
    return "Service"


def _service_slug(chunk: Chunk) -> str:
    """The unit's Service slug: `source_job`'s `service:` suffix, else the chunk id."""
    src = str(getattr(chunk, "source_job", "") or "")
    return src.removeprefix("service:") if src.startswith("service:") else str(chunk.chunk_id)


def _service_contract(chunk: Chunk, inventory: dict | None) -> str:
    """The unit's non-empty `service_contract`, when the unit is a contracted
    Service. Used only by the unit-first empty-asset entry gate (C-M2): a Service
    with a contract but no PRE-AGGREGATED surface still discovers its surface."""
    if _unit_kind(chunk) != "Service":
        return ""
    contracts = (inventory or {}).get("service_contracts") or {}
    return str(contracts.get(_service_slug(chunk), "") or "") if isinstance(contracts, dict) else ""


def _aggregated_endpoints_repr(aggregations: list[dict] | None, slug: str) -> str:
    """Render the Service's OWN already-aggregated endpoints from the live
    aggregation view, one `METHOD /path (baseurl)` per row. `(none)` when the
    Service aggregates nothing yet, so a thin surface renders explicitly."""
    lines: list[str] = []
    for row in aggregations or []:
        if row.get("slug") != slug or "Endpoint" not in (row.get("labels") or []):
            continue
        props = row.get("props") or {}
        path = props.get("path")
        if not isinstance(path, str):
            continue
        method = str(props.get("method") or "").upper()
        baseurl = props.get("baseurl")
        line = " ".join(part for part in (method, path) if part)
        if baseurl:
            line = f"{line} ({baseurl})"
        lines.append(line)
    return "; ".join(lines) if lines else "(none)"


def _unit_block(chunk: Chunk, *, inventory: dict | None = None,
                aggregations: list[dict] | None = None) -> str:
    """The `unit` base source: the ONE unit this workflow enriches, its kind, its
    DESCRIPTION, and the direction-dependent central question (T2).

    A Service unit carries its `service_contract` and the endpoints it already
    aggregates; a System unit carries its bootstrapped `description`. The central
    question is stated FORWARD for a Service (which Systems does it rely on) and in
    REVERSE for a System (which Services rely on this overlay). The unit - not any
    asset name - is the reasoning anchor; the description is what the typist reasons
    FROM, so an absent description renders explicitly rather than as a blank line."""
    slug = str(chunk.chunk_id)
    kind = _unit_kind(chunk)
    inv = inventory or {}
    service = _service_slug(chunk)
    if kind == "System":
        key = str(getattr(chunk, "source_job", "") or "").removeprefix("system:")
        description = (inv.get("system_descriptions") or {}).get(key, "")
        description_line = f"UNIT DESCRIPTION (the mechanism overlay): {description.strip() or '(none)'}"
        question = (
            "CENTRAL QUESTION (inverse): which Services rely on this technical "
            "overlay, and how? Name each rider and the edge label that binds it.")
        # B-m9: a System unit has no Service aggregation key, so the "already
        # aggregates" line would always read (none) and mislead. Omit it.
        aggregates_line = ""
    elif kind == "Residual":
        # B-m8: the residual is the surface NO Service aggregates, so it is not a
        # forward Service with an empty contract. Frame it neutrally.
        description_line = (
            "UNIT DESCRIPTION (residual): this surface belongs to no Service.")
        question = (
            "CENTRAL QUESTION (residual): this surface belongs to no Service; which "
            "cross-cutting technical Systems does it evidence, and which are already "
            "mapped?")
        aggregates_line = ""
    else:
        description = (inv.get("service_contracts") or {}).get(service, "")
        description_line = f"UNIT DESCRIPTION (the service_contract): {description.strip() or '(none)'}"
        question = (
            "CENTRAL QUESTION (forward): given the catalog, which technical Systems "
            "could this Service rely on to offer its contract, and HOW is the contract "
            "implemented? Name the relied-upon Systems that are NOT yet mapped.")
        aggregates_line = (
            f"UNIT ALREADY AGGREGATES: {_aggregated_endpoints_repr(aggregations, service)}\n")
    return (
        f"UNIT: {slug}\n"
        f"UNIT KIND: {kind}\n"
        f"{description_line}\n"
        f"{aggregates_line}"
        f"{question}\n"
        "This unit - not any asset name - is the reasoning anchor. Its FUNCTIONAL "
        "role is to ask the central question above, then DISCOVER the surface that "
        "answers it through the tools; a Service aggregates surface, a System "
        "fingerprints it and the Services that ride it bring the rest."
    )


def type_mechanisms(
    chunk: Chunk,
    *,
    invoke_fn=None,
    inventory: dict | None = None,
    aggregations: list[dict] | None = None,
    run_id: str | None = None,
    tags: list | None = None,
    memory: "AnalysisMemoryStore | None" = None,
    project_id: str | None = None,
    first_definer: bool = False,
) -> L1DeltaBatch:
    """The A.1 mechanism-typist body (grilled #9, unit-first T2): the `WORKFLOW`
    sub-problem chain (orient_from_catalog -> harvest_surface -> prior_insights ->
    mechanism_hypotheses -> page_clusters -> systems_extract -> link -> closure) over
    one unit (Service OR System), returning a narrowed `L1DeltaBatch{systems,
    system_edges}`.

    `invoke_fn(messages, *, schema, system_prompt) -> AnalysisTurn | None` is injected
    (unit-testable). FAIL-CLOSED on hypotheses exhaustion (the chain halts); SOFT
    pass-through on a later step's exhaustion (write what earlier steps produced).
    Fail-open on any exception - never crashes the caller.

    `memory` / `project_id` thread the per-unit analysis backstop into `run_workflow`
    (ADR D31); `first_definer=True` applies the ADR D19 compounding rule, used only by
    the service-sourced loop. Both are inert for the streamed default."""
    if not chunk.assets and not _service_contract(chunk, inventory):
        # C-M2: an empty PRE-AGGREGATED surface is not a skip when the Service has a
        # contract - discovery is the point. A unit with neither contract nor assets
        # is a valid empty with no LLM call.
        return L1DeltaBatch()
    invoke_fn = invoke_fn or _default_invoke_fn
    # The skill rides the stateful seam's `system_prompt=` binding (the converged
    # seam), so it is the leading prefix of every request and never enters the
    # checkpointed trail. The legacy one-shot seam prepends it itself.
    skill = _load_skill()

    from polymerhus.analysis.l1_curator import vocabulary_prompt
    from polymerhus.analysis.proposer_turn import proposer_batch
    from polymerhus.analysis.reasoning_workflow import run_workflow, to_delta_batch

    # The volatile base sources the workflow injects verbatim: the unit subject with
    # its description and direction-dependent central question, its adversarial
    # observation insight, the bootstrapped Systems (with the live Service list), the
    # RDF catalog, and the linking context. The whole settled surface is NOT a base
    # source: the model DISCOVERS it through the tools (L1-unit-first).
    all_services = frozenset((inventory or {}).get("services") or [])
    primary, secondary, owned = partition_services(chunk.assets, aggregations or [], all_services)
    base_artifacts = {
        "unit": _unit_block(chunk, inventory=inventory, aggregations=aggregations),
        "observations": _asset_observation_paragraphs(chunk),
        "inventory": _defined_systems_block(inventory),
        "vocabulary": vocabulary_prompt(),
        "candidates": _linking_context(primary, secondary, owned, all_services),
    }

    # Per-batch memory: the whole chain of ONE chunk shares a session (the batch
    # scope), so the reasoning is the extraction's context; the next chunk opens a
    # fresh thread. The scope is inert for the one-shot legacy seam. The fail-closed
    # gate halts the chain when the hypotheses turn exhausts.
    try:
        with proposer_batch(chunk.chunk_id):
            run = run_workflow(
                WORKFLOW, invoke_fn=invoke_fn, system_prompt=skill,
                base_artifacts=base_artifacts,
                halt_when=lambda sp, turn: sp.id == "mechanism_hypotheses" and turn is None,
                unit_slug=chunk.chunk_id, memory=memory, project_id=project_id, run_id=run_id,
                note_kind="system",
            )
    except Exception:
        logger.warning("mechanism_typist: workflow failed; degrading to empty batch", exc_info=True)
        return L1DeltaBatch()

    if run.turns.get("mechanism_hypotheses") is None:
        logger.warning("mechanism_typist: hypotheses exhausted; fail-closed to empty batch")
        return L1DeltaBatch()

    # #9/#18: attach the reasoning to the run-correlated trace (explicit run
    # correlation - the supervisor no longer opens an agent span, so the ambient
    # update would go nowhere). Otherwise the WHY behind each System proposal is
    # built, consumed, and discarded, leaving nothing to evaluate against.
    from polymerhus.app.observability import trace_reasoning
    trace_reasoning(run.artifacts.get("mechanism_hypotheses", ""),
                    call="typist-reflection", run_id=run_id, tags=tags)

    systems_turn = run.turns.get("systems_extract")
    link_turn = run.turns.get("link")
    systems_batch = to_delta_batch(systems_turn) if systems_turn is not None else L1DeltaBatch()
    link_batch = to_delta_batch(link_turn) if link_turn is not None else L1DeltaBatch()

    # #18/observability: persist the typist's STRUCTURED output (systems + edges, with each
    # system's kind/discriminator) alongside its reasoning - otherwise the WHAT it
    # proposed (not just the WHY) leaves no inspectable trace (moodique cc29fd4a).
    from polymerhus.app.observability import trace_generation
    trace_generation("typist-systems-and-edges",
                     run_id=run_id, tags=tags,
                     output={"systems": [{"kind": s.kind, "discriminator": s.discriminator}
                                         for s in (list(systems_batch.systems) + list(link_batch.systems))],
                             "edges": [{"service_slug": e.service_slug, "kind": e.kind,
                                        "discriminator": e.discriminator, "rel": e.rel}
                                       for e in (link_batch.system_edges or [])]})

    merged_systems = _merge_systems(systems_batch.systems, link_batch.systems)
    # #53: the two structured calls disagree on the WebPresentation discriminator; deterministically
    # de-duplicate the singleton and snap its orphaned edge to the real per-cluster node.
    reconciled_systems, reconciled_edges = _reconcile_webpresentation(merged_systems, link_batch.system_edges)
    combined = L1DeltaBatch(
        systems=reconciled_systems,
        system_edges=reconciled_edges,
    )
    combined = narrow_to_typing(combined)
    combined = drop_unknown_vocabulary(combined, kinds=_known_kinds(), rels=_known_rels())
    if first_definer:
        # ADR D19: strip the description from any System an earlier Service already
        # defined, so N Services never re-compound it. Inert on the streamed path.
        combined = strip_recompounded_descriptions(
            combined, existing_keys=frozenset((inventory or {}).get("systems") or ()))
    return combined


# --- supervisor wiring (the proposer_bodies["mechanism_typist"] seam) ----------

def _default_read_inventory(project_id: str) -> dict:
    from polymerhus.analysis.l1_inventory import read_l1_inventory
    return read_l1_inventory(project_id)


def _default_read_aggregations(project_id: str) -> list[dict]:
    from polymerhus.analysis.l1_read import read_service_aggregations
    return read_service_aggregations(project_id)


def mechanism_typist_body(
    dispatch,
    state: dict,
    *,
    invoke_fn=None,
    read_inventory=None,
    read_aggregations=None,
    memory: "AnalysisMemoryStore | None" = None,
    first_definer: bool = False,
) -> L1DeltaBatch | None:
    """The supervisor proposer BODY - matches `supervisor.ProposerBody` EXACTLY, like
    the Assigner (grilled #9 wiring caveat): route the A.1 create phase to
    `type_mechanisms` over the dispatch's `service` chunk + the LIVE inventory +
    Service->L0 aggregations (re-derived, never a frozen snapshot). A non-A.1 phase
    yields `None` (hollow). Every read is guarded, so the body never raises; the
    supervisor wrapper degrades a raising body fail-open regardless."""
    if getattr(dispatch, "phase", None) != "A1":
        return None  # A.2 (missing-systems sweep) is a later slice
    chunk = getattr(dispatch, "chunk", None)
    if chunk is None:
        return L1DeltaBatch()
    project_id = state.get("project_id", "")
    read_inventory = read_inventory or _default_read_inventory
    read_aggregations = read_aggregations or _default_read_aggregations
    try:
        inventory = read_inventory(project_id)
    except Exception:  # a read failure degrades to no inventory context, never crashes
        logger.warning("mechanism_typist: inventory read failed; typing without it", exc_info=True)
        inventory = {}
    # C-M2: a contracted Service with no PRE-AGGREGATED surface still discovers its
    # own; only a unit with neither contract nor assets is a valid no-op.
    if not getattr(chunk, "assets", None) and not _service_contract(chunk, inventory):
        return L1DeltaBatch()
    try:
        aggregations = read_aggregations(project_id)
    except Exception:
        logger.warning("mechanism_typist: aggregation read failed; no primary-service split", exc_info=True)
        aggregations = []
    # Convergence: the supervisor no longer opens an agent span, so the WHY/WHAT
    # records below carry their own explicit run correlation (the handler tree
    # plus the run tag preserve structure and join).
    run_id = (state.get("run_id") or "").removeprefix("stream-")
    tags = ["analysis", getattr(dispatch, "role", "mechanism_typist")]
    return type_mechanisms(chunk, invoke_fn=invoke_fn, inventory=inventory,
                           aggregations=aggregations, run_id=run_id or None,
                           tags=tags, memory=memory, project_id=project_id or None,
                           first_definer=first_definer)
