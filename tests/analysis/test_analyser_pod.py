"""FR-ANALYSER unit tier — the analyser subgraph's control flow + the
proposal->delta mapping, with injected fake collaborators (no live LLM/DB).
Store-level idempotency is the integration tier
(tests/integration/test_analyser_pod_merge.py).

Each test names the assertion it encodes (docs/design/L1-MVP-plan.md §5).
"""
from polymerhus.analysis.analyser_types import (
    AggregatesProposal,
    DataFlowProposal,
    DataItemProposal,
    L1DeltaBatch,
    ServiceProposal,
    SystemEdgeProposal,
    SystemProposal,
    proposals_to_deltas,
)
from polymerhus.analysis import l1_curator as real_l1_curator
from polymerhus.analysis import pod as analyser_pod
from polymerhus.analysis.l1_types import L0Ref, Provenance
from polymerhus.analysis.pod import (
    AnalyserExport,
    build_analyser_graph,
    default_curate_fn,
    default_curate_with_enrichment_fn,
    run_analyser,
)


PROV = Provenance(job="analyser:run-1", model="strong-model", prompt_id=None)


# --- AST-ANALYSER-04: proposals map to deltas with SYSTEM-supplied provenance ---

def test_proposals_to_deltas_injects_provenance_llm_cannot_set():
    batch = L1DeltaBatch(
        services=[ServiceProposal(business_function_slug="checkout", props={"label": "Checkout"})],
        systems=[SystemProposal(kind="RESTApi")],
        aggregates=[AggregatesProposal(
            service_slug="checkout", confidence=0.8, evidence_refs=["obs:1"],
            l0=L0Ref(label="Endpoint", identity={"path": "/pay", "method": "POST", "baseurl": "https://a"}),
        )],
    )
    services, systems, aggregates = proposals_to_deltas(batch, PROV)
    assert services[0].provenance is PROV  # injected, not from the LLM proposal
    assert systems[0].provenance is PROV
    # the judgment envelope is built here: confidence carried, status committed (MVP)
    assert aggregates[0].envelope.confidence == 0.8
    assert aggregates[0].envelope.status == "committed"
    assert aggregates[0].envelope.evidence_refs == ["obs:1"]
    assert aggregates[0].envelope.provenance is PROV


def test_proposal_models_have_no_provenance_field():
    """The LLM-facing proposals deliberately omit provenance (it is
    system-controlled), so the LLM cannot spoof it."""
    assert "provenance" not in ServiceProposal.model_fields
    assert "provenance" not in SystemProposal.model_fields
    assert "provenance" not in AggregatesProposal.model_fields


def test_empty_batch_is_valid():
    b = L1DeltaBatch()
    assert b.services == [] and b.systems == [] and b.aggregates == []


# --- AST-ANALYSER-01 (flow): read -> analyse -> curate, deltas reach the curator ---

def test_subgraph_flow_routes_deltas_to_curator():
    read_calls, curate_calls = [], []

    def fake_read(project_id):
        read_calls.append(project_id)
        return {"nodes": [{"type": "Endpoint", "path": "/x"}], "links": []}

    def fake_analyse(l0_slice, observations):
        assert l0_slice["nodes"]  # the read slice reached the analyser
        return L1DeltaBatch(services=[ServiceProposal(business_function_slug="orders")])

    def fake_curate(batch, project_id, provenance):
        curate_calls.append((len(batch.services), len(batch.systems), len(batch.aggregates), project_id))
        return AnalyserExport(services_written=len(batch.services), systems_written=len(batch.systems),
                              aggregates_written=len(batch.aggregates))

    graph = build_analyser_graph(read_fn=fake_read, analyse_fn=fake_analyse, curate_fn=fake_curate)
    export = run_analyser("proj-1", "run-1", [], graph=graph)

    assert read_calls == ["proj-1"]
    assert curate_calls == [(1, 0, 0, "proj-1")]  # the proposed Service reached the curator
    assert export.services_written == 1
    assert export.error is None


def test_curate_receives_provenance_stamped_deltas():
    captured = {}

    def fake_curate(batch, project_id, provenance):
        captured["prov_job"] = provenance.job  # provenance is system-supplied, passed to curate
        return AnalyserExport(services_written=1)

    graph = build_analyser_graph(
        read_fn=lambda p: {"nodes": [], "links": []},
        analyse_fn=lambda s, o: L1DeltaBatch(services=[ServiceProposal(business_function_slug="x")]),
        curate_fn=fake_curate,
    )
    run_analyser("proj-9", "run-42", observations=[], graph=graph)  # explicit [] keeps this unit test hermetic
    assert captured["prov_job"] == "analyser:run-42"  # run-scoped, system-supplied


