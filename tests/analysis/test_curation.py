"""FR-CURATE + FR-TYPESEP-b integrator unit tier: the post-recon curation pass.

Injected fakes only (no live LLM / no live DB): `propose_fn` and `read_fn` are
injected on `run_curation`, and the `l1_curator` / `sweep` / `anatomy` seams are
monkeypatched so every test is hermetic. Each test names the assertion it encodes
(docs/design/post-recon-curation-and-l1-remediation-plan.md §4/§5 ledgers).
"""
import pytest

from polymerhus.analysis import curation
from polymerhus.analysis import anatomy, index_card, l1_curator, sweep
from polymerhus.analysis.anatomy import AnatomyResult
from polymerhus.analysis.curation_types import (
    CurationBatch,
    DeleteProposal,
    MergeProposal,
    RelabelProposal,
    RehomeProposal,
    curation_proposals_to_ops,
)
from polymerhus.analysis.l1_types import Provenance


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


# --- AST-CUR-01: run_curation executes the proposed ops; report counts match ---

def test_curation_executes_proposed_ops(monkeypatch):
    captured = {}

    def fake_reconcile(project_id, *, merges=None, deletes=None, relabels=None, merge_fn=None):
        captured["merges"] = merges
        captured["deletes"] = deletes
        captured["relabels"] = relabels
        return {"merged": len(merges or []), "deleted": len(deletes or []),
                "relabelled": len(relabels or [])}

    monkeypatch.setattr(l1_curator, "reconcile", fake_reconcile)
    _stub_anatomy(monkeypatch)

    batch = CurationBatch(
        merges=[MergeProposal(kind="service", canonical="checkout", duplicate="check-out")],
    )
    report = curation.run_curation("proj1", "run1", read_fn=_empty_read_fn,
                                   propose_fn=lambda ctx: batch)

    # reconcile was called with the mapped merge op
    assert len(captured["merges"]) == 1
    op = captured["merges"][0]
    assert op.label == "L1Service"
    assert op.canonical == {"business_function_slug": "checkout"}
    assert op.duplicate == {"business_function_slug": "check-out"}

    # report counts reflect what was executed
    assert report.merged == 1
    assert report.error is None


# --- AST-CUR-01: a stage that raises does not abort later stages (fail-open) ---

def test_stage_fail_open(monkeypatch):
    sweep_calls = {}

    def fake_stale(project_id, *, labels=None, read_fn=None):
        sweep_calls["stale"] = True
        return 7

    def fake_owners(project_id, *, read_fn=None):
        sweep_calls["owners"] = True
        return sweep.StaleOwnershipBatch(proposals=[
            sweep.StaleAssetOwnership(asset_ref={"path": "/healthz"}, kind="AuthorizationSystem"),
        ])

    monkeypatch.setattr(sweep, "stale_pool_count", fake_stale)
    monkeypatch.setattr(sweep, "resolve_stale_owners", fake_owners)
    _stub_anatomy(monkeypatch)

    def boom(ctx):
        raise RuntimeError("llm down")

    report = curation.run_curation("proj1", "run1", read_fn=_empty_read_fn, propose_fn=boom)

    # the propose failure is recorded but did NOT abort the pass
    assert report.error and "propose" in report.error
    # the sweep stage still ran despite the earlier failure
    assert sweep_calls.get("stale") and sweep_calls.get("owners")
    assert report.stale_count == 7
    assert report.stale_owners == [{"asset_ref": {"path": "/healthz"}, "service_slug": None,
                                    "kind": "AuthorizationSystem", "rationale": None}]


# --- AST-CUR-03: anatomy skill + both sweeps invoked; results land in the report ---

