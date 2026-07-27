# src/polymerhus/recon/control/jobs.py
"""Job registry + phase DAG for the recon pipeline.

JOBS maps each fleet tool (matching a PARSERS key exactly) to a JobSpec
describing its command template, the asset node type it consumes, and the
node types it produces. PHASES groups job names into an ordered execution
plan such that every job's `consumes` type is either the pre-seeded root
type ("Domain"), the seed host injected into every "Subdomain"-consuming
job (`pipeline._inject_seed_host`), or has been produced by a job in an
earlier phase.
"""

from polymerhus.recon.domain.types import AssetSelector, JobSpec

DOMAIN = "Domain"  # pre-seeded root asset type (the project's target domain)

JOBS: dict[str, JobSpec] = {
    "subfinder": JobSpec(
        tool="subfinder",
        skill="subdomain_discovery",
        command_template="subfinder -d {domain} -all -json -silent",
        produces=["Subdomain"],
        consumes="Domain",
        use_auth=False,
    ),
    "amass": JobSpec(
        tool="amass",
        skill="subdomain_discovery",
        command_template="amass enum -json -d {domain}",
        produces=["Subdomain", "IP"],
        consumes="Domain",
        use_auth=False,
    ),
    "whois": JobSpec(
        tool="whois",
        skill="whois_lookup",
        command_template="whois {domain}",
        produces=["Domain"],
        consumes="Domain",
        use_auth=False,
    ),
    "dnsx": JobSpec(
        tool="dnsx",
        skill="dns_resolution",
        command_template="echo {target} | dnsx -json -a -aaaa -cname -silent",
        produces=["IP", "DNSRecord", "Subdomain"],
        consumes="Subdomain",
        use_auth=False,
    ),
    "puredns": JobSpec(
        tool="puredns",
        skill="dns_resolution",
        command_template="echo {target} | puredns resolve -r /resolvers/resolvers.txt -q",
        produces=["Subdomain"],
        consumes="Subdomain",
        use_auth=False,
    ),
    "subdomain_takeover": JobSpec(
        tool="subdomain_takeover",
        skill="takeover_check",
        command_template=(
            "subzy run --target {target} --output /work/{session}/takeover.json "
            "--hide_fails ; cat /work/{session}/takeover.json"
        ),
        produces=["ExternalDomain"],
        consumes="Subdomain",
        use_auth=False,
    ),
    "naabu": JobSpec(
        tool="naabu",
        skill="port_scan",
        command_template="naabu -host {target} -top-ports 100 -json",
        produces=["IP", "Port", "Service"],
        consumes="Subdomain",
        use_auth=False,
    ),
    "httpx": JobSpec(
        tool="httpx",
        skill="http_probe",
        command_template="httpx -u {target} -sc -title -server -td -fr -silent -json -irh {auth_header}",
        produces=["BaseURL", "Endpoint", "Technology", "Certificate", "Header"],
        consumes="Subdomain",
        use_auth=True,
    ),
    "httpx_reprofile": JobSpec(
        tool="httpx_reprofile",
        skill="http_probe",
        # Same httpx probe as the phase-3 job, but pointed at ENDPOINTS instead of
        # Subdomains. Reuses parse_httpx (registered under this tool name in
        # PARSERS), so each Endpoint's profile is assigned via the identical
        # noise_filter.classify_profile path - no duplicated classify logic.
        command_template="httpx -u {target} -sc -title -server -td -fr -silent -json -irh {auth_header}",
        produces=["BaseURL", "Endpoint", "Technology", "Certificate", "Header"],
        # D16 per-endpoint split: profile EVERY produced Endpoint, not just
        # BaseURL roots. `{target}` resolves to the Endpoint's own `url`, so httpx
        # probes each endpoint (incl. crawler/JS-minted `/api/...` under a webapp
        # root) and parse_httpx stamps that Endpoint's own `profile`; the root `/`
        # probe additionally mirrors onto `BaseURL.profile`. The input set is
        # prepared by `batching.prepare_endpoint_profile_assets` (dedup dynamic
        # routes + materialise a root `/` per BaseURL) via the endpoint_profiling
        # flag - the same seam `batch` uses for jsluice.
        consumes="Endpoint",
        endpoint_profiling=True,
        use_auth=True,
    ),
    # gau removed from the pipeline (forward decision D-gau, 2026-07-09):
    # its passive-archive harvest produced overwhelming noise (866 low-value
    # assets in one run vs katana's crawl). The pure parser stays for a possible
    # future re-introduction behind a noise filter; only the JOBS/PHASES wiring
    # is withdrawn so the orchestrator no longer schedules it.
    "paramspider": JobSpec(
        tool="paramspider",
        skill="passive_url_harvest",
        command_template="paramspider -d {domain}",
        produces=["BaseURL", "Endpoint", "Parameter"],
        consumes="Domain",
        use_auth=False,
    ),
    "katana": JobSpec(
        tool="katana",
        skill="crawl",
        command_template=(
            # AMV-8 ticket 6 (source-side belt to the curator-gate noise filter):
            # `-ef` filters presentational static assets (stylesheets, fonts,
            # sourcemaps, images, media, archives) from crawl OUTPUT at the
            # source, so they never become Endpoints even before the gate sees
            # them. `.js`/`.mjs` are deliberately NOT filtered - they are
            # jsluice's input (D17). `-cos` excludes installed-dependency source
            # trees and ftp/backup artefacts from being crawled at all. The
            # curator gate (noise_filter) still catches anything that slips
            # through, incl. generated JS these coarse flags cannot express.
            # `-fx` (form-extraction) makes katana emit response.forms[] with each
            # form's method/action/parameters, so form/body request parameters are
            # discovered (not just query params from crawled URLs) - the built-in
            # param-discovery capability the katana_parser now turns into Parameters.
            "katana -u {target} -d 3 -jc -kf robotstxt -fx -c 10 -rl 50 "
            "-ef css,scss,less,woff,woff2,ttf,eot,otf,map,"
            "png,jpg,jpeg,gif,svg,webp,ico,bmp,mp3,wav,mp4,webm,mov,pdf,zip "
            "-cos 'node_modules/|bower_components/|\\.(bak|old|swp|orig|tmp)($|\\?)' "
            "-silent -jsonl {auth_header}"
        ),
        produces=["BaseURL", "Endpoint", "Parameter"],
        consumes="BaseURL",
        use_auth=True,
    ),
    "ffuf": JobSpec(
        tool="ffuf",
        skill="content_discovery",
        command_template=(
            # `-of json` only sets the FORMAT of the file written by `-o`; without
            # an `-o` destination ffuf emits its human banner/progress to stdout and
            # the JSON is never produced, so parse_ffuf silently gets []. Write the
            # JSON to the per-pod /work/{session} dir then cat it to stdout for the
            # parser. ffuf ALSO prints its results table to stdout, so its own
            # stdout is redirected to /dev/null - otherwise the parser receives
            # `<results table>\n{JSON}`, json.loads fails, and every endpoint is
            # silently dropped (the live-run failure). `&&` is kept so a real ffuf
            # error still propagates a non-zero exit for the pod gate to retry.
            # `-ac` (auto-calibration) derives dynamic size/word filters from
            # baseline junk requests so a SPA soft-404 catch-all (every path -> 200,
            # uniform body) is filtered while genuinely-distinct paths like /api
            # still surface.
            "ffuf -u {target}/FUZZ -w /usr/share/seclists/Discovery/Web-Content/common.txt "
            "-mc 200,403 -ac -o /work/{session}/ffuf.json -of json {rate_flags} {auth_header} "
            ">/dev/null && cat /work/{session}/ffuf.json"
        ),
        produces=["Endpoint"],
        consumes="BaseURL",
        use_auth=True,
    ),
    "kiterunner": JobSpec(
        tool="kiterunner",
        skill="content_discovery",
        command_template="kr scan {target} -w /opt/localbin/routes-small.kite {auth_header}",
        produces=["Endpoint"],
        # kiterunner scans for API routes under an evidence-derived API-root
        # prefix (D16 per-endpoint split). It consumes the `restapi` ENDPOINTS a
        # host exposes (not just its root profile), and `api_scope` collapses
        # them per host into scan-target prefixes via
        # batching.build_api_scope_assets, so it fuzzes `<host>/api/` even when
        # the root `/` is a webapp. `{target}` is each derived prefix URL.
        consumes="Endpoint",
        consumes_where=AssetSelector(field="profile", op="equals", values=["restapi"]),
        api_scope=True,
        # kr scans routes that may sit behind auth, so it receives the
        # project's cookies/headers like the other request-based tools (`kr`
        # takes repeated -H "k: v" flags, the shared default format).
        use_auth=True,
    ),
    "jsluice": JobSpec(
        tool="jsluice",
        skill="js_secret_scan",
        # Batched: the per-pod command is built from the pod's bundle batch by
        # polymerhus.recon.control.batching.build_batch_command (fetch + jsluice urls/secrets
        # + sourcemap extraction), NOT from this template. Left empty because a
        # batched job never routes through fill_template.
        command_template="",
        produces=["Endpoint", "Secret"],
        # jsluice consumes the discovered JS bundles (the `.js`/`.mjs` Endpoints
        # katana crawls up), NOT the HTML BaseURL root - the D17 defect fix. The
        # selector is path-suffix, not content-type, because katana-minted `.js`
        # Endpoints carry no content_type (D17/Q5).
        consumes="Endpoint",
        consumes_where=AssetSelector(field="path", op="ends_with", values=[".js", ".mjs"]),
        batch=True,
        use_auth=False,
    ),
    "graphql-cop": JobSpec(
        tool="graphql-cop",
        skill="graphql_audit",
        command_template="graphql-cop -t {target} -o json {auth_header}",
        produces=["Endpoint"],
        # graphql-cop audits ONE GraphQL endpoint, so it consumes the EXACT
        # `graphql_api` Endpoint (D16 per-endpoint split), targeting that
        # endpoint's own URL (`{target}` = the Endpoint `url`) rather than gating
        # on the BaseURL root. A GraphQL surface at any path is now audited, not
        # only where the root `/` classifies graphql_api.
        consumes="Endpoint",
        consumes_where=AssetSelector(field="profile", op="equals", values=["graphql_api"]),
        # graphql-cop probes a GraphQL surface that may sit behind auth, so it
        # receives the project's cookies/headers (its own --headers format:
        # comma-joined `Key:Value` pairs, see pod._COMMA_HEADERS_FLAG_TOOLS).
        use_auth=True,
    ),
    "steel_crawl": JobSpec(
        tool="steel_crawl",
        skill="agentic_crawl",
        command_template="",
        produces=["BaseURL", "Endpoint", "Parameter"],
        consumes="BaseURL",
        use_auth=True,
        configurator_mode="agent",
    ),
    "arjun": JobSpec(
        tool="arjun",
        skill="param_discovery",
        command_template=(
            # arjun writes NO `-oJ` file when it discovers zero parameters, so a
            # bare `arjun ... && cat file` makes `cat` fail on a clean
            # zero-finding run; the chain then exits non-zero and the pod gate
            # misreads a valid "found nothing" result as a tool failure (retried
            # to exhaustion). Seed a valid empty-JSON default first so a
            # zero-finding run stays exit 0 and parses to []. arjun also prints
            # its `[!]` progress to stdout, so its own stdout is suppressed
            # (`>/dev/null`) - otherwise the parser gets `[!] lines\n{JSON}` and
            # drops every parameter. `&&` throughout keeps a real arjun crash
            # propagating a non-zero exit for the gate to retry.
            # `--rate-limit 5`: arjun's parameter detection is non-deterministic
            # run-to-run on the IDENTICAL surface (an e2e drew 58 params one run, 5
            # the next, FR-CURE2E forensics), rooted in the target throttling the
            # request burst - arjun's own error handler reads a rate-limited target
            # as an anomaly, so throttled responses become phantom (or missed)
            # parameters. Capping the request rate removes the burst that provokes
            # it. Measured against a local Juice Shop (`/api/Products`, 2 runs per
            # setting): arjun issues ~260 requests per URL and the wall-clock is
            # exactly linear in the cap - unlimited 4s, `--rate-limit 20` 13s,
            # `10` 26s, `5` 52s, all recovering the identical 10 parameters.
            # 5 rps is the chosen point: ~52s per URL leaves ~6x headroom under
            # EXEC_TIMEOUT_S=300, while cutting the per-process burst ~13x from the
            # measured ~65 rps of the unlimited default. That default matters more
            # than it looks - arjun is unbatched and runs MAX_PODS=20 pods at once,
            # so the aggregate burst against a single host is ~1300 rps unlimited
            # vs ~100 rps here.
            # NOT `--stable`: it forces threads=1 AND injects a random 3-10s delay
            # before EVERY request (arjun/core/requester.py), i.e. 13-43 min per URL
            # at ~260 requests - roughly 10x over EXEC_TIMEOUT_S, so every arjun pod
            # would time out and the job would yield nothing at all.
            # A fixed cap is still a guess at the target's real budget; the adaptive
            # ladder (degrade on an observed 429/403, with a pause) is AMV-17.
            "printf '{}' > /work/{session}/arjun.json "
            "&& arjun -u {target} --rate-limit 5 -oJ /work/{session}/arjun.json {auth_header} "
            ">/dev/null && cat /work/{session}/arjun.json"
        ),
        produces=["Parameter"],
        consumes="Endpoint",
        use_auth=True,
    ),
}


