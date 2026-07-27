"""FR-ELICIT - bootstrap the L1 Service skeleton from the operator KB.

Step 1 of the analysis (spec §7.2), and a PRE-ANALYSIS PHASE in its own right:
before any recon surface exists, the operator's free-text solution architecture
(`settings.operator_kb`) is projected into an L1 **Service skeleton** -
business-function Services plus the **linchpin auth-identity Systems** that
everything later extends. This is a *pure business projection*: it needs no
surface and writes **no L0 references** (no AGGREGATES). Assignment (attaching L0
elements to these Services) is the Assigner's job, later.

The Bootstrapper is NOT a supervised analyser proposer - it runs once, ahead of
the analysis, and is triggered over the app API (`POST /projects/{id}/bootstrap`),
so a future frontend can ingest the operator's knowledge and kick it off.

`operator_kb` is free text for now (operator decision 2026-07-16); a typed
service-contract template is an after-MVP enhancement (AMV-4).

FAIL-CLOSED on generation (#26 Q6): the skeleton is a hard data dependency for
every later phase, so a retry-exhausted LLM call or a write failure BLOCKS the
analysis (`BootstrapExport.blocked`) rather than degrading to a silently-empty
skeleton whose emptiness then gets misread as a modelling result. An empty
`operator_kb` is NOT a failure - it yields the linchpins-only skeleton and
proceeds.
"""
from __future__ import annotations

import logging
from contextlib import nullcontext
from typing import NamedTuple

from pydantic import BaseModel, Field

from polymerhus.analysis.analyser_types import (
    L1DeltaBatch,
    ServiceProposal,
    SystemProposal,
    proposals_to_deltas,
)
from polymerhus.analysis.l1_types import L1_SINGLETON, Provenance

logger = logging.getLogger(__name__)


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


# The 3 forced linchpin auth-identity Systems (#26 Q8): the identify / authenticate
# / authorize triad every later auth skill extends.
_LINCHPIN_SYSTEMS = ("IdentificationSystem", "AuthenticationMechanism", "AuthorizationSystem")

# The Service props baseline (#26 Q7, mirrors the Assigner #8 allowlist): a minted
# Service keeps ONLY a validated `exposure` + its `service_contract`; every other
# key the LLM hands us (label / salience / any A.1 slot) is DROPPED and never
# persisted, so absence keeps meaning not-yet-filled for the later proposers.
_ALLOWED_SERVICE_PROPS = frozenset({"exposure", "service_contract"})
_EXPOSURE_VALUES = frozenset({"public", "authenticated"})
_REASON_ATTEMPTS = 3

# `service_contract` length cap (#29). A contract is a brief functional PROFILE for
# semantic matching, not documentation: past that length the model has stopped
# profiling and started narrating, and the text stops discriminating between
# Services - which is the one job the contract has. Trimmed, never rejected: a
# too-long contract still carries its discriminating nouns in the first sentences.
_CONTRACT_MAX_CHARS = 600


class _LinchpinService(NamedTuple):
    """One broad umbrella business-function Service the Bootstrapper guarantees on
    the L1 skeleton. A DEFAULT-PENDING-RATIFICATION record (gap-3): `slug` is the
    umbrella identity, `exposure` its forced baseline, `forced` selects HARD-force
    (minted even when the LLM omits it, like the system linchpins) vs PROMPT-PRIOR
    (only carried when the LLM grounds it), `note` is the one-line prompt cue, and
    `contract` is the `service_contract` a HARD-forced row is minted with.

    `note` and `contract` are deliberately DIFFERENT texts (#29). The note is a
    prompt cue and carries adversarial rationale ("where critical auth bugs
    concentrate") - which is `salience`, a Phase-B concern. The contract is the
    routing profile a later Assigner semantically matches endpoint path nouns
    against, so it states domain nouns and actions and nothing else. Collapsing
    them would put adversarial prose into the one field whose whole job is to
    discriminate between business functions."""

    slug: str
    exposure: str  # baseline exposure for a FORCED service (in _EXPOSURE_VALUES)
    forced: bool   # True: hard-force always; False: prompt-prior (grounded proposals only)
    note: str      # rendered into the prompt from this single source (no drift)
    contract: str  # the service_contract minted with a forced row (routing profile)


