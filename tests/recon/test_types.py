# tests/recon/test_types.py
import pytest
from pydantic import ValidationError

from polymerhus.recon.domain.types import (
    PROFILE_VALUES, AssetDelta, Edge, Observation, JobSpec, ExecResult,
)

def test_asset_delta_with_edge_roundtrips():
    d = AssetDelta(
        type="Endpoint",
        identity={"path": "/api/v1/users", "method": "GET", "baseurl": "https://app.example.com"},
        props={"status_code": 200},
        edges=[Edge(rel="HAS_ENDPOINT", dir="in", node_type="BaseURL",
                    node_identity={"url": "https://app.example.com"})],
    )
    assert d.type == "Endpoint"
    assert d.edges[0].node_type == "BaseURL"

def test_asset_delta_accepts_every_typed_profile_value():
    for profile in sorted(PROFILE_VALUES):
        d = AssetDelta(type="Endpoint", identity={"path": "/x", "method": "GET",
                                                  "baseurl": "https://a.example"},
                       props={"profile": profile})
        assert d.props["profile"] == profile

def test_asset_delta_rejects_an_untyped_profile_value():
    # The D16 profile is a typed literal (webapp/restapi/graphql_api): a delta
    # carrying anything else is a programmer error and must fail loud at the
    # delta seam (the same guard also sits at the curator graph-write seam).
    with pytest.raises(ValidationError):
        AssetDelta(type="Endpoint", identity={"path": "/x", "method": "GET",
                                              "baseurl": "https://a.example"},
                   props={"profile": "rest"})

def test_asset_delta_non_profile_props_are_untouched():
    d = AssetDelta(type="Technology", identity={"name": "Nginx"}, props={"version": "1.30.1"})
    assert d.props["version"] == "1.30.1"

def test_jobspec_defaults():
    j = JobSpec(tool="httpx", skill="http_probe",
                command_template="httpx -u {target} -j", produces=["BaseURL","Endpoint"],
                consumes="Subdomain")
    assert j.use_auth is False
    assert j.configurator_mode == "deterministic"

def test_exec_result_fields():
    r = ExecResult(stdout="x", stderr="", returncode=0, duration_ms=5)
    assert r.returncode == 0
