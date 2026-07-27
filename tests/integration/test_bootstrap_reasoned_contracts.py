"""Contract predicates (integration tier) for the Bootstrapper redesign (#26,
agent spec #7). Mechanises C1-C13.

Written against the intended API (shells_to_batch + bootstrap_reasoned) BEFORE the
build - per /to-assertions they collect, execute, and FAIL for the predicate's
reason (the path is NotImplementedError), and go green when the build fills the
stubs. Expected values come from the spec, not recomputed. Verifier-gated tier; not
selected by the tdd unit loop.
"""
import pytest

from polymerhus.analysis.bootstrap import (
    ServiceShell,
    SystemShell,
    bootstrap_reasoned,
    shells_to_batch,
)

_LINCHPINS = {"IdentificationSystem", "AuthenticationMechanism", "AuthorizationSystem"}
# The HARD-forced service linchpins (gap-3): the pre-auth account surface the
# Bootstrapper always mints, mirroring the system linchpins. account-management is
# PROMPT-PRIOR (not hard-forced), so it is deliberately absent from this set.
_FORCED_SERVICE_LINCHPINS = {"sign-in", "register", "password-recovery"}


def _svc_props(batch):
    return {s.business_function_slug: s.props for s in batch.services}


# --- C1: shell A.1 attributes emptied + not persisted -------------------------

def test_C1_shell_maps_to_exposure_only_service_a1_slots_dropped():
    shell = ServiceShell(
        business_function_slug="checkout", exposure="public",
        label="X", salience="high", aggregates=[{"x": 1}], exposed_via=[{"y": 2}],
        data_flows=[{"z": 3}], surfaces_at=[{"w": 4}],
    )
    batch = shells_to_batch([shell], [])
    assert _svc_props(batch)["checkout"] == {"exposure": "public"}  # exposure-only
    assert batch.aggregates == [] and batch.system_edges == []
    assert batch.data_items == [] and batch.data_flows == [] and batch.surfaces_at == []


# --- C2: invalid exposure dropped (allowlist as defense-in-depth) -------------

def test_C2_invalid_exposure_and_label_dropped():
    batch = shells_to_batch([ServiceShell(business_function_slug="x", exposure="bogus", label="X")], [])
    assert _svc_props(batch)["x"] == {}  # bogus exposure + label both dropped


# --- C3: exposure omitted when KB silent, Service still emitted ----------------

def test_C3_exposure_none_yields_empty_props_service_still_emitted():
    batch = shells_to_batch([ServiceShell(business_function_slug="x", exposure=None)], [])
    props = _svc_props(batch)
    assert "x" in props and props["x"] == {}


# --- C4: the 3 linchpins forced regardless + singleton dedup ------------------

def test_C4_linchpins_forced_when_llm_omits_all():
    batch = shells_to_batch([], [])
    assert {s.kind for s in batch.systems} == _LINCHPINS


def test_C4_linchpins_no_duplicate_when_llm_proposes_one():
    batch = shells_to_batch([], [SystemShell(kind="AuthorizationSystem", roles=["admin"])])
    kinds = [s.kind for s in batch.systems]
    assert set(kinds) == _LINCHPINS
    assert kinds.count("AuthorizationSystem") == 1  # singleton dedup


def test_C4_linchpin_descriptive_discriminator_folds_onto_singleton():
    """Regression (found live on the moodique KB): the LLM may hand a linchpin a
    DESCRIPTIVE discriminator (AuthorizationSystem:moodique-pyramid,
    AuthenticationMechanism:prestashop-login). That must NOT duplicate the forced
    singleton - it is coerced to the sentinel, the role/realm vocabulary lands on
    the ONE singleton, and no non-singleton linchpin node survives."""
    batch = shells_to_batch([], [
        SystemShell(kind="AuthorizationSystem", discriminator="moodique-pyramid",
                    roles=["anonymous", "customer", "admin"], realms=["storefront"]),
        SystemShell(kind="AuthenticationMechanism", discriminator="prestashop-login"),
    ])
    kinds = [s.kind for s in batch.systems]
    assert set(kinds) == _LINCHPINS
    assert kinds.count("AuthorizationSystem") == 1  # no duplicate singleton
    assert kinds.count("AuthenticationMechanism") == 1
    # every linchpin is the singleton (no descriptive discriminator survives)
    linchpin_discs = {s.discriminator for s in batch.systems if s.kind in _LINCHPINS}
    assert linchpin_discs == {"__singleton__"}
    # the pyramid vocabulary is on the (singleton) AuthorizationSystem, not stranded
    authz = next(s for s in batch.systems if s.kind == "AuthorizationSystem")
    assert authz.props.get("roles") == ["anonymous", "customer", "admin"]
    assert authz.props.get("realms") == ["storefront"]