# Service linchpins (gap-3, operator-CRITICAL; DEFAULT-PENDING-RATIFICATION): the
# BROAD umbrella business-function Services the Bootstrapper ensures exist, so the
# pre-auth account surface (sign-in / register / password-recovery) is never dropped
# - observed live on the moodique KB, where that surface got absorbed into the
# AuthenticationMechanism System and lost, and it is exactly where critical auth bugs
# (e.g. password-recovery-by-security-question) concentrate. Each is a BROAD umbrella
# that phase-A.2 "service decomposition" (the screaming step) later splits into fine
# leaves (sign-in -> sign-in-sso / sign-in-credential; account-management -> address /
# payment / profile / coupons management), so the linchpin is the umbrella, NEVER a leaf.
# SINGLE SOURCE OF TRUTH (CODING_STANDARD §7): this ONE constant feeds BOTH the forcing
# logic in shells_to_batch AND the prompt text (`_service_linchpin_prompt`), exactly as
# SYSTEM_KINDS feeds both build_system_cypher and vocabulary_prompt.
# GROWING SET (operator, B-Q1): the near-universal business-function umbrellas any
# non-trivial webapp exposes, and where bugs concentrate. Only the pre-auth trio is
# HARD-forced (forced=True, B-Q2); the rest are PROMPT-PRIOR (forced=False) - carried
# only when the KB grounds them, so a headless / minimal target is never injected with a
# surface it lacks. This is a §7 extension point: add a row as new universal surfaces are
# recognised. (The prompt-prior rows are declarative today - the prompt render that would
# cue them is retained-not-wired pending the breadth-safe wiring, see _service_linchpin_prompt.)
# Each `contract` is deliberately domain-GENERIC: these rows are forced without
# reading the KB, so their contract may not name application-specific nouns the way
# an elicited one does. It states the universal actions and records of the surface
# (sign in, reset, credential, session) - enough for an Assigner to match a
# `/login` or `/reset-password` path, and never a guessed path (#29).
_LINCHPIN_SERVICES: tuple[_LinchpinService, ...] = (
    _LinchpinService("sign-in", "public", True,
                     "the pre-auth credential / SSO entry point",
                     "Authenticate an existing account holder and start their session. "
                     "Deals in credentials, login, sign-in, single sign-on and session start."),
    _LinchpinService("register", "public", True,
                     "the pre-auth account-creation surface",
                     "Create a new account from user-supplied details and verify it. "
                     "Deals in registration, sign-up, account creation and verification."),
    _LinchpinService("password-recovery", "public", True,
                     "the pre-auth credential-reset surface (security-question / email reset "
                     "- where critical auth bugs concentrate)",
                     "Let a locked-out account holder prove identity without a password and "
                     "set a new one. Deals in forgotten passwords, reset tokens and links, "
                     "security questions and password change."),
    _LinchpinService("account-management", "authenticated", False,
                     "the post-auth self-service umbrella (address / payment / profile / "
                     "coupons); propose ONLY when the KB grounds a self-service account area",
                     "Let a signed-in account holder view and change what the account holds "
                     "about them. Deals in profile, addresses, saved payment methods and "
                     "account preferences."),
    _LinchpinService("sign-out", "authenticated", False,
                     "the post-auth session-termination ACTION (the solution-profile "
                     "counterpart; the session LIFECYCLE itself is a technical System "
                     "concern, not a Service) - a CSRF / session-fixation surface",
                     "End a signed-in session on request. Deals in sign-out, logout and "
                     "session termination."),
    _LinchpinService("notifications", "authenticated", False,
                     "the notification surface (email / in-app / preferences) - an SSRF / "
                     "template-injection / IDOR-on-preferences surface",
                     "Deliver messages to an account holder and let them choose what they "
                     "receive. Deals in notifications, messages, alerts, subscriptions and "
                     "notification preferences."),
    _LinchpinService("admin-console", "authenticated", False,
                     "the privileged back-office / admin surface - the highest-value "
                     "authorization surface; propose ONLY when the KB grounds a management area",
                     "Let privileged staff administer the application and the records other "
                     "business functions own. Deals in administration, back-office management, "
                     "user and content moderation."),
)


def _service_linchpin_prompt() -> str:
    """Render the service-linchpin umbrellas into the prompt FROM `_LINCHPIN_SERVICES`
    (CODING_STANDARD §7: the ONE constant feeds both this prompt text and the forcing
    in shells_to_batch, so the two can never drift).

    RETAINED-NOT-WIRED (§12): this is currently NOT called by `default_reason_fn` -
    weaving it into the reasoning prompt globally coarsened breadth (a live eval
    collapsed 25/16/20 Services -> 13). The forcing in shells_to_batch guarantees the
    account surface without it; re-wiring a breadth-safe variant is gated on the
    force-vs-prompt-prior ratification (B-Q2). Kept single-sourced + tested (C18) so a
    ratified re-wire is one line."""
    lines = []
    for ls in _LINCHPIN_SERVICES:
        tag = "ALWAYS propose as a broad umbrella" if ls.forced else "propose ONLY when the KB grounds it"
        lines.append(f"  - `{ls.slug}` (exposure {ls.exposure}; {tag}): {ls.note}")
    return (
        "ACCOUNT-SURFACE UMBRELLAS - these BROAD business-function Services are where "
        "critical auth bugs concentrate, and a later phase splits each into fine leaves "
        "(sign-in -> sign-in-sso / sign-in-credential; account-management -> address / "
        "payment / profile management). Propose them as BROAD umbrellas (NEVER the fine "
        "leaves), unless the architecture genuinely lacks them (e.g. authentication is "
        "handled by an external IdP, or a headless B2B API has no self-service surface):\n"
        + "\n".join(lines)
    )


