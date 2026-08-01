"""FR-SPINE / FR-AUTHZSKILL: the system-anatomy skill subsystem (L1D-31).

A system-anatomy skill actively DETERMINES Layer-1 facts that are neither parsed
from Layer 0 nor read from a document - it runs a system-specific analysis
procedure over runtime signals. Every skill is a TRIPLE (spec §7.6), each leg
landing on machinery that already exists:

  1. signals -> a typed CLASSIFICATION  -> a typed spine slot (a prop on the L1
     unit, written via `l1_curator`);
  2. the corroborating signals -> NL EVIDENCE -> an `Observation` (via the L0
     curator seam);
  3. deeper probes -> a backward-recon REQUEST -> an `AnalyserReconRequest` on
     interface-B (`origin=anatomy_skill`), whose result routes back to the skill.

This module carries the shared triple contract (`SpineClassification`,
`AnatomyResult`) and the first seed skill, **webpage-profile** (FR-SPINE), which
classifies the two INDEPENDENT dimensions `navigation_model` and `rendering_model`
(L1D-31a: neither inferred from the other; a framework fingerprint alone is NEVER
sufficient). The independence + fingerprint-insufficiency rules are enforced
STRUCTURALLY here (a backstop to the SKILL.md prompt, since a weaker model ignores
prose discipline). The authorization-pyramid skill (FR-AUTHZSKILL) reuses the same
triple contract.

Fail-open throughout: an LLM/skill error degrades to an empty result, never
crashing the caller (mirrors the analyser pod).
"""
from __future__ import annotations

import logging
import os
from typing import Literal

from pydantic import BaseModel, Field

from polymerhus.recon.domain.types import Observation

logger = logging.getLogger(__name__)

# The two INDEPENDENT webpage dimensions (L1D-31a) + their controlled vocabularies.
NAVIGATION_MODELS = ("SPA", "MPA", "Hybrid")
RENDERING_MODELS = ("CSR", "SSR", "SSG", "StreamingSSR", "HydratedSSR")
CONFIDENCE_LEVELS = ("High", "Medium", "Low")

# The System kind + the classification slots that make up the web-presentation
# channel. A cross-cutting MECHANISM classification is a System prop reached by a
# typed edge, NEVER a Service prop (the L1 domain-model correction): these two
# slots are written as INDEPENDENT props on a `WebPresentation` System the Service
# is `EXPOSED_VIA`, not as props on the Service itself.
WEB_PRESENTATION_KIND = "WebPresentation"
_WEBPRESENTATION_SLOTS = frozenset({"navigation_model", "rendering_model"})

# The deeper webpage-profile probe needs live CDP interaction (Document-vs-Fetch,
# Page.frameNavigated), which rides the Steel/CDP crawl - hence the STEEL_API_KEY
# config gate. The probe REQUEST is emitted regardless; its live execution is the
# unbuilt dep (non-goal), so it degrades gracefully.
_DEEP_PROBE_JOB = "steel_crawl"
_SKILL_ID = "webpage_profile"


class SpineClassification(BaseModel):
    """One typed spine-slot classification a skill produces (leg 1 of the triple):
    a `value` for a spine `slot`, with `confidence` and verbatim `evidence`.
    `fingerprint_only` records that ONLY a framework fingerprint supported it -
    which (L1D-31a) is never sufficient, so the runner caps such a classification
    below High and forces a probe."""

    slot: str
    value: str
    confidence: Literal["High", "Medium", "Low"]
    evidence: str
    fingerprint_only: bool = False


class AnatomyResult(BaseModel):
    """The anatomy-skill triple's output: typed `classifications` (-> spine slots),
    `observations` (-> NL evidence), and `probes` (-> interface-B backward recon).
    `system_edges` carries typed Service->System edges an anatomy skill writes
    structurally (e.g. the authorization-pyramid skill's `AUTHORIZED_BY {role}` /
    `AUTHENTICATED_BY {realm}`; L1D-18) - written via the l1_curator sole-writer."""

    classifications: list[SpineClassification] = Field(default_factory=list)
    observations: list[Observation] = Field(default_factory=list)
    probes: list = Field(default_factory=list)  # list[AnalyserReconRequest]
    system_edges: list = Field(default_factory=list)  # list[SystemEdgeDelta]


