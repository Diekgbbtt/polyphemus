"""FR-ELICIT unit tier — the bootstrap logic with injected fakes (no LLM/DB).
Encodes the FR-ELICIT ledger (docs/design/L1-MVP-plan.md).
"""
from agent.recon.analysis import bootstrap
from agent.recon.analysis.analyser_types import (
    AggregatesProposal,
    L1DeltaBatch,
    ServiceProposal,
    SystemProposal,
)
from agent.recon.analysis.l1_types import L0Ref


def _capture_curate():
    captured = {}

    def curate_fn(services, systems, project_id):
        captured["services"] = services
        captured["systems"] = systems
        captured["project_id"] = project_id
        return (len(services), len(systems))

    return captured, curate_fn


# --- AST-ELICIT-01/02: elicits services + always-present linchpin auth Systems ---

def test_bootstrap_writes_services_and_linchpin_systems():
    captured, curate_fn = _capture_curate()

    def elicit_fn(kb):
        return L1DeltaBatch(
            services=[ServiceProposal(business_function_slug="checkout"),
                      ServiceProposal(business_function_slug="orders")],
            systems=[SystemProposal(system_kind="RESTApi")],
        )

    export = bootstrap.bootstrap_from_kb("proj-1", "we sell things; users check out and view orders",
                                         elicit_fn=elicit_fn, curate_fn=curate_fn)

    slugs = {s.business_function_slug for s in captured["services"]}
    kinds = {s.system_kind for s in captured["systems"]}
    assert slugs == {"checkout", "orders"}
    # linchpin auth Systems are ALWAYS present, even though the LLM only elicited RESTApi
    assert {"AuthenticationMechanism", "AuthorizationSystem"} <= kinds
    assert "RESTApi" in kinds
    assert export.services_written == 2 and export.error is None


def test_linchpins_not_duplicated_when_llm_elicits_them():
    captured, curate_fn = _capture_curate()

    def elicit_fn(kb):
        return L1DeltaBatch(systems=[SystemProposal(system_kind="AuthenticationMechanism")])

    bootstrap.bootstrap_from_kb("proj-1", "kb", elicit_fn=elicit_fn, curate_fn=curate_fn)
    kinds = [s.system_kind for s in captured["systems"]]
    assert kinds.count("AuthenticationMechanism") == 1  # not doubled
    assert "AuthorizationSystem" in kinds


# --- AST-ELICIT-03: bootstrap is a pure business projection — NO L0 refs (aggregates dropped) ---

def test_bootstrap_drops_any_aggregates_no_l0_refs():
    captured, curate_fn = _capture_curate()
    aggregates_seen = {"n": None}

    def elicit_fn(kb):
        # a misbehaving LLM emits an aggregate; bootstrap must NOT write it
        return L1DeltaBatch(
            services=[ServiceProposal(business_function_slug="checkout")],
            aggregates=[AggregatesProposal(
                service_slug="checkout",
                l0=L0Ref(label="Endpoint", identity={"path": "/x", "method": "GET", "baseurl": "https://a"}),
            )],
        )

    # curate_fn signature is (services, systems, project_id) — there is no
    # aggregates parameter, proving bootstrap has no path to write an AGGREGATES edge.
    export = bootstrap.bootstrap_from_kb("proj-1", "kb", elicit_fn=elicit_fn, curate_fn=curate_fn)
    assert export.services_written == 1
    assert "aggregates" not in captured  # only services+systems were curated


# --- AST-ELICIT-04: operator_kb read from settings.recon.operator_kb (free text) ---

def test_run_bootstrap_reads_operator_kb_from_settings():
    seen = {}

    def fake_load_settings(project_id):
        return {"operator_kb": "an online marketplace with reviews and reward points", "target_domain": "x"}

    def elicit_fn(kb):
        seen["kb"] = kb
        return L1DeltaBatch(services=[ServiceProposal(business_function_slug="reviews")])

    _cap, curate_fn = _capture_curate()
    bootstrap.run_bootstrap("proj-1", load_settings_fn=fake_load_settings, elicit_fn=elicit_fn, curate_fn=curate_fn)
    assert seen["kb"] == "an online marketplace with reviews and reward points"


