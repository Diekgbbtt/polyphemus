"""FR-ANALYSER unit tier — the analyser subgraph's control flow + the
proposal->delta mapping, with injected fake collaborators (no live LLM/DB).
Store-level idempotency is the integration tier
(tests/integration/test_analyser_pod_merge.py).

Each test names the assertion it encodes (docs/design/L1-MVP-plan.md §5).
"""
from agent.recon.analysis.analyser_types import (
    AggregatesProposal,
    DataFlowProposal,
    DataItemProposal,
    L1DeltaBatch,
    ServiceProposal,
    SystemEdgeProposal,
    SystemProposal,
    proposals_to_deltas,
)
from agent.recon.analysis import l1_curator as real_l1_curator
from agent.recon.analysis import pod as analyser_pod
from agent.recon.analysis.l1_types import L0Ref, Provenance
from agent.recon.analysis.pod import (
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
        systems=[SystemProposal(system_kind="RESTApi")],
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
    run_analyser("proj-9", "run-42", graph=graph)
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
    export = run_analyser("proj-1", "run-1", graph=graph)  # must NOT raise

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
    export = run_analyser("proj-1", "run-1", graph=graph)  # must NOT raise
    assert export.error and "read" in export.error


def test_curate_error_degrades_not_raised():
    def exploding_curate(batch, project_id, provenance):
        raise RuntimeError("write failed")

    graph = build_analyser_graph(
        read_fn=lambda p: {"nodes": [], "links": []},
        analyse_fn=lambda s, o: L1DeltaBatch(services=[ServiceProposal(business_function_slug="x")]),
        curate_fn=exploding_curate,
    )
    export = run_analyser("proj-1", "run-1", graph=graph)  # must NOT raise
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

    # default_curate_fn does `from agent.recon.analysis import l1_curator` at call
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
    deltas AND the FR-ENRICH deltas from one batch, with system provenance, and
    seed the DataRelationship catalogue when enrichment is present. Guards the
    load-bearing FIX 2 wiring end-to-end (was inspection-only)."""
    calls = {}

    def fake_l1_curate(services, systems, project_id):
        calls["l1_curate"] = (len(services), len(systems))
        return (len(services), len(systems))

    def fake_write_aggregates(aggregates, project_id):
        calls["write_aggregates"] = len(aggregates)
        return len(aggregates)

    def fake_seed(project_id):
        calls["seeded"] = project_id

    def fake_enrich(project_id, **enrich_deltas):
        # capture the per-category delta counts + that provenance was injected
        calls["enrich"] = {k: len(v) for k, v in enrich_deltas.items()}
        calls["enrich_prov"] = enrich_deltas["data_items"][0].provenance.job if enrich_deltas["data_items"] else None
        return {k: len(v) for k, v in enrich_deltas.items()}

    monkeypatch.setattr(real_l1_curator, "l1_curate", fake_l1_curate)
    monkeypatch.setattr(real_l1_curator, "write_aggregates", fake_write_aggregates)
    monkeypatch.setattr(real_l1_curator, "seed_data_relationship_kinds", fake_seed)
    monkeypatch.setattr(real_l1_curator, "enrich", fake_enrich)

    batch = L1DeltaBatch(
        services=[ServiceProposal(business_function_slug="sales-analysis")],
        systems=[SystemProposal(system_kind="RESTApi")],
        aggregates=[AggregatesProposal(service_slug="sales-analysis",
                                       l0=L0Ref(label="Endpoint", identity={"path": "/s", "method": "GET", "baseurl": "https://a"}))],
        data_items=[DataItemProposal(item_key="sales_figure")],
        data_flows=[DataFlowProposal(service_slug="sales-analysis", item_key="sales_figure", direction="consumes",
                                     assumption="authorized for THIS user")],
        system_edges=[SystemEdgeProposal(service_slug="sales-analysis", system_kind="RESTApi", rel="EXPOSED_VIA")],
    )
    prov = Provenance(job="analyser:run-77", model="m", prompt_id=None)
    export = default_curate_with_enrichment_fn(batch, "proj-1", prov)

    # core written
    assert calls["l1_curate"] == (1, 1)
    assert calls["write_aggregates"] == 1
    # enrichment written (the FIX 2 seam) with the right per-category counts
    assert calls["seeded"] == "proj-1"  # catalogue seeded because enrichment present
    assert calls["enrich"]["data_items"] == 1
    assert calls["enrich"]["data_flows"] == 1
    assert calls["enrich"]["system_edges"] == 1
    # provenance is system-supplied (run-scoped), injected at the curate boundary
    assert calls["enrich_prov"] == "analyser:run-77"
    # export surfaces both core counts and the enrichment counts
    assert export.services_written == 1 and export.aggregates_written == 1
    assert export.enrichment["system_edges"] == 1


def test_default_curate_with_enrichment_skips_enrich_when_no_enrichment_deltas(monkeypatch):
    """When the batch has no enrichment deltas, the enrich path (and its catalogue
    seed) must NOT fire - only the core write runs."""
    calls = {"enrich": False, "seeded": False}
    monkeypatch.setattr(real_l1_curator, "l1_curate", lambda s, sy, p: (len(s), len(sy)))
    monkeypatch.setattr(real_l1_curator, "write_aggregates", lambda a, p: len(a))
    monkeypatch.setattr(real_l1_curator, "seed_data_relationship_kinds", lambda p: calls.__setitem__("seeded", True))
    monkeypatch.setattr(real_l1_curator, "enrich", lambda p, **k: calls.__setitem__("enrich", True))

    batch = L1DeltaBatch(services=[ServiceProposal(business_function_slug="x")])  # core only
    export = default_curate_with_enrichment_fn(batch, "proj-1", PROV)
    assert calls["enrich"] is False and calls["seeded"] is False  # no enrichment -> no enrich/seed
    assert export.enrichment is None
    assert export.services_written == 1


# --- analyser skill config (overthink + critical-thinking wired into the prompt) ---

def test_analyser_skill_loads_and_strips_frontmatter():
    analyser_pod._ANALYSER_SKILL = None  # bypass cache for a clean load
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
    analyser_pod._ANALYSER_SKILL = None
    first = analyser_pod._load_analyser_skill()
    second = analyser_pod._load_analyser_skill()
    assert first is second  # cached (same object), not re-read


def test_vocabulary_prompt_lists_controlled_values():
    """Regression for an e2e-caught defect: the LLM proposed 'Authentication'
    (not the canonical 'AuthenticationMechanism') and the delta was silently
    dropped. The prompt must enumerate the exact allowed vocabularies."""
    from agent.recon.analysis.l1_curator import vocabulary_prompt

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
    analyser_pod._ANALYSER_SKILL = None  # force a re-read that will fail
    skill = analyser_pod._load_analyser_skill()
    assert skill == analyser_pod._ANALYSER_SYSTEM_PROMPT  # graceful degrade, no crash
    analyser_pod._ANALYSER_SKILL = None  # reset cache so other tests re-load the real file