# --- webpage-profile skill (FR-SPINE) -----------------------------------------

class WebpageProfileProposal(BaseModel):
    """The webpage-profile LLM's structured output. `navigation_*` and
    `rendering_*` are DELIBERATELY separate fields (the two dimensions are
    independent, L1D-31a; the model classifies each on its own signals). Each
    carries its own confidence, verbatim evidence, and a `*_fingerprint_only`
    honesty flag the runner enforces against."""

    navigation_model: Literal["SPA", "MPA", "Hybrid"]
    navigation_confidence: Literal["High", "Medium", "Low"]
    navigation_evidence: str
    navigation_fingerprint_only: bool = False
    rendering_model: Literal["CSR", "SSR", "SSG", "StreamingSSR", "HydratedSSR"]
    rendering_confidence: Literal["High", "Medium", "Low"]
    rendering_evidence: str
    rendering_fingerprint_only: bool = False
    probe_reason: str | None = None  # why deeper live interaction is needed, if it is


def _steel_available(override: bool | None) -> bool:
    if override is not None:
        return override
    return bool(os.environ.get("STEEL_API_KEY"))


def _enforce_fingerprint_insufficiency(cls: SpineClassification) -> tuple[SpineClassification, bool]:
    """L1D-31a structural backstop: a framework fingerprint alone is NEVER
    sufficient, so a fingerprint-only classification is forced to Low confidence
    (not merely below High) and always demands a corroborating probe. Returns the
    (possibly downgraded) classification and whether a probe is now required."""
    if cls.fingerprint_only:
        if cls.confidence != "Low":
            cls = cls.model_copy(update={"confidence": "Low"})
        return cls, True  # fingerprint-only always requires a corroborating probe
    return cls, False


def _webpage_observation(cls: SpineClassification, base_url: str | None) -> Observation:
    """Leg 2: the corroborating signals recorded verbatim as an NL Observation,
    anchored to the target BaseURL (a broad, allowlisted anchor)."""
    return Observation(
        macro_kind="webpage_profile",
        severity="info",
        evidence=cls.evidence,
        rationale=f"{cls.slot} := {cls.value} (confidence {cls.confidence})",
        anchor={"type": "BaseURL", "identity": {"url": base_url or ""}},
        source_job=f"anatomy:{_SKILL_ID}",
        source_tool=_SKILL_ID,
    )


def _webpage_probe(service_id: str | None, base_url: str | None, requester_id: str, note: str):
    """Leg 3: a backward-recon request for the deeper live signals (Document-vs-
    Fetch, frameNavigated) that passive L0 signals cannot settle. origin=
    anatomy_skill so the result routes back to this skill (interface-B). `note`
    carries WHY the probe was raised + which spine slot(s) it must settle."""
    from polymerhus.recon.control.targeted import AnalyserReconRequest, ReconScope

    return AnalyserReconRequest(
        job=_DEEP_PROBE_JOB,
        scope=ReconScope(unit_id=service_id, targets=[base_url] if base_url else [], note=note),
        origin="anatomy_skill",
        skill_id=_SKILL_ID,
        requester_id=requester_id,
    )


_WEBPAGE_FALLBACK_PROMPT = (
    "You are the webpage-profile system-anatomy skill. Classify the TWO INDEPENDENT "
    "dimensions navigation_model (SPA|MPA|Hybrid) and rendering_model "
    "(CSR|SSR|SSG|StreamingSSR|HydratedSSR) from the given signals. The dimensions "
    "are independent - never infer one from the other (an SPA may be SSR-rendered). "
    "A framework fingerprint alone (e.g. __NEXT_DATA__, id=root) is NEVER sufficient: "
    "set the corresponding *_fingerprint_only=true and confidence=Low when only a "
    "fingerprint supports the call. Give verbatim evidence for each."
)


def _load_webpage_skill() -> str:
    from polymerhus.recon.domain.skills import skill_for
    return skill_for("analysis/anatomy/webpage-profile", fallback=_WEBPAGE_FALLBACK_PROMPT)


