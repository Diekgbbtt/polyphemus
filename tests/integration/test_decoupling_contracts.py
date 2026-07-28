"""Contract predicates (integration tier) for the recon/analysis decoupling (#34).

Mechanises AST-DEC-06 and AST-DEC-07 from `docs/design/recon-analysis-decoupling.md`
§6, over the real provider construction and the real sole-writer against a live
Neo4j. The feed's own scheduling contract (AST-DEC-01..05) is pure and lives in the
unit tier (`tests/analysis/test_feed.py`).

Verifier-gated; not selected by the tdd unit red/green loop.
"""
import asyncio
import os
import uuid

import pytest

from polymerhus.analysis.analyser_types import AggregatesProposal, L1DeltaBatch
from polymerhus.analysis.l1_types import L0Ref
from polymerhus.app.clients import neo4j_client
from polymerhus.recon.domain.types import AssetDelta

BU = "https://dec.example"


# --- AST-DEC-06: a provider call is time-bounded ------------------------------

def test_AST_DEC_06_provider_calls_carry_a_finite_timeout_and_no_sdk_retry():
    """The mechanism behind the measured stall: an UNBOUNDED request sat under
    `_invoke_with_retry(attempts=3)`, so a provider that never answered blocked its
    caller indefinitely, three times over - one pass on run 64f2ccb8 took 1157 s
    against a 59 s median. The bound must live on the client itself, because the
    retry ladder above it cannot interrupt a request that never returns."""
    from polymerhus.app.llm.providers import build_chat_model

    os.environ.setdefault("API_KEY_OPENROUTER", "test-key-not-used")
    model = build_chat_model("openrouter", "some/model")

    assert model.request_timeout is not None, "an unbounded provider call is the stall"
    assert 0 < float(model.request_timeout) < 3600
    # Retry policy belongs to the ONE layer that already owns it (pod._invoke_with_retry);
    # leaving the SDK default of 2 multiplies the ladders into up to nine attempts.
    assert model.max_retries == 0


def test_AST_DEC_06b_the_timeout_is_operator_tunable():
    from polymerhus.app.llm import providers

    assert isinstance(providers.LLM_REQUEST_TIMEOUT_S, float)
    assert providers.LLM_REQUEST_TIMEOUT_S > 0


# --- AST-DEC-07: idempotent replay over an identical surface ------------------

def _seed_l0(project_id, paths):
    """Curate a small real L0 surface through the L0 sole-writer."""
    from polymerhus.recon.domain.curator import curate

    assets = [
        AssetDelta(type="BaseURL", identity={"url": BU}, props={"profile": "restapi"}),
        *[AssetDelta(type="Endpoint",
                     identity={"path": p, "method": "GET", "baseurl": BU})
          for p in paths],
    ]
    curate(assets, [], project_id)


def _seed_l1_service(project_id, slug):
    """Mint one Service through the L1 sole-writer, as the Bootstrapper would."""
    from polymerhus.analysis import l1_curator
    from polymerhus.analysis.l1_types import Provenance, ServiceDelta

    l1_curator.l1_curate(
        [ServiceDelta(business_function_slug=slug,
                      props={"service_contract": "Owns orders."},
                      provenance=Provenance(job="test:bootstrap"))],
        [], project_id,
    )


def _counts(project_id):
    # Counted independently: a chained MATCH would drop the whole row when there
    # are no AGGREGATES yet, reporting zero Services as well and turning a real
    # "1 service, 0 edges" state into an indistinguishable "nothing here".
    rows = neo4j_client.read(
        "RETURN COUNT { MATCH (s:L1Service) WHERE s.project_id = $p } AS services, "
        "COUNT { MATCH (:L1Service)-[r:AGGREGATES]->(e) WHERE e.project_id = $p } "
        "AS aggregates",
        {"p": project_id},
    )
    return (rows[0]["services"], rows[0]["aggregates"])


def _cleanup(project_id):
    neo4j_client.merge("MATCH (n) WHERE n.project_id = $p DETACH DELETE n", {"p": project_id})


@pytest.fixture()
def project():
    pid = f"dec-{uuid.uuid4().hex[:8]}"
    yield pid
    _cleanup(pid)


def test_AST_DEC_07_two_consecutive_passes_write_no_new_identities(project):
    """A replayed pass over an identical surface converges rather than duplicating.
    This is what makes conflation safe: a coalesced cursor costs one extra pass, and
    an extra pass must cost nothing."""
    from polymerhus.analysis.supervisor import analyse_chunked

    _seed_l0(project, ["/orders/42", "/orders/43"])
    _seed_l1_service(project, "checkout")

    def fake_llm(messages):
        # A deterministic proposal naming BOTH seeded Endpoints, above the bar.
        return L1DeltaBatch(aggregates=[
            AggregatesProposal(
                service_slug="checkout",
                l0=L0Ref(label="Endpoint",
                         identity={"path": p, "method": "GET", "baseurl": BU}),
                confidence=0.95, evidence_refs=[f"path segment {p}"],
            ) for p in ("/orders/42", "/orders/43")
        ])

    def one_pass():
        return asyncio.run(analyse_chunked(project, f"stream-{project}",
                                           invoke_fn=fake_llm, observe=False))

    first = one_pass()
    after_first = _counts(project)
    assert after_first == (1, 2), f"the first pass must actually write: {after_first}"
    assert first.census.dispatches_entered >= 1     # non-vacuity: a dispatch ran
    assert first.census.l0_assets_read >= 3

    one_pass()
    assert _counts(project) == after_first          # twice yields the same one


def test_AST_DEC_07b_a_pass_over_an_empty_surface_records_what_it_observed(project):
    """The census must distinguish 'read nothing' from 'read surface and judged
    nothing' - the whole basis of the drain's evidence bar (DQ2b)."""
    from polymerhus.analysis.supervisor import analyse_chunked

    result = asyncio.run(analyse_chunked(
        project, f"stream-{project}", invoke_fn=lambda m: None, observe=False,
        terminal=True,
    ))
    assert result.census.l0_assets_read == 0
    assert result.census.dispatches_entered == 0
    assert result.census.terminal is True
