import pytest

from agent.recon.parsers import PARSERS
from agent.recon.jobs import JOBS, PHASES, build_phase_plan, validate_job_subset


def test_every_job_tool_has_a_parser():
    for name, job in JOBS.items():
        assert job.tool == name
        assert job.tool in PARSERS, f"{job.tool} has no parser"


def test_amass_template_has_enum_json():
    assert "enum -json" in JOBS["amass"].command_template


def test_dnsx_template_has_json():
    assert "-json" in JOBS["dnsx"].command_template


def test_subdomain_takeover_template_has_target_placeholder():
    # A placeholder-less template gives the pod nothing to scan (silent
    # zero deltas). Guard against that regression.
    assert "{target}" in JOBS["subdomain_takeover"].command_template


def test_phase_zero_is_subdomain_discovery():
    assert "subfinder" in PHASES[0]
    assert "amass" in PHASES[0]


def test_consumes_deps_respected_across_full_plan():
    available = {"Domain"}
    for phase in PHASES:
        for job_name in phase:
            job = JOBS[job_name]
            assert job.consumes in available, (
                f"{job_name} consumes {job.consumes} before it is available"
            )
        for job_name in phase:
            available.update(JOBS[job_name].produces)


def test_validate_job_subset_httpx_alone_raises():
    with pytest.raises(ValueError):
        validate_job_subset(["httpx"])


def test_validate_job_subset_subfinder_passes():
    validate_job_subset(["subfinder"])


def test_validate_job_subset_subfinder_dnsx_passes():
    validate_job_subset(["subfinder", "dnsx"])


def test_validate_job_subset_subfinder_httpx_passes():
    validate_job_subset(["subfinder", "httpx"])


def test_build_phase_plan_full():
    plan = build_phase_plan()
    assert plan == PHASES
    # ensure it's a copy, not the same list objects (defensive)
    assert plan is not PHASES


def test_build_phase_plan_subset():
    plan = build_phase_plan(["subfinder", "httpx"])
    flat = [j for phase in plan for j in phase]
    assert flat == ["subfinder", "httpx"]


def test_build_phase_plan_invalid_subset_raises():
    with pytest.raises(ValueError):
        build_phase_plan(["httpx"])


def test_steel_crawl_job_tool_matches_registered_parser():
    assert JOBS["steel_crawl"].tool in PARSERS


def test_steel_crawl_job_is_agent_configurator_mode():
    assert JOBS["steel_crawl"].configurator_mode == "agent"


def test_steel_crawl_job_consumes_baseurl_and_is_placed_after_httpx():
    assert JOBS["steel_crawl"].consumes == "BaseURL"
    httpx_phase_idx = next(i for i, phase in enumerate(PHASES) if "httpx" in phase)
    steel_crawl_phase_idx = next(i for i, phase in enumerate(PHASES) if "steel_crawl" in phase)
    assert steel_crawl_phase_idx > httpx_phase_idx


def test_validate_job_subset_with_steel_crawl_passes():
    validate_job_subset(["subfinder", "httpx", "steel_crawl"])


def test_jsluice_consumes_js_endpoints_via_path_selector_and_is_batched():
    job = JOBS["jsluice"]
    assert job.consumes == "Endpoint"
    assert job.batch is True
    assert job.command_template == ""  # batched: command built per-pod, not filled
    assert job.consumes_where is not None
    assert job.consumes_where.field == "path"
    assert job.consumes_where.op == "ends_with"
    assert set(job.consumes_where.values) == {".js", ".mjs"}


def test_jsluice_runs_after_the_endpoint_producing_crawlers():
    # jsluice must sit in a LATER phase than katana (which mints the `.js`
    # Endpoints it consumes) or the phase barrier feeds it nothing (D17).
    jsluice_idx = next(i for i, p in enumerate(PHASES) if "jsluice" in p)
    katana_idx = next(i for i, p in enumerate(PHASES) if "katana" in p)
    assert jsluice_idx > katana_idx


def test_gau_is_not_a_scheduled_job():
    # gau is withdrawn from the pipeline (D-gau): no JOBS entry, not in any phase.
    assert "gau" not in JOBS
    assert not any("gau" in phase for phase in PHASES)


def test_arjun_runs_after_jsluice_so_recovered_endpoints_reach_it():
    arjun_idx = next(i for i, p in enumerate(PHASES) if "arjun" in p)
    jsluice_idx = next(i for i, p in enumerate(PHASES) if "jsluice" in p)
    assert arjun_idx > jsluice_idx


def test_kiterunner_is_gated_to_the_webapi_profile():
    # D16: kiterunner (API-route scanner) only consumes BaseURLs httpx profiled
    # as `webapi`, via the D17 consumes_where selector.
    job = JOBS["kiterunner"]
    assert job.consumes == "BaseURL"
    assert job.consumes_where is not None
    assert job.consumes_where.field == "profile"
    assert job.consumes_where.op == "equals"
    assert job.consumes_where.values == ["webapi"]


def test_kiterunner_runs_after_httpx_which_sets_the_profile():
    # The profile it gates on is set by httpx, so httpx must run in an earlier
    # phase (else the phase barrier feeds kiterunner unprofiled BaseURLs).
    httpx_idx = next(i for i, p in enumerate(PHASES) if "httpx" in p)
    kite_idx = next(i for i, p in enumerate(PHASES) if "kiterunner" in p)
    assert kite_idx > httpx_idx
