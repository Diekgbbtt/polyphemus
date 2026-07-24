"""Contract predicates (integration tier) for increment 1 - analysis/chunking.py
(#23). Mechanises C1-C13 of the assertion catalogue attached to #23.

These range over the pure chunk-builder and the profile gate; no live graph or LLM
(the builder is pure - reads are injected as arguments). Expected values come from
the spec, not recomputed. They gate the verifier and are NOT selected by the tdd
unit red/green loop.
"""
from polymerhus.analysis.chunking import Chunk, chunks_for_job, profiled_origins
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


def _by_concern(chunks):
    return {c.concern: c for c in chunks}


# --- C1: concern partition + type-coherence -----------------------------------

def test_C1_partitions_into_type_coherent_service_and_data_chunks():
    assets = [
        _asset("BaseURL", baseurl=BU), _ep("/x"), _asset("Technology", name="nginx"),
        _param("q"), _asset("Secret", key="tok"),
    ]
    chunks = chunks_for_job(JOB, assets, profiled=frozenset({BU}))
    by = _by_concern(chunks)
    assert set(by) == {"service", "data"}
    assert all(a.type in {"BaseURL", "Endpoint", "Technology", "Certificate", "Header"} for a in by["service"].assets)
    assert all(a.type in {"Parameter", "Secret", "Header"} for a in by["data"].assets)


# --- C2: Header dual routing --------------------------------------------------

def test_C2_header_appears_in_both_service_and_data_chunks():
    header = _asset("Header", name="X-Api")
    assets = [_asset("BaseURL", baseurl=BU), header, _param("q")]
    chunks = chunks_for_job(JOB, assets, profiled=frozenset({BU}))
    containing = [c.concern for c in chunks if any(a.type == "Header" for a in c.assets)]
    assert sorted(containing) == ["data", "service"]


# --- C3 / C4: empty-valid -----------------------------------------------------

def test_C3_prehttp_only_delta_yields_no_chunks():
    assets = [_asset("Subdomain", host="s.a"), _asset("IP", addr="1.2.3.4"), _asset("Port", num="443")]
    assert chunks_for_job(JOB, assets, profiled=frozenset()) == []


def test_C4_empty_delta_yields_no_chunks():
    assert chunks_for_job(JOB, [], profiled=frozenset()) == []


# --- C5: unmapped type -> service generalist ----------------------------------

def test_C5_unmapped_type_falls_back_to_service():
    assets = [_asset("BaseURL", baseurl=BU), _asset("Frobnicate", x="1")]
    chunks = chunks_for_job(JOB, assets, profiled=frozenset({BU}))
    service = _by_concern(chunks)["service"]
    assert any(a.type == "Frobnicate" for a in service.assets)


# --- C6: batch-overflow -------------------------------------------------------

def test_C6_batch_overflow_splits_into_ordered_chunks_tail_kept():
    assets = [_asset("Technology", name=f"t{i}") for i in range(250)]  # non-gated service type
    chunks = chunks_for_job(JOB, assets, profiled=frozenset(), max_assets=100)
    assert len(chunks) == 3
    assert all(c.concern == "service" and c.batch_total == 3 for c in chunks)
    assert [c.batch_index for c in chunks] == [0, 1, 2]
    assert [len(c.assets) for c in chunks] == [100, 100, 50]
    union = [a for c in chunks for a in c.assets]
    assert len(union) == 250  # tail never dropped


# --- C7 / C8: the httpx gate (withhold at delivery, flagged at barrier) --------

def test_C7_unprofiled_endpoint_is_withheld_at_delivery():
    assets = [_ep("/x", BU), _ep("/y", BU2)]  # BU profiled, BU2 not
    chunks = chunks_for_job(JOB, assets, profiled=frozenset({BU}), barrier=False)
    service = _by_concern(chunks)["service"]
    paths = {a.identity["path"] for a in service.assets}
    assert paths == {"/x"}
    assert service.flagged is False


def test_C8_barrier_admits_unprofiled_endpoint_flagged():
    assets = [_ep("/x", BU), _ep("/y", BU2)]
    chunks = chunks_for_job(JOB, assets, profiled=frozenset({BU}), barrier=True)
    service = _by_concern(chunks)["service"]
    paths = {a.identity["path"] for a in service.assets}
    assert paths == {"/x", "/y"}
    assert service.flagged is True


# --- C9: Parameter gated on its BaseURL ---------------------------------------

def test_C9_unprofiled_parameter_is_withheld():
    assets = [_param("p1", BU), _param("p2", BU2)]
    chunks = chunks_for_job(JOB, assets, profiled=frozenset({BU}), barrier=False)
    data = _by_concern(chunks)["data"]
    names = {a.identity["name"] for a in data.assets}
    assert names == {"p1"}


# --- C10: non-gated types are not profile-gated -------------------------------

def test_C10_non_gated_types_survive_empty_profiled_set():
    assets = [
        _asset("Technology", name="nginx"), _asset("Certificate", cn="a"),
        _asset("Secret", key="tok"), _asset("BaseURL", baseurl=BU2),
    ]
    chunks = chunks_for_job(JOB, assets, profiled=frozenset(), barrier=False)
    by = _by_concern(chunks)
    service_types = {a.type for a in by["service"].assets}
    data_types = {a.type for a in by["data"].assets}
    assert {"Technology", "Certificate", "BaseURL"} <= service_types
    assert "Secret" in data_types


# --- C11: malformed asset excluded, never crashes -----------------------------

def test_C11_malformed_asset_excluded_not_crashed():
    good = _ep("/x", BU)
    no_type = AssetDelta(type="", identity={"path": "/z", "baseurl": BU})
    no_identity = AssetDelta(type="Endpoint", identity={})  # no baseurl -> gated out anyway
    chunks = chunks_for_job(JOB, [good, no_type, no_identity], profiled=frozenset({BU}), barrier=False)
    service = _by_concern(chunks)["service"]
    assert [a.identity["path"] for a in service.assets] == ["/x"]  # only the valid one


# --- C12: profiled_origins reuse + fail-safe exclusion -------------------------

def test_C12_profiled_origins_excludes_blank_or_none_profile():
    records = [
        {"baseurl": "a", "profile": "restapi"},
        {"baseurl": "b", "profile": None},
        {"baseurl": "c", "profile": ""},
        {"baseurl": "d", "profile": "webapp"},
    ]
    assert profiled_origins(records) == frozenset({"a", "d"})


# --- C13: idempotency / replay ------------------------------------------------

def test_C13_replay_yields_identical_chunk_set():
    assets = [_ep("/x", BU), _param("q", BU), _asset("Technology", name="nginx")]
    a = chunks_for_job(JOB, assets, profiled=frozenset({BU}))
    b = chunks_for_job(JOB, assets, profiled=frozenset({BU}))
    assert [c.chunk_id for c in a] == [c.chunk_id for c in b]
    assert [len(c.assets) for c in a] == [len(c.assets) for c in b]
    assert a == b
