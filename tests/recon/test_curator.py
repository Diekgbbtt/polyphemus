from polymerhus.recon.domain.types import AssetDelta, Edge, Observation
from polymerhus.recon.domain import curator

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
    """Anchors are restricted to broad, well-identified assets. These cases all
    still raise, but for two distinct reasons after D8's re-anchor repair landed:

    - `tool_output` is an invented pseudo-type, not a real primitive, so it is
      not a re-anchor candidate at all and is rejected outright.
    - `Endpoint`/`Parameter`/`Technology` ARE real narrow primitives, but here
      their anchor identity is the minimal `{"name": "q"}` with NO owner key
      (`baseurl`/`ip_address`). D8's `broaden_anchor` is pure identity-key
      derivation - with no owner key present it returns None, so these fall
      through to the same drop-and-log path as before. (When the owner key IS
      present, Endpoint/Header/Parameter/Port are repaired - see the tests
      below; Technology has no owner key in its identity and always drops.)"""
    import pytest
    for bad in ("Parameter", "Endpoint", "Technology", "tool_output"):
        o = Observation(macro_kind="auth_surface", severity="info", evidence="e",
                        rationale="r", anchor={"type": bad, "identity": {"name": "q"}},
                        source_job="j", source_tool="t")
        with pytest.raises(ValueError):
            curator.build_observation_cypher(o)


# --- D8: deterministic re-anchor repair (pure broaden_anchor) --------------

def test_broaden_anchor_endpoint_header_parameter_to_baseurl():
    """Endpoint/Header/Parameter carry the owning BaseURL url in their `baseurl`
    identity key, so pure derivation rewrites the anchor to that BaseURL."""
    for narrow in ("Endpoint", "Header", "Parameter"):
        broad = curator.broaden_anchor(
            {"type": narrow, "identity": {"name": "x", "baseurl": "https://a"}}
        )
        assert broad == {"type": "BaseURL", "identity": {"url": "https://a"}}


def test_broaden_anchor_port_to_ip_canonical_and_alias():
    """Port carries the owning IP in `ip_address` (canonical) or `ip` (alias)."""
    assert curator.broaden_anchor(
        {"type": "Port", "identity": {"number": 443, "ip_address": "1.2.3.4"}}
    ) == {"type": "IP", "identity": {"address": "1.2.3.4"}}
    assert curator.broaden_anchor(
        {"type": "Port", "identity": {"number": 443, "ip": "1.2.3.4"}}
    ) == {"type": "IP", "identity": {"address": "1.2.3.4"}}


def test_broaden_anchor_returns_none_when_not_repairable():
    """Technology (no owner key), a narrow anchor missing its owner key, a
    non-primitive pseudo-type, and malformed input are all unrepairable."""
    assert curator.broaden_anchor(
        {"type": "Technology", "identity": {"name": "nginx", "version": ""}}
    ) is None
    assert curator.broaden_anchor(
        {"type": "Endpoint", "identity": {"path": "/x", "method": "GET"}}
    ) is None  # no baseurl key
    assert curator.broaden_anchor(
        {"type": "Port", "identity": {"number": 443}}
    ) is None  # no ip_address/ip key
    assert curator.broaden_anchor(
        {"type": "tool_output", "identity": {"name": "q"}}
    ) is None  # not a real primitive
    assert curator.broaden_anchor({"type": "Endpoint"}) is None  # no identity
    assert curator.broaden_anchor("not-a-dict") is None


def test_build_observation_cypher_reanchors_narrow_anchor():
    """A narrow-but-repairable anchor is rewritten to its broad owner instead of
    being dropped; the MERGE targets the broad node and the narrow node's
    identity is preserved in the observation evidence."""
    o = Observation(macro_kind="auth_surface", severity="info",
                    evidence="login form present",
                    rationale="r",
                    anchor={"type": "Endpoint",
                            "identity": {"path": "/login", "method": "GET",
                                         "baseurl": "https://a"}},
                    source_job="j", source_tool="httpx")
    cy, params = curator.build_observation_cypher(o)
    assert "MERGE (a:BaseURL {url: $anchor_url, project_id: $project_id})" in cy
    assert params["anchor_url"] == "https://a"
    # narrow identity is carried into evidence, deterministically (sorted keys)
    assert params["evidence"] == (
        "login form present [re-anchored from Endpoint "
        "{baseurl=https://a, method=GET, path=/login}]"
    )


