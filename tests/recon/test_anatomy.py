"""FR-SPINE unit tier — the webpage-profile system-anatomy skill: two INDEPENDENT
spine dimensions (L1D-31a), fingerprint-insufficiency enforced structurally, and
the anatomy triple (classification->spine, evidence->Observation, probe->interface-B).
Injected fakes (no live LLM/DB).

Each test names the assertion it encodes (docs/design/L1-MVP-plan.md FR-SPINE ledger).
"""
from agent.recon.analysis import anatomy
from agent.recon.analysis.anatomy import (
    AnatomyResult, SpineClassification, WebpageProfileProposal, webpage_profile, commit_anatomy,
)


def _proposal(**kw) -> WebpageProfileProposal:
    base = dict(
        navigation_model="SPA", navigation_confidence="High",
        navigation_evidence="pushState nav, JSON fetches, no Document reload",
        navigation_fingerprint_only=False,
        rendering_model="CSR", rendering_confidence="High",
        rendering_evidence="initial HTML is <div id=root></div>, DOM built post-JS",
        rendering_fingerprint_only=False,
        probe_reason=None,
    )
    base.update(kw)
    return WebpageProfileProposal(**base)


# --- AST-SPINE-01: two SEPARATE independent spine slots ---

def test_webpage_profile_sets_two_independent_slots():
    res = webpage_profile({"base_url": "https://a"}, profile_fn=lambda s: _proposal(), steel_available=True)
    slots = {c.slot for c in res.classifications}
    assert slots == {"navigation_model", "rendering_model"}  # both dimensions, separately
    assert len(res.classifications) == 2


# --- AST-SPINE-02: independence — SPA + SSR both survive (SPA does NOT force CSR) ---

def test_dimensions_are_independent_spa_ssr():
    # a server-rendered single-page app: navigation=SPA, rendering=SSR
    p = _proposal(navigation_model="SPA", rendering_model="SSR",
                  rendering_evidence="server returns fully-formed HTML for /route")
    res = webpage_profile({"base_url": "https://a"}, profile_fn=lambda s: p, steel_available=True)
    by_slot = {c.slot: c.value for c in res.classifications}
    assert by_slot["navigation_model"] == "SPA"
    assert by_slot["rendering_model"] == "SSR"  # not collapsed to CSR by the SPA nav


# --- AST-SPINE-03: fingerprint-only is capped below High AND raises a probe (L1D-31a) ---

def test_fingerprint_only_is_capped_and_probes():
    # the model (over-)confidently classifies rendering from ONLY a __NEXT_DATA__ fingerprint
    p = _proposal(rendering_model="SSR", rendering_confidence="High",
                  rendering_evidence="saw __NEXT_DATA__ in the HTML",
                  rendering_fingerprint_only=True)
    res = webpage_profile({"base_url": "https://a"}, profile_fn=lambda s: p, steel_available=True)
    ren = next(c for c in res.classifications if c.slot == "rendering_model")
    assert ren.confidence != "High"  # a fingerprint alone can never be High (structural cap)
    assert ren.confidence == "Low"
    assert len(res.probes) == 1  # and it raises a corroborating backward-recon probe
    assert res.probes[0].origin == "anatomy_skill" and res.probes[0].skill_id == "webpage_profile"
    # the probe self-describes: which slot(s) it must settle (N3) rides scope.note
    assert res.probes[0].scope.note and "rendering_model" in res.probes[0].scope.note


def test_fingerprint_only_medium_is_also_capped_to_low():
    # "a fingerprint alone is NEVER sufficient" -> even a Medium fingerprint-only
    # call is floored to Low (not merely capped below High)
    p = _proposal(navigation_model="MPA", navigation_confidence="Medium",
                  navigation_evidence="ng-version attribute present",
                  navigation_fingerprint_only=True)
    res = webpage_profile({"base_url": "https://a"}, profile_fn=lambda s: p, steel_available=True)
    nav = next(c for c in res.classifications if c.slot == "navigation_model")
    assert nav.confidence == "Low"  # Medium fingerprint-only -> Low
    assert len(res.probes) == 1


def test_behavioural_high_confidence_needs_no_probe():
    res = webpage_profile({"base_url": "https://a"}, profile_fn=lambda s: _proposal(), steel_available=True)
    assert all(c.confidence == "High" for c in res.classifications)
    assert res.probes == []  # behavioural evidence -> no probe needed


