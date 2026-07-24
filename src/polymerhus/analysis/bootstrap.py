"""FR-ELICIT — bootstrap the L1 Service skeleton from the operator KB.

Step 1 of the analyser pipeline (spec §7.2): before any recon surface exists, the
operator's free-text solution architecture (`settings.recon.operator_kb`) is
projected into an L1 **Service skeleton** — business-function Services plus the
**linchpin auth Systems** (authentication mechanism + authorization system) that
everything later extends. This is a *pure business projection*: it needs no
surface and writes **no L0 references** (no AGGREGATES). Assignment (attaching L0
elements to these Services) is the analyser subgraph's job, later.

`operator_kb` is free text for now (operator decision 2026-07-16); a typed
service-contract template is an after-MVP enhancement (AMV-4). Fail-open
throughout: an LLM or write failure degrades to an empty/partial skeleton and
never raises into the caller.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from polymerhus.analysis.analyser_types import (
    L1DeltaBatch,
    ServiceProposal,
    SystemProposal,
    proposals_to_deltas,
)
from polymerhus.analysis.l1_types import L1_SINGLETON, Provenance

logger = logging.getLogger(__name__)

# The linchpin auth Systems that the bootstrap always ensures exist, regardless
# of what the LLM elicits (spec §7.2: "linchpin System nodes (authentication,
# authorization) that everything later extends"). Deterministic so the skeleton
# never lacks the two systems the authorization-pyramid / auth skills extend.
_LINCHPIN_SYSTEMS = ("AuthenticationMechanism", "AuthorizationSystem")


class BootstrapExport(BaseModel):
    """Result of a bootstrap: how many L1 skeleton nodes were written.

    Increment 2b (#26): `blocked` is the FAIL-CLOSED signal - True when the
    Bootstrapper could not produce a skeleton (retry exhausted on either call, or
    a write failure) and the analysis MUST NOT proceed (the downstream data
    dependency is unmet). Distinct from an empty-but-valid bootstrap (empty KB ->
    linchpins-only, `blocked=False`)."""

    services_written: int = 0
    systems_written: int = 0
    error: str | None = None
    blocked: bool = False


_BOOTSTRAP_INSTRUCTION = (
    "This is the BOOTSTRAP step: you are given the operator's free-text solution "
    "architecture / knowledge base, NOT a recon surface. Project it into the L1 "
    "business skeleton: propose the business-function `services` (sign-in, "
    "checkout, orders, reward-points, cart, reviews, product-introspection, "
    "sales-analysis, ...) and any cross-cutting `systems` the text clearly implies. "
    "Emit NO `aggregates` - there is no Layer-0 surface to assign yet. Propose only "
    "business functions the text actually supports; return empty lists if it "
    "supports none."
)


def default_elicit_fn(operator_kb: str, *, service_slugs: list[str] | None = None) -> L1DeltaBatch:
    """Real collaborator: ask the analyser LLM to elicit the Service skeleton from
    the operator KB. Reuses the analyser role + skill (same structured-output
    pattern as default_analyse_fn); the KB text is the whole input.

    FR-INVENTORY: `service_slugs` are the CURRENT L1 Service identities; rendered
    as the un-truncated EXISTING L1 IDENTITIES reuse block at the top so a
    re-bootstrap reuses an existing slug instead of coining a synonym."""
    from langchain_core.messages import SystemMessage, HumanMessage

    from polymerhus.app.llm.roles import chat_model_for
    from polymerhus.analysis.l1_curator import vocabulary_prompt
    from polymerhus.analysis.pod import (
        _invoke_with_retry,
        _inventory_block,
        _load_analyser_skill,
    )

    llm = chat_model_for("analyser")
    structured_llm = llm.with_structured_output(L1DeltaBatch, method="function_calling")
    inventory = {"services": service_slugs or [], "systems": [], "data_items": []}
    prompt = (
        f"{_inventory_block(inventory)}\n\n{_BOOTSTRAP_INSTRUCTION}\n\n"
        f"{vocabulary_prompt()}\n\nOperator KB (free text):\n{operator_kb}"
    )
    messages = [SystemMessage(content=_load_analyser_skill()), HumanMessage(content=prompt)]
    # Bounded retry, exactly as the analyser pod does. `with_structured_output`
    # intermittently returns None or raises on a truncated provider response
    # (observed live: deepseek returned malformed JSON mid-elicitation). Without
    # the retry a single transient zeroes the ENTIRE bootstrap skeleton - the
    # fail-open then yields services=0 and every downstream stage runs against an
    # empty L1, which looks like a modelling failure rather than a provider blip.
    return _invoke_with_retry(structured_llm.invoke, messages)


def bootstrap_from_kb(
    project_id: str,
    operator_kb: str,
    *,
    run_id: str = "bootstrap",
    elicit_fn=None,
    curate_fn=None,
) -> BootstrapExport:
    """Elicit the Service skeleton from `operator_kb` and write it (services +
    linchpin auth Systems, NO L0 refs) through the L1 sole-writer. Idempotent
    (l1_curate MERGEs on identity). Fail-open.

    `elicit_fn(operator_kb) -> L1DeltaBatch` and
    `curate_fn(services, systems, project_id) -> (int, int)` are injected
    (defaulting to the analyser LLM and l1_curator) so this is testable without a
    live LLM/DB.
    """
    if not operator_kb or not operator_kb.strip():
        logger.info("bootstrap_from_kb: empty operator_kb for project=%s; nothing to elicit", project_id)
        # still ensure the linchpin systems + kind catalogue exist (below)
        batch = L1DeltaBatch()
    else:
        if elicit_fn is None:
            # FR-INVENTORY: seed the default elicitation with the CURRENT service
            # slugs so a re-bootstrap reuses existing identities instead of coining
            # synonyms. read_l1_inventory is fail-open (empty on any read error).
            from polymerhus.analysis.l1_inventory import read_l1_inventory
            _slugs = read_l1_inventory(project_id).get("services", [])

            def elicit_fn(kb):
                return default_elicit_fn(kb, service_slugs=_slugs)
        try:
            batch = elicit_fn(operator_kb)
        except Exception as exc:  # fail-open: an LLM error degrades to no elicited skeleton
            logger.warning("bootstrap_from_kb: elicit (LLM) failed for project=%s", project_id, exc_info=True)
            return BootstrapExport(error=f"elicit: {exc}")
        if batch is None:
            # The bounded retry returns None when EVERY attempt failed. Without this
            # guard that None reaches `batch.systems` below and raises AttributeError
            # straight out of a function contracted to be fail-open. It must also not
            # be mistaken for a successful-but-empty elicitation: an exhausted retry
            # is a provider failure and has to say so, or a run silently proceeds on
            # an empty skeleton and the emptiness gets blamed on the model.
            logger.warning(
                "bootstrap_from_kb: elicit returned no batch after retries for project=%s", project_id
            )
            return BootstrapExport(error="elicit: LLM returned no parseable batch after retries")

    # Always ensure the two linchpin auth Systems exist, whether or not the LLM
    # elicited them (dedup is handled by the singleton MERGE, so adding them when
    # the LLM already proposed them is harmless).
    elicited_kinds = {s.kind for s in batch.systems}
    linchpins = [SystemProposal(kind=k) for k in _LINCHPIN_SYSTEMS if k not in elicited_kinds]
    batch = batch.model_copy(update={"systems": list(batch.systems) + linchpins})

    provenance = Provenance(job=f"bootstrap:{run_id}", model=None, prompt_id=None)
    # Bootstrap is a pure business projection: drop any aggregates the LLM emitted
    # (no L0 surface exists yet) so no AGGREGATES edge is written here.
    services, systems, _aggregates_dropped = proposals_to_deltas(batch, provenance)

    if curate_fn is None:
        from polymerhus.analysis import l1_curator
        # No catalogue seeding: a System's kind is a plain `kind` attribute validated
        # against l1_curator.SYSTEM_KINDS (operator correction 2026-07-20), so there
        # is no `:SystemKind` catalogue to seed.
        def curate_fn(svc, sysd, pid):
            return l1_curator.l1_curate(svc, sysd, pid)

    try:
        services_written, systems_written = curate_fn(services, systems, project_id)
    except Exception as exc:  # fail-open: a write failure never crashes the caller
        logger.warning("bootstrap_from_kb: curate failed for project=%s", project_id, exc_info=True)
        return BootstrapExport(error=f"curate: {exc}")

    return BootstrapExport(services_written=services_written, systems_written=systems_written)


def run_bootstrap(project_id: str, *, load_settings_fn=None, **kwargs) -> BootstrapExport:
    """Convenience: read `operator_kb` from the project's settings and bootstrap.
    `load_settings_fn(project_id) -> dict` defaults to pg.load_settings."""
    if load_settings_fn is None:
        from polymerhus.app.clients import pg
        load_settings_fn = pg.load_settings
    settings = load_settings_fn(project_id) or {}
    operator_kb = settings.get("operator_kb") or ""
    return bootstrap_from_kb(project_id, operator_kb, **kwargs)


# ==============================================================================
# Increment 2b (#26): the grilled reasoning+prompt redesign - API surface.
# Stubs raise NotImplementedError so the /to-assertions catalogue (#26) collects,
# executes, and fails for the predicate's reason (the path is not built yet); the
# build fills these. The existing bootstrap_from_kb above stays intact until the
# redesign supersedes it (kept green through the transition).
# ==============================================================================

# The 3 forced linchpin auth-identity Systems (#26 Q8): the identify / authenticate
# / authorize triad every later auth skill extends. Expanded from 2 to 3.
_LINCHPIN_SYSTEMS_V2 = ("IdentificationSystem", "AuthenticationMechanism", "AuthorizationSystem")

# Exposure-only baseline (#26 Q7, mirrors the Assigner #8 / bootstrap #7 allowlist):
# a minted Service keeps ONLY a validated `exposure`; everything else is dropped.
_EXPOSURE_VALUES = frozenset({"public", "authenticated"})
_REASON_ATTEMPTS = 3


class ServiceShell(BaseModel):
    """Call-2 per-Service elicitation shell (#26 Q7): bootstrap fills
    `business_function_slug` + `exposure`; the phase-A.1 attributes are PRESENT but
    EMPTIED (label/salience/aggregates/exposed_via/data_flows/surfaces_at), owned by
    the later proposers. Mapped DOWN to a `ServiceProposal` (exposure-only props;
    the empty A.1 slots are NOT persisted - absence means not-yet-filled)."""

    business_function_slug: str
    # permissive on purpose (#7 fork B: the LLM strays) - the exposure-only allowlist
    # {public, authenticated} is enforced as defense-in-depth in shells_to_batch.
    exposure: str | None = None
    # phase-A.1 attributes, present-but-emptied (never filled at bootstrap):
    label: str | None = None
    salience: str | None = None
    aggregates: list = Field(default_factory=list)
    exposed_via: list = Field(default_factory=list)
    data_flows: list = Field(default_factory=list)
    surfaces_at: list = Field(default_factory=list)


class SystemShell(BaseModel):
    """Call-2 per-System elicitation shell (#26 Q8): bootstrap fills `kind` (in
    SYSTEM_KINDS) + `discriminator`. `claim` is a TRANSIENT hypothesis rationale
    (Langfuse, never persisted). The AuthorizationSystem EXCEPTION carries a
    shallow KB-sourced `roles`/`realms` vocabulary (its pyramid skeleton), with NO
    edges; every other spine slot is A.1-emptied."""

    kind: str
    discriminator: str = "__singleton__"
    claim: str | None = None  # transient -> Langfuse only, not persisted
    roles: list[str] = Field(default_factory=list)   # AuthorizationSystem only
    realms: list[str] = Field(default_factory=list)  # AuthorizationSystem only


class BootstrapElicitation(BaseModel):
    """Call-2 structured output: the Service + System shells extracted from call-1's
    free-text reasoning. Every list defaults empty so a 'nothing to add' extraction
    is a valid, well-typed result."""

    services: list[ServiceShell] = Field(default_factory=list)
    systems: list[SystemShell] = Field(default_factory=list)


def shells_to_batch(
    service_shells: list[ServiceShell], system_shells: list[SystemShell]
) -> L1DeltaBatch:
    """Map the call-2 shells DOWN to the sole-writer's `L1DeltaBatch` (#26 Q7/Q8).

    Services -> exposure-only props (invalid/None exposure -> empty props; label /
    salience / any A.1 slot dropped and NOT persisted - absence means not-yet-filled).
    Systems -> kind + discriminator; the AuthorizationSystem carries its shallow
    KB-sourced `roles`/`realms` vocabulary; the transient `claim` is dropped; NO
    `system_edges` are emitted at bootstrap. The 3 linchpins are FORCED (added if the
    LLM omitted them), deduped by (kind, discriminator)."""
    services = []
    for sh in service_shells:
        props = {"exposure": sh.exposure} if sh.exposure in _EXPOSURE_VALUES else {}
        services.append(ServiceProposal(business_function_slug=sh.business_function_slug, props=props))

    systems = []
    seen: set[tuple[str, str]] = set()
    for sh in system_shells:
        key = (sh.kind, sh.discriminator)
        if key in seen:  # singleton dedup
            continue
        seen.add(key)
        props: dict = {}
        if sh.kind == "AuthorizationSystem":  # the KB-sourced pyramid vocabulary (shallow, no edges)
            if sh.roles:
                props["roles"] = list(sh.roles)
            if sh.realms:
                props["realms"] = list(sh.realms)
        systems.append(SystemProposal(kind=sh.kind, discriminator=sh.discriminator, props=props))

    for kind in _LINCHPIN_SYSTEMS_V2:  # force the triad regardless of the LLM
        if (kind, L1_SINGLETON) not in seen:
            seen.add((kind, L1_SINGLETON))
            systems.append(SystemProposal(kind=kind))

    # aggregates / system_edges / data lists default EMPTY on L1DeltaBatch -> the
    # A.1 attributes are never persisted at bootstrap.
    return L1DeltaBatch(services=services, systems=systems)


def bootstrap_reasoned(
    project_id: str,
    operator_kb: str,
    *,
    run_id: str = "bootstrap",
    reason_fn=None,
    extract_fn=None,
    curate_fn=None,
    service_slugs: list[str] | None = None,
) -> BootstrapExport:
    """The redesigned two-call Bootstrapper (#26): call 1 (`reason_fn`) runs the
    free-text 5-step reasoning over the KB; call 2 (`extract_fn`) extracts the
    Service/System shells FROM that reasoning; the shells map down through the
    sole-writer, the 3 linchpins are forced, and the reasoning trace is traced to
    Langfuse (transient).

    FAIL-CLOSED (#26 Q6): a bounded retry per call; on retry exhaustion of EITHER
    call, or a write failure, return `BootstrapExport(blocked=True)` - the analysis
    must halt (the downstream data dependency is unmet). An empty `operator_kb` is a
    valid proceed (linchpins-only, `blocked=False`), never a block.
    `reason_fn(operator_kb, service_slugs) -> reasoning`,
    `extract_fn(reasoning) -> (service_shells, system_shells)`, and
    `curate_fn(services, systems, project_id) -> (int, int)` are injected."""
    from polymerhus.analysis.proposer_reasoning import bounded_retry

    if reason_fn is None:
        reason_fn = default_reason_fn
    if extract_fn is None:
        extract_fn = default_extract_fn
    if curate_fn is None:
        from polymerhus.analysis import l1_curator

        def curate_fn(svc, sysd, pid):
            return l1_curator.l1_curate(svc, sysd, pid)

    if service_slugs is None:
        # FR-INVENTORY: thread the CURRENT Service slugs into call 1 so a re-bootstrap
        # REUSES existing identities instead of coining synonyms (suppresses the AMV-12
        # drift a non-deterministic LLM otherwise accumulates run-to-run).
        # read_l1_inventory is fail-open (empty on any read error).
        from polymerhus.analysis.l1_inventory import read_l1_inventory

        service_slugs = read_l1_inventory(project_id).get("services", [])

    service_shells: list[ServiceShell] = []
    system_shells: list[SystemShell] = []

    # Empty KB is a valid minimal bootstrap (linchpins-only), NOT a block: no LLM call.
    if operator_kb and operator_kb.strip():
        reasoning = bounded_retry(lambda: reason_fn(operator_kb, service_slugs), attempts=_REASON_ATTEMPTS)
        if reasoning is None:  # FAIL-CLOSED: call-1 exhausted -> block the analysis
            logger.warning("bootstrap_reasoned: call-1 (reason) exhausted for project=%s; BLOCKING", project_id)
            return BootstrapExport(blocked=True, error="reason: exhausted after retries")
        logger.debug("bootstrap_reasoned: call-1 reasoning (project=%s, run=%s) traced", project_id, run_id)

        extracted = bounded_retry(lambda: extract_fn(reasoning), attempts=_REASON_ATTEMPTS)
        if extracted is None:  # FAIL-CLOSED: call-2 exhausted -> block
            logger.warning("bootstrap_reasoned: call-2 (extract) exhausted for project=%s; BLOCKING", project_id)
            return BootstrapExport(blocked=True, error="extract: exhausted after retries")
        service_shells, system_shells = extracted

    batch = shells_to_batch(service_shells, system_shells)
    provenance = Provenance(job=f"bootstrap:{run_id}", model=None, prompt_id=None)
    # Bootstrap is a pure business projection: proposals_to_deltas drops aggregates.
    services, systems, _aggregates_dropped = proposals_to_deltas(batch, provenance)

    try:
        services_written, systems_written = curate_fn(services, systems, project_id)
    except Exception as exc:  # FAIL-CLOSED: a write failure means no skeleton -> block
        logger.warning("bootstrap_reasoned: curate failed for project=%s; BLOCKING", project_id, exc_info=True)
        return BootstrapExport(blocked=True, error=f"curate: {exc}")

    return BootstrapExport(services_written=services_written, systems_written=systems_written)


# --- default two-call collaborators (the real LLM path; the prompt redesign) ---

_BOOTSTRAP_ROLE = (
    "a solution architect projecting an operator's free-text solution architecture "
    "into the L1 business-function Service/System skeleton, before any recon surface exists"
)
_BOOTSTRAP_GOAL = (
    "an exhaustive, well-grounded, breadth-leaning skeleton in which EVERY Service is "
    "grounded in specific KB evidence - reflecting THIS architecture, never a template"
)
_BOOTSTRAP_STEPS = [
    "ARCHITECT-DECOMPOSE: break the KB into its distinct business-function components "
    "and the cross-cutting systems it implies; separate what the text STATES from what "
    "you are assuming.",
    "EXPAND-CANDIDATES: widen laterally to adjacent/implied business functions (lean "
    "toward breadth - a missed Service is costlier than an over-proposed one).",
    "HYPOTHESIS + GROUND: for EACH candidate, state a falsifiable claim tied to a "
    "SPECIFIC KB span; classify its exposure (public / authenticated) from KB signals, "
    "or omit exposure when the KB is silent (never guess).",
    "CRITICAL-CHECK / WITHHOLD: drop ONLY candidates with NO KB support; surface what "
    "is missing or merely assumed. Non-obvious Systems are CLAIM-BASED - record them as "
    "shallow hypotheses, and give the AuthorizationSystem its KB-sourced role/realm "
    "vocabulary (no per-service bindings - those need surface).",
    "DECIDE + REUSE: commit to the grounded skeleton, REUSING an existing inventory "
    "slug over coining a synonym.",
]

# Two DIVERGENT-domain few-shot CoT exemplars (#26 Q4): neither ecommerce nor a likely
# target, so they cancel each other's domain anchoring. Each shows the 5-step trace
# with a WITHHELD candidate, an exposure CLASSIFIED, and an exposure OMITTED.
_FEW_SHOT = [
    (
        "KB: 'A B2B payments platform. Merchants onboard and manage payout accounts "
        "(login required). A public developer docs portal. Settlement runs nightly.'\n"
        "1. Decompose -> business functions: merchant-onboarding, payout-account-management, "
        "developer-docs; cross-cutting: an AuthenticationMechanism (merchant login), an "
        "AuthorizationSystem (merchant vs support roles). Assumed (not stated): a fraud engine.\n"
        "2. Expand -> settlement-processing is implied by 'settlement runs nightly'.\n"
        "3. Ground -> merchant-onboarding [KB: 'Merchants onboard'] exposure=authenticated; "
        "payout-account-management [KB: 'manage payout accounts (login required)'] "
        "exposure=authenticated; developer-docs [KB: 'public developer docs portal'] "
        "exposure=public; settlement-processing [KB: 'Settlement runs nightly'] exposure OMITTED "
        "(the KB never says who reaches it).\n"
        "4. Withhold -> the 'fraud engine' was only my assumption, NO KB span supports it: DROP. "
        "AuthorizationSystem roles from the KB: [merchant, support].\n"
        "5. Decide -> services: merchant-onboarding(auth), payout-account-management(auth), "
        "developer-docs(public), settlement-processing(no exposure). Systems: linchpins + "
        "AuthorizationSystem{roles:[merchant, support]}."
    ),
    (
        "KB: 'An internal IT-operations console for employees. Engineers file and track "
        "incidents; managers approve change requests. SSO via the corporate IdP.'\n"
        "1. Decompose -> business functions: incident-management, change-approval; cross-cutting: "
        "an AuthenticationMechanism (SSO), an IdentificationSystem, an AuthorizationSystem "
        "(engineer vs manager). Stated: employees-only.\n"
        "2. Expand -> a reporting/dashboard function is plausible but NOT described.\n"
        "3. Ground -> incident-management [KB: 'Engineers file and track incidents'] "
        "exposure=authenticated; change-approval [KB: 'managers approve change requests'] "
        "exposure=authenticated. SSO -> AuthenticationMechanism.\n"
        "4. Withhold -> the reporting/dashboard candidate has NO KB support: DROP. "
        "AuthorizationSystem roles from the KB: [engineer, manager]; realms: [corporate].\n"
        "5. Decide -> services: incident-management(auth), change-approval(auth). Systems: "
        "linchpins + AuthorizationSystem{roles:[engineer, manager], realms:[corporate]}."
    ),
]


def default_reason_fn(operator_kb: str, service_slugs: list[str] | None = None) -> str | None:
    """Call 1 - the free-text 5-step reasoning over the KB, using the reusable
    fragments + the 2 divergent-domain few-shot CoT exemplars + the FR-INVENTORY
    reuse block. Returns the reasoning text (None if the model produced nothing)."""
    from langchain_core.messages import HumanMessage, SystemMessage

    from polymerhus.app.llm.roles import chat_model_for
    from polymerhus.analysis.pod import _inventory_block
    from polymerhus.analysis.proposer_reasoning import cot_scaffold, few_shot_block, role_header

    inventory = {"services": service_slugs or [], "systems": [], "data_items": []}
    system = role_header(_BOOTSTRAP_ROLE, _BOOTSTRAP_GOAL)
    human = (
        f"{cot_scaffold(_BOOTSTRAP_STEPS)}\n\n{few_shot_block(_FEW_SHOT)}\n\n"
        f"{_inventory_block(inventory)}\n\nOperator KB (free text):\n{operator_kb}\n\n"
        "Now produce YOUR reasoning for this KB, following the 5 steps."
    )
    result = chat_model_for("analyser").invoke([SystemMessage(content=system), HumanMessage(content=human)])
    text = getattr(result, "content", None)
    return text or None


def default_extract_fn(reasoning: str):
    """Call 2 - extract the Service/System shells FROM call-1's reasoning (structured
    output), leaving the phase-A.1 attributes empty. Returns (service_shells,
    system_shells), or None when the model emits no parseable extraction."""
    from langchain_core.messages import HumanMessage, SystemMessage

    from polymerhus.app.llm.roles import chat_model_for

    structured = chat_model_for("analyser").with_structured_output(
        BootstrapElicitation, method="function_calling"
    )
    prompt = (
        "Extract the Service and System SHELLS decided in the reasoning below. For each "
        "Service set ONLY business_function_slug + exposure (public/authenticated, or omit); "
        "leave label/salience/aggregates/exposed_via/data_flows/surfaces_at EMPTY. For each "
        "System set kind + discriminator; give the AuthorizationSystem its roles/realms; leave "
        "other spine slots empty.\n\nREASONING:\n" + reasoning
    )
    result = structured.invoke([
        SystemMessage(content="You extract typed shells from prior reasoning; you never invent beyond it."),
        HumanMessage(content=prompt),
    ])
    if result is None:
        return None
    return list(result.services), list(result.systems)
