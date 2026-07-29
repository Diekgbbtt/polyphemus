"""The TechnicalSystem Analyser (agent spec #9), realising #20 increment 2b's
mechanism-typing proposer slice.

Sole owner of MECHANISM TYPING: it defines/extends the cross-cutting `System`s the
target lies on and links them to Services as typed `Service->System` edges - NEVER
as Service props (the mechanism-as-System correction). BREADTH-ONLY (grilled #9):
it emits `L1DeltaBatch{systems, system_edges}`; all System DEEPENING (WebPresentation
rendering/navigation, authz inverse-pyramid, backward-recon probes, the AnatomyResult
triple) is Phase B (epic #39; deepening #41; System under-typing #40).

Algorithm (grilled #9) - THREE sequential calls over one `service` chunk delivered
AFTER the Assigner (`chunking.CONCERN_ROLES["service"] = ("assigner", "mechanism_typist")`):

  1. REFLECTION (free-text prose, the "reason" call): a hypothesis-driven meta-process
     (overthink + critical-thinking + define/debug-hypothesis) over each asset paired
     with its triager observation insight, the currently-defined Systems WITH their
     descriptions, and the static SYSTEM_KINDS vocabulary. Exhaustion => the WHOLE step
     degrades to an empty batch (FAIL-CLOSED).
  2. SYSTEMS EXTRACTION (structured): the prose -> `systems` deltas (new/extended, each
     carrying a COMPOUNDED NL `description` prop that folds in the adversarial insight -
     never emptied; the description is the System-side discriminative attribute). Soft
     pass-through on exhaustion.
  3. SERVICES LINKING (structured): the prose + systems + services split PRIMARY (those
     aggregating this chunk's assets, live from AGGREGATES) vs SECONDARY (other
     asset-bearing services) -> `system_edges`. Soft pass-through on exhaustion.

Standalone + injected `invoke_fn` / reads (unit-testable, no live LLM/graph); the body
matches the `supervisor.ProposerBody` protocol EXACTLY (like the Assigner) - it is
register-ready in `proposer_bodies["mechanism_typist"]`. Fail-open throughout.
"""
from __future__ import annotations

import logging
from collections import defaultdict

from polymerhus.analysis.analyser_types import L1DeltaBatch
from polymerhus.analysis.chunking import Chunk
from polymerhus.analysis.proposer_reasoning import bounded_retry, cot_scaffold, role_header

logger = logging.getLogger(__name__)

_SINGLETON = "__singleton__"

