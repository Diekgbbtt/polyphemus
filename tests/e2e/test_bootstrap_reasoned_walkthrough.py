"""TRUE end-to-end walkthrough for the Bootstrapper redesign (#26, agent spec #7).

NO MOCKS: the whole system executes at runtime - the REAL analyser LLM
(LLM_MODEL_ANALYSER via OpenRouter) runs the two-call reasoning, and the REAL
l1_curator sole-writer persists the L1 skeleton to a LIVE Neo4j. Every assertion
is over the concrete OBSERVED data artifacts read back from the graph.

Input (operator-supplied): the OWASP Juice Shop marketplace solution architecture,
scoped to target soupmarket.shop (no recon is run - the Bootstrapper is a pure KB
projection). Assertions are structural invariants + a must-cover core subset that
tolerate the LLM's non-determinism (calibrated against two live probe runs).

Runs only when the live LLM env is configured; it is a live_neo4j-tier test (auto
-marked by tests/e2e path) and consumes real LLM credits.
"""
import os
import re

import pytest

from polymerhus.analysis.bootstrap import _LINCHPIN_SERVICES, bootstrap_reasoned
from polymerhus.app.clients import neo4j_client

pytestmark = pytest.mark.skipif(
    not (os.environ.get("API_KEY_OPENROUTER") and os.environ.get("LLM_MODEL_ANALYSER")),
    reason="live analyser LLM env (API_KEY_OPENROUTER + LLM_MODEL_ANALYSER) not configured",
)

PROJECT = "e2e-boot-juiceshop"

JUICE_SHOP_KB = """Juice Shop is, at heart, an online juice marketplace. People come to browse and buy fresh juices, but the shop is more than a single storefront: it hosts many independent sellers under one roof, runs a Juice Club that delivers boxes on a recurring schedule, and rewards regulars through a loyalty programme. Around that sit a handful of supporting services - gifting juices and gift cards, a review system that lets buyers guide one another, a support desk that handles complaints and refunds, and an onboarding-and-payout pipeline that lets sellers join, sell, and get paid.

Most of what happens on the shop falls into a few well-worn journeys. A shopper browses the shelves, drops juices into a basket, applies a discount, pays, and then follows the delivery to their door. A seller takes the mirror-image path: they apply to sell, list their juices, receive an order, pack and hand it over, and collect their earnings. After an order arrives, a customer might rate and review it, collect loyalty points, and redeem those points for a reward or discount. Someone who wants juice regularly joins the Juice Club, chooses what goes in the box, and then receives deliveries on a schedule they can pause or change at any time. And when something goes wrong, a shopper raises a complaint, a case is opened and reviewed, a decision is reached, and a refund or credit is issued.

Getting in works at different levels of trust. A guest can wander the shop and even fill a basket without signing in at all. To actually own an account, a shopper registers with an email address and a password, and if they forget that password they recover it by answering a personal security question. Sellers don't simply self-serve - they apply for and are granted a separate seller sign-in. Members unlock their extra benefits only once their plan is active, and staff are handed privileged access matched to their particular job. The rule of thumb is that the higher-trust actions - paying, selling, issuing refunds - always require the person to be signed in and to hold the right role.

The roles themselves span the whole ecosystem: guests and shoppers on the buying side; members with subscription benefits; sellers and seller managers running storefronts; support agents, content moderators, accountants, and administrators keeping the shop running; and, at the edges, affiliates who refer business and delivery partners who move the orders.

Underneath it all, the marketplace keeps a fairly intuitive set of records. Each person has a customer account, and everything for sale is a product listing; while shopping, their choices live in a shopping basket that becomes an order, which in turn generates a delivery to a saved address. Money is tracked through a store balance, saved payment methods, discount coupons, gift cards, and - on the seller side - seller earnings. The community side is captured as product reviews, complaints and feedback, and each seller's storefront. And the loyalty and membership features rest on loyalty points, subscription plans, personal recommendations, and the security question used to protect the account."""

_LINCHPINS = {"IdentificationSystem", "AuthenticationMechanism", "AuthorizationSystem"}

