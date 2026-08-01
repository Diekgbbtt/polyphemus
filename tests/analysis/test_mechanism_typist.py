"""Unit tier for the TechnicalSystem Analyser (`mechanism_typist`, #9) - the GRILLED
3-call design (reflection -> systems-extraction -> linking).

Mocks every collaborator (the injected `invoke_fn` honouring its `schema` kwarg, plus
`read_inventory` / `read_aggregations`) - NO live LLM or Neo4j (conftest enforces the
DB boundary). Covers the pure shapers, the primary/secondary partition, the 3-call
chain (order, fail-closed reflection, soft pass-through), the compounding-description
prompt, the read-seam extension, and the supervisor body seam. The integration/e2e
assertion catalogues (N1-N11, W-N1) live under the verifier gate, not here.
"""
from polymerhus.analysis.analyser_types import (
    L1DeltaBatch,
    ServiceProposal,
    SystemEdgeProposal,
    SystemProposal,
)
from polymerhus.analysis.chunking import Chunk
from polymerhus.analysis.mechanism_typist import (
    drop_unknown_vocabulary,
    mechanism_typist_body,
    narrow_to_typing,
    partition_services,
    type_mechanisms,
)
from polymerhus.recon.domain.types import AssetDelta, Observation

_KINDS = frozenset({"WebPresentation", "RESTApi", "AuthenticationMechanism", "WAF", "CDN"})
_RELS = frozenset({"EXPOSED_VIA", "AUTHENTICATED_BY", "FRONTED_BY"})


def _endpoint(path, baseurl="https://a"):
    return AssetDelta(type="Endpoint", identity={"path": path, "baseurl": baseurl})


def _service_chunk(*assets, observations=()):
    return Chunk(chunk_id="c", concern="service", assets=tuple(assets or (_endpoint("/x"),)),
                 observations=tuple(observations))


class _Recorder:
    """A 3-call `invoke_fn` honouring the `schema` kwarg: `schema=None` -> prose
    (reflection); a schema -> a crafted batch keyed by the task marker in the prompt.
    Records the call order for the sequence assertion (N2)."""

    def __init__(self, prose="I reason about the mechanisms.", systems=None, edges=None):
        self.calls: list[str] = []
        self.prose = prose
        self.systems = systems if systems is not None else L1DeltaBatch(
            systems=[SystemProposal(kind="RESTApi", props={"description": "REST surface"})])
        self.edges = edges if edges is not None else L1DeltaBatch(
            system_edges=[SystemEdgeProposal(service_slug="checkout", kind="RESTApi", rel="EXPOSED_VIA")])

    def __call__(self, messages, *, schema=None):
        content = messages[-1].content
        if schema is None:
            self.calls.append("reflect")
            return self.prose
        if "EXTRACT SYSTEMS" in content:
            self.calls.append("systems")
            return self.systems
        self.calls.append("link")
        return self.edges


# --- pure shaping -------------------------------------------------------------

def test_N1_narrow_to_typing_only():
    raw = L1DeltaBatch(
        services=[ServiceProposal(business_function_slug="checkout")],
        aggregates=[],
        systems=[SystemProposal(kind="RESTApi")],
        system_edges=[SystemEdgeProposal(service_slug="checkout", kind="RESTApi", rel="EXPOSED_VIA")],
    )
    out = narrow_to_typing(raw)
    assert out.services == [] and out.aggregates == []
    assert out.data_items == [] and out.data_flows == []
    assert out.systems and out.system_edges


def test_N5_drop_unknown_vocabulary():
    raw = L1DeltaBatch(
        systems=[SystemProposal(kind="RESTApi"), SystemProposal(kind="RenderingSystem_CSR_JSMap")],
        system_edges=[
            SystemEdgeProposal(service_slug="s", kind="RESTApi", rel="EXPOSED_VIA"),
            SystemEdgeProposal(service_slug="s", kind="RESTApi", rel="RENDERED_BY"),   # deleted rel
            SystemEdgeProposal(service_slug="s", kind="BogusKind", rel="EXPOSED_VIA"),
        ],
    )
    out = drop_unknown_vocabulary(raw, kinds=_KINDS, rels=_RELS)
    assert [s.kind for s in out.systems] == ["RESTApi"]
    assert [(e.kind, e.rel) for e in out.system_edges] == [("RESTApi", "EXPOSED_VIA")]