def default_webpage_profile_fn(signals: dict) -> WebpageProfileProposal:
    """Real collaborator: ask the analyser-role LLM to classify the webpage profile
    from `signals`, guided by the webpage-profile skill. Structured output via
    function_calling (same pattern as the analyser)."""
    from langchain_core.messages import SystemMessage, HumanMessage
    from polymerhus.app.llm.roles import chat_model_for

    llm = chat_model_for("analyser")
    structured = llm.with_structured_output(WebpageProfileProposal, method="function_calling")
    prompt = (
        "Classify the webpage profile from these runtime signals. Remember: the two "
        "dimensions are INDEPENDENT and a fingerprint alone is never sufficient.\n\n"
        f"Signals: {signals}"
    )
    return structured.invoke([SystemMessage(content=_load_webpage_skill()),
                              HumanMessage(content=prompt)])


def webpage_profile(
    signals: dict,
    *,
    service_id: str | None = None,
    requester_id: str = "anatomy:webpage_profile",
    profile_fn=None,
    steel_available: bool | None = None,
) -> AnatomyResult:
    """Run the webpage-profile anatomy skill over `signals`, returning the triple
    (classifications -> spine slots, observations, probes). Structurally enforces
    L1D-31a: the two dimensions are emitted as SEPARATE independent classifications,
    and a fingerprint-only classification is capped below High + raises a probe.
    Fail-open: an LLM error degrades to an empty result. `profile_fn(signals) ->
    WebpageProfileProposal` is injectable for testing."""
    if profile_fn is None:
        profile_fn = default_webpage_profile_fn
    try:
        p = profile_fn(signals)
    except Exception as exc:  # fail-open: a skill/LLM error never crashes the caller
        logger.warning("webpage_profile: skill failed for service=%s; empty result", service_id, exc_info=True)
        return AnatomyResult()

    nav = SpineClassification(slot="navigation_model", value=p.navigation_model,
                              confidence=p.navigation_confidence, evidence=p.navigation_evidence,
                              fingerprint_only=p.navigation_fingerprint_only)
    ren = SpineClassification(slot="rendering_model", value=p.rendering_model,
                              confidence=p.rendering_confidence, evidence=p.rendering_evidence,
                              fingerprint_only=p.rendering_fingerprint_only)

    classifications = []
    probe_slots: list[str] = []  # which spine slots the probe must settle (N3)
    for cls in (nav, ren):
        cls, needs_probe = _enforce_fingerprint_insufficiency(cls)
        if needs_probe:
            probe_slots.append(cls.slot)
        classifications.append(cls)
    probe_needed = bool(p.probe_reason) or bool(probe_slots)

    base_url = signals.get("base_url")
    observations = [_webpage_observation(c, base_url) for c in classifications]

    probes = []
    if probe_needed:
        reason = p.probe_reason or "fingerprint-only classification needs live corroboration (L1D-31a)"
        if probe_slots:  # name the slot(s) that triggered it so the routed result knows what to refine
            reason = f"{reason} [settle: {', '.join(probe_slots)}]"
        # the deeper probe rides the Steel/CDP path; emit the request regardless of
        # the STEEL_API_KEY gate (its live execution is the unbuilt dep). Record the
        # gate state for the caller.
        probe = _webpage_probe(service_id, base_url, requester_id, reason)
        probes.append(probe)
        if not _steel_available(steel_available):
            logger.info("webpage_profile: deeper probe emitted but STEEL_API_KEY absent; "
                        "it will degrade until the CDP tap is available")

    return AnatomyResult(classifications=classifications, observations=observations, probes=probes)


