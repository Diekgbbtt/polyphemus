"""FR-CURATE + FR-TYPESEP-b integrator unit tier: the post-recon curation pass.

Injected fakes only (no live LLM / no live DB): `propose_fn` and `read_fn` are
injected on `run_curation`, and the `l1_curator` / `sweep` / `anatomy` seams are
monkeypatched so every test is hermetic. Each test names the assertion it encodes
(docs/design/post-recon-curation-and-l1-remediation-plan.md §4/§5 ledgers).
"""
import pytest

from agent.recon.analysis import curation
from agent.recon.analysis import anatomy, index_card, l1_curator, sweep
from agent.recon.analysis.anatomy import AnatomyResult
from agent.recon.analysis.curation_types import (
    CurationBatch,
    DeleteProposal,
    MergeProposal,
    RelabelProposal,
    RehomeProposal,
    curation_proposals_to_ops,
)
from agent.recon.analysis.l1_types import Provenance


def _empty_read_fn(query, params):
    """A permissive fake: every curation read returns an empty result, so the
    card / inventory / sweep reads degrade to empties without a live DB."""
    if "count(n) AS c" in query:
        return [{"c": 0}]
    return []


def _service_card(slug, project_id="p", props=None, rels=None):
    base = {"business_function_slug": slug, "project_id": project_id}
    base.update(props or {})
    return {"labels": ["L1TestableUnit", "L1Service"], "props": base, "rels": rels or []}


def _stub_anatomy(monkeypatch):
    """Keep the anatomy stage inert (no live LLM) for tests not about anatomy."""
    monkeypatch.setattr(anatomy, "webpage_profile", lambda *a, **k: AnatomyResult())
    monkeypatch.setattr(anatomy, "commit_anatomy", lambda *a, **k: {})


# --- AST-CUR-01: run_curation executes proposed ops + writes journeys; counts match ---

def test_curation_executes_proposed_ops(monkeypatch):
    captured = {}

    def fake_reconcile(project_id, *, merges=None, deletes=None, relabels=None, merge_fn=None):
        captured["merges"] = merges
        captured["deletes"] = deletes
        captured["relabels"] = relabels
        return {"merged": len(merges or []), "deleted": len(deletes or []),
                "relabelled": len(relabels or [])}

    def fake_curate(services, systems, project_id, *, merge_fn=None):
        captured.setdefault("journey_deltas", []).extend(services)
        return (len(services), 0)

    monkeypatch.setattr(l1_curator, "reconcile", fake_reconcile)
    monkeypatch.setattr(l1_curator, "l1_curate", fake_curate)
    _stub_anatomy(monkeypatch)

    batch = CurationBatch(
        merges=[MergeProposal(kind="service", canonical="checkout", duplicate="check-out")],
        journeys={"checkout-flow": ["checkout"]},
    )
    report = curation.run_curation("proj1", "run1", read_fn=_empty_read_fn,
                                   propose_fn=lambda ctx: batch)

    # reconcile was called with the mapped merge op
    assert len(captured["merges"]) == 1
    op = captured["merges"][0]
    assert op.label == "L1Service"
    assert op.canonical == {"business_function_slug": "checkout"}
    assert op.duplicate == {"business_function_slug": "check-out"}

    # the journey membership was written onto the member Service
    deltas = captured["journey_deltas"]
    checkout = next(d for d in deltas if d.business_function_slug == "checkout")
    assert "checkout-flow" in checkout.props["journeys"]

    # report counts reflect what was executed
    assert report.merged == 1
    assert report.journeys_written == 1
    assert report.error is None


# --- AST-CUR-01: a stage that raises does not abort later stages (fail-open) ---