class ServiceShell(BaseModel):
    """Call-2 per-Service elicitation shell (#26 Q7): bootstrap fills
    `business_function_slug` + `exposure` + `service_contract`; the phase-A.1
    attributes are PRESENT but EMPTIED (label/salience/aggregates/exposed_via/
    data_flows/surfaces_at), owned by the later proposers. Mapped DOWN to a
    `ServiceProposal` (the empty A.1 slots are NOT persisted - absence means
    not-yet-filled)."""

    business_function_slug: str
    # permissive on purpose (#7 fork B: the LLM strays) - the exposure-only allowlist
    # {public, authenticated} is enforced as defense-in-depth in shells_to_batch.
    exposure: str | None = None
    # The brief functional profile of the business function (#29): what it does and
    # what it owns, in the application's own domain nouns and action verbs. This is
    # the PRIMARY evidence the cross-layer Assigner (#8) semantically matches
    # endpoint path nouns against, so it is written FOR that consumer. Paths / URLs
    # / parameter names are forbidden in it - the KB never states them, so any path
    # is a guess that would enter the graph looking like evidence.
    service_contract: str | None = None
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


def _known_system_kinds() -> frozenset[str]:
    """The controlled System-kind vocabulary, single-sourced from `l1_curator`
    (CODING_STANDARD §7) so this seam's validation can never drift from the
    sole-writer's. Imported lazily - importing this module must not pull the curator
    (and its driver) in."""
    from polymerhus.analysis.l1_curator import SYSTEM_KINDS

    return frozenset(kind for kind, _desc in SYSTEM_KINDS)


def _clean_contract(raw: str | None) -> str | None:
    """Validate + normalise a `service_contract` (#29): whitespace-collapsed, trimmed
    to `_CONTRACT_MAX_CHARS`, and None when it carries no content.

    Blank-but-present is normalised to None rather than persisted, so an empty string
    can never masquerade as a filled contract: `absence means not-yet-filled` is the
    convention every consumer reads, and an empty-string prop would satisfy a
    presence check while telling the Assigner nothing."""
    if not raw or not raw.strip():
        return None
    text = " ".join(raw.split())  # collapse the model's newlines/indentation
    if len(text) > _CONTRACT_MAX_CHARS:
        text = text[:_CONTRACT_MAX_CHARS].rstrip()
    return text


def _service_props(shell: ServiceShell) -> dict:
    """The POSITIVE props allowlist for a bootstrap-minted Service (#7 fork B, #29).

    Only `exposure` (validated against the enum) and a cleaned `service_contract`
    survive; label / salience / every A.1 slot is DROPPED. Positive rather than
    subtractive on purpose: a new attribute the LLM invents is silently excluded
    instead of silently persisted, so `l1_curator` stays policy-free while the
    baseline holds by construction."""
    props: dict = {}
    if shell.exposure in _EXPOSURE_VALUES:
        props["exposure"] = shell.exposure
    contract = _clean_contract(shell.service_contract)
    if contract:
        props["service_contract"] = contract
    return {k: v for k, v in props.items() if k in _ALLOWED_SERVICE_PROPS}