# --- AST-ANALYSER-03: an LLM error fails open — empty deltas, no write, no crash ---

def test_llm_error_degrades_to_empty_no_write_no_crash():
    curate_calls = []

    def exploding_analyse(l0_slice, observations):
        raise RuntimeError("LLM 500")

    def fake_curate(batch, project_id, provenance):
        curate_calls.append((len(batch.services), len(batch.systems), len(batch.aggregates)))
        return AnalyserExport()  # nothing to write

    graph = build_analyser_graph(
        read_fn=lambda p: {"nodes": [], "links": []},
        analyse_fn=exploding_analyse,
        curate_fn=fake_curate,
    )
    export = run_analyser("proj-1", "run-1", observations=[], graph=graph)  # must NOT raise

    assert export.error and "LLM 500" in export.error
    assert curate_calls == [(0, 0, 0)]  # curator ran with an EMPTY batch: no write
    assert export.services_written == 0


def test_read_error_degrades_and_still_completes():
    def exploding_read(project_id):
        raise RuntimeError("neo4j down")

    graph = build_analyser_graph(
        read_fn=exploding_read,
        analyse_fn=lambda s, o: L1DeltaBatch(),
        curate_fn=lambda batch, p, prov: AnalyserExport(),
    )
    export = run_analyser("proj-1", "run-1", observations=[], graph=graph)  # must NOT raise
    assert export.error and "read" in export.error


def test_curate_error_degrades_not_raised():
    def exploding_curate(batch, project_id, provenance):
        raise RuntimeError("write failed")

    graph = build_analyser_graph(
        read_fn=lambda p: {"nodes": [], "links": []},
        analyse_fn=lambda s, o: L1DeltaBatch(services=[ServiceProposal(business_function_slug="x")]),
        curate_fn=exploding_curate,
    )
    export = run_analyser("proj-1", "run-1", observations=[], graph=graph)  # must NOT raise
    assert export.error and "curate" in export.error


# --- default_curate_fn wires the real l1_curator (DB-free, l1_curator faked) ---

def test_default_curate_fn_calls_l1_curator_and_assembles_counts(monkeypatch):
    calls = {}

    def fake_l1_curate(services, systems, project_id):
        calls["l1_curate"] = (len(services), len(systems), project_id)
        return (len(services), len(systems))

    def fake_write_aggregates(aggregates, project_id):
        calls["write_aggregates"] = (len(aggregates), project_id)
        return len(aggregates)

    # default_curate_fn does `from polymerhus.analysis import l1_curator` at call
    # time; patch that module's attrs (the same object it resolves via sys.modules).
    monkeypatch.setattr(real_l1_curator, "l1_curate", fake_l1_curate)
    monkeypatch.setattr(real_l1_curator, "write_aggregates", fake_write_aggregates)

    services = [1, 2]           # counts are all default_curate_fn uses
    systems = [1]
    aggregates = [1, 2, 3]
    export = default_curate_fn(services, systems, aggregates, "proj-1")

    assert calls["l1_curate"] == (2, 1, "proj-1")
    assert calls["write_aggregates"] == (3, "proj-1")
    assert (export.services_written, export.systems_written, export.aggregates_written) == (2, 1, 3)


# --- FIX 2: the DEFAULT curate path writes core AND enrichment (l1_curator faked) ---