# Ordered phases: job names grouped by their consumes/produces dependencies,
# rooted at subdomain discovery. Each job's `consumes` type is either
# DOMAIN (always available) or produced by a job in an earlier phase.
PHASES: list[list[str]] = [
    ["subfinder", "amass", "whois"],
    ["dnsx", "puredns", "subdomain_takeover"],
    ["naabu"],
    ["httpx"],
    # Crawl phase. kiterunner + graphql-cop were moved OUT of this phase (D27):
    # they now run after the reprofile pass so they can gate on the JS-derived
    # API surface, not just httpx's originals.
    ["katana", "ffuf", "paramspider", "steel_crawl"],
    # jsluice consumes the `.js`/`.mjs` Endpoints the phase-4 crawler (katana)
    # produces, so it MUST run in a later phase than it - the phase
    # barrier resolves a job's inputs before any same-phase job runs, so keeping
    # jsluice in phase 4 would feed it only httpx's endpoints, not katana's
    # bundles (the D17 defect). Its own recovered Endpoints then reach arjun.
    ["jsluice"],
    # Reprofile pass (D27): re-probe every BaseURL a crawler minted without a
    # `profile` - katana/ffuf endpoints and the JS-derived API hosts jsluice
    # recovers from bundles - and classify each webapp/restapi/graphql_api the
    # same way httpx does. MUST sit after jsluice (the last BaseURL producer)
    # and before the API phases, so kiterunner/graphql-cop finally see the
    # JS-derived API surface rather than only httpx's originally-probed hosts.
    ["httpx_reprofile"],
    # "api enumeration" (D27): kiterunner scans REST-API routes, gated
    # profile==restapi - which now matches reprofiled crawler/JS BaseURLs.
    ["kiterunner"],
    # arjun runs after api enumeration so it discovers Parameters on the routes
    # kiterunner just found (as well as jsluice's recovered Endpoints). A future
    # deferred ffuf API fuzzer (D26 `ffuf_api`) would slot HERE, right after
    # arjun, since it needs both endpoints and parameters known.
    ["arjun"],
    # "static api testing" (D27): graphql-cop audits a GraphQL surface, gated
    # profile==graphql_api. Kept a SEPARATE phase from api enumeration per the
    # operator decision (the two have no data dependency on each other, so the
    # split is a deliberate semantic boundary, not a forced one).
    ["graphql-cop"],
]