def test_stage_fail_open(monkeypatch):
    sweep_calls = {}

    def fake_stale(project_id, *, labels=None, read_fn=None):
        sweep_calls["stale"] = True
        return 7

    def fake_missing(project_id, *, read_fn=None):
        sweep_calls["missing"] = True
        return ["WAF", "CDN"]

    monkeypatch.setattr(sweep, "stale_pool_count", fake_stale)
    monkeypatch.setattr(sweep, "missing_system_kinds", fake_missing)
    _stub_anatomy(monkeypatch)

    def boom(ctx):
        raise RuntimeError("llm down")

    report = curation.run_curation("proj1", "run1", read_fn=_empty_read_fn, propose_fn=boom)

    # the propose failure is recorded but did NOT abort the pass
    assert report.error and "propose" in report.error
    # the sweep stage still ran despite the earlier failure
    assert sweep_calls.get("stale") and sweep_calls.get("missing")
    assert report.stale_count == 7
    assert report.missing_kinds == ["WAF", "CDN"]


# --- AST-CUR-02: same-journey services share the journey; append-not-clobber ---

def test_curation_groups_same_journey_services(monkeypatch):
    captured = {}

    def fake_curate(services, systems, project_id, *, merge_fn=None):
        captured.setdefault("deltas", []).extend(services)
        return (len(services), 0)

    monkeypatch.setattr(l1_curator, "l1_curate", fake_curate)
    monkeypatch.setattr(l1_curator, "reconcile",
                        lambda *a, **k: {"merged": 0, "deleted": 0, "relabelled": 0})
    _stub_anatomy(monkeypatch)

    def read_fn(query, params):
        if "L1TestableUnit" in query:  # index_cards
            return [
                _service_card("cart", props={"journeys": ["browse-flow"]}),  # already a member
                _service_card("checkout"),
                _service_card("payment"),
            ]
        if "count(n) AS c" in query:
            return [{"c": 0}]
        return []

    batch = CurationBatch(journeys={"checkout-flow": ["cart", "checkout", "payment"]})
    report = curation.run_curation("p", "run1", read_fn=read_fn, propose_fn=lambda ctx: batch)

    by_slug = {d.business_function_slug: list(d.props.get("journeys", [])) for d in captured["deltas"]}
    assert set(by_slug) == {"cart", "checkout", "payment"}
    assert "checkout-flow" in by_slug["checkout"]
    assert "checkout-flow" in by_slug["payment"]
    # append-not-clobber: cart keeps its prior journey AND gains the new one
    assert set(by_slug["cart"]) == {"browse-flow", "checkout-flow"}
    assert report.journeys_written == 3


# --- AST-CUR-03: anatomy skill + both sweeps invoked; results land in the report ---

def test_curation_invokes_anatomy_and_sweep(monkeypatch):
    calls = {"profiled": [], "committed": [], "stale": 0, "missing": 0}

    def fake_profile(signals, *, service_id=None, **kw):
        calls["profiled"].append(service_id)
        return AnatomyResult()

    def fake_commit(result, project_id, slug, **kw):
        calls["committed"].append(slug)
        return {}

    def fake_stale(project_id, *, labels=None, read_fn=None):
        calls["stale"] += 1
        return 5

    def fake_missing(project_id, *, read_fn=None):
        calls["missing"] += 1
        return ["CDN"]

    monkeypatch.setattr(anatomy, "webpage_profile", fake_profile)
    monkeypatch.setattr(anatomy, "commit_anatomy", fake_commit)
    monkeypatch.setattr(sweep, "stale_pool_count", fake_stale)
    monkeypatch.setattr(sweep, "missing_system_kinds", fake_missing)
    monkeypatch.setattr(l1_curator, "reconcile",
                        lambda *a, **k: {"merged": 0, "deleted": 0, "relabelled": 0})

    def read_fn(query, params):
        if "L1TestableUnit" in query:
            return [_service_card("checkout")]
        if "count(n) AS c" in query:
            return [{"c": 0}]
        return []

    report = curation.run_curation("p", "run1", read_fn=read_fn, propose_fn=lambda ctx: CurationBatch())

    assert calls["profiled"] == ["checkout"]     # anatomy webpage-profile invoked
    assert calls["committed"] == ["checkout"]    # and committed
    assert calls["stale"] == 1 and calls["missing"] == 1  # both sweeps invoked
    assert report.stale_count == 5
    assert report.missing_kinds == ["CDN"]
    assert report.anatomy.get("profiled") == 1


