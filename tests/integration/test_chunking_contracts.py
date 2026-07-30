"""Contract predicates (integration tier) for the chunk stream + the per-role
admission table. Mechanises C1-C12 of the catalogue attached to #34, which reshapes
the increment-1 chunk builder (#23) per D1/D2/D7/D8.

These range over the pure chunk-builder, the retained Parameter profile gate, and
`admit_for_role`; no live graph or LLM (the builder is pure - reads are injected as
arguments). Expected values come from the spec, not recomputed. They gate the
verifier and are NOT selected by the tdd unit red/green loop.
"""
from polymerhus.analysis.chunking import (
    ROLE_ADMITS,
    Chunk,
    admit_for_role,
    chunks_for_job,
    profiled_origins,
)
from polymerhus.recon.domain.types import AssetDelta, JobSpec, Observation

JOB = JobSpec(tool="katana", skill="crawl", command_template="t", produces=["BaseURL", "Endpoint"], consumes="BaseURL")
BU = "https://a"
BU2 = "https://b"


def _ep(path, baseurl=BU):
    return AssetDelta(type="Endpoint", identity={"path": path, "method": "GET", "baseurl": baseurl})


def _param(name, baseurl=BU):
    return AssetDelta(type="Parameter", identity={"name": name, "baseurl": baseurl})


def _asset(t, **identity):
    return AssetDelta(type=t, identity=identity)


# --- C1: ONE stream, no concern partition -------------------------------------

def test_C1_single_stream_no_concern_partition():
    assets = [
        _asset("BaseURL", baseurl=BU), _asset("BaseURL", baseurl=BU2),
        _ep("/x"), _ep("/y", BU2), _asset("Technology", name="nginx"),
        _param("q"), _asset("Header", name="X-Api"), _asset("Secret", key="tok"),
        _asset("Subdomain", host="s.a"), _asset("Certificate", cn="a"),
    ]
    chunks = chunks_for_job(JOB, assets, profiled=frozenset({BU}), max_assets=100)
    assert len(chunks) == 1
    (chunk,) = chunks
    assert chunk.chunk_id == "katana:0"          # no concern segment
    assert not hasattr(chunk, "concern")          # the attribute is gone, not defaulted
    assert len(chunk.assets) == 10                # every asset, each exactly once
    # the Header rides ONE chunk now, not two (it was dual-concern before #34 D8)
    assert sum(1 for a in chunk.assets if a.type == "Header") == 1


# --- C2: D1 - the Endpoint gate is dropped ------------------------------------

def test_C2_unprofiled_endpoint_is_streamed():
    assets = [_ep("/x", BU), _ep("/y", BU2)]  # BU profiled, BU2 not
    (chunk,) = chunks_for_job(JOB, assets, profiled=frozenset({BU}), barrier=False)
    assert {a.identity["path"] for a in chunk.assets} == {"/x", "/y"}
    assert chunk.flagged is False


# --- C3 / C4: D1 - the Parameter gate is retained -----------------------------

def test_C3_unprofiled_parameter_still_gated():
    assets = [_param("q", BU), _param("r", BU2)]
    (chunk,) = chunks_for_job(JOB, assets, profiled=frozenset({BU}), barrier=False)
    assert {a.identity["name"] for a in chunk.assets} == {"q"}


def test_C4_barrier_admits_unprofiled_parameter_flagged():
    assets = [_param("q", BU), _param("r", BU2)]
    (chunk,) = chunks_for_job(JOB, assets, profiled=frozenset({BU}), barrier=True)
    assert {a.identity["name"] for a in chunk.assets} == {"q", "r"}
    assert chunk.flagged is True


# --- C5: D2 - every type is streamed, pre-HTTP included -----------------------

def test_C5_prehttp_types_are_streamed():
    assets = [_asset("Subdomain", host="s.a"), _asset("IP", addr="1.2.3.4"), _asset("Port", num="443")]
    chunks = chunks_for_job(JOB, assets, profiled=frozenset())
    assert len(chunks) == 1
    assert sorted(a.type for a in chunks[0].assets) == ["IP", "Port", "Subdomain"]


# --- C6: ordering / overflow --------------------------------------------------

def test_C6_overflow_ordered_tail_kept():
    assets = [_asset("Technology", name=f"t{i}") for i in range(250)]
    chunks = chunks_for_job(JOB, assets, profiled=frozenset(), max_assets=100)
    assert len(chunks) == 3
    assert [c.batch_index for c in chunks] == [0, 1, 2]
    assert all(c.batch_total == 3 for c in chunks)
    assert [len(c.assets) for c in chunks] == [100, 100, 50]
    assert len([a for c in chunks for a in c.assets]) == 250  # tail never dropped


# --- C7: malformed asset excluded, never crashes ------------------------------

def test_C7_malformed_asset_excluded_not_crashed():
    good = _ep("/x", BU)
    no_type = AssetDelta(type="", identity={"path": "/z", "baseurl": BU})
    (chunk,) = chunks_for_job(JOB, [good, no_type], profiled=frozenset({BU}), barrier=False)
    assert len(chunk.assets) == 1
    assert chunk.assets[0].identity["path"] == "/x"