def test_default_curate_with_enrichment_writes_core_and_enrichment(monkeypatch):
    """The default analyser curate collaborator must map+write BOTH the core
    deltas AND the FR-ENRICH deltas from one batch, with system provenance. No
    catalogue seeding fires (operator correction 2026-07-20: a DataRelationship
    kind IS its edge type, so there is no :DataRelationshipKind catalogue). Guards
    the load-bearing FIX 2 wiring end-to-end (was inspection-only)."""
    calls = {}

    def fake_l1_curate(services, systems, project_id):
        calls["l1_curate"] = (len(services), len(systems))
        return (len(services), len(systems))

    def fake_write_aggregates(aggregates, project_id):
        calls["write_aggregates"] = len(aggregates)
        return len(aggregates)

    def fake_enrich(project_id, **enrich_deltas):
        # capture the per-category delta counts + that provenance was injected
        calls["enrich"] = {k: len(v) for k, v in enrich_deltas.items()}
        calls["enrich_prov"] = enrich_deltas["data_items"][0].provenance.job if enrich_deltas["data_items"] else None
        return {k: len(v) for k, v in enrich_deltas.items()}

    monkeypatch.setattr(real_l1_curator, "l1_curate", fake_l1_curate)
    monkeypatch.setattr(real_l1_curator, "write_aggregates", fake_write_aggregates)
    monkeypatch.setattr(real_l1_curator, "enrich", fake_enrich)

    batch = L1DeltaBatch(
        services=[ServiceProposal(business_function_slug="sales-analysis")],
        systems=[SystemProposal(kind="RESTApi")],
        aggregates=[AggregatesProposal(service_slug="sales-analysis",
                                       l0=L0Ref(label="Endpoint", identity={"path": "/s", "method": "GET", "baseurl": "https://a"}))],
        data_items=[DataItemProposal(item_key="sales_figure")],
        data_flows=[DataFlowProposal(service_slug="sales-analysis", item_key="sales_figure", direction="consumes",
                                     assumption="authorized for THIS user")],
        system_edges=[SystemEdgeProposal(service_slug="sales-analysis", kind="RESTApi", rel="EXPOSED_VIA")],
    )
    prov = Provenance(job="analyser:run-77", model="m", prompt_id=None)
    export = default_curate_with_enrichment_fn(batch, "proj-1", prov)

    # core written
    assert calls["l1_curate"] == (1, 1)
    assert calls["write_aggregates"] == 1
    # enrichment written (the FIX 2 seam) with the right per-category counts
    assert calls["enrich"]["data_items"] == 1
    assert calls["enrich"]["data_flows"] == 1
    assert calls["enrich"]["system_edges"] == 1
    # provenance is system-supplied (run-scoped), injected at the curate boundary
    assert calls["enrich_prov"] == "analyser:run-77"
    # export surfaces both core counts and the enrichment counts
    assert export.services_written == 1 and export.aggregates_written == 1
    assert export.enrichment["system_edges"] == 1


def test_default_curate_with_enrichment_skips_enrich_when_no_enrichment_deltas(monkeypatch):
    """When the batch has no enrichment deltas, the enrich path must NOT fire -
    only the core write runs."""
    calls = {"enrich": False}
    monkeypatch.setattr(real_l1_curator, "l1_curate", lambda s, sy, p: (len(s), len(sy)))
    monkeypatch.setattr(real_l1_curator, "write_aggregates", lambda a, p: len(a))
    monkeypatch.setattr(real_l1_curator, "enrich", lambda p, **k: calls.__setitem__("enrich", True))

    batch = L1DeltaBatch(services=[ServiceProposal(business_function_slug="x")])  # core only
    export = default_curate_with_enrichment_fn(batch, "proj-1", PROV)
    assert calls["enrich"] is False  # no enrichment -> no enrich fired
    assert export.enrichment is None
    assert export.services_written == 1


# --- FIX 3: data modelling gets its own dedicated analyse pass (e2e-caught) ---

def test_two_pass_analyse_runs_dedicated_data_modelling_pass():
    """Regression for an e2e-caught defect: one combined LLM call reliably returned
    0 data_items while emitting 150 aggregates + 90 system_edges (finish_reason
    'tool_calls', NOT a token cutoff) - the model deprioritised data modelling under
    assignment load. The analyser must issue a SEPARATE data-modelling pass whose
    output is merged in, so DataItems survive even when the assignment pass has
    none."""
    calls = []

    def fake_invoke(messages):
        calls.append(messages[-1].content)
        if len(calls) == 1:
            # assignment pass: aggregates + system_edges, NO data_items (the live shape)
            return L1DeltaBatch(
                aggregates=[AggregatesProposal(
                    service_slug="orders",
                    l0=L0Ref(label="Endpoint", identity={"path": "/api/Orders", "method": "GET", "baseurl": "https://a"}))],
                system_edges=[SystemEdgeProposal(service_slug="orders", kind="RESTApi", rel="EXPOSED_VIA")],
            )
        # dedicated data-modelling pass supplies the DataItems + flows
        return L1DeltaBatch(
            data_items=[DataItemProposal(item_key="order")],
            data_flows=[DataFlowProposal(service_slug="orders", item_key="order", direction="produces")],
        )

    merged = analyser_pod._two_pass_analyse(fake_invoke, {"nodes": [{"type": "Endpoint"}]}, [])

    assert len(calls) == 2  # a dedicated data-modelling pass ran
    assert "TASK 1 of 2" in calls[0] and "LOGICAL DATA MODELLING" in calls[1]  # the two distinct tasks
    # assignment preserved AND data modelling merged in (the load-bearing fix)
    assert [a.service_slug for a in merged.aggregates] == ["orders"]
    assert [e.rel for e in merged.system_edges] == ["EXPOSED_VIA"]
    assert [d.item_key for d in merged.data_items] == ["order"]
    assert [f.direction for f in merged.data_flows] == ["produces"]