def test_empty_operator_kb_still_ensures_linchpins():
    captured, curate_fn = _capture_curate()
    # empty KB -> no elicited services, but the linchpin systems must still be ensured
    export = bootstrap.bootstrap_from_kb("proj-1", "   ", curate_fn=curate_fn)
    kinds = {s.system_kind for s in captured["systems"]}
    assert {"AuthenticationMechanism", "AuthorizationSystem"} <= kinds
    assert captured["services"] == []
    assert export.error is None


# --- AST-ELICIT-05: fail-open on LLM error ---

def test_elicit_error_is_degraded_not_raised():
    _cap, curate_fn = _capture_curate()

    def boom(kb):
        raise RuntimeError("LLM down")

    export = bootstrap.bootstrap_from_kb("proj-1", "kb", elicit_fn=boom, curate_fn=curate_fn)
    assert export.error and "LLM down" in export.error
    assert export.services_written == 0  # nothing written


def test_curate_error_is_degraded_not_raised():
    def elicit_fn(kb):
        return L1DeltaBatch(services=[ServiceProposal(business_function_slug="x")])

    def boom_curate(services, systems, project_id):
        raise RuntimeError("neo4j down")

    export = bootstrap.bootstrap_from_kb("proj-1", "kb", elicit_fn=elicit_fn, curate_fn=boom_curate)
    assert export.error and "curate" in export.error


# --- AST-ELICIT-05: the elicitation LLM call is retried, like the analyser's ---
# Regression guard for a defect FR-CURE2E hit live: deepseek returned truncated
# JSON ("Expecting value: line 1109 column 1") and default_elicit_fn, which called
# structured_llm.invoke() with NO retry, fail-opened to services=0 - zeroing the
# whole bootstrap skeleton so every downstream stage ran against an empty L1.
# The analyser pod was hardened against exactly this transient with
# _invoke_with_retry(attempts=3); bootstrap has the same exposure and was missed.

def test_elicit_retries_a_transient_structured_output_failure(monkeypatch):
    """A transient JSONDecodeError from the provider must be retried, not silently
    collapsed into an empty skeleton."""
    import json as _json

    from agent.app.llm import roles as _roles

    good = L1DeltaBatch(services=[ServiceProposal(business_function_slug="checkout")])
    calls = {"n": 0}

    class _FakeStructured:
        def invoke(self, messages):
            calls["n"] += 1
            if calls["n"] < 3:      # fail twice, succeed on the third
                raise _json.JSONDecodeError("Expecting value", "doc", 6094)
            return good

    class _FakeLLM:
        def with_structured_output(self, schema, method=None):
            return _FakeStructured()

    monkeypatch.setattr(_roles, "chat_model_for", lambda role: _FakeLLM())

    batch = bootstrap.default_elicit_fn("an online juice marketplace")

    assert calls["n"] == 3, f"expected 3 attempts (bounded retry), got {calls['n']}"
    assert batch is not None and batch.services, "a retried success must return the batch"
    assert batch.services[0].business_function_slug == "checkout"


def test_elicit_exhausting_its_retries_is_fail_open_with_a_clear_error():
    """When every retry attempt fails, _invoke_with_retry returns None. That must
    degrade to a reported error, NOT crash the caller (fail-open) and NOT look like
    a successful empty elicitation."""
    exp = bootstrap_from_kb_none = bootstrap.bootstrap_from_kb(
        "p_none", "an online juice marketplace",
        elicit_fn=lambda kb: None,
        curate_fn=lambda services, systems, project_id: (len(services), len(systems)),
    )
    assert exp.error, "an exhausted-retry elicitation must report an error, not a silent empty skeleton"
    assert "elicit" in exp.error.lower()
    assert exp.services_written == 0