def shells_to_batch(
    service_shells: list[ServiceShell], system_shells: list[SystemShell]
) -> L1DeltaBatch:
    """Map the call-2 shells DOWN to the sole-writer's `L1DeltaBatch` (#26 Q7/Q8).

    Services -> the allowlisted props `{exposure, service_contract}` (invalid/None
    exposure and a blank contract are omitted; label / salience / any A.1 slot dropped
    and NOT persisted - absence means not-yet-filled).
    Systems -> kind + discriminator; an out-of-vocabulary `kind` is DROPPED with a
    warning; the AuthorizationSystem carries its shallow KB-sourced `roles`/`realms`
    vocabulary; the transient `claim` is dropped; NO `system_edges` are emitted at
    bootstrap. The 3 linchpins are FORCED (added if the LLM omitted them), deduped by
    (kind, discriminator)."""
    services: list[ServiceProposal] = []
    svc_by_slug: dict[str, ServiceProposal] = {}
    for sh in service_shells:
        props = _service_props(sh)
        existing = svc_by_slug.get(sh.business_function_slug)
        if existing is None:  # dedup on Service identity (project_id, business_function_slug)
            sp = ServiceProposal(business_function_slug=sh.business_function_slug, props=props)
            svc_by_slug[sh.business_function_slug] = sp
            services.append(sp)
        else:
            # a duplicate slug: FILL empty slots from a later shell, never CLOBBER a
            # filled one. Applies per-key, so a second shell can contribute a contract
            # to a Service whose exposure the first one set (and vice versa).
            for key, value in props.items():
                if value and not existing.props.get(key):
                    existing.props[key] = value

    # Force the HARD service linchpins (the pre-auth account surface) when the LLM
    # omitted them, so the surface where critical auth bugs concentrate is never dropped
    # (gap-3, observed live on the moodique KB). Mirrors the system-linchpin force below;
    # deduped on Service identity (the LLM's own proposal, incl. an FR-INVENTORY reuse,
    # wins and its exposure + contract are preserved). account-management is PROMPT-PRIOR
    # (forced=False) - a headless B2B API legitimately has no self-service account surface,
    # so blind-forcing it would inject a false Service; it is carried only when the LLM
    # grounds it above. A forced row carries its own `contract` (single-sourced from
    # `_LINCHPIN_SERVICES`) so a forced Service is never contract-less and stays routable.
    for ls in _LINCHPIN_SERVICES:
        if ls.forced and ls.slug not in svc_by_slug:
            sp = ServiceProposal(
                business_function_slug=ls.slug,
                props={"exposure": ls.exposure, "service_contract": ls.contract},
            )
            svc_by_slug[ls.slug] = sp
            services.append(sp)
        elif ls.forced and not svc_by_slug[ls.slug].props.get("service_contract"):
            # the LLM proposed the linchpin but gave it no usable contract: fill from
            # the constant rather than leave the guaranteed surface unroutable.
            svc_by_slug[ls.slug].props["service_contract"] = ls.contract

    systems: list[SystemProposal] = []
    by_key: dict[tuple[str, str], SystemProposal] = {}
    dropped_kinds: list[str] = []
    for sh in system_shells:
        # Validate `kind` against the controlled vocabulary HERE (#29 D6). The
        # sole-writer's typo-guard already skips an unknown kind, but it does so
        # SILENTLY: a live run's `PaymentSystem` vanished with no warning and no
        # counter, so a KB whose Systems are systematically mis-named would yield a
        # linchpins-only skeleton that reads like a modelling result. Drop it here,
        # loudly, where the count can be reported.
        if sh.kind not in _known_system_kinds():
            dropped_kinds.append(sh.kind)
            continue
        # The identify / authenticate / authorize triad are SINGLETONS at bootstrap
        # ("linchpin System nodes ... that everything later extends", spec §7.2).
        # Coerce any DESCRIPTIVE discriminator the LLM handed a linchpin kind (e.g.
        # AuthorizationSystem:moodique-pyramid, AuthenticationMechanism:prestashop-login)
        # to the sentinel, so an LLM-named linchpin can never slip past the forced-
        # singleton dedup and strand its role/realm vocabulary on a non-canonical node
        # while the forced singleton is left empty (observed live on the moodique KB).
        # Non-linchpin systems keep their discriminator - a genuine multi-instance kind
        # (two CDN products) still distinguishes.
        disc = L1_SINGLETON if sh.kind in _LINCHPIN_SYSTEMS else sh.discriminator
        key = (sh.kind, disc)
        props: dict = {}
        if sh.kind == "AuthorizationSystem":  # the KB-sourced pyramid vocabulary (shallow, no edges)
            if sh.roles:
                props["roles"] = list(sh.roles)
            if sh.realms:
                props["realms"] = list(sh.realms)
        existing = by_key.get(key)
        if existing is None:
            sp = SystemProposal(kind=sh.kind, discriminator=disc, props=props)
            by_key[key] = sp
            systems.append(sp)
        else:  # a coerced/duplicate key: fill an empty role/realm vocabulary from a later shell
            for k, v in props.items():
                if v and not existing.props.get(k):
                    existing.props[k] = v

    for kind in _LINCHPIN_SYSTEMS:  # force the triad regardless of the LLM
        if (kind, L1_SINGLETON) not in by_key:
            sp = SystemProposal(kind=kind)
            by_key[(kind, L1_SINGLETON)] = sp
            systems.append(sp)

    if dropped_kinds:
        logger.warning(
            "shells_to_batch: dropped %d System shell(s) with an out-of-vocabulary kind: %s "
            "(allowed: %s)",
            len(dropped_kinds), sorted(set(dropped_kinds)), sorted(_known_system_kinds()),
        )

    # aggregates / system_edges / data lists default EMPTY on L1DeltaBatch -> the
    # A.1 attributes are never persisted at bootstrap.
    return L1DeltaBatch(services=services, systems=systems)


# ==============================================================================
# Observability (#18 recipe, #26 Q12/story 17). EVERY helper here is fail-open:
# tracing is best-effort and must never fail a bootstrap, so each swallows its
# exception and degrades to a no-op. Langfuse v4: the trace attributes travel via
# `propagate_attributes(trace_name=, session_id=, tags=)` - the `langfuse_trace_name`
# metadata key of the older recipe is NOT a v4 key and silently does nothing.
# ==============================================================================