# --- primary/secondary partition (N7) -----------------------------------------

def test_N7_partition_primary_secondary_and_asset_less_excluded():
    chunk_assets = (_endpoint("/checkout"), _endpoint("/checkout/pay"))
    aggregations = [
        {"slug": "checkout", "labels": ["Endpoint"], "props": {"path": "/checkout", "baseurl": "https://a"}},
        {"slug": "account", "labels": ["Endpoint"], "props": {"path": "/account", "baseurl": "https://a"}},
    ]
    # "empty-svc" has NO aggregated asset -> must be excluded from candidates
    primary, secondary, owned = partition_services(
        chunk_assets, aggregations, frozenset({"checkout", "account", "empty-svc"}))
    assert primary == ["checkout"]                 # aggregates this chunk's asset
    assert secondary == ["account"]                # asset-bearing, but not this chunk
    assert "empty-svc" not in primary + secondary  # no aggregated asset -> not a candidate
    assert owned["checkout"] == ["Endpoint:/checkout"]


# --- the 3-call chain (N2 order, N3 fail-closed, N4 soft pass-through) ---------

def test_N2_three_call_sequence_in_order():
    rec = _Recorder()
    out = type_mechanisms(_service_chunk(), invoke_fn=rec)
    assert rec.calls == ["reflect", "systems", "link"]
    assert [s.kind for s in out.systems] == ["RESTApi"]
    assert [(e.service_slug, e.rel) for e in out.system_edges] == [("checkout", "EXPOSED_VIA")]


def test_N3_reflection_exhaustion_fails_closed():
    def invoke(messages, *, schema=None):
        return None if schema is None else L1DeltaBatch(systems=[SystemProposal(kind="RESTApi")])

    out = type_mechanisms(_service_chunk(), invoke_fn=invoke)
    assert out == L1DeltaBatch()  # no reflection -> whole step empty, no systems/edges


def test_N4_systems_exhaustion_soft_passthrough_no_systems():
    def invoke(messages, *, schema=None):
        if schema is None:
            return "prose"
        return None  # both structured calls exhaust
    out = type_mechanisms(_service_chunk(), invoke_fn=invoke)
    assert out.systems == [] and out.system_edges == []  # degraded, never crashed


def test_N4_linking_exhaustion_keeps_systems_drops_edges():
    def invoke(messages, *, schema=None):
        if schema is None:
            return "prose"
        if "EXTRACT SYSTEMS" in messages[-1].content:
            return L1DeltaBatch(systems=[SystemProposal(kind="CDN", props={"description": "edge"})])
        return None  # linking exhausts
    out = type_mechanisms(_service_chunk(), invoke_fn=invoke)
    assert [s.kind for s in out.systems] == ["CDN"]
    assert out.system_edges == []  # soft pass-through: systems survive, edges degrade


def test_N5_end_to_end_emits_only_valid_vocabulary():
    rec = _Recorder(
        systems=L1DeltaBatch(systems=[SystemProposal(kind="RESTApi"), SystemProposal(kind="Nonsense")]),
        edges=L1DeltaBatch(system_edges=[
            SystemEdgeProposal(service_slug="s", kind="RESTApi", rel="EXPOSED_VIA"),
            SystemEdgeProposal(service_slug="s", kind="RESTApi", rel="RENDERED_BY"),
        ]),
    )
    out = type_mechanisms(_service_chunk(), invoke_fn=rec)
    from polymerhus.analysis.l1_curator import _KNOWN_KINDS, SYSTEM_EDGE_RELS
    assert all(s.kind in _KNOWN_KINDS for s in out.systems)
    assert all(e.rel in SYSTEM_EDGE_RELS and e.kind in _KNOWN_KINDS for e in out.system_edges)


