"""FR-ANALYSER unit tier — the proposal->delta mapping and the sole-writer curate
collaborators, with injected fake collaborators (no live LLM/DB). Store-level
idempotency is the integration tier (tests/integration/test_analyser_pod_merge.py).

RETIRED (#48 section 11 step 6, ratified 2026-07-30): the legacy compiled
`build_analyser_graph` subgraph (`read -> analyse -> curate`, with its per-node
fail-open degrade behaviour) and the legacy two-pass prompt/skill-loader
(`_two_pass_analyse`, `_load_analyser_skill`, `_L0_REFERENCE_GUIDE`,
`_ANALYSER_SYSTEM_PROMPT`) are deleted along with the whole legacy pod - see
`pod.py`'s module docstring. The behaviours those tests guarded now live
elsewhere: per-step fail-open degrade is exercised by `supervisor.analyse_chunked`
(each read/dispatch/write already guarded, tested in
`tests/integration/test_control_plane_contracts.py` and the walkthroughs), and the
positive-recipe / observed-fields-only / reflect-then-extract prompt disciplines
now live in `data_modeller.py` (`tests/analysis/test_data_modeller.py`,
`tests/integration/test_data_modeller_contracts.py`).

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
    default_curate_fn,
    default_curate_with_enrichment_fn,
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


# `_invoke_with_retry` was RETIRED (#73): structured analyser calls now retry via the
# single escalating-budget layer, covered by
# tests/test_llm_providers.py::test_escalating_invoke_*.


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


def test_slice_repr_is_untruncated():
    """#48 section 11 step 6: the legacy 400-node cap is retired as a provable
    no-op - every consumer now renders a single chunk, bounded well under it."""
    nodes = [{"type": "Endpoint", "path": f"/x{i}"} for i in range(150)]
    out = analyser_pod._slice_repr({"nodes": nodes})
    assert "150 nodes" in out
    assert "omitted" not in out  # nothing is ever dropped now
    assert all(f"/x{i}" in out for i in (0, 149))  # first AND last node both survive