_TRACE_NAME = "bootstrap-service-skeleton"


def _bootstrap_span(project_id: str, run_id: str):
    """The one span per bootstrap, session-correlated so its trace joins the run's
    other traces (one run = one session, #18). Degrades to a `nullcontext`.

    BOTH pieces are needed. `propagate_attributes` sets the TRACE-level attributes
    (name, session, tags) but creates NO observation, so on its own every
    `update_current_span` / `score_current_span` below finds no active span and is
    silently skipped - the reasoning trace, the claims and the breadth score would
    all go nowhere while the code read as if it were instrumented. That is the same
    silent no-op as the `langfuse_trace_name` metadata key this recipe replaced, so
    `start_as_current_observation` opens the actual span the updates attach to."""
    try:
        from contextlib import ExitStack

        from langfuse import get_client, propagate_attributes

        stack = ExitStack()
        stack.enter_context(propagate_attributes(
            trace_name=_TRACE_NAME,
            session_id=run_id,
            tags=["analysis", "bootstrapper"],
            metadata={"project_id": project_id},
        ))
        stack.enter_context(get_client().start_as_current_observation(
            name=_TRACE_NAME, as_type="agent", input={"project_id": project_id},
        ))
        return stack
    except Exception:  # tracing unavailable / misconfigured -> run untraced
        logger.debug("bootstrap: Langfuse span unavailable; running untraced", exc_info=True)
        return nullcontext()


def _trace_reasoning(reasoning: str) -> None:
    """Attach call-1's free-text reasoning to the current span (transient - inspectable
    in the trace, never persisted to the graph)."""
    try:
        from langfuse import get_client

        get_client().update_current_span(input={"call": "reason"}, output=reasoning)
    except Exception:
        logger.debug("bootstrap: could not trace call-1 reasoning", exc_info=True)


def _trace_claims(system_shells: list[SystemShell]) -> None:
    """Record the transient per-System `claim` rationales on the span. `shells_to_batch`
    drops them, so without this a claim-based System hypothesis leaves no record of WHY
    it was proposed and stops being falsifiable."""
    claims = {sh.kind: sh.claim for sh in system_shells or [] if sh.claim}
    if not claims:
        return
    try:
        from langfuse import get_client

        get_client().update_current_span(metadata={"system_claims": claims})
    except Exception:
        logger.debug("bootstrap: could not trace System claims", exc_info=True)


def _score_breadth(services_written: int) -> None:
    """The NUMERIC `skeleton-breadth` score (#18 flat kebab-case vocabulary)."""
    try:
        from langfuse import get_client

        get_client().score_current_span(name="skeleton-breadth", value=float(services_written))
    except Exception:
        logger.debug("bootstrap: could not record skeleton-breadth score", exc_info=True)


def _flush_traces() -> None:
    """Flush before returning: a bootstrap is short-lived and may run in a request
    worker that exits before the background exporter fires (`flush`, never `shutdown`
    - the client is a process-wide singleton later runs reuse)."""
    try:
        from langfuse import get_client

        get_client().flush()
    except Exception:
        logger.debug("bootstrap: Langfuse flush failed", exc_info=True)


def _analyser_model_id() -> str | None:
    """The configured analyser model id, stamped into provenance (`prov_model`) so a
    skeleton records WHICH model produced it - the eval needs that attribution, and it
    was always None before (#26 story 17). Fail-open: provenance must never be the
    reason a bootstrap fails, and an injected `reason_fn` legitimately has no model."""
    try:
        from polymerhus.app.llm.providers import resolve_role

        provider, model = resolve_role("analyser")
        return f"{provider}:{model}"
    except Exception:
        return None