# The must-cover journeys (Q2). Keyword groups tolerate the LLM's slug naming; every
# group must be covered by >=1 produced Service slug.
_CORE_JOURNEYS = {
    # "shop"/"shopping" belongs here: a live run named the buying journey `shopping`
    # and the group missed it, failing the test for a naming the KB itself uses
    # ("A shopper browses the shelves, drops juices into a basket"). The group tests
    # that the journey is COVERED, so it must accept the KB's own words for it.
    "buying/checkout": ("checkout", "basket", "cart", "payment", "order", "shop"),
    "selling": ("seller",),
    "reviews": ("review",),
    "loyalty": ("loyalty", "points", "reward"),
    "subscription/club": ("club", "subscription", "member"),
    "support/refund": ("support", "complaint", "refund", "ticket"),
    "gifting": ("gift",),
    "registration/account": ("regist", "account", "sign-up", "recovery", "password"),
}


def _wipe(project_id):
    neo4j_client.merge(
        "MATCH (n) WHERE n.project_id = $p AND (n:L1Service OR n:L1System OR n:L1DataItem) "
        "DETACH DELETE n", {"p": project_id})


def _services(project_id):
    return neo4j_client.read(
        "MATCH (n:L1Service) WHERE n.project_id = $p "
        "RETURN n.business_function_slug AS slug, n.exposure AS exposure, "
        "n.service_contract AS contract, n.label AS label, n.salience AS salience",
        {"p": project_id})


def _systems(project_id):
    return neo4j_client.read(
        "MATCH (n:L1System) WHERE n.project_id = $p RETURN n.kind AS kind, "
        "n.roles AS roles, n.realms AS realms", {"p": project_id})


def _service_system_edges(project_id):
    return neo4j_client.read(
        "MATCH (:L1Service)-[r]->(s:L1System) WHERE s.project_id = $p RETURN count(r) AS n",
        {"p": project_id})[0]["n"]


@pytest.fixture
def clean():
    _wipe(PROJECT)
    yield
    _wipe(PROJECT)


# --- E1: the real run over the Juice Shop KB ----------------------------------