def test_curation_anatomy_failure_is_fail_open(monkeypatch):
    def boom_profile(signals, **kw):
        raise RuntimeError("anatomy down")

    fired = {"stale": False}

    def fake_stale(project_id, *, labels=None, read_fn=None):
        fired["stale"] = True
        return 3

    monkeypatch.setattr(anatomy, "webpage_profile", boom_profile)
    monkeypatch.setattr(sweep, "stale_pool_count", fake_stale)
    monkeypatch.setattr(sweep, "missing_system_kinds", lambda p, *, read_fn=None: [])
    monkeypatch.setattr(l1_curator, "reconcile",
                        lambda *a, **k: {"merged": 0, "deleted": 0, "relabelled": 0})

    def read_fn(query, params):
        if "L1TestableUnit" in query:
            return [_service_card("checkout")]
        if "count(n) AS c" in query:
            return [{"c": 0}]
        return []

    report = curation.run_curation("p", "run1", read_fn=read_fn, propose_fn=lambda ctx: CurationBatch())
    # anatomy blew up but the later sweep stage still ran (fail-open)
    assert fired["stale"] is True
    assert report.stale_count == 3


# --- AST-MODEL-03 / AST-TYPE-02: rehome a rendering prop wrongly set on a Service
# into the WebPresentation System (the mechanism-as-System correction) ---

def _capture_rehome_seams(monkeypatch, captured):
    """Monkeypatch the three l1_curator write seams the re-homing uses (l1_curate
    for the System props, enrich for the edge, strip_props for the stale prop) so
    the re-homing is exercised hermetically (no live DB)."""
    def fake_curate(services, systems, project_id, *, merge_fn=None):
        captured.setdefault("services", []).extend(services or [])
        captured.setdefault("systems", []).extend(systems or [])
        return (len(services or []), len(systems or []))

    def fake_enrich(project_id, *, system_edges=None, **kw):
        captured.setdefault("system_edges", []).extend(system_edges or [])
        return {"system_edges": len(system_edges or [])}

    def fake_strip(project_id, ops, *, merge_fn=None):
        captured.setdefault("strip_ops", []).extend(ops or [])
        return len(ops or [])

    monkeypatch.setattr(l1_curator, "l1_curate", fake_curate)
    monkeypatch.setattr(l1_curator, "enrich", fake_enrich)
    monkeypatch.setattr(l1_curator, "strip_props", fake_strip)
    monkeypatch.setattr(l1_curator, "reconcile",
                        lambda *a, **k: {"merged": 0, "deleted": 0, "relabelled": 0})


def test_curation_rehomes_rendering_prop_to_system(monkeypatch):
    captured = {}
    _capture_rehome_seams(monkeypatch, captured)
    _stub_anatomy(monkeypatch)

    def read_fn(query, params):
        if "L1TestableUnit" in query:
            return [_service_card("checkout", props={"rendering_model": "CSR"})]
        if "count(n) AS c" in query:
            return [{"c": 0}]
        return []

    report = curation.run_curation("p", "run1", read_fn=read_fn, propose_fn=lambda ctx: CurationBatch())

    # an EXPOSED_VIA edge to the WebPresentation System was created (NOT RENDERED_BY)
    edges = captured["system_edges"]
    assert len(edges) == 1
    edge = edges[0]
    assert edge.service_slug == "checkout"
    assert edge.rel == "EXPOSED_VIA"
    assert edge.system_kind == "WebPresentation"
    # the rendering VALUE is written as a PROP on the WebPresentation System (not lost)
    systems = captured["systems"]
    assert len(systems) == 1
    assert systems[0].system_kind == "WebPresentation"
    assert systems[0].props.get("rendering_model") == "CSR"
    # and the stale Service prop was stripped via the sole-writer prop-strip
    ops = captured["strip_ops"]
    assert len(ops) == 1
    assert ops[0].label == "L1Service"
    assert ops[0].identity == {"business_function_slug": "checkout"}
    assert "rendering_model" in ops[0].prop_keys
    assert report.rehomed == 1