def test_build_observation_cypher_reanchored_obs_id_reflects_repair():
    """obs_id hashes the POST-repair evidence+anchor, so a repaired observation
    gets one stable id distinct from the (dropped) pre-repair form."""
    narrow = Observation(macro_kind="k", severity="info", evidence="e",
                         rationale="r",
                         anchor={"type": "Port",
                                 "identity": {"number": 443, "ip_address": "1.2.3.4"}},
                         source_job="j", source_tool="naabu")
    equivalent_broad = Observation(
        macro_kind="k", severity="info",
        evidence="e [re-anchored from Port {ip_address=1.2.3.4, number=443}]",
        rationale="r",
        anchor={"type": "IP", "identity": {"address": "1.2.3.4"}},
        source_job="j", source_tool="naabu")
    _, p_narrow = curator.build_observation_cypher(narrow)
    _, p_broad = curator.build_observation_cypher(equivalent_broad)
    assert p_narrow["obs_id"] == p_broad["obs_id"]


def test_curate_merges_reanchored_and_still_drops_unrepairable():
    """A repairable narrow anchor is now merged (was dropped pre-D8); a
    Technology anchor (no owner key) still drops-and-logs."""
    calls = []
    def fake_merge(cy, params): calls.append((cy, params))
    repairable = Observation(macro_kind="k", severity="info", evidence="e",
                             rationale="r",
                             anchor={"type": "Endpoint",
                                     "identity": {"path": "/x", "method": "GET",
                                                  "baseurl": "https://a"}},
                             source_job="j", source_tool="t")
    unrepairable = Observation(macro_kind="k", severity="info", evidence="e",
                               rationale="r",
                               anchor={"type": "Technology",
                                       "identity": {"name": "nginx", "version": ""}},
                               source_job="j", source_tool="t")
    a, o = curator.curate([], [repairable, unrepairable], "proj1", merge_fn=fake_merge)
    assert a == 0 and o == 1
    assert len(calls) == 1
    assert "MERGE (a:BaseURL" in calls[0][0]


def test_observation_anchor_accepts_broad_assets():
    """The five broad, durable anchor types are accepted."""
    for label, ident in [("Domain", {"name": "a.com"}), ("Subdomain", {"name": "x.a.com"}),
                         ("BaseURL", {"url": "https://a"}), ("IP", {"address": "1.2.3.4"}),
                         ("Service", {"port": 443, "ip": "1.2.3.4"})]:
        o = Observation(macro_kind="k", severity="info", evidence="e", rationale="r",
                        anchor={"type": label, "identity": ident},
                        source_job="j", source_tool="t")
        cy, _ = curator.build_observation_cypher(o)
        assert f"MERGE (a:{label}" in cy

def test_curate_counts_and_skips_bad_delta():
    calls = []
    def fake_merge(cy, params): calls.append((cy, params))
    good = AssetDelta(type="BaseURL", identity={"url": "https://a"})
    bad = AssetDelta(type="Nope", identity={"x": 1})
    a, o = curator.curate([good, bad], [], "proj1", merge_fn=fake_merge)
    assert a == 1 and o == 0
    assert len(calls) == 1

def test_curate_continues_batch_when_merge_fn_raises(caplog):
    """§10.6: one bad delta (here, a merge_fn exception) never aborts the job -
    the remaining valid deltas must still be processed."""
    calls = []
    state = {"n": 0}
    def flaky_merge(cy, params):
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("boom: transient neo4j failure")
        calls.append((cy, params))

    first = AssetDelta(type="BaseURL", identity={"url": "https://a"})
    second = AssetDelta(type="BaseURL", identity={"url": "https://b"})

    with caplog.at_level("WARNING"):
        a, o = curator.curate([first, second], [], "proj1", merge_fn=flaky_merge)

    assert a == 1 and o == 0
    assert len(calls) == 1
    assert state["n"] == 2  # both items were attempted, the raise did not abort the batch
    assert any("merge failed" in rec.message for rec in caplog.records)