def bootstrap_reasoned(
    project_id: str,
    operator_kb: str,
    *,
    run_id: str | None = None,
    reason_fn=None,
    extract_fn=None,
    curate_fn=None,
    service_slugs: list[str] | None = None,
) -> BootstrapExport:
    """The two-call Bootstrapper (#26): call 1 (`reason_fn`) runs the free-text
    5-step reasoning over the KB; call 2 (`extract_fn`) extracts the Service/System
    shells FROM that reasoning; the shells map down through the sole-writer, the 3
    linchpins are forced, and the reasoning trace goes to Langfuse (transient).

    FAIL-CLOSED (#26 Q6): a bounded retry per call; on retry exhaustion of EITHER
    call, or a write failure, return `BootstrapExport(blocked=True)` - the analysis
    must halt (the downstream data dependency is unmet). An empty `operator_kb` is a
    valid proceed (linchpins-only, `blocked=False`), never a block.

    `run_id` is PROMOTED (#26 story 17): it flows to provenance (`prov_job`) and to
    the Langfuse `session_id`, so a trace correlates to its run. It defaults to a
    fresh uuid rather than the literal "bootstrap" - a constant default silently
    collapsed every run's provenance and session onto one id, which is
    indistinguishable from having no correlation at all.

    `reason_fn(operator_kb, service_slugs) -> reasoning`,
    `extract_fn(reasoning) -> (service_shells, system_shells)`, and
    `curate_fn(services, systems, project_id) -> (int, int)` are injected."""
    import uuid

    from polymerhus.analysis.proposer_reasoning import bounded_retry

    if run_id is None:
        run_id = str(uuid.uuid4())
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

    # ONE span per bootstrap, session-correlated to the run (#18 recipe / #26 Q12).
    # Fail-open: tracing must never fail a bootstrap, so an unconfigured or broken
    # Langfuse degrades to a nullcontext and the projection runs untraced.
    with _bootstrap_span(project_id, run_id):
        # Empty KB is a valid minimal bootstrap (linchpins-only), NOT a block: no LLM call.
        if operator_kb and operator_kb.strip():
            reasoning = bounded_retry(
                lambda: reason_fn(operator_kb, service_slugs), attempts=_REASON_ATTEMPTS
            )
            if reasoning is None:  # FAIL-CLOSED: call-1 exhausted -> block the analysis
                logger.warning(
                    "bootstrap_reasoned: call-1 (reason) exhausted for project=%s; BLOCKING", project_id
                )
                return BootstrapExport(blocked=True, error="reason: exhausted after retries")
            # The reasoning is TRANSIENT (#26 Q12): inspectable in the trace, never
            # persisted to the graph. This is the ONLY record of WHY each item was
            # proposed, so it is logged before the shells discard it.
            _trace_reasoning(reasoning)

            extracted = bounded_retry(lambda: extract_fn(reasoning), attempts=_REASON_ATTEMPTS)
            if extracted is None:  # FAIL-CLOSED: call-2 exhausted -> block
                logger.warning(
                    "bootstrap_reasoned: call-2 (extract) exhausted for project=%s; BLOCKING", project_id
                )
                return BootstrapExport(blocked=True, error="extract: exhausted after retries")
            service_shells, system_shells = extracted

        # The per-System `claim` rationale is transient too - dropped by shells_to_batch,
        # so the trace is the only place a claim-based hypothesis stays falsifiable.
        _trace_claims(system_shells)

        batch = shells_to_batch(service_shells, system_shells)
        provenance = Provenance(job=f"bootstrap:{run_id}", model=_analyser_model_id(), prompt_id=None)
        # Bootstrap is a pure business projection: proposals_to_deltas drops aggregates.
        services, systems, _aggregates_dropped = proposals_to_deltas(batch, provenance)

        try:
            services_written, systems_written = curate_fn(services, systems, project_id)
        except Exception as exc:  # FAIL-CLOSED: a write failure means no skeleton -> block
            logger.warning(
                "bootstrap_reasoned: curate failed for project=%s; BLOCKING", project_id, exc_info=True
            )
            return BootstrapExport(blocked=True, error=f"curate: {exc}")

        # `skeleton-breadth` (#18 vocabulary, flat kebab-case): the numeric signal the
        # breadth-leaning bar is judged on, and the regression detector for any future
        # prompt change (a prompt edit once collapsed breadth 25/16/20 -> 13).
        _score_breadth(services_written)
        _flush_traces()

    return BootstrapExport(services_written=services_written, systems_written=systems_written)


# --- default two-call collaborators (the real LLM path; the prompt redesign) ---

# The Bootstrapper's system message is TWO layers: this base prompt (identity, pipeline
# position, breadth stakes, and the output-field contract - the WHAT, a stable Python
# constant) and, prepended in `default_reason_fn`, the reasoning discipline from
# `skills/analysis/bootstrapper/SKILL.md` (the HOW - the 5 stages, service-contract craft
# and critical-withholding disciplines, operator-tunable without a code change, #29).
# The base stays here because it is an output contract, not a reasoning discipline, and
# because it must hold even when the skills mount is unavailable.
_BOOTSTRAPPER_BASE_SYSTEM = (
    "You are the solution-architecture Bootstrapper. You read the operator's free-text "
    "solution architecture - the knowledge base, written in business terms - and project it "
    "into the Layer-1 skeleton: the business-function `Service`s it describes and the "
    "cross-cutting `System`s it implies.\n\n"
    "You run FIRST, before any reconnaissance. You have no endpoints, parameters, headers or "
    "observed surface of any kind - only the operator's prose. Everything you emit is a "
    "projection of that prose, and every later phase builds on the skeleton you leave behind.\n\n"
    "Your skeleton is a hard data dependency, so breadth matters: a missed Service forces "
    "every later agent to coin a synonym for it or drop the surface that belongs to it, while "
    "an over-proposed one a later anti-clutter pass prunes cheaply. Widen to what the text "
    "SUPPORTS - never pad with what a similar application might have.\n\n"
    "Fill exactly three fields per Service: `business_function_slug` (its stable identity), "
    "`exposure`, and `service_contract`. Leave the display label, salience summary, surface "
    "assignments, data flows and system bindings EMPTY - the later phases that hold the "
    "surface fill those. For each System fill `kind` (from the controlled vocabulary you are "
    "given; a kind outside it is discarded) and, where the mechanism has multiple instances, "
    "a discriminator. The AuthorizationSystem alone carries content: the role and realm "
    "vocabulary the text states, as a flat list, with no per-Service bindings. Return empty "
    "lists over padding."
)