def test_curation_rehomes_navigation_without_cross_dimension_inference(monkeypatch):
    """AST-MODEL-03: navigation_model re-homes to a navigation_model PROP on the
    WebPresentation System - it does NOT infer a CSR rendering (L1D-31a: the two
    dimensions are independent; the old SPA->CSR inference is deleted)."""
    captured = {}
    _capture_rehome_seams(monkeypatch, captured)
    _stub_anatomy(monkeypatch)

    def read_fn(query, params):
        if "L1TestableUnit" in query:
            return [_service_card("storefront", props={"navigation_model": "SPA"})]
        if "count(n) AS c" in query:
            return [{"c": 0}]
        return []

    report = curation.run_curation("p", "run1", read_fn=read_fn, propose_fn=lambda ctx: CurationBatch())

    edges = captured["system_edges"]
    assert len(edges) == 1
    assert edges[0].rel == "EXPOSED_VIA" and edges[0].system_kind == "WebPresentation"
    systems = captured["systems"]
    # the SPA value lands as a navigation_model prop - NO rendering_model is inferred
    assert systems[0].props.get("navigation_model") == "SPA"
    assert "rendering_model" not in systems[0].props
    assert report.rehomed == 1


def test_curation_rehomes_auth_methods_to_authenticated_by(monkeypatch):
    """AST-MODEL-03: auth_methods re-homes off the Service to an AUTHENTICATED_BY
    edge to the AuthenticationMechanism System (mechanism = System, L1D-5), and the
    stale Service prop is stripped."""
    captured = {}
    _capture_rehome_seams(monkeypatch, captured)
    _stub_anatomy(monkeypatch)

    def read_fn(query, params):
        if "L1TestableUnit" in query:
            return [_service_card("sign-in", props={"auth_methods": "password"})]
        if "count(n) AS c" in query:
            return [{"c": 0}]
        return []

    report = curation.run_curation("p", "run1", read_fn=read_fn, propose_fn=lambda ctx: CurationBatch())

    edges = captured["system_edges"]
    assert len(edges) == 1
    assert edges[0].rel == "AUTHENTICATED_BY"
    assert edges[0].system_kind == "AuthenticationMechanism"
    ops = captured["strip_ops"]
    assert len(ops) == 1 and "auth_methods" in ops[0].prop_keys
    assert report.rehomed == 1


def test_curation_rehomes_llm_proposed_prop(monkeypatch):
    """The batch may also carry explicit rehome proposals (a Service prop that is
    really a System fact); they re-home the same way as the deterministic scan."""
    captured = {}
    monkeypatch.setattr(l1_curator, "enrich",
                        lambda project_id, *, system_edges=None, **k:
                        captured.setdefault("edges", []).extend(system_edges or []) or {"system_edges": 1})
    monkeypatch.setattr(l1_curator, "strip_props",
                        lambda project_id, ops, **k:
                        captured.setdefault("strip", []).extend(ops or []) or len(ops or []))
    monkeypatch.setattr(l1_curator, "reconcile",
                        lambda *a, **k: {"merged": 0, "deleted": 0, "relabelled": 0})
    _stub_anatomy(monkeypatch)

    batch = CurationBatch(rehome=[RehomeProposal(service_slug="api", prop_key="api_paradigm",
                                                 prop_value="GraphQL")])
    report = curation.run_curation("p", "run1", read_fn=_empty_read_fn, propose_fn=lambda ctx: batch)

    edges = captured["edges"]
    assert len(edges) == 1
    assert edges[0].rel == "EXPOSED_VIA"
    assert edges[0].system_kind == "GraphQLApi"
    assert report.rehomed == 1


# --- curation_proposals_to_ops: the pure batch -> reconcile-op mapping ---