def test_curation_invokes_anatomy_and_sweep(monkeypatch):
    calls = {"profiled": [], "committed": [], "stale": 0, "owners": 0}

    def fake_profile(signals, *, service_id=None, **kw):
        calls["profiled"].append(service_id)
        return AnatomyResult()

    def fake_commit(result, project_id, slug, **kw):
        calls["committed"].append(slug)
        return {}

    def fake_stale(project_id, *, labels=None, read_fn=None):
        calls["stale"] += 1
        return 5

    def fake_owners(project_id, *, read_fn=None):
        calls["owners"] += 1
        return sweep.StaleOwnershipBatch(proposals=[
            sweep.StaleAssetOwnership(asset_ref={"path": "/x"}, kind="CDN"),
        ])

    monkeypatch.setattr(anatomy, "webpage_profile", fake_profile)
    monkeypatch.setattr(anatomy, "commit_anatomy", fake_commit)
    monkeypatch.setattr(sweep, "stale_pool_count", fake_stale)
    monkeypatch.setattr(sweep, "resolve_stale_owners", fake_owners)
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
    assert calls["stale"] == 1 and calls["owners"] == 1  # both sweeps invoked
    assert report.stale_count == 5
    assert [p["kind"] for p in report.stale_owners] == ["CDN"]
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
    monkeypatch.setattr(sweep, "resolve_stale_owners", lambda p, *, read_fn=None: sweep.StaleOwnershipBatch())
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
    assert edge.kind == "WebPresentation"
    # the rendering VALUE is written as a PROP on the WebPresentation System (not lost)
    systems = captured["systems"]
    assert len(systems) == 1
    assert systems[0].kind == "WebPresentation"
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
    assert edges[0].rel == "EXPOSED_VIA" and edges[0].kind == "WebPresentation"
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
    assert edges[0].kind == "AuthenticationMechanism"
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
    assert edges[0].kind == "GraphQLApi"
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
    assert merges[0].canonical == {"kind": "CDN", "discriminator": "__singleton__"}
    assert merges[0].duplicate == {"kind": "CDN", "discriminator": "Datadome"}

    assert deletes[0].label == "L1Service"
    assert deletes[0].identity == {"business_function_slug": "healthz"}

    assert relabels[0].from_label == "L1Service"
    assert relabels[0].to_label == "L1System"
    assert relabels[0].identity == {"business_function_slug": "graphql-api"}
    assert relabels[0].new_identity == {"kind": "GraphQLApi", "discriminator": "__singleton__"}


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
    monkeypatch.setattr(sweep, "resolve_stale_owners", lambda *a, **k: sweep.StaleOwnershipBatch())

    batch = CurationBatch(merges=[MergeProposal(kind="service", canonical="checkout", duplicate="check-out")])
    report = curation.run_curation("p", "r", read_fn=_empty_read_fn, propose_fn=lambda ctx: batch)

    assert report.merged == 1
    assert "check-out" not in anatomy_calls, (
        f"anatomy ran for the merged-away duplicate (stale context): {anatomy_calls}"
    )
    assert live == {"checkout"}, f"the merged-away duplicate was resurrected: {sorted(live)}"


# --- AST-CUR-05: dedup is SEMANTIC equivalence, not exact-key identity reuse ---
# The last e2e produced 0 merges partly because the prompt FORBADE semantic merges:
# it defined a duplicate as `iff they share a business_function_slug intent`, an
# exact-key test that is near-tautologically empty over a set of already-distinct
# keys. These two tests pin the NEW prompt contract (prompt string + SKILL.md) so a
# future edit cannot silently reintroduce the exact-key rule.

def test_curation_prompt_defines_dedup_as_semantic_not_exact_key():
    """`_curation_prompt` must instruct SEMANTIC equivalence (meaning judged over
    the full L1 context, not the slug), require a pairwise comparison BEFORE an
    empty result, keep the precision guard, carry a positive worked example, and
    NO LONGER carry the old exact-key `iff they share a business_function_slug
    intent` rule."""
    ctx = {"inventory": {"services": ["account", "account-management"],
                         "systems": [], "data_items": []},
           "cards": [], "stale_pool": []}
    p = curation._curation_prompt(ctx)
    low = p.lower()
    # semantic-equivalence instruction: judge MEANING, the slug is only a label
    assert "semantic" in low
    assert "meaning" in low or "denote the same" in low
    assert "slug is a label" in low or "label, not the identity" in low
    # pairwise-comparison-before-empty instruction (empty is EARNED, not default)
    assert "every pair" in low
    assert "different slug" in low and "not sufficient" in low
    # the precision guard survives the looser recall rule
    assert "cart" in low and "checkout" in low
    # a positive worked example (weaker models need a recipe)
    assert "account-management" in p
    # the OLD exact-key rule is GONE
    assert "iff they share a business_function_slug intent" not in p


def test_curation_skill_defines_dedup_as_semantic_not_identity_reuse():
    """The SKILL.md loaded by the pass must encode the same semantic-equivalence
    contract: retitled away from `Dedup is identity reuse`, a meaning-based test,
    a pairwise-before-empty rule, the precision guard, a worked example, and NONE
    of the old exact-key `iff` rule."""
    from polymerhus.recon.domain import skills
    skills.clear_cache()
    text = skills.skill_for("analysis/curation")
    low = text.lower()
    assert not text.startswith("---")  # frontmatter stripped
    # retitled + semantic definition
    assert "semantic equivalence" in low
    assert "dedup is identity reuse" not in low
    # meaning-based, not slug-based
    assert "slug is a label" in low
    assert "account-management" in text  # the worked example
    # empty is EARNED via a pairwise comparison, not a default
    assert "every pair" in low
    assert "different slug" in low
    # precision guard
    assert "cart" in low and "checkout" in low
    # the old exact-key `iff` rules are GONE
    assert "iff they share a single business-function intent" not in text
    assert "iff they share a `kind:discriminator`" not in text
    skills.clear_cache()


