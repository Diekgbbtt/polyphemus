"""Walkthrough predicate (e2e tier) for increment 1 - analysis/chunking.py (#23).
Mechanises E1: one katana-job delta of exact composition, before and after the
phase-barrier, to the exact per-chunk asset counts, concern tags, and flags.

Pure builder (no live graph/LLM); expected quantities taken from the spec. Gates
the verifier only; not selected by the tdd unit loop.
"""
from polymerhus.analysis.chunking import chunks_for_job, profiled_origins
from polymerhus.recon.domain.types import AssetDelta, JobSpec, Observation

JOB = JobSpec(tool="katana", skill="crawl", command_template="t",
              produces=["BaseURL", "Endpoint", "Technology"], consumes="BaseURL")
A = "https://a"   # profiled
B = "https://b"   # un-profiled


def _asset(t, **identity):
    return AssetDelta(type=t, identity=identity)


def _delta():
    return [
        _asset("BaseURL", baseurl=A), _asset("BaseURL", baseurl=B),
        _asset("Endpoint", path="/x", method="GET", baseurl=A),
        _asset("Endpoint", path="/y", method="GET", baseurl=B),
        _asset("Technology", name="nginx"),
        _asset("Parameter", name="q", baseurl=A),
        _asset("Parameter", name="r", baseurl=B),
        _asset("Header", name="X-Api"),
        _asset("Secret", key="tok"),
        _asset("Subdomain", host="s.a"),
    ]


def _by_concern(chunks):
    return {c.concern: c for c in chunks}


def test_E1_katana_delta_normal_then_barrier():
    records = [{"baseurl": A, "profile": "restapi"}, {"baseurl": B, "profile": None}]
    profiled = profiled_origins(records)
    assert profiled == frozenset({A})

    obs = [Observation(macro_kind="k", severity="low", evidence="e", rationale="why",
                       anchor={"type": "Endpoint", "identity": {"path": "/x", "method": "GET", "baseurl": A}},
                       source_job="katana", source_tool="katana")]

    # --- normal delivery (barrier=False) ---
    chunks = chunks_for_job(JOB, _delta(), obs, profiled=profiled, barrier=False)
    by = _by_concern(chunks)
    assert set(by) == {"service", "data"}

    service_types = sorted(a.type for a in by["service"].assets)
    # service = 2 BaseURL + Endpoint /x (only; /y@B withheld) + Technology + Header
    assert service_types == ["BaseURL", "BaseURL", "Endpoint", "Header", "Technology"]
    assert len(by["service"].assets) == 5
    assert by["service"].flagged is False
    # /y is withheld
    assert all(a.identity.get("path") != "/y" for a in by["service"].assets)

    data_types = sorted(a.type for a in by["data"].assets)
    # data = Parameter q (only; r@B withheld) + Header + Secret
    assert data_types == ["Header", "Parameter", "Secret"]
    assert len(by["data"].assets) == 3
    assert by["data"].flagged is False
    assert all(a.identity.get("name") != "r" for a in by["data"].assets)

    # the /x observation rides the service chunk (its anchor asset is there)
    assert len(by["service"].observations) == 1
    assert by["data"].observations == ()

    # Subdomain (pre-HTTP) is in no chunk
    assert all(a.type != "Subdomain" for c in chunks for a in c.assets)

    # --- barrier delivery (barrier=True): withheld assets rejoin, flagged ---
    bchunks = chunks_for_job(JOB, _delta(), obs, profiled=profiled, barrier=True)
    bby = _by_concern(bchunks)
    assert len(bby["service"].assets) == 6   # /y@B rejoins
    assert {a.identity.get("path") for a in bby["service"].assets if a.type == "Endpoint"} == {"/x", "/y"}
    assert bby["service"].flagged is True
    assert len(bby["data"].assets) == 4      # r@B rejoins
    assert {a.identity.get("name") for a in bby["data"].assets if a.type == "Parameter"} == {"q", "r"}
    assert bby["data"].flagged is True