def _available_types_by_phase(subset: set[str] | None = None) -> list[tuple[list[str], set[str]]]:
    """Walk PHASES, tracking which node types are available before each phase.

    Returns a list of (phase_jobs, available_before_phase) pairs, where
    phase_jobs is filtered to `subset` when provided.

    `Subdomain` is seeded alongside the `Domain` root because
    `pipeline._inject_seed_host` unconditionally injects the scope's seed host
    into any `Subdomain`-consuming job's input set (httpx/naabu/
    subdomain_takeover) regardless of whether a discovery job (subfinder/
    amass/dnsx) is in the selected subset - so a subset that runs httpx
    without subfinder is valid at runtime and must not be rejected here.
    """
    available = {DOMAIN, "Subdomain"}
    result = []
    for phase in PHASES:
        phase_jobs = [j for j in phase if subset is None or j in subset]
        result.append((phase_jobs, set(available)))
        for job_name in phase_jobs:
            available.update(JOBS[job_name].produces)
    return result


def validate_job_subset(subset: list[str]) -> None:
    """Raise ValueError if any selected job's `consumes` type is not produced
    by an earlier selected job (and is not the pre-seeded Domain root, nor
    "Subdomain" - always satisfied by the seed host `pipeline._inject_seed_host`
    injects into every Subdomain-consuming job)."""
    unknown = [j for j in subset if j not in JOBS]
    if unknown:
        raise ValueError(f"unknown job(s): {unknown}")

    subset_set = set(subset)
    for phase_jobs, available in _available_types_by_phase(subset_set):
        for job_name in phase_jobs:
            consumes = JOBS[job_name].consumes
            if consumes not in available:
                raise ValueError(
                    f"job '{job_name}' consumes '{consumes}' which is not produced "
                    "by any earlier selected job (and is not the seeded Domain root)"
                )


def build_phase_plan(job_subset: list[str] | None = None) -> list[list[str]]:
    """Return the ordered phase plan, optionally restricted to a validated
    subset of jobs. Phases with no selected jobs are dropped."""
    if job_subset is None:
        return [list(phase) for phase in PHASES]

    validate_job_subset(job_subset)
    subset_set = set(job_subset)
    return [
        [j for j in phase if j in subset_set]
        for phase in PHASES
        if any(j in subset_set for j in phase)
    ]