def test_N6_extend_prompt_shows_existing_description_and_demands_enrichment():
    """Compounding (grilled #9 Q7): the extraction prompt must surface the currently-
    defined System WITH its description AND instruct enrich-never-blank, or the model
    cannot compound and would clobber."""
    captured = {}

    def invoke(messages, *, schema=None):
        if schema is None:
            return "prose"
        if "EXTRACT SYSTEMS" in messages[-1].content:
            captured["systems_prompt"] = messages[-1].content
        return L1DeltaBatch()
    inventory = {"services": [], "systems": ["AuthenticationMechanism"],
                 "system_descriptions": {"AuthenticationMechanism": "bearer-token auth"}}
    type_mechanisms(_service_chunk(), invoke_fn=invoke, inventory=inventory)
    p = captured["systems_prompt"]
    assert "bearer-token auth" in p            # the existing description is shown
    assert "ENRICHED" in p and "never blank" in p  # enrich-not-clobber is directed


def test_co_produced_systems_from_linking_are_captured_not_discarded():
    """Runtime finding (live soupmarket e2e): the model emits typed systems+edges
    together in the LINKING call while the dedicated extraction call returns empty.
    Those co-produced Systems (with their descriptions) MUST be captured by the merge,
    never discarded - else the graph gets edge-materialised bare Systems with no
    description (the discriminative attribute)."""
    def invoke(messages, *, schema=None):
        if schema is None:
            return "prose naming a REST API"
        if "EXTRACT SYSTEMS" in messages[-1].content:
            return L1DeltaBatch()  # extraction empty (observed live)
        return L1DeltaBatch(  # linking co-produces both
            systems=[SystemProposal(kind="RESTApi", props={"description": "unified REST API"})],
            system_edges=[SystemEdgeProposal(service_slug="checkout", kind="RESTApi", rel="EXPOSED_VIA")],
        )
    out = type_mechanisms(_service_chunk(), invoke_fn=invoke,
                          inventory={"services": ["checkout"]}, aggregations=[])
    assert [s.kind for s in out.systems] == ["RESTApi"]                 # captured
    assert (out.systems[0].props or {}).get("description") == "unified REST API"  # with its desc
    assert any(e.kind == "RESTApi" for e in out.system_edges)


def test_N8_observations_feed_reflection_only():
    captured = {}

    def invoke(messages, *, schema=None):
        content = messages[-1].content
        if schema is None:
            captured["reflect"] = content
        elif "EXTRACT SYSTEMS" in content:
            captured["systems"] = content
        return "prose" if schema is None else L1DeltaBatch()
    obs = Observation(macro_kind="header", severity="info", evidence="Set-Cookie: sid",
                      rationale="session cookie missing Secure",
                      anchor={"type": "Endpoint", "identity": {"path": "/x", "baseurl": "https://a"}},
                      source_job="triager", source_tool="triager")
    type_mechanisms(_service_chunk(_endpoint("/x"), observations=(obs,)), invoke_fn=invoke)
    assert "session cookie missing Secure" in captured["reflect"]   # insight in reflection
    assert "session cookie missing Secure" not in captured["systems"]  # NOT re-shown to extract


def test_baseurl_anchored_observation_reaches_its_endpoint_insight():
    """REGRESSION (silent-empty-insight defect). The triager anchors observations UP
    to the nearest broad asset - the curator's ANCHOR_ALLOWLIST = {Domain, Subdomain,
    BaseURL, IP, Service} silently DROPS any Endpoint/Header/Parameter anchor - so a
    persisted observation is NEVER anchored to an Endpoint. The typist must therefore
    surface an Endpoint's insight by looking up observations anchored to its PARENT
    BaseURL, not to the endpoint itself. Before the fix the exact (type, identity)
    match never connects the two, so the per-asset insight shown to the model is empty
    every time - a feature that can never have anything to say."""
    captured = {}

    def invoke(messages, *, schema=None):
        if schema is None:
            captured["reflect"] = messages[-1].content
        return "prose" if schema is None else L1DeltaBatch()

    obs = Observation(macro_kind="cors", severity="high",
                      evidence="access_control_allow_origin: *",
                      rationale="wide-open CORS enables cross-origin exfiltration",
                      anchor={"type": "BaseURL", "identity": {"url": "https://a"}},
                      source_job="triager", source_tool="triager")
    type_mechanisms(
        _service_chunk(_endpoint("/rest/admin", baseurl="https://a"), observations=(obs,)),
        invoke_fn=invoke,
    )
    assert "wide-open CORS enables cross-origin exfiltration" in captured["reflect"]