# The FALLBACK below is a degraded stand-in for the SKILL.md discipline, used only when the
# skills mount is unavailable (`skill_for` logs a warning). The base prompt above is always
# prepended, so this covers HOW-to-reason only: the 5 stages, ground-or-withhold,
# exposure-or-omit, and the contract with its no-invented-paths rule - a weaker projection
# than the full skill, but still constrained.
_BOOTSTRAPPER_SKILL_FALLBACK = (
    "Reason out loud through five stages, in order: (1) DECOMPOSE the text into distinct "
    "business-function components and the cross-cutting systems it implies, separating what "
    "it STATES from what you ASSUME; (2) EXPAND laterally to adjacent/implied functions "
    "(a missed Service costs more than an over-proposed one); (3) GROUND each candidate as a "
    "falsifiable claim tied to a SPECIFIC span, classifying exposure (public/authenticated) "
    "from the text's trust signals or omitting it when the text is silent - never guess; "
    "(4) WITHHOLD candidates with NO support, recording non-obvious Systems as shallow "
    "claim-based hypotheses and capturing the AuthorizationSystem's stated roles and realms; "
    "(5) DECIDE, reusing an identity already in the inventory over a synonym.\n\n"
    "For EVERY Service also write a `service_contract`: a brief functional profile of what "
    "the function does and what it owns, in the application's OWN domain nouns and action "
    "verbs. A later agent matches observed endpoint path nouns against it, so it must "
    "discriminate this function from the others. NEVER write a path, URL, route or parameter "
    "name - the text states none, and a guessed path would enter the model looking like "
    "evidence."
)


def _load_bootstrapper_skill() -> str:
    """The Bootstrapper's reasoning discipline = `skills/analysis/bootstrapper/SKILL.md`,
    loaded through the shared `skill_for` (FR-SKILLIF) exactly as the analyser pod
    loads its own: single-sourced, frontmatter stripped, cached, and degraded to the
    terse fallback above if the mount is unavailable, so a missing mount never crashes
    or blocks a bootstrap. It is the HOW layer only; `default_reason_fn` prepends the
    `_BOOTSTRAPPER_BASE_SYSTEM` identity/output-contract layer to form the system message."""
    from polymerhus.recon.domain.skills import skill_for

    return skill_for("analysis/bootstrapper", fallback=_BOOTSTRAPPER_SKILL_FALLBACK)


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
        "AuthorizationSystem{roles:[merchant, support]}.\n"
        "   Contracts (domain nouns/verbs, NO invented paths): merchant-onboarding = 'Take a "
        "prospective merchant through application and approval onto the platform; owns the "
        "merchant application and its approval state. Deals in merchants, onboarding, "
        "applications and approval.' payout-account-management = 'Let a merchant register and "
        "maintain the bank accounts their money is paid into; owns payout account details. "
        "Deals in payout accounts, bank details and verification.' settlement-processing = "
        "'Batch the day's captured transactions and pay merchants what they are owed. Deals in "
        "settlement, batches, transactions and payouts.'"
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
        "linchpins + AuthorizationSystem{roles:[engineer, manager], realms:[corporate]}.\n"
        "   Contracts (domain nouns/verbs, NO invented paths): incident-management = 'Let an "
        "engineer raise an incident and follow it to resolution; owns the incident record and "
        "its status history. Deals in incidents, tickets, severity, assignment and resolution.' "
        "change-approval = 'Route a proposed change to the manager who must approve it before it "
        "ships; owns the change request and its approval decision. Deals in change requests, "
        "approvals, reviewers and sign-off.'"
    ),
]