# --- AST-CUR-06: RECALL seam - a semantic merge is carried end-to-end -----------
# Because dedup is now the LLM's JUDGMENT we cannot unit-test the model's output;
# we test the SEAM instead. A semantic-duplicate pair (account / account-management)
# whose merge the model proposes must be executed through the sole-writer reconcile.
# The identity keys DIFFER - only their meaning is the same - so this proves the
# plumbing carries a semantic (not exact-key) merge, not that the LLM will find it.

def test_curation_carries_a_semantic_merge_through_reconcile(monkeypatch):
    captured = {}

    def fake_reconcile(project_id, *, merges=None, deletes=None, relabels=None, merge_fn=None):
        captured["merges"] = merges
        return {"merged": len(merges or []), "deleted": 0, "relabelled": 0}

    monkeypatch.setattr(l1_curator, "reconcile", fake_reconcile)
    monkeypatch.setattr(l1_curator, "l1_curate",
                        lambda services, systems, project_id, **k: (len(services), 0))
    _stub_anatomy(monkeypatch)

    def read_fn(query, params):
        if "count(n) AS c" in query:                        # stale count (matches L1Service too)
            return [{"c": 0}]
        if "L1TestableUnit" in query:                       # index_cards
            return [_service_card("account"), _service_card("account-management")]
        if "L1Service" in query:                            # inventory: the dup pair
            return [{"slug": "account"}, {"slug": "account-management"}]
        return []

    seen = {}

    def propose(ctx):
        # the model judged the two slugs to denote the SAME function -> merge
        seen["services"] = (ctx.get("inventory") or {}).get("services")
        return CurationBatch(merges=[MergeProposal(
            kind="service", canonical="account", duplicate="account-management")])

    report = curation.run_curation("p", "r", read_fn=read_fn, propose_fn=propose)

    # the inventory the model saw carried BOTH semantic-dup slugs (plumbing works)
    assert set(seen["services"]) == {"account", "account-management"}
    # the semantic merge was executed through the sole-writer reconcile
    assert len(captured["merges"]) == 1
    op = captured["merges"][0]
    assert op.label == "L1Service"
    assert op.canonical == {"business_function_slug": "account"}
    assert op.duplicate == {"business_function_slug": "account-management"}
    assert report.merged == 1
    assert report.error is None


# --- AST-CUR-07: PRECISION seam - the pipeline never fabricates a merge ---------
# The looser semantic-recall rule must not let the pipeline invent merges. A
# near-pair the model correctly keeps distinct (cart vs checkout - adjacent steps,
# different functions) yields ZERO merges: only proposed ops execute, and reconcile
# is not even invoked when nothing is proposed.

def test_curation_never_fabricates_an_unproposed_merge(monkeypatch):
    captured = {"reconcile_called": False}

    def fake_reconcile(project_id, *, merges=None, deletes=None, relabels=None, merge_fn=None):
        captured["reconcile_called"] = True
        return {"merged": len(merges or []), "deleted": 0, "relabelled": 0}

    monkeypatch.setattr(l1_curator, "reconcile", fake_reconcile)
    monkeypatch.setattr(l1_curator, "l1_curate",
                        lambda services, systems, project_id, **k: (len(services), 0))
    _stub_anatomy(monkeypatch)

    def read_fn(query, params):
        if "count(n) AS c" in query:                        # stale count (matches L1Service too)
            return [{"c": 0}]
        if "L1TestableUnit" in query:
            return [_service_card("cart"), _service_card("checkout")]
        if "L1Service" in query:
            return [{"slug": "cart"}, {"slug": "checkout"}]
        return []

    # the model compared cart vs checkout and (correctly) kept them distinct
    report = curation.run_curation("p", "r", read_fn=read_fn,
                                   propose_fn=lambda ctx: CurationBatch())

    assert report.merged == 0
    # reconcile is not invoked at all when there is nothing to reconcile: the
    # pipeline executes only what the model proposes, never a fabricated merge
    assert captured["reconcile_called"] is False
    assert report.error is None