# --- AST-SPINE-04: confidence + verbatim evidence; the triple lands correctly ---

def test_triple_lands_on_spine_observation_and_interfaceB():
    p = _proposal(navigation_fingerprint_only=True, navigation_confidence="High",
                  probe_reason="navigate /x and watch Document vs Fetch")
    res = webpage_profile({"base_url": "https://shop.example"}, service_id="svc-1",
                          requester_id="req-1", profile_fn=lambda s: p, steel_available=True)

    # each classification carries confidence + verbatim evidence
    for c in res.classifications:
        assert c.confidence in ("High", "Medium", "Low")
        assert c.evidence  # verbatim, non-empty

    # leg 2: evidence -> Observation with the skill's provenance + macro_kind
    assert res.observations and all(o.macro_kind == "webpage_profile" for o in res.observations)
    assert all(o.source_tool == "webpage_profile" for o in res.observations)
    assert res.observations[0].anchor == {"type": "BaseURL", "identity": {"url": "https://shop.example"}}

    # leg 3: probe -> interface-B AnalyserReconRequest
    assert len(res.probes) == 1
    probe = res.probes[0]
    assert probe.origin == "anatomy_skill" and probe.skill_id == "webpage_profile"
    assert probe.scope.service_id == "svc-1" and probe.requester_id == "req-1"
    assert probe.job == "steel_crawl"  # the deeper probe rides the Steel/CDP path

    # leg 1 (commit): classifications -> spine props on the Service via l1_curator
    captured = {}

    def fake_curate(services, project_id):
        captured["services"] = services
        captured["project_id"] = project_id
        return (len(services), 0)

    def fake_observe(observations, project_id):
        captured["observations"] = observations
        return (0, len(observations))

    written = commit_anatomy(res, "proj-1", "storefront", curate_fn=fake_curate, observe_fn=fake_observe)
    svc = captured["services"][0]
    assert svc.business_function_slug == "storefront"
    assert svc.props["navigation_model"] == "SPA"
    assert svc.props["rendering_model"] == "CSR"
    assert "navigation_model_evidence" in svc.props and "rendering_model_confidence" in svc.props
    assert written["classifications"] == 2 and written["observations"] == 2 and written["probes"] == 1


# --- AST-SPINE-05: fail-open + STEEL config gate ---

def test_webpage_profile_fail_open_and_steel_gate():
    # an LLM/skill error degrades to an empty result, never raises
    def boom(signals):
        raise RuntimeError("LLM 500")

    res = webpage_profile({"base_url": "https://a"}, profile_fn=boom)
    assert res.classifications == [] and res.observations == [] and res.probes == []

    # STEEL_API_KEY absent: the deeper probe is STILL emitted as a request, and the
    # classifications still proceed from passive signals (graceful degrade)
    p = _proposal(rendering_fingerprint_only=True, rendering_confidence="High")
    res2 = webpage_profile({"base_url": "https://a"}, profile_fn=lambda s: p, steel_available=False)
    assert len(res2.classifications) == 2  # classification proceeds
    assert len(res2.probes) == 1  # probe still emitted despite no Steel


def test_commit_anatomy_fail_open_on_write_error():
    res = webpage_profile({"base_url": "https://a"}, profile_fn=lambda s: _proposal(), steel_available=True)

    def exploding_curate(services, project_id):
        raise RuntimeError("neo4j down")

    # a write failure degrades per-leg, never crashes
    written = commit_anatomy(res, "proj-1", "storefront",
                             curate_fn=exploding_curate, observe_fn=lambda o, p: (0, len(o)))
    assert written["classifications"] == 0  # leg 1 degraded
    assert written["observations"] == 2     # leg 2 still ran


# --- AST-SPINE-06: the SKILL.md encodes the L1D-31a discipline + both vocabularies ---

def test_webpage_profile_skill_encodes_discipline():
    from agent.recon import skills
    skills.clear_cache()
    text = skills.skill_for("analysis/anatomy/webpage-profile")
    assert not text.startswith("---")  # frontmatter stripped
    # independent dimensions + fingerprint-insufficiency (L1D-31a)
    assert "independent" in text.lower()
    assert "fingerprint" in text.lower() and "never" in text.lower()
    # both controlled vocabularies present
    for v in anatomy.NAVIGATION_MODELS:
        assert v in text
    for v in anatomy.RENDERING_MODELS:
        assert v in text
    skills.clear_cache()