# --- C8: replay determinism ---------------------------------------------------

def test_C8_replay_yields_identical_chunks():
    assets = [_ep("/x", BU), _param("q", BU), _asset("Technology", name="nginx")]
    a = chunks_for_job(JOB, assets, profiled=frozenset({BU}))
    b = chunks_for_job(JOB, assets, profiled=frozenset({BU}))
    assert [c.chunk_id for c in a] == [c.chunk_id for c in b]
    assert a == b


# --- C9 / C10 / C11 / C12: the per-role admission table (D7) ------------------

def _mixed_chunk(extra=()):
    return Chunk(chunk_id="katana:0", source_job="katana", assets=(
        _ep("/x"), _param("q"), _asset("Header", name="X-Api"),
        _asset("Technology", name="nginx"), _asset("Subdomain", host="s.a"), *extra,
    ))


def test_C9_assigner_admits_endpoints_only():
    admitted = admit_for_role(_mixed_chunk(), "assigner")
    assert len(admitted) == 1
    assert admitted[0].type == "Endpoint"


def test_C10_data_modeller_admits_parameter_and_header():
    admitted = admit_for_role(_mixed_chunk(), "data_modeller")
    assert [a.type for a in admitted] == ["Parameter", "Header"]  # stream order kept


def test_C11_mechanism_typist_admits_everything_including_unmapped():
    chunk = _mixed_chunk(extra=(_asset("Frobnicate", x="1"),))
    admitted = admit_for_role(chunk, "mechanism_typist")
    assert len(admitted) == 6
    assert any(a.type == "Frobnicate" for a in admitted)  # fork H: never dropped
    assert ROLE_ADMITS["mechanism_typist"] == "*"


def test_C12_no_admissible_assets_yields_empty():
    chunk = Chunk(chunk_id="katana:0", assets=(_param("q"), _param("r")))
    assert admit_for_role(chunk, "assigner") == ()  # empty-valid, not an error


# --- C12b: profiled_origins reuse + fail-safe exclusion (unchanged by #34) -----

def test_C12b_profiled_origins_excludes_blank_or_none_profile():
    records = [
        {"baseurl": "a", "profile": "restapi"},
        {"baseurl": "b", "profile": None},
        {"baseurl": "c", "profile": ""},
        {"baseurl": "d", "profile": "webapp"},
    ]
    assert profiled_origins(records) == frozenset({"a", "d"})


# --- C27: script Endpoints are excluded from the stream -----------------------

def test_C27_js_script_endpoints_are_excluded_for_every_agent():
    """Recon keeps producing them (jsluice mines them); no proposer wants them."""
    assets = [
        _ep("/orders/42"), _ep("/static/app.js"), _ep("/bundle.JS"),
        _ep("/main.js?v=2"), _ep("/js/api/orders"),   # a /js/ path segment is NOT a script
    ]
    (chunk,) = chunks_for_job(JOB, assets, profiled=frozenset({BU}))
    assert {a.identity["path"] for a in chunk.assets} == {"/orders/42", "/js/api/orders"}


def test_C27b_non_endpoint_assets_found_on_scripts_survive():
    """A Parameter or Header discovered on a script is a real finding."""
    assets = [
        _ep("/app.js"),
        AssetDelta(type="Parameter", identity={"name": "token", "baseurl": BU}),
        AssetDelta(type="Header", identity={"name": "X-Api"}),
    ]
    (chunk,) = chunks_for_job(JOB, assets, profiled=frozenset({BU}))
    assert sorted(a.type for a in chunk.assets) == ["Header", "Parameter"]


def _obs_on(anchor_type, identity):
    return Observation(macro_kind="k", severity="info", evidence="e", rationale="r",
                       anchor={"type": anchor_type, "identity": identity},
                       source_job="triager", source_tool="triager")


def test_C28_baseurl_anchored_observation_rides_via_its_endpoints_parent():
    """Silent-empty-insight fix (chunking half). Observations are anchored UP to the
    BaseURL (curator ANCHOR_ALLOWLIST drops narrow anchors), so a chunk of Endpoints
    must carry its BaseURL's observations via the parent hop (`broaden_anchor`), even
    when the BaseURL node itself is not an asset in the chunk. An observation on an
    UNRELATED BaseURL must NOT ride."""
    on_bu = _obs_on("BaseURL", {"url": BU})            # parent of /x
    on_other = _obs_on("BaseURL", {"url": BU2})        # unrelated
    (chunk,) = chunks_for_job(JOB, [_ep("/x")], [on_bu, on_other], profiled=frozenset({BU}))
    riding = [(o.anchor["type"], o.anchor["identity"]) for o in chunk.observations]
    assert ("BaseURL", {"url": BU}) in riding          # inherited from the endpoint's parent
    assert ("BaseURL", {"url": BU2}) not in riding      # unrelated BaseURL excluded