def test_two_pass_analyse_fail_open_keeps_assignment_when_data_pass_raises():
    """If the dedicated data-modelling pass raises, the assignment pass must survive
    (fail-open) - a data-pass error degrades enrichment, never loses assignment."""
    calls = []

    def fake_invoke(messages):
        calls.append(1)
        if len(calls) == 1:
            return L1DeltaBatch(services=[ServiceProposal(business_function_slug="orders")])
        raise RuntimeError("data pass LLM 500")

    merged = analyser_pod._two_pass_analyse(fake_invoke, {"nodes": []}, [])

    assert [s.business_function_slug for s in merged.services] == ["orders"]  # assignment kept
    assert merged.data_items == []  # degraded to no enrichment, no crash


def test_invoke_with_retry_returns_first_non_none():
    """Bounded retry returns the first non-None structured result."""
    seq = iter([None, None, L1DeltaBatch(services=[ServiceProposal(business_function_slug="ok")])])
    out = analyser_pod._invoke_with_retry(lambda m: next(seq), ["m"], attempts=3)
    assert [s.business_function_slug for s in out.services] == ["ok"]


def test_invoke_with_retry_survives_exceptions_then_succeeds():
    """A raising attempt is retried, not propagated (transient provider error)."""
    calls = []

    def flaky(m):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("transient 503")
        return L1DeltaBatch(services=[ServiceProposal(business_function_slug="ok")])

    out = analyser_pod._invoke_with_retry(flaky, ["m"], attempts=3)
    assert out is not None and [s.business_function_slug for s in out.services] == ["ok"]


def test_invoke_with_retry_gives_up_after_attempts():
    assert analyser_pod._invoke_with_retry(lambda m: None, ["m"], attempts=2) is None


def test_two_pass_analyse_recovers_from_transient_none_on_assignment():
    """Regression for a live-observed flake: a transient None on a pass must not
    zero the whole analyser - the pass is retried and a later success is used."""
    calls = []

    def fake_invoke(messages):
        content = messages[-1].content
        calls.append(content)
        if "TASK 1 of 2" in content:
            # assignment: None on the first attempt, a real batch on the retry
            if sum("TASK 1 of 2" in c for c in calls) == 1:
                return None
            return L1DeltaBatch(
                services=[ServiceProposal(business_function_slug="orders")],
                aggregates=[AggregatesProposal(service_slug="orders",
                    l0=L0Ref(label="Endpoint", identity={"path": "/x", "method": "GET", "baseurl": "https://a"}))])
        return L1DeltaBatch(data_items=[DataItemProposal(item_key="order")])

    merged = analyser_pod._two_pass_analyse(fake_invoke, {"nodes": []}, [])
    assert [s.business_function_slug for s in merged.services] == ["orders"]  # recovered on retry
    assert [d.item_key for d in merged.data_items] == ["order"]  # data pass still merged


def test_data_modelling_prompt_grounds_in_assignment():
    """Pass-2's prompt must carry pass-1's Service->endpoint assignment so data
    modelling is grounded in what was actually assigned (token-light: <=8 paths)."""
    assignment = L1DeltaBatch(aggregates=[
        AggregatesProposal(service_slug="sign-in",
            l0=L0Ref(label="Endpoint", identity={"path": "/rest/user/login", "method": "POST", "baseurl": "https://a"})),
    ])
    p = analyser_pod._data_modelling_prompt({"nodes": []}, assignment)
    assert "LOGICAL DATA MODELLING" in p
    assert "sign-in: /rest/user/login" in p  # the assignment is echoed as grounding


def test_data_modelling_prompt_is_positive_recipe_with_example():
    """The data prompt must be a POSITIVE, example-led recipe - NOT a negative
    'leave the other lists empty' framing that made a weaker model anchor on the
    empties and return zero data_items. Guards the reframing."""
    p = analyser_pod._data_modelling_prompt({"nodes": []}, L1DeltaBatch())
    # a concrete worked example the weak model can pattern-match
    assert '"item_key": "shopping_basket"' in p
    assert "WORKED EXAMPLE" in p
    # a directive demand for at least one item (the failure was zero)
    assert "at least" in p and "data_items" in p
    # NO harmful negative framing telling it to leave lists empty
    assert "EMPTY" not in p and "leave" not in p.lower()
    # the worked example must use a REAL controlled DataRelationship kind (a bogus
    # example kind would teach the model to emit deltas the curator drops)
    from polymerhus.analysis.l1_curator import _KNOWN_DATA_REL_KINDS
    import re as _re
    example_kinds = set(_re.findall(r'"kind":\s*"([a-z_]+)"', p))
    assert example_kinds and example_kinds <= _KNOWN_DATA_REL_KINDS, example_kinds
    # data_flows must be told to copy service slugs verbatim (avoid orphan services)
    assert "VERBATIM" in p


