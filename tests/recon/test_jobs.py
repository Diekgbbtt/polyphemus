import pytest

from polymerhus.recon.domain.parsers import PARSERS
from polymerhus.recon.control.jobs import JOBS, PHASES, build_phase_plan, validate_job_subset


def test_every_job_tool_has_a_parser():
    for name, job in JOBS.items():
        assert job.tool == name
        assert job.tool in PARSERS, f"{job.tool} has no parser"


def test_amass_template_has_enum_json():
    assert "enum -json" in JOBS["amass"].command_template


def test_dnsx_template_has_json():
    assert "-json" in JOBS["dnsx"].command_template


def test_katana_template_excludes_static_assets_but_keeps_js():
    """AMV-8 ticket 6: katana filters presentational static extensions and
    excludes dependency/backup trees from the crawl at the source, but never
    filters `.js`/`.mjs` (jsluice's D17 input) and still emits JSONL."""
    template = JOBS["katana"].command_template
    # static assets filtered from crawl output via -ef ...
    for ext in ("css", "woff2", "map", "png", "svg", "mp4", "pdf", "zip"):
        assert f",{ext}" in template or f"-ef {ext}" in template or f" {ext}," in template
    # ... but JS is NEVER in the extension filter (it is jsluice's input).
    ef_segment = template.split("-ef ", 1)[1].split(" ", 1)[0]
    assert "js" not in ef_segment.split(",")
    assert "mjs" not in ef_segment.split(",")
    # dependency / backup trees excluded from crawl scope.
    assert "-cos" in template and "node_modules/" in template
    # output contract preserved.
    assert "-jsonl" in template


def test_ffuf_template_writes_json_to_file_and_cats_it_with_autocalibration():
    # `-of json` alone (no `-o` destination) makes ffuf emit its human banner to
    # stdout and never produce JSON, so parse_ffuf silently gets []. The template
    # must write JSON to the per-pod /work/{session} dir and cat it to stdout,
    # and carry `-ac` to filter the SPA soft-404 catch-all noise.
    template = JOBS["ffuf"].command_template
    assert "-o /work/{session}/ffuf.json" in template
    assert "-of json" in template
    # ffuf ALSO prints its results table to stdout, so its own stdout must be
    # suppressed (`>/dev/null`) before the `&& cat` - otherwise the parser gets
    # `<table>\n{JSON}` and json.loads fails, silently dropping every endpoint.
    # `&&` is kept so a real ffuf failure still propagates a non-zero exit.
    assert ">/dev/null && cat /work/{session}/ffuf.json" in template
    assert "-ac" in template
    # auth + rate slots preserved
    assert "{auth_header}" in template
    assert "{rate_flags}" in template


def test_arjun_template_seeds_default_suppresses_stdout_and_reads_file():
    # Two coupled faults the template must fix:
    #  1. arjun writes NO `-oJ` file when it finds zero params, so a bare
    #     `arjun ... && cat file` makes `cat` fail on a clean zero-finding run;
    #     the shell chain then exits non-zero and the pod gate misreads a valid
    #     "found nothing" result as a tool failure (retried to exhaustion).
    #     Seeding a valid empty-JSON default keeps a zero-finding run at exit 0.
    #  2. arjun prints its `[!]` progress to stdout, so its own stdout must be
    #     suppressed (`>/dev/null`) or the parser gets `[!] lines\n{JSON}`.
    # `&&` is preserved throughout so a real arjun crash still exits non-zero.
    template = JOBS["arjun"].command_template
    assert "printf '{}' > /work/{session}/arjun.json" in template
    assert "-oJ /work/{session}/arjun.json" in template
    assert ">/dev/null && cat /work/{session}/arjun.json" in template
    assert "{auth_header}" in template


def test_arjun_template_caps_request_rate_for_deterministic_yield():
    # FR-CURE2E trace forensics: arjun's parameter detection is non-deterministic
    # run-to-run on the IDENTICAL surface (one e2e drew 58 Parameters, another only
    # 5), rooted in the target throttling the request burst - arjun reads a
    # throttled response as an anomaly, so it invents or misses parameters.
    # Capping the request rate removes the burst that provokes it.
    # Guard the cap so it cannot be silently dropped.
    template = JOBS["arjun"].command_template
    assert "--rate-limit" in template

    # And guard the VALUE stays in the band the measurement justified (operator
    # decision 2026-07-22). arjun issues ~260 requests per URL and its wall-clock
    # is exactly linear in the cap, so the rung is bounded on both sides:
    #   * too high and the burst that caused the defect returns;
    #   * too low and a single URL exceeds EXEC_TIMEOUT_S=300 (at 1 rps a pod is
    #     already at ~260s, with no headroom for a slower remote target), which
    #     turns the fix into a total yield loss.
    rate = int(template.split("--rate-limit", 1)[1].split()[0])
    assert 2 <= rate <= 10, f"arjun --rate-limit {rate} is outside the justified band"