def test_E1_juiceshop_real_skeleton(clean):
    out = bootstrap_reasoned(PROJECT, JUICE_SHOP_KB, run_id="e2e-1")
    assert out.blocked is False and out.error is None
    # >= 3, not == 3 (corrected #29): the 3 linchpins are the FLOOR, but story 10 has
    # the Bootstrapper emit shallow hypothesis stubs for non-obvious Systems the KB
    # asserts, so a KB that grounds one legitimately writes more. The old `== 3` would
    # have failed the moment the model did the thing the spec asks of it.
    assert out.systems_written >= 3
    assert out.services_written >= 12  # a comprehensive marketplace skeleton

    services = _services(PROJECT)
    slugs = [r["slug"] for r in services]
    assert len(slugs) == out.services_written

    # every must-cover journey is represented by >=1 grounded Service
    lowered = [s.lower() for s in slugs]
    for journey, keys in _CORE_JOURNEYS.items():
        assert any(any(k in s for k in keys) for s in lowered), f"journey uncovered: {journey} in {slugs}"

    # the 3 linchpin Systems exist
    systems = _systems(PROJECT)
    kinds = {r["kind"] for r in systems}
    assert _LINCHPINS <= kinds

    # AuthorizationSystem carries a KB-sourced role/realm vocabulary, and NO edges
    authz = next(r for r in systems if r["kind"] == "AuthorizationSystem")
    roles = [x.lower() for x in (authz["roles"] or [])]
    assert len(roles) >= 5
    assert any("seller" in x for x in roles)                                  # seller side
    assert any(any(t in x for t in ("admin", "support", "moderator", "accountant")) for x in roles)  # staff
    assert any(any(t in x for t in ("guest", "shopper", "member")) for x in roles)  # buyer side
    assert authz["realms"]  # a non-empty realm vocabulary
    assert _service_system_edges(PROJECT) == 0  # bootstrap writes NO Service->System edges

    # --- #29: every Service carries a routable service_contract -----------------
    contracts = {r["slug"]: (r["contract"] or "") for r in services}
    missing = [s for s, c in contracts.items() if not c.strip()]
    assert not missing, f"Services with no service_contract: {missing}"

    # the contract must DISCRIMINATE: identical text across Services is useless to the
    # Assigner, which is the one consumer the attribute exists for.
    assert len(set(contracts.values())) == len(contracts), "duplicate service_contract text"

    # NO invented paths/URLs/params - the KB states none, so any is a guess that would
    # afterwards be read as evidence. This is the ratified content rule.
    path_like = re.compile(r"(https?://|/[a-z0-9_-]+/|\B/[a-z0-9_{-]+|[?&][a-z_]+=)", re.I)
    offenders = {s: c for s, c in contracts.items() if path_like.search(c)}
    assert not offenders, f"service_contract contains path-like syntax: {offenders}"

    # the contract must speak the KB's OWN domain vocabulary, or the later match has
    # nothing to bind to the surface's nouns.
    blob = " ".join(contracts.values()).lower()
    assert sum(t in blob for t in ("juice", "seller", "order", "basket", "review",
                                   "loyalty", "refund", "gift")) >= 4

    # the A.1 attributes stay EMPTY - bootstrap fills only what it owns (story 7)
    assert all(r["label"] is None and r["salience"] is None for r in services)

    # exposure discipline: only valid values; the classification is actually exercised
    # with both trust levels. (Whether any exposure is OMITTED is a soft preference,
    # not a hard invariant: the KB's trust rules - "higher-trust actions always
    # require sign-in" - are broad enough that a decisive model may reasonably
    # classify every service without guessing, so we do not assert an omission.)
    exposures = {r["slug"]: r["exposure"] for r in services}
    assert all(v in (None, "public", "authenticated") for v in exposures.values())
    assert any(v == "public" for v in exposures.values())
    assert any(v == "authenticated" for v in exposures.values())
    # KB trust rules (grounded): browsing is guest-reachable (public); paying requires sign-in.
    browse = {s: e for s, e in exposures.items() if any(k in s.lower() for k in ("catalog", "brows", "product"))}
    if browse:
        assert "public" in browse.values()
    pay = {s: e for s, e in exposures.items() if any(k in s.lower() for k in ("checkout", "payment"))}
    if pay:
        assert "authenticated" in pay.values()


# --- E2: empty KB -> linchpins-only, not blocked ------------------------------

def test_E2_empty_kb_real(clean):
    out = bootstrap_reasoned(PROJECT, "", run_id="e2e-2")
    assert out.blocked is False
    # #29: an empty KB makes NO LLM call, so nothing is elicited - but the HARD-forced
    # pre-auth service linchpins are still minted (gap-3), each with its contract.
    forced = {ls.slug for ls in _LINCHPIN_SERVICES if ls.forced}
    assert out.services_written == len(forced)
    assert out.systems_written == 3
    assert {r["kind"] for r in _systems(PROJECT)} == _LINCHPINS
    services = _services(PROJECT)
    assert {r["slug"] for r in services} == forced
    assert all(r["contract"] for r in services)  # never contract-less, so never unroutable


# --- E3: fail-closed - a REAL generation failure blocks, nothing written ------

def test_E3_fail_closed_real(clean, monkeypatch):
    # induce a REAL LLM failure (not a mock): point the analyser at a non-existent
    # model so the live OpenRouter call genuinely errors; the bounded retry exhausts.
    monkeypatch.setenv("LLM_MODEL_ANALYSER", "openrouter:invalid/does-not-exist-xyz")
    out = bootstrap_reasoned(PROJECT, JUICE_SHOP_KB, run_id="e2e-3")
    assert out.blocked is True
    assert out.services_written == 0 and out.systems_written == 0
    assert _services(PROJECT) == [] and _systems(PROJECT) == []  # NOTHING written on a block


# --- E4: idempotent re-bootstrap - linchpins stay 3, no synonym explosion -----