def test_data_modelling_prompt_uses_identity_only_surface_not_full_dump():
    """Pass-2's surface digest must be IDENTITY-ONLY - the full node property dump
    ballooned the prompt to ~123k chars and pass-2 timed out / returned no
    structured output. Guards that heavy props never reach the data prompt."""
    slice_ = {"nodes": [
        {"type": "Endpoint", "properties": {
            "path": "/api/Orders", "method": "GET", "baseurl": "https://a",
            "status_code": 200, "body_snippet": "Z" * 500}},
        {"type": "Parameter", "properties": {
            "name": "orderId", "position": "query", "endpoint_path": "/api/Orders", "baseurl": "https://a"}},
        {"type": "Header", "properties": {"name": "Server", "value": "nginx"}},
    ]}
    eps, params = analyser_pod._compact_l0_for_data(slice_)
    assert eps == [{"path": "/api/Orders", "method": "GET", "baseurl": "https://a"}]  # no status_code/body
    assert params == [{"name": "orderId", "position": "query", "endpoint_path": "/api/Orders", "baseurl": "https://a"}]
    p = analyser_pod._data_modelling_prompt(slice_, L1DeltaBatch())
    assert "status_code" not in p and "Z" * 500 not in p  # heavy props excluded from the prompt
    assert "/api/Orders" in p and "orderId" in p  # identities present

def test_analyser_skill_loads_and_strips_frontmatter():
    from polymerhus.recon.domain import skills
    skills.clear_cache()  # bypass the shared skill_for cache for a clean load
    skill = analyser_pod._load_analyser_skill()
    assert not skill.startswith("---")  # YAML frontmatter stripped
    # embodies the overthink discipline (deliberate, staged reasoning)
    assert "Reason deliberately" in skill
    assert "Verify before you emit" in skill
    # embodies the critical-thinking discipline (claims/evidence/assumptions/burden)
    assert "Separate the claim from its support" in skill
    assert "Surface hidden assumptions" in skill
    assert "Burden of proof" in skill
    # is the analyser's task prompt (proposes deltas, evidence-bound, honest-empty)
    assert "attack-surface analyser" in skill
    assert "Return empty lists" in skill


def test_analyser_skill_is_cached():
    from polymerhus.recon.domain import skills
    skills.clear_cache()
    first = analyser_pod._load_analyser_skill()
    second = analyser_pod._load_analyser_skill()
    assert first is second  # cached (same object), not re-read


def test_vocabulary_prompt_lists_controlled_values():
    """Regression for an e2e-caught defect: the LLM proposed 'Authentication'
    (not the canonical 'AuthenticationMechanism') and the delta was silently
    dropped. The prompt must enumerate the exact allowed vocabularies."""
    from polymerhus.analysis.l1_curator import vocabulary_prompt

    v = vocabulary_prompt()
    assert "AuthenticationMechanism" in v and "AuthorizationSystem" in v
    assert "RESTApi" in v
    assert "EXPOSED_VIA" in v and "AUTHORIZED_BY" in v  # system-edge rels
    assert "equals_hash_of" in v  # data-relationship kinds
    assert "__singleton__" in v


def test_l0_reference_guide_teaches_label_is_node_type():
    """Regression for an e2e-caught defect: the LLM put a URL value in
    aggregates.l0.label instead of the node TYPE ('Endpoint'), and the safe-label
    guard dropped the assignment. The guide must teach label=type + the per-label
    identity keys."""
    guide = analyser_pod._L0_REFERENCE_GUIDE
    assert "label" in guide and "TYPE" in guide
    assert "Endpoint: {path, method, baseurl}" in guide
    assert "BaseURL: {url}" in guide
    assert "NEVER put a value" in guide


def test_analyser_skill_degrades_to_fallback_when_missing(monkeypatch):
    import pathlib

    def boom(self, *a, **k):
        raise OSError("no skill mount")

    monkeypatch.setattr(pathlib.Path, "read_text", boom)
    from polymerhus.recon.domain import skills
    skills.clear_cache()  # force a re-read that will fail
    skill = analyser_pod._load_analyser_skill()
    assert skill == analyser_pod._ANALYSER_SYSTEM_PROMPT  # graceful degrade, no crash
    skills.clear_cache()  # reset cache so other tests re-load the real file