# --- C5: AuthorizationSystem carries roles/realms, NO edges --------------------

def test_C5_authorization_system_roles_realms_no_edges():
    batch = shells_to_batch([], [SystemShell(
        kind="AuthorizationSystem", roles=["anonymous", "user", "admin"], realms=["web"],
    )])
    authz = next(s for s in batch.systems if s.kind == "AuthorizationSystem")
    assert authz.props.get("roles") == ["anonymous", "user", "admin"]
    assert authz.props.get("realms") == ["web"]
    assert batch.system_edges == []  # no AUTHORIZED_BY / AUTHENTICATED_BY at bootstrap


# --- C6: claim-based System = shallow stub, claim transient --------------------

def test_C6_claim_based_system_shallow_stub_claim_not_persisted():
    batch = shells_to_batch([], [SystemShell(kind="WAF", claim="KB says behind Cloudflare")])
    waf = next(s for s in batch.systems if s.kind == "WAF")
    assert waf.discriminator == "__singleton__"
    assert "claim" not in waf.props  # transient -> Langfuse only
    assert "rendering_model" not in waf.props and "navigation_model" not in waf.props


# --- C7: the code adds no candidates of its own (anti-pollution) ---------------

def test_C7_emitted_slugs_equal_extracted_set_no_hardcoded_slugs():
    captured = {}

    def curate(services, systems, project_id):
        captured["slugs"] = {s.business_function_slug for s in services}
        return len(services), len(systems)

    def reason(operator_kb, service_slugs):
        return "reasoning"

    def extract(reasoning):
        return ([ServiceShell(business_function_slug="shipment-tracking"),
                 ServiceShell(business_function_slug="carrier-rates")], [])

    bootstrap_reasoned("p1", "some logistics KB", reason_fn=reason, extract_fn=extract, curate_fn=curate)
    # The extracted slugs pass through verbatim PLUS the hard-forced service linchpins
    # (gap-3); the anti-pollution guarantee is that NO domain-specific slug (checkout /
    # cart / orders) is ever injected by the code.
    assert captured["slugs"] == {"shipment-tracking", "carrier-rates"} | _FORCED_SERVICE_LINCHPINS
    assert not ({"checkout", "cart", "orders"} & captured["slugs"])


# --- C8/C9/C10: fail-closed -> blocking signal --------------------------------

def test_C8_call1_exhaustion_blocks():
    out = bootstrap_reasoned("p1", "kb", reason_fn=lambda kb, service_slugs: None,
                             extract_fn=lambda r: ([], []), curate_fn=lambda s, y, p: (0, 0))
    assert out.blocked is True
    assert out.services_written == 0 and out.systems_written == 0


def test_C9_call2_exhaustion_blocks():
    out = bootstrap_reasoned("p1", "kb", reason_fn=lambda kb, service_slugs: "reasoning",
                             extract_fn=lambda r: None, curate_fn=lambda s, y, p: (0, 0))
    assert out.blocked is True


def test_C10_write_failure_blocks():
    def boom(services, systems, project_id):
        raise RuntimeError("neo4j down")

    out = bootstrap_reasoned("p1", "kb", reason_fn=lambda kb, service_slugs: "reasoning",
                             extract_fn=lambda r: ([ServiceShell(business_function_slug="x")], []),
                             curate_fn=boom)
    assert out.blocked is True


# --- C11: empty KB -> linchpins-only, NOT blocked -----------------------------

def test_C11_empty_kb_proceeds_linchpins_only_not_blocked():
    calls = {"reason": 0}

    def reason(operator_kb, service_slugs):
        calls["reason"] += 1
        return "reasoning"

    out = bootstrap_reasoned("p1", "", reason_fn=reason, extract_fn=lambda r: ([], []),
                             curate_fn=lambda services, systems, p: (len(services), len(systems)))
    assert out.blocked is False
    # gap-3: even an empty KB carries the HARD-forced service linchpins (the pre-auth
    # account surface), exactly as it carries the 3 system linchpins - the surface where
    # critical auth bugs concentrate is never dropped. account-management stays absent
    # (prompt-prior, un-grounded on an empty KB).
    assert out.services_written == len(_FORCED_SERVICE_LINCHPINS)  # sign-in/register/password-recovery
    assert out.systems_written == 3  # the system linchpins
    assert calls["reason"] == 0  # no elicitation on an empty KB


