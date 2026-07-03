from agent.recon.types import AssetDelta, Edge, Observation
from agent.recon import curator

def test_asset_cypher_merges_on_identity_plus_project():
    d = AssetDelta(type="Endpoint",
                   identity={"path": "/x", "method": "GET", "baseurl": "https://a"},
                   props={"status_code": 200})
    cy, params = curator.build_asset_cypher(d)
    assert "MERGE" in cy and ":Endpoint" in cy
    assert "first_seen" in cy and "last_seen" in cy
    assert params["project_id"]  # injected by caller path; see curate()
    assert params["props"]["status_code"] == 200

def test_unknown_label_rejected():
    import pytest
    d = AssetDelta(type="Bogus", identity={"x": 1})
    with pytest.raises(ValueError):
        curator.build_asset_cypher(d)

def test_observation_anchor_allowlist_enforced():
    import pytest
    o = Observation(macro_kind="auth_surface", severity="info", evidence="e",
                    rationale="r", anchor={"type": "Parameter", "identity": {"name": "q"}},
                    source_job="j", source_tool="t")
    with pytest.raises(ValueError):
        curator.build_observation_cypher(o)

def test_curate_counts_and_skips_bad_delta():
    calls = []
    def fake_merge(cy, params): calls.append((cy, params))
    good = AssetDelta(type="BaseURL", identity={"url": "https://a"})
    bad = AssetDelta(type="Nope", identity={"x": 1})
    a, o = curator.curate([good, bad], [], "proj1", merge_fn=fake_merge)
    assert a == 1 and o == 0
    assert len(calls) == 1