def commit_anatomy(
    result: AnatomyResult,
    project_id: str,
    business_function_slug: str,
    *,
    provenance=None,
    curate_fn=None,
    observe_fn=None,
    edge_fn=None,
) -> dict:
    """Write the triple: leg 1 (classifications -> their correct L1 home via the
    l1_curator sole-writer; typed system_edges -> the l1_curator system-edge
    writer), leg 2 (observations -> the L0 curator seam). Leg 3 (probes) is
    RETURNED for the caller to dispatch via request_targeted_recon (kept out of the
    write path so committing never blocks on a live probe). Fail-open per leg.

    Leg 1 routing (the mechanism-as-System correction): the web-presentation
    dimensions (`rendering_model`, `navigation_model`) are cross-cutting MECHANISM
    classifications, so they are written as INDEPENDENT props on a `WebPresentation`
    System the Service is `EXPOSED_VIA` - NEVER as Service props, and neither is
    inferred from the other (L1D-31a). Any other classification (e.g. the authz
    skill's `authz_model`, a Service-level contract facet) stays a Service prop."""
    from polymerhus.analysis.l1_types import (
        Provenance, ServiceDelta, SystemDelta, SystemEdgeDelta,
    )

    if provenance is None:
        provenance = Provenance(job=f"anatomy:{_SKILL_ID}", model=None, prompt_id=None)

    # partition the classifications by their correct L1 home.
    webpres_props: dict = {}
    service_props: dict = {}
    for c in result.classifications:
        bucket = webpres_props if c.slot in _WEBPRESENTATION_SLOTS else service_props
        bucket[c.slot] = c.value
        bucket[f"{c.slot}_confidence"] = c.confidence
        bucket[f"{c.slot}_evidence"] = c.evidence

    service_deltas: list = []
    system_deltas: list = []
    presentation_edges: list = []
    if service_props:
        service_deltas.append(ServiceDelta(
            business_function_slug=business_function_slug, props=service_props, provenance=provenance))
    if webpres_props:
        # Phase-B (deepening) home for this WebPresentation profiling path: issue #41.
        # WebPresentation is PER-SERVICE (#9 DP-3 / T1): key its System on the owning
        # service's slug as the discriminator, on BOTH the node AND its EXPOSED_VIA
        # edge - `build_system_edge_cypher` MATCHes the target System on
        # (kind, discriminator), so omitting it here would collapse every service's
        # presentation onto the ONE `__singleton__` node. Only WebPresentation takes
        # the per-service discriminator; shared-System edges (the authz skill's) keep
        # their own `__singleton__`.
        system_deltas.append(SystemDelta(
            kind=WEB_PRESENTATION_KIND, discriminator=business_function_slug,
            props=webpres_props, provenance=provenance))
        presentation_edges.append(SystemEdgeDelta(
            service_slug=business_function_slug, kind=WEB_PRESENTATION_KIND,
            discriminator=business_function_slug, rel="EXPOSED_VIA", provenance=provenance))

    written = {"classifications": 0, "observations": 0, "probes": len(result.probes)}

    # leg 1: classifications -> Service facets AND/OR WebPresentation System props.
    if service_deltas or system_deltas:
        if curate_fn is None:
            from polymerhus.analysis import l1_curator
            def curate_fn(services, systems, project_id):  # noqa: E306
                return l1_curator.l1_curate(services, systems, project_id)
        try:
            curate_fn(service_deltas, system_deltas, project_id)
            written["classifications"] = len(result.classifications)
        except Exception:  # fail-open
            logger.warning("commit_anatomy: classification write failed for %s", business_function_slug, exc_info=True)

    # leg 2: evidence observations via the L0 curator seam
    if result.observations:
        if observe_fn is None:
            from polymerhus.recon.domain import curator
            def observe_fn(observations, project_id):  # noqa: E306
                return curator.curate([], observations, project_id)
        try:
            observe_fn(result.observations, project_id)
            written["observations"] = len(result.observations)
        except Exception:  # fail-open
            logger.warning("commit_anatomy: observation write failed for %s", business_function_slug, exc_info=True)

    # leg 1b: typed Service->System edges (the authz skill's AUTHORIZED_BY {role} /
    # AUTHENTICATED_BY {realm} edges PLUS the WebPresentation EXPOSED_VIA edge) via
    # the L1 sole-writer's system-edge writer - structural, MERGE-idempotent.
    edges = list(result.system_edges) + presentation_edges
    written["system_edges"] = 0
    if edges:
        if edge_fn is None:
            from polymerhus.analysis import l1_curator
            def edge_fn(system_edges, project_id):  # noqa: E306
                return l1_curator.enrich(project_id, system_edges=system_edges)
        try:
            counts = edge_fn(edges, project_id)
            written["system_edges"] = (counts or {}).get("system_edges", len(edges)) \
                if isinstance(counts, dict) else len(edges)
        except Exception:  # fail-open
            logger.warning("commit_anatomy: system-edge write failed for %s", business_function_slug, exc_info=True)

    return written


# --- authorization-pyramid skill (FR-AUTHZSKILL) ------------------------------

_AUTHZ_SKILL_ID = "authorization_pyramid"
# Re-issue the SAME action under each role's credentials; httpx is a use_auth
# request tool, so the interface-B executor threads scope.auth_context onto it.
_AUTHZ_PROBE_JOB = "httpx"