# The hypothesis-driven reflection scaffold (grilled #9): the numbered process the
# reason call works THROUGH out loud, synthesising overthink (staged reasoning),
# critical-thinking (claim/evidence/assumption/fallacy) and define/debug-hypothesis.
_REFLECTION_STEPS = [
    "ORIENT: what technical mechanisms could this batch of surface plausibly evidence? "
    "Read each asset together with its adversarial observation insight.",
    "HYPOTHESISE: for each asset+observation, define candidate hypotheses of the form "
    "'this asset impacts a System of kind K - newly-defined, OR extending currently-defined "
    "System X'. Hold more than one candidate kind for an ambiguous asset.",
    "VERIFY / FALSIFY: test each hypothesis against the evidence actually present. A "
    "framework fingerprint alone is NOT the mechanism-in-use; separate the claim from its "
    "support; decide new-vs-extend against the currently-defined Systems listed.",
    "INTEGRATE the adversarial observation insight into the surviving System's "
    "characterisation - what makes that mechanism attackable.",
    "EMIT a prose delta overview: the verified NEW and EXTENDED Systems and their "
    "adversarial characterisations. Do NOT deep-profile (no rendering/navigation model, "
    "no authorization pyramid) - that is a later phase.",
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

def _asset_observation_paragraphs(chunk: Chunk) -> str:
    """Render each streamed asset paired with its triager observation INSIGHT as a
    paragraph (grilled #9 Q4): the adversarial NLP layer that drives System typing
    rides beside the asset it anchors to. Observations already travel on the chunk."""
    by_anchor: dict[tuple, list] = defaultdict(list)
    for o in chunk.observations:
        anchor = o.anchor or {}
        by_anchor[(anchor.get("type"), _idkey(anchor.get("identity") or {}))].append(o)
    paras: list[str] = []
    for a in chunk.assets:
        insights = by_anchor.get((a.type, _idkey(a.identity or {})), [])
        head = f"- {a.type} {dict(a.identity or {})}"
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
    `system_descriptions` is the additive map `read_l1_inventory` now returns."""
    inv = inventory or {}
    systems = inv.get("systems") or []
    descs = inv.get("system_descriptions") or {}
    if not systems:
        return "CURRENTLY-DEFINED SYSTEMS: (none yet)"
    lines = ["CURRENTLY-DEFINED SYSTEMS (extend these by their EXACT key; enrich - never blank - a description):"]
    for s in systems:
        d = (descs.get(s) or "").strip()
        lines.append(f"- {s}" + (f" :: {d}" if d else ""))
    return "\n".join(lines)


def _reflection_prompt(chunk: Chunk, inventory: dict | None) -> str:
    from polymerhus.analysis.l1_curator import vocabulary_prompt

    return (
        f"{role_header('the TechnicalSystem mechanism-typist', 'reconstruct, at breadth, the cross-cutting technical Systems this streamed surface evidences and how they overlay the Services')}\n\n"
        f"{_defined_systems_block(inventory)}\n\n"
        f"{vocabulary_prompt()}\n\n"
        "STREAMED SURFACE (each asset with its adversarial observation insight):\n"
        f"{_asset_observation_paragraphs(chunk)}\n\n"
        f"{cot_scaffold(_REFLECTION_STEPS)}\n\n"
        "Write your reasoning as prose. Do not emit JSON or a tool call in this step."
    )


def _systems_prompt(prose: str, inventory: dict | None) -> str:
    from polymerhus.analysis.l1_curator import vocabulary_prompt

    return (
        f"{_defined_systems_block(inventory)}\n\n"
        f"{vocabulary_prompt()}\n\n"
        "Your reflection:\n"
        f"{prose}\n\n"
        # POSITIVE framing (mirrors pod.py's data-modelling fix): a negative "leave
        # X, Y, Z EMPTY" litany makes a weaker model anchor on the empties and return
        # an all-empty batch (observed live: reflection named 5 mechanisms, extraction
        # returned 0 systems). State what to FILL, and that empty is wrong.
        "TASK - EXTRACT SYSTEMS. Your reflection above named the cross-cutting mechanisms "
        "this surface evidences. Propose ONE `systems` entry for EACH mechanism you "
        "identified: a known `kind` (+ `discriminator`, default __singleton__) with a "
        "`description` prop in `props` - a brief adversarially-oriented NL characterisation "
        "of that mechanism. You MUST return at least one system whenever your reflection "
        "named a mechanism; an empty `systems` list is a wrong answer here. For a System "
        "already listed above, REUSE its exact key and output an ENRICHED description (fold "
        "your new insight in - never blank it, never merely restate). Do not link edges here."
    )


def _linking_prompt(prose: str, systems_batch: L1DeltaBatch, primary: list[str],
                    secondary: list[str], owned: dict[str, list[str]],
                    inventory: dict | None) -> str:
    proposed = sorted({s.kind if s.discriminator == _SINGLETON else f"{s.kind}:{s.discriminator}"
                       for s in systems_batch.systems})
    defined = (inventory or {}).get("systems") or []
    prim_lines = "\n".join(
        f"  - {slug} (owns: {', '.join(owned.get(slug, [])) or 'surface in this chunk'})"
        for slug in primary) or "  (none)"
    return (
        "Your reflection:\n"
        f"{prose}\n\n"
        f"Systems now available to link (proposed this step + already defined): "
        f"{sorted(set(proposed) | set(defined))}\n\n"
        "PRIMARY services (they aggregate this chunk's assets - link Systems to THESE first):\n"
        f"{prim_lines}\n"
        f"SECONDARY services (other asset-bearing services): {secondary or '(none)'}\n\n"
        "TASK - LINK SERVICES (system_edges ONLY). Propose `system_edges`: connect each "
        "touched System to the Service(s) it overlays, choosing the exact edge label "
        "(EXPOSED_VIA a REST/GraphQL API; FRONTED_BY / PROTECTED_BY / ROUTED_BY a perimeter; "
        "IDENTIFIED_BY / AUTHENTICATED_BY / AUTHORIZED_BY the identity Systems). Copy each "
        "service_slug VERBATIM from the lists above; prefer PRIMARY services. Leave every "
        "other list EMPTY."
    )


# --- the injected LLM seam ----------------------------------------------------

def _default_invoke_fn(messages, *, schema=None):
    """Real collaborator: the analyser-role model. `schema=None` returns the free-text
    content (the reflection call); a pydantic `schema` returns structured output via
    function_calling (the extraction/linking calls). Same model as the pod/assigner."""
    from polymerhus.app.llm.roles import chat_model_for

    llm = chat_model_for("analyser")
    if schema is None:
        resp = llm.invoke(messages)
        return getattr(resp, "content", None) or None
    return llm.with_structured_output(schema, method="function_calling").invoke(messages)


def _load_skill() -> str:
    """The mechanism-typist's OWN skill (grilled #9): hypothesis-driven mechanism-typing
    discipline + the >=6 breadth exemplars. NOT the assignment-oriented analyser skill."""
    from polymerhus.recon.domain.skills import skill_for

    return skill_for("analysis/technical-system", fallback=(
        "You are the TechnicalSystem mechanism-typist. Define/extend the cross-cutting "
        "technical Systems the streamed surface evidences and link them to Services as "
        "typed Service->System edges - never Service props. Reason by hypothesis: for each "
        "asset+observation, hypothesise which System it impacts (new or extending an "
        "existing one) and verify against the evidence (a framework fingerprint alone is "
        "never sufficient). Enrich each System's description with the adversarial insight."
    ))


# --- the 3-call proposer body -------------------------------------------------

def type_mechanisms(
    chunk: Chunk,
    *,
    invoke_fn=None,
    inventory: dict | None = None,
    aggregations: list[dict] | None = None,
) -> L1DeltaBatch:
    """The A.1 mechanism-typist body (grilled #9): the reflection -> systems-extraction
    -> services-linking chain over a `service` chunk, returning a narrowed
    `L1DeltaBatch{systems, system_edges}`.

    `invoke_fn(messages, *, schema) -> str | L1DeltaBatch | None` is injected (unit-
    testable). FAIL-CLOSED on reflection exhaustion (empty batch); SOFT pass-through on
    a later step's exhaustion (write what earlier steps produced). Fail-open on any
    exception - never crashes the caller."""
    from langchain_core.messages import HumanMessage, SystemMessage

    if not chunk.assets:  # empty delta -> nothing to type (valid empty)
        return L1DeltaBatch()
    invoke_fn = invoke_fn or _default_invoke_fn
    skill = _load_skill()

    # Call 1 - REFLECTION (reason). Exhaustion => fail-closed (whole step empty).
    prose = bounded_retry(lambda: invoke_fn(
        [SystemMessage(content=skill), HumanMessage(content=_reflection_prompt(chunk, inventory))],
        schema=None,
    ))
    if not prose:
        logger.warning("mechanism_typist: reflection exhausted; fail-closed to empty batch")
        return L1DeltaBatch()

    # Call 2 - SYSTEMS EXTRACTION (extract). Soft pass-through on exhaustion.
    systems_batch = bounded_retry(lambda: invoke_fn(
        [SystemMessage(content=skill), HumanMessage(content=_systems_prompt(prose, inventory))],
        schema=L1DeltaBatch,
    )) or L1DeltaBatch()

    # Call 3 - SERVICES LINKING (extract). Soft pass-through on exhaustion.
    all_services = frozenset((inventory or {}).get("services") or [])
    primary, secondary, owned = partition_services(chunk.assets, aggregations or [], all_services)
    link_batch = bounded_retry(lambda: invoke_fn(
        [SystemMessage(content=skill),
         HumanMessage(content=_linking_prompt(prose, systems_batch, primary, secondary, owned, inventory))],
        schema=L1DeltaBatch,
    )) or L1DeltaBatch()

    combined = L1DeltaBatch(
        systems=_merge_systems(systems_batch.systems, link_batch.systems),
        system_edges=link_batch.system_edges,
    )
    combined = narrow_to_typing(combined)
    return drop_unknown_vocabulary(combined, kinds=_known_kinds(), rels=_known_rels())


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
    if chunk is None or not getattr(chunk, "assets", None):
        return L1DeltaBatch()
    project_id = state.get("project_id", "")
    read_inventory = read_inventory or _default_read_inventory
    read_aggregations = read_aggregations or _default_read_aggregations
    try:
        inventory = read_inventory(project_id)
    except Exception:  # a read failure degrades to no inventory context, never crashes
        logger.warning("mechanism_typist: inventory read failed; typing without it", exc_info=True)
        inventory = {}
    try:
        aggregations = read_aggregations(project_id)
    except Exception:
        logger.warning("mechanism_typist: aggregation read failed; no primary-service split", exc_info=True)
        aggregations = []
    return type_mechanisms(chunk, invoke_fn=invoke_fn, inventory=inventory, aggregations=aggregations)