def default_reason_fn(operator_kb: str, service_slugs: list[str] | None = None) -> str | None:
    """Call 1 - the free-text 5-step reasoning over the KB. The SYSTEM message is the base
    prompt (identity, pipeline position, breadth stakes, output-field contract) plus the
    Bootstrapper skill (the 5 stages, the disciplines, the service_contract craft); the HUMAN
    message carries the run-specific material: the 2 divergent-domain few-shot CoT exemplars,
    the FR-INVENTORY reuse block, and the KB itself. Returns the reasoning text (None if the
    model produced nothing).

    The exemplars stay in the HUMAN turn on purpose (#29): they are prompt MECHANICS
    (they demonstrate the trace shape and cancel each other's domain anchoring) sitting
    adjacent to the task, where they demonstrably work today. Only the operator-tunable
    reasoning discipline moved into the skill."""
    from langchain_core.messages import HumanMessage, SystemMessage

    from polymerhus.app.llm.roles import chat_model_for
    from polymerhus.analysis.pod import _inventory_block
    from polymerhus.analysis.proposer_reasoning import few_shot_block

    inventory = {"services": service_slugs or [], "systems": [], "data_items": []}
    # NB: the service-linchpin prompt (`_service_linchpin_prompt`) is DELIBERATELY NOT
    # woven in here. Pushing the account-surface umbrellas through the reasoning prompt
    # globally coarsened the model's granularity prior - a live 3-target eval collapsed
    # every skeleton to ~13 umbrella Services (was 25/16/20), re-bundling distinct
    # functions (daytona snapshots+volumes+region -> one node). The pre-auth account
    # surface (gap-3) is guaranteed DETERMINISTICALLY by the forcing in shells_to_batch,
    # so the breadth prompt stays untouched. Whether to re-add a minimal, breadth-safe
    # prompt mention is the force-vs-prompt-prior ratification question (B-Q2, #31).
    human = (
        f"{few_shot_block(_FEW_SHOT)}\n\n"
        f"{_inventory_block(inventory)}\n\nOperator KB (free text):\n{operator_kb}\n\n"
        "Now produce YOUR reasoning for this KB, following the five stages."
    )
    system = f"{_BOOTSTRAPPER_BASE_SYSTEM}\n\n{_load_bootstrapper_skill()}"
    result = chat_model_for("analyser").invoke([
        SystemMessage(content=system),
        HumanMessage(content=human),
    ])
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
        "Service set ONLY business_function_slug + exposure (public/authenticated, or omit) "
        "+ service_contract; leave label/salience/aggregates/exposed_via/data_flows/"
        "surfaces_at EMPTY. For each System set kind + discriminator; give the "
        "AuthorizationSystem its roles/realms; leave other spine slots empty.\n\n"
        # The contract is COMPOSED here, from the reasoning's own grounding prose. The
        # reasoning states each candidate as a justification ("the KB says X, so this
        # exists"); left unguided the extraction copies that, and every contract reads
        # as a citation instead of a profile. So the target shape is stated explicitly.
        "SERVICE CONTRACT - for every Service, compose a brief functional profile from "
        "what the reasoning established about it: what the business function DOES and "
        "what it OWNS, in the application's own domain nouns and action verbs. Write it "
        "for a reader who will later see concrete endpoint paths and must decide which "
        "Service each one belongs to - so it has to DISCRIMINATE this function from the "
        "others, and a profile true of every Service ('manages platform resources') is "
        "useless. Two or three sentences. Use the operator's own words for things "
        "(their 'volume' or 'sandbox', not your paraphrase). NEVER write a path, URL, "
        "route, query parameter or field name: none appear in the source text, so any "
        "you write is invented, and it would be read later as if it were evidence. "
        "Restate a justification as a profile - not \"exists because the KB mentions "
        "seller payouts\" but \"Pay sellers their accumulated earnings on a schedule; "
        "owns the payout record and its status. Deals in payouts, earnings, balances "
        "and payment schedules.\"\n\nREASONING:\n" + reasoning
    )
    result = structured.invoke([
        SystemMessage(content="You extract typed shells from prior reasoning; you never invent beyond it."),
        HumanMessage(content=prompt),
    ])
    if result is None:
        return None
    return list(result.services), list(result.systems)


# --- entry point ---------------------------------------------------------------

def run_bootstrap(project_id: str, *, load_settings_fn=None, **kwargs) -> BootstrapExport:
    """THE entry point: read `operator_kb` from the project's settings and project it
    into the L1 skeleton. This is what the API route (and any future caller) invokes.

    It delegates to `bootstrap_reasoned` - the two-call, fail-CLOSED path. It used to
    call the superseded single-call `bootstrap_from_kb`, which meant the ONE
    settings-aware entry point still ran the example-polluted, fail-OPEN elicitation
    long after its replacement had shipped and been verified live; that function is
    now retired (#29).

    `load_settings_fn(project_id) -> dict` defaults to pg.load_settings."""
    if load_settings_fn is None:
        from polymerhus.app.clients import pg
        load_settings_fn = pg.load_settings
    settings = load_settings_fn(project_id) or {}
    operator_kb = settings.get("operator_kb") or ""
    return bootstrap_reasoned(project_id, operator_kb, **kwargs)
