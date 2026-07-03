# tests/recon/test_types.py
from agent.recon.types import AssetDelta, Edge, Observation, JobSpec, ExecResult

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

def test_jobspec_defaults():
    j = JobSpec(tool="httpx", skill="http_probe",
                command_template="httpx -u {target} -j", produces=["BaseURL","Endpoint"],
                consumes="Subdomain")
    assert j.use_auth is False
    assert j.configurator_mode == "deterministic"

def test_exec_result_fields():
    r = ExecResult(stdout="x", stderr="", returncode=0, duration_ms=5)
    assert r.returncode == 0