def test_arjun_template_does_not_use_stable_mode():
    # `--stable` was REJECTED as the fix (operator, 2026-07-22). It forces
    # threads=1 AND injects a random 3-10s delay before EVERY request
    # (arjun/core/requester.py), i.e. 13-43 min for the ~260 requests one URL
    # takes - roughly 10x over EXEC_TIMEOUT_S=300. Every arjun pod would time out
    # and the job would yield nothing, so this "reliability" flag is a silent
    # total-loss switch here. Guard it against being reintroduced.
    assert "--stable" not in JOBS["arjun"].command_template


def test_subdomain_takeover_template_has_target_placeholder():
    # A placeholder-less template gives the pod nothing to scan (silent
    # zero deltas). Guard against that regression.
    assert "{target}" in JOBS["subdomain_takeover"].command_template


def test_phase_zero_is_subdomain_discovery():
    assert "subfinder" in PHASES[0]


def test_amass_and_paramspider_are_out_of_production():
    # Withdrawn from PHASES (operator 2026-07-28), like gau: JobSpec kept, only
    # scheduling removed. amass is broken vs v4.2.0 (degraded every run);
    # paramspider withdrawn to cut phase-4 crawl load on the constrained host.
    scheduled = {j for phase in PHASES for j in phase}
    assert "amass" not in scheduled
    assert "paramspider" not in scheduled
    # JobSpecs (and parsers) remain for easy re-introduction.
    assert "amass" in JOBS and "paramspider" in JOBS


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


def test_validate_job_subset_httpx_alone_passes():
    # httpx consumes "Subdomain", but pipeline._inject_seed_host unconditionally
    # injects the scope's seed host into any Subdomain-consuming job's input
    # set regardless of whether a discovery job (subfinder/amass/dnsx) ran -
    # so httpx alone is a valid, runnable subset.
    validate_job_subset(["httpx"])


def test_validate_job_subset_unmet_dependency_raises():
    # arjun consumes "Endpoint", which nothing in this subset produces and is
    # not covered by the seed-host injection (only "Subdomain" is).
    with pytest.raises(ValueError):
        validate_job_subset(["arjun"])


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
        build_phase_plan(["arjun"])


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


def test_kiterunner_is_an_authenticated_job():
    # kiterunner scans REST routes behind auth just like ffuf/katana - it must
    # receive the project's cookies/headers, so it belongs to the use_auth set
    # and its command_template has an {auth_header} slot to fill.
    job = JOBS["kiterunner"]
    assert job.use_auth is True
    assert "{auth_header}" in job.command_template


def test_graphql_cop_is_an_authenticated_job():
    # graphql-cop probes a GraphQL surface that may sit behind auth, so it must
    # receive the project's cookies/headers like the other request-based tools.
    job = JOBS["graphql-cop"]
    assert job.use_auth is True
    assert "{auth_header}" in job.command_template


def test_kiterunner_is_gated_to_the_restapi_profile():
    # D16 per-endpoint split: kiterunner consumes the `restapi` ENDPOINTS a host
    # exposes (not just its root BaseURL profile) and flags api_scope, so its
    # input is collapsed into evidence-derived API-root scan prefixes.
    job = JOBS["kiterunner"]
    assert job.consumes == "Endpoint"
    assert job.api_scope is True
    assert job.consumes_where is not None
    assert job.consumes_where.field == "profile"
    assert job.consumes_where.op == "equals"
    assert job.consumes_where.values == ["restapi"]


def test_kiterunner_runs_after_httpx_which_sets_the_profile():
    # The profile it gates on is set by httpx, so httpx must run in an earlier
    # phase (else the phase barrier feeds kiterunner unprofiled BaseURLs).
    httpx_idx = next(i for i, p in enumerate(PHASES) if "httpx" in p)
    kite_idx = next(i for i, p in enumerate(PHASES) if "kiterunner" in p)
    assert kite_idx > httpx_idx


def test_graphql_cop_is_gated_to_the_graphql_api_profile():
    # graphql-cop previously had no consumes_where and fired at every BaseURL
    # (54 on the last live run). It only makes sense against a GraphQL surface,
    # so it is gated to the dedicated `graphql_api` profile httpx derives from
    # the endpoint path (a miss = no run, the accepted tradeoff).
    job = JOBS["graphql-cop"]
    # D16 per-endpoint split: it audits the EXACT graphql_api Endpoint, so it
    # consumes Endpoint (target = the endpoint's own url), not the BaseURL root.
    assert job.consumes == "Endpoint"
    assert job.consumes_where is not None
    assert job.consumes_where.field == "profile"
    assert job.consumes_where.op == "equals"
    assert job.consumes_where.values == ["graphql_api"]