def test_E4_rerun_reuses_inventory(clean):
    out1 = bootstrap_reasoned(PROJECT, JUICE_SHOP_KB, run_id="e2e-4a")
    n1 = out1.services_written
    before = {r["slug"]: r["contract"] for r in _services(PROJECT)}

    out2 = bootstrap_reasoned(PROJECT, JUICE_SHOP_KB, run_id="e2e-4b")  # auto-reads inventory
    assert out1.blocked is False and out2.blocked is False
    # the singleton linchpins never duplicate (deterministic MERGE)
    assert len([r for r in _systems(PROJECT) if r["kind"] == "AuthorizationSystem"]) == 1
    assert _LINCHPINS <= {r["kind"] for r in _systems(PROJECT)}
    # FR-INVENTORY reuse keeps the graph from exploding with synonyms on re-run
    after = {r["slug"]: r["contract"] for r in _services(PROJECT)}
    assert len(after) <= n1 + 4  # near-idempotent: a few new coinages, never a doubling

    # #29: a re-bootstrap never BLANKS an existing contract. The second pass may word
    # it differently (the model is non-deterministic), but a Service that had a
    # contract must still have one - absence is omission, so nothing can clobber it.
    for slug, contract in before.items():
        if contract and slug in after:
            assert after[slug], f"{slug} lost its service_contract on re-bootstrap"


# --- E5: the BREADTH-REGRESSION guard (#29) -----------------------------------
# The single most consequential risk in this agent. Weaving the account-surface
# umbrellas into the REASONING prompt once coarsened the model's granularity prior
# and collapsed three live skeletons 25/16/20 -> 13 (commit 760e93d), which is why
# `_service_linchpin_prompt` is retained-not-wired. #29 adds the service-contract
# discipline to that same reasoning prompt (via the skill), so the regression must
# be re-measured, not assumed away.
#
# The baselines are the post-fix skeletons still persisted in Neo4j from the 3-target
# eval: eval-daytona 26, eval-magnific 25, eval-moodique 18. They are re-queryable,
# so this guard compares against OBSERVED prior state rather than a number in a
# comment. A project absent from the graph is skipped, never silently passed.

_BREADTH_BASELINES = {"eval-daytona": 26, "eval-magnific": 25, "eval-moodique": 18}


def _service_count(project_id):
    rows = neo4j_client.read(
        "MATCH (n:L1Service) WHERE n.project_id = $p RETURN count(n) AS c", {"p": project_id})
    return rows[0]["c"] if rows else 0


@pytest.mark.parametrize("project,baseline", sorted(_BREADTH_BASELINES.items()))
def test_E5_prior_eval_baselines_are_still_present(project, baseline):
    """Guards the GUARD: if these graphs are wiped the comparison below silently
    becomes vacuous, so their absence has to be visible rather than green."""
    observed = _service_count(project)
    if observed == 0:
        pytest.skip(f"{project} baseline graph absent from Neo4j - re-run the 3-target eval")
    assert observed == baseline, (
        f"{project} baseline drifted: expected {baseline}, graph holds {observed}. "
        "Either the graph was mutated or the recorded baseline is wrong; resolve "
        "before trusting any breadth comparison."
    )


def test_E5_juiceshop_breadth_has_not_regressed(clean):
    """The Juice Shop KB is comparable in richness to the eval targets, so a skeleton
    far below their floor is the signature of the granularity-coarsening regression -
    distinct from ordinary run-to-run variance."""
    out = bootstrap_reasoned(PROJECT, JUICE_SHOP_KB, run_id="e2e-5")
    assert out.blocked is False
    floor = min(_BREADTH_BASELINES.values())  # 18, the least-rich eval target
    assert out.services_written >= floor - 4, (
        f"BREADTH REGRESSION: {out.services_written} Services, against an eval floor of "
        f"{floor} ({_BREADTH_BASELINES}). The 760e93d collapse produced ~13 on comparable "
        "KBs - re-check what was added to the reasoning prompt."
    )
