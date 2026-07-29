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

def test_AST_DEC_06_provider_calls_carry_a_finite_bounded_timeout():
    """The mechanism behind the measured stall: an UNBOUNDED request sat under
    `_invoke_with_retry(attempts=3)`, so a provider that never answered blocked its
    caller indefinitely, three times over - one pass on run 64f2ccb8 took 1157 s
    against a 59 s median. The bound must live on the client itself, because the
    retry ladder above it cannot interrupt a request that never returns.

    The BOUND is asserted here; its VALUES are #32's to choose, and this assertion
    was rewritten onto #32's implementation when the two met on `dev`. That merge is
    worth recording: #34 independently set `timeout=120s, max_retries=0`, and both
    numbers were worse. 120s sits BELOW the ~150s a legitimate Bootstrapper
    reasoning call takes, so it would have timed out healthy calls and failed closed
    on a working provider; and `max_retries=0` removes the only retry the recon roles
    have, since `bounded_retry` lives in analysis alone. #32's split connect/read
    budget with `max_retries=1` is kept, and this predicate now checks the property
    both agreed on rather than one side's constants."""
    from polymerhus.app.llm.providers import build_chat_model

    os.environ.setdefault("API_KEY_OPENROUTER", "test-key-not-used")
    model = build_chat_model("openrouter", "some/model")

    timeout = model.request_timeout
    assert timeout is not None, "an unbounded provider call is the stall"
    read = getattr(timeout, "read", timeout)
    assert 0 < float(read) < 3600
    # bounded, and not multiplied into a ladder nobody can reason about
    assert 0 <= model.max_retries <= 1


def test_AST_DEC_06b_the_timeout_is_operator_tunable():
    """Correctable in the field without a rebuild, and an unusable override is a
    config lie that must fail fast rather than degrade silently to the default."""
    from polymerhus.app.llm import providers

    assert providers.request_timeout().read > 0

    os.environ["LLM_REQUEST_TIMEOUT_SECONDS"] = "42"
    try:
        assert providers.request_timeout().read == 42.0
        for bad in ("not-a-number", "-1", "0"):
            os.environ["LLM_REQUEST_TIMEOUT_SECONDS"] = bad
            with pytest.raises(providers.LLMConfigError):
                providers.request_timeout()
    finally:
        os.environ.pop("LLM_REQUEST_TIMEOUT_SECONDS", None)


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
        # Null the typist seam: this contract is about the Assigner's aggregate
        # convergence, and the two-role schedule (#9) would otherwise drive the
        # mechanism_typist against the live LLM. A None-returning invoke keeps the
        # pass deterministic (the typist fail-closes to an empty batch).
        return asyncio.run(analyse_chunked(project, f"stream-{project}",
                                           invoke_fn=fake_llm,
                                           typist_invoke_fn=lambda *a, **k: None,
                                           observe=False))

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