def test_curation_proposals_to_ops_maps_keys():
    prov = Provenance(job="c", model=None, prompt_id=None)
    batch = CurationBatch(
        merges=[MergeProposal(kind="system", canonical="CDN", duplicate="CDN:Datadome")],
        deletes=[DeleteProposal(kind="service", key="healthz")],
        relabels=[RelabelProposal(from_kind="service", to_kind="system",
                                  key="graphql-api", new_key="GraphQLApi")],
    )
    merges, deletes, relabels = curation_proposals_to_ops(batch, prov)

    assert merges[0].label == "L1System"
    assert merges[0].canonical == {"system_kind": "CDN", "discriminator": "__singleton__"}
    assert merges[0].duplicate == {"system_kind": "CDN", "discriminator": "Datadome"}

    assert deletes[0].label == "L1Service"
    assert deletes[0].identity == {"business_function_slug": "healthz"}

    assert relabels[0].from_label == "L1Service"
    assert relabels[0].to_label == "L1System"
    assert relabels[0].identity == {"business_function_slug": "graphql-api"}
    assert relabels[0].new_identity == {"system_kind": "GraphQLApi", "discriminator": "__singleton__"}


# --- AST-CUR-04: stages after reconcile must see the POST-reconciliation graph ---
# Regression guard for the FR-CURE2E defect: run_curation read its index-cards ONCE
# at stage 1 and handed that snapshot to the later stages. Stage 3 merged a duplicate
# away, then stage 5 (anatomy) iterated the STALE list and commit_anatomy MERGEd the
# deleted Service back into existence - so curation silently undid its own dedup and
# reported merged=1 forever. Found by the adversarial dirty-graph probe; invisible to
# the FR-MERGE integration tests because reconcile is correct in ISOLATION.

def test_curation_does_not_resurrect_a_merged_away_service(monkeypatch):
    """A Service removed by the reconcile stage must NOT be re-created by any later
    stage: the post-reconcile stages operate on refreshed context, never the stale
    pre-merge card list."""
    live = {"checkout", "check-out"}          # the mutable "graph"
    anatomy_calls: list[str] = []

    def fake_index_cards(project_id, *, read_fn=None):
        # Cards always reflect the CURRENT graph, like the real reader would.
        return [{"kind": "Service", "key": {"business_function_slug": s}, "spine": {}, "edge_degree": {}}
                for s in sorted(live)]

    def fake_reconcile(project_id, *, merges=None, deletes=None, relabels=None, merge_fn=None):
        for op in merges or []:
            live.discard(op.duplicate.get("business_function_slug"))
        for op in deletes or []:
            live.discard(op.identity.get("business_function_slug"))
        return {"merged": len(merges or []), "deleted": len(deletes or []),
                "relabelled": len(relabels or [])}

    def fake_commit_anatomy(result, project_id, slug, *, provenance=None):
        anatomy_calls.append(slug)
        live.add(slug)   # commit_anatomy MERGEs the Service - the resurrection vector
        return {}

    monkeypatch.setattr(index_card, "index_cards", fake_index_cards)
    monkeypatch.setattr(l1_curator, "reconcile", fake_reconcile)
    monkeypatch.setattr(l1_curator, "l1_curate", lambda services, systems, project_id, **k: (len(services), 0))
    monkeypatch.setattr(anatomy, "webpage_profile", lambda *a, **k: AnatomyResult())
    monkeypatch.setattr(anatomy, "commit_anatomy", fake_commit_anatomy)
    monkeypatch.setattr(sweep, "stale_pool_count", lambda *a, **k: 0)
    monkeypatch.setattr(sweep, "missing_system_kinds", lambda *a, **k: [])

    batch = CurationBatch(merges=[MergeProposal(kind="service", canonical="checkout", duplicate="check-out")])
    report = curation.run_curation("p", "r", read_fn=_empty_read_fn, propose_fn=lambda ctx: batch)

    assert report.merged == 1
    assert "check-out" not in anatomy_calls, (
        f"anatomy ran for the merged-away duplicate (stale context): {anatomy_calls}"
    )
    assert live == {"checkout"}, f"the merged-away duplicate was resurrected: {sorted(live)}"