def _load_authz_skill() -> str:
    from polymerhus.recon.domain.skills import skill_for
    return skill_for("analysis/anatomy/authorization-pyramid", fallback=(
        "You are the authorization-pyramid anatomy skill. Reverse-engineer the "
        "role->permission structure by probing the SAME service action under "
        "DIFFERENT roles (the inverse-pyramid probe), carrying each role's own "
        "auth_context. Record which roles are authorised as typed AUTHORIZED_BY "
        "{role} edges and each realm as AUTHENTICATED_BY {realm} - structurally, "
        "never as prose. You record who CAN act, not who SHOULD (that is downstream)."
    ))


def plan_authz_probes(
    action: str,
    roles,
    auth_context: dict | None,
    *,
    service_slug: str | None = None,
    requester_id: str = "anatomy:authorization_pyramid",
):
    """The inverse-pyramid probe (leg 3): for EACH role, emit an interface-B
    request that re-issues the same `action` (a target URL/handle) carrying THAT
    role's SELECTED credentials (select_auth_context). origin=anatomy_skill so each
    result routes back to this skill. Returns a list[AnalyserReconRequest]."""
    from polymerhus.recon.control.auth import select_auth_context
    from polymerhus.recon.control.targeted import AnalyserReconRequest, ReconScope

    probes = []
    for role in roles:
        creds = select_auth_context(auth_context, role)
        probes.append(AnalyserReconRequest(
            job=_AUTHZ_PROBE_JOB,
            scope=ReconScope(
                unit_id=service_slug, targets=[action], auth_context=creds or None,
                note=f"authz inverse-pyramid probe: '{action}' as role '{role}'",
            ),
            origin="anatomy_skill", skill_id=_AUTHZ_SKILL_ID, requester_id=requester_id,
        ))
    return probes


def classify_authz(
    action: str,
    results: dict,
    *,
    service_slug: str,
    role_realms: dict | None = None,
    base_url: str | None = None,
    provenance=None,
) -> AnatomyResult:
    """From per-role outcomes `results` (role -> allowed bool), build the STRUCTURAL
    authz result: an `AUTHORIZED_BY {role}` typed system-edge (Service ->
    AuthorizationSystem) for each authorised role, an `AUTHENTICATED_BY {realm}`
    edge (-> AuthenticationMechanism) per distinct realm, an `authz_model` spine
    classification, and an evidence Observation recording authorised vs denied
    roles. Records who CAN act (structural facts); privilege judgment is Stage-3."""
    from polymerhus.analysis.l1_types import Provenance, SystemEdgeDelta

    if provenance is None:
        provenance = Provenance(job=f"anatomy:{_AUTHZ_SKILL_ID}", model=None, prompt_id=None)
    role_realms = role_realms or {}

    authorized = sorted(r for r, ok in results.items() if ok)
    denied = sorted(r for r, ok in results.items() if not ok)

    system_edges = [
        SystemEdgeDelta(service_slug=service_slug, kind="AuthorizationSystem",
                        rel="AUTHORIZED_BY", role=role, provenance=provenance)
        for role in authorized
    ]
    for realm in sorted({rl for rl in role_realms.values() if rl}):
        system_edges.append(SystemEdgeDelta(
            service_slug=service_slug, kind="AuthenticationMechanism",
            rel="AUTHENTICATED_BY", realm=realm, provenance=provenance))

    # authz_model = a STRUCTURAL fact about the probed role set (not a judgment)
    if not authorized:
        model = "locked"           # no probed role could perform it
    elif not denied:
        model = "unrestricted"     # every probed role could
    else:
        model = "role-restricted"  # some roles gated out
    evidence = f"action '{action}': authorized={authorized} denied={denied}"
    classification = SpineClassification(
        slot="authz_model", value=model, confidence="High", evidence=evidence)
    obs = Observation(
        macro_kind="authorization_pyramid", severity="info", evidence=evidence,
        rationale=f"authz_model := {model}",
        anchor={"type": "BaseURL", "identity": {"url": base_url or ""}},
        source_job=f"anatomy:{_AUTHZ_SKILL_ID}", source_tool=_AUTHZ_SKILL_ID)

    return AnatomyResult(classifications=[classification], observations=[obs],
                         system_edges=system_edges)