def test_response_evidence_props_reach_reflection_not_path_alone():
    """REGRESSION (typist blind to content_type). The mechanism a path evidences is
    discriminated by what it SERVES - content_type / title / status / server - not by
    its path string. The renderer used to emit the identity dict ALONE, so an
    API-looking path returning text/html (a client-routed SPA view) was
    indistinguishable from a REST endpoint and no WebPresentation could be typed. The
    reflection prompt must now carry the discriminative props AND drop pipeline
    plumbing (profile/source) so the surface stays no-noise."""
    captured = {}

    def invoke(messages, *, schema=None):
        if schema is None:
            captured["reflect"] = messages[-1].content
        return "prose" if schema is None else L1DeltaBatch()

    shell = AssetDelta(
        type="Endpoint",
        identity={"path": "/git/clone", "method": "GET", "baseurl": "https://a"},
        props={"content_type": "text/html", "title": "Daytona", "status_code": 200,
               "server": "AmazonS3", "profile": "webapp", "source": "httpx"},
    )
    type_mechanisms(_service_chunk(shell), invoke_fn=invoke)
    reflect = captured["reflect"]
    assert "content_type=text/html" in reflect      # the discriminating evidence reaches it
    assert "title=Daytona" in reflect
    assert "profile=webapp" not in reflect           # pipeline plumbing filtered out (no-noise)
    assert "source=httpx" not in reflect


def test_webpresentation_per_service_cluster_survives_shaping():
    """#53: WebPresentation is per (service, rendered-page cluster), not a singleton. A
    `<service>::<cluster>` discriminator carrying the cluster's member paths in a `pages`
    prop must pass shaping UNCHANGED (kind is known; discriminator + props are free-form),
    never collapsed to __singleton__ nor dropped - so the downstream agent can locate the
    exact pages a service is exposed on."""
    batch = L1DeltaBatch(
        systems=[SystemProposal(
            kind="WebPresentation", discriminator="catalogue::product-detail",
            props={"description": "product pages", "pages": ["/it/prodotto/1", "/it/prodotto/2"]})],
        system_edges=[SystemEdgeProposal(
            service_slug="catalogue", kind="WebPresentation",
            discriminator="catalogue::product-detail", rel="EXPOSED_VIA")],
    )
    out = drop_unknown_vocabulary(narrow_to_typing(batch), kinds=_KINDS, rels=_RELS)
    assert len(out.systems) == 1
    s = out.systems[0]
    assert s.discriminator == "catalogue::product-detail"          # per (service, cluster), not singleton
    assert s.props["pages"] == ["/it/prodotto/1", "/it/prodotto/2"]  # location index preserved
    assert len(out.system_edges) == 1
    assert out.system_edges[0].discriminator == "catalogue::product-detail"  # edge hits the cluster node


def test_webpresentation_singleton_duplicate_and_orphan_edge_reconciled():
    """#53 fault (moodique 6c21005b, red loop): the two typist calls disagree on the
    WebPresentation discriminator. The SYSTEMS call emits the ratified per-cluster node
    (`catalogue::homepage`, pages=['/']); the LINKING call re-describes the SAME homepage
    but at the DEFAULT __singleton__ discriminator and points its edge THERE (dropping the
    'copy VERBATIM' instruction). `_merge_systems` keys on (kind, discriminator), so the two
    survive as DISTINCT nodes -> a DUPLICATE WebPresentation; and the edge lands on the
    singleton, leaving the real per-cluster node ORPHANED (exactly the neo4j state:
    __singleton__ carries the service edge, catalogue::homepage has zero edges).

    Correct behaviour: one WebPresentation per (service, cluster) and the edge hits the
    discriminated node - uniqueness + coherent service-linking, the two properties #53 must
    guarantee."""
    desc = "PrestaShop-rendered HTML homepage at GET / (redirects to /it/)."
    chunk = _service_chunk(_endpoint("/"))
    systems = L1DeltaBatch(systems=[SystemProposal(
        kind="WebPresentation", discriminator="catalogue_and_discovery::homepage",
        props={"description": desc, "pages": ["/"]})])
    # linking call co-produces the SAME system at the default discriminator + an edge to it
    link = L1DeltaBatch(
        systems=[SystemProposal(kind="WebPresentation", props={"description": desc})],  # discriminator=__singleton__
        system_edges=[SystemEdgeProposal(
            service_slug="catalogue_and_discovery", kind="WebPresentation", rel="EXPOSED_VIA")])  # discriminator=__singleton__
    invoke = _Recorder(systems=systems, edges=link)

    out = type_mechanisms(chunk, invoke_fn=invoke, inventory={"services": ["catalogue_and_discovery"]},
                          aggregations=[])

    wps = [s for s in out.systems if s.kind == "WebPresentation"]
    assert len(wps) == 1, f"duplicate WebPresentation not reconciled: {[s.discriminator for s in wps]}"
    assert wps[0].discriminator == "catalogue_and_discovery::homepage"  # the real per-cluster node kept
    assert wps[0].props.get("pages") == ["/"]                            # location index survives
    assert len(out.system_edges) == 1
    assert out.system_edges[0].discriminator == "catalogue_and_discovery::homepage"  # edge snapped to real node