def test_graphql_cop_runs_after_httpx_which_sets_the_profile():
    # The profile it gates on is set by httpx, so httpx must run in an earlier
    # phase (else the phase barrier feeds graphql-cop unprofiled BaseURLs).
    httpx_idx = next(i for i, p in enumerate(PHASES) if "httpx" in p)
    gql_idx = next(i for i, p in enumerate(PHASES) if "graphql-cop" in p)
    assert gql_idx > httpx_idx


# --- D27: reprofile pass + relocated API phases ----------------------------


def test_httpx_reprofile_reuses_the_httpx_parser():
    # The reprofile job re-probes BaseURLs and must classify them via the SAME
    # parser as httpx (no duplicated classify logic), keyed under its own tool
    # name so the `job.tool == name` invariant holds.
    job = JOBS["httpx_reprofile"]
    assert job.tool == "httpx_reprofile"
    assert PARSERS["httpx_reprofile"] is PARSERS["httpx"]


def test_httpx_reprofile_consumes_endpoints_for_per_endpoint_profiling():
    # D16 per-endpoint split: it consumes the ENDPOINT population (each endpoint's
    # own URL becomes {target}), not just BaseURL roots, and flags
    # endpoint_profiling so its input set gets dedup + root-`/`-materialisation
    # prep. It is an authenticated probe so behind-auth endpoints classify right.
    job = JOBS["httpx_reprofile"]
    assert job.consumes == "Endpoint"
    assert job.consumes_where is None
    assert job.endpoint_profiling is True
    assert job.use_auth is True
    assert "{target}" in job.command_template
    assert "{auth_header}" in job.command_template


def test_httpx_reprofile_runs_after_jsluice_and_before_the_api_phases():
    # It must sit after jsluice (the last BaseURL producer, minting JS-derived
    # API hosts) and before kiterunner/graphql-cop, so those gate on the
    # reprofiled surface, not just httpx's originally-probed hosts.
    jsluice_idx = next(i for i, p in enumerate(PHASES) if "jsluice" in p)
    reprofile_idx = next(i for i, p in enumerate(PHASES) if "httpx_reprofile" in p)
    kite_idx = next(i for i, p in enumerate(PHASES) if "kiterunner" in p)
    gql_idx = next(i for i, p in enumerate(PHASES) if "graphql-cop" in p)
    assert reprofile_idx > jsluice_idx
    assert kite_idx > reprofile_idx
    assert gql_idx > reprofile_idx


def test_kiterunner_and_graphql_cop_left_the_crawl_phase():
    # D27: they were moved out of phase 4 (the katana/ffuf crawl phase) so they
    # can gate on the reprofiled API surface. ffuf keeps its crawl role there.
    crawl_phase = next(p for p in PHASES if "katana" in p)
    assert "kiterunner" not in crawl_phase
    assert "graphql-cop" not in crawl_phase
    assert "ffuf" in crawl_phase


def test_kiterunner_and_graphql_cop_are_two_separate_phases():
    # Operator decision: api enumeration (kiterunner) and static api testing
    # (graphql-cop) stay distinct phases, not one combined phase.
    kite_phase = next(p for p in PHASES if "kiterunner" in p)
    gql_phase = next(p for p in PHASES if "graphql-cop" in p)
    assert kite_phase is not gql_phase
    assert "graphql-cop" not in kite_phase
    assert "kiterunner" not in gql_phase


def test_arjun_runs_after_api_enumeration():
    # D27/GP4-a: arjun repositioned after kiterunner so it discovers Parameters
    # on the routes api enumeration just found (still after jsluice too).
    arjun_idx = next(i for i, p in enumerate(PHASES) if "arjun" in p)
    kite_idx = next(i for i, p in enumerate(PHASES) if "kiterunner" in p)
    jsluice_idx = next(i for i, p in enumerate(PHASES) if "jsluice" in p)
    assert arjun_idx > kite_idx
    assert arjun_idx > jsluice_idx


def test_full_plan_still_validates_with_the_reprofile_and_api_phases():
    # The relocated API jobs must still satisfy the consumes/produces DAG:
    # every job's consumes type is produced by an earlier phase (or Domain).
    validate_job_subset(list(JOBS.keys()))


def test_validate_job_subset_httpx_reprofile_needs_a_baseurl_producer():
    # It consumes BaseURL, so alone (no producer) it must fail; with httpx (a
    # BaseURL producer) upstream it passes.
    with pytest.raises(ValueError):
        validate_job_subset(["httpx_reprofile"])
    validate_job_subset(["subfinder", "httpx", "httpx_reprofile"])