# --- C12: two-call ordering + reasoning handoff -------------------------------

def test_C12_reason_before_extract_and_reasoning_passed_forward():
    order = []

    def reason(operator_kb, service_slugs):
        order.append("reason")
        return "THE-REASONING"

    def extract(reasoning):
        order.append("extract")
        assert reasoning == "THE-REASONING"  # extract grounded in call-1 reasoning
        return ([], [])

    bootstrap_reasoned("p1", "kb", reason_fn=reason, extract_fn=extract,
                       curate_fn=lambda s, y, p: (0, 3))
    assert order == ["reason", "extract"]


# --- C13: idempotent re-bootstrap reuse ---------------------------------------

def test_C13_inventory_threaded_and_two_runs_equal():
    seen = {}

    def reason(operator_kb, service_slugs):
        seen["slugs"] = list(service_slugs or [])
        return "reasoning"

    def extract(reasoning):
        return ([ServiceShell(business_function_slug="shipment-tracking", exposure="public")], [])

    def curate(services, systems, project_id):
        return len(services), len(systems)

    a = bootstrap_reasoned("p1", "kb", reason_fn=reason, extract_fn=extract, curate_fn=curate,
                           service_slugs=["shipment-tracking"])
    b = bootstrap_reasoned("p1", "kb", reason_fn=reason, extract_fn=extract, curate_fn=curate,
                           service_slugs=["shipment-tracking"])
    assert seen["slugs"] == ["shipment-tracking"]  # FR-INVENTORY threaded into call 1
    assert a == b  # idempotent


# --- C14-C17 (gap-3): service linchpins - the pre-auth account surface never dropped

def test_C14_auth_entry_services_forced_when_llm_omits_them():
    """gap-3 (operator-CRITICAL, moodique): the pre-auth sign-in / register /
    password-recovery umbrella surface must be minted with the `public` baseline even
    when the LLM absorbs it into the AuthenticationMechanism System and proposes none."""
    props = _svc_props(shells_to_batch([], []))
    for slug in _FORCED_SERVICE_LINCHPINS:
        assert slug in props, f"forced service linchpin {slug!r} missing"
        assert props[slug] == {"exposure": "public"}  # pre-auth baseline


def test_C15_forced_service_linchpin_not_duplicated_when_llm_proposes_it():
    """Dedup on Service identity: the LLM proposing sign-in (incl. an FR-INVENTORY
    reuse) must not double-mint it, and the LLM's own exposure is preserved."""
    batch = shells_to_batch(
        [ServiceShell(business_function_slug="sign-in", exposure="public")], [])
    slugs = [s.business_function_slug for s in batch.services]
    assert slugs.count("sign-in") == 1  # no duplicate
    assert _svc_props(batch)["sign-in"] == {"exposure": "public"}
    # the OTHER forced linchpins are still added alongside the LLM's proposal
    assert {"register", "password-recovery"} <= set(slugs)


def test_C16_account_management_is_prompt_prior_not_hard_forced():
    """account-management is PROMPT-PRIOR (a headless B2B API legitimately has no
    self-service account surface), so it is NEVER blind-forced when the LLM omits it."""
    assert "account-management" not in _svc_props(shells_to_batch([], []))


def test_C17_account_management_kept_with_exposure_when_llm_grounds_it():
    """When the LLM DOES ground account-management, it is carried through with its
    (authenticated) exposure - the umbrella, not yet split into leaves."""
    batch = shells_to_batch(
        [ServiceShell(business_function_slug="account-management", exposure="authenticated")], [])
    assert _svc_props(batch)["account-management"] == {"exposure": "authenticated"}


def test_C18_prompt_single_sources_the_service_linchpin_constant():
    """CODING_STANDARD §7: the prompt text is rendered FROM `_LINCHPIN_SERVICES`, the
    same constant the forcing logic reads, so the two can never drift."""
    from polymerhus.analysis.bootstrap import _LINCHPIN_SERVICES, _service_linchpin_prompt

    rendered = _service_linchpin_prompt()
    for ls in _LINCHPIN_SERVICES:
        assert ls.slug in rendered  # every umbrella drawn from the one source
    # the forced-vs-prompt-prior policy is visible to the model
    assert "ALWAYS propose" in rendered and "ONLY when the KB grounds it" in rendered