def test_N9_idempotent_same_inputs_same_batch():
    a = type_mechanisms(_service_chunk(), invoke_fn=_Recorder())
    b = type_mechanisms(_service_chunk(), invoke_fn=_Recorder())
    assert a == b


def test_empty_chunk_yields_empty_batch():
    assert type_mechanisms(Chunk(chunk_id="c", concern="service"), invoke_fn=_Recorder()) == L1DeltaBatch()


# --- supervisor body seam (N11 protocol) --------------------------------------

class _Dispatch:
    def __init__(self, phase, chunk):
        self.phase = phase
        self.chunk = chunk


def test_N11_body_routes_a1_reads_live_inventory_and_aggregations():
    seen = {}

    def read_inventory(pid):
        seen["inv"] = pid
        return {"services": ["checkout"], "systems": [], "system_descriptions": {}}

    def read_aggregations(pid):
        seen["agg"] = pid
        return [{"slug": "checkout", "labels": ["Endpoint"], "props": {"path": "/x", "baseurl": "https://a"}}]

    out = mechanism_typist_body(
        _Dispatch("A1", _service_chunk(_endpoint("/x"))), {"project_id": "proj-1"},
        invoke_fn=_Recorder(), read_inventory=read_inventory, read_aggregations=read_aggregations,
    )
    assert seen == {"inv": "proj-1", "agg": "proj-1"}   # both re-derived LIVE, not frozen
    assert [s.kind for s in out.systems] == ["RESTApi"]


def test_body_non_a1_phase_is_hollow():
    out = mechanism_typist_body(_Dispatch("A2", _service_chunk()), {"project_id": "p"}, invoke_fn=_Recorder())
    assert out is None


def test_body_degrades_when_reads_fail():
    def boom(pid):
        raise RuntimeError("neo4j down")
    out = mechanism_typist_body(
        _Dispatch("A1", _service_chunk()), {"project_id": "p"},
        invoke_fn=_Recorder(), read_inventory=boom, read_aggregations=boom,
    )
    assert [s.kind for s in out.systems] == ["RESTApi"]  # typed without context, never crashed


# --- read-seam extension (N10) ------------------------------------------------

def test_N10_read_l1_inventory_carries_system_descriptions_additively():
    from polymerhus.analysis.l1_inventory import read_l1_inventory

    def fake_read(cypher, params):
        if "L1Service" in cypher:
            return [{"slug": "checkout", "contract": "take a basket to a paid order"}]
        if "L1System" in cypher:
            return [{"kind": "RESTApi", "disc": "__singleton__", "description": "REST surface"},
                    {"kind": "WAF", "disc": "__singleton__", "description": None}]
        return []

    inv = read_l1_inventory("p", read_fn=fake_read)
    assert inv["systems"] == ["RESTApi", "WAF"]                       # flat list unchanged
    assert inv["system_descriptions"] == {"RESTApi": "REST surface"}  # additive; blank omitted


def test_read_service_aggregations_shape():
    from polymerhus.analysis.l1_read import read_service_aggregations

    def fake_read(cypher, params):
        return [{"slug": "checkout", "labels": ["Endpoint"], "props": {"path": "/x"}},
                {"slug": None, "labels": ["Endpoint"], "props": {"path": "/y"}}]  # slug-less dropped
    rows = read_service_aggregations("p", read_fn=fake_read)
    assert rows == [{"slug": "checkout", "labels": ["Endpoint"], "props": {"path": "/x"}}]
