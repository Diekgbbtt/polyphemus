# agent/recon/jobs.py
"""Job registry + phase DAG for the recon pipeline.

JOBS maps each fleet tool (matching a PARSERS key exactly) to a JobSpec
describing its command template, the asset node type it consumes, and the
node types it produces. PHASES groups job names into an ordered execution
plan such that every job's `consumes` type is either the pre-seeded root
type ("Domain") or has been produced by a job in an earlier phase.
"""

from agent.recon.types import AssetSelector, JobSpec

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
            "katana -u {target} -d 3 -jc -kf robotstxt -c 10 -rl 50 "
            "-ef css,woff,woff2,ttf -silent -jsonl {auth_header}"
        ),
        produces=["BaseURL", "Endpoint", "Parameter"],
        consumes="BaseURL",
        use_auth=True,
    ),
    "ffuf": JobSpec(
        tool="ffuf",
        skill="content_discovery",
        command_template=(
            "ffuf -u {target}/FUZZ -w /usr/share/seclists/Discovery/Web-Content/common.txt "
            "-mc 200,403 -of json {auth_header}"
        ),
        produces=["Endpoint"],
        consumes="BaseURL",
        use_auth=True,
    ),
    "kiterunner": JobSpec(
        tool="kiterunner",
        skill="content_discovery",
        command_template="kr scan {target} -w /opt/localbin/routes-small.kite",
        produces=["Endpoint"],
        consumes="BaseURL",
        use_auth=False,
    ),
    "jsluice": JobSpec(
        tool="jsluice",
        skill="js_secret_scan",
        # Batched: the per-pod command is built from the pod's bundle batch by
        # agent.recon.batching.build_batch_command (fetch + jsluice urls/secrets
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
        command_template="graphql-cop -t {target} -o json",
        produces=["Endpoint"],
        consumes="BaseURL",
        use_auth=False,
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
            "arjun -u {target} -oJ /work/{session}/arjun.json {auth_header} "
            "&& cat /work/{session}/arjun.json"
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
    ["katana", "ffuf", "kiterunner", "graphql-cop", "paramspider", "steel_crawl"],
    # jsluice consumes the `.js`/`.mjs` Endpoints the phase-4 crawler (katana)
    # produces, so it MUST run in a later phase than it - the phase
    # barrier resolves a job's inputs before any same-phase job runs, so keeping
    # jsluice in phase 4 would feed it only httpx's endpoints, not katana's
    # bundles (the D17 defect). Its own recovered Endpoints then reach arjun.
    ["jsluice"],
    ["arjun"],
]


def _available_types_by_phase(subset: set[str] | None = None) -> list[tuple[list[str], set[str]]]:
    """Walk PHASES, tracking which node types are available before each phase.

    Returns a list of (phase_jobs, available_before_phase) pairs, where
    phase_jobs is filtered to `subset` when provided.
    """
    available = {DOMAIN}
    result = []
    for phase in PHASES:
        phase_jobs = [j for j in phase if subset is None or j in subset]
        result.append((phase_jobs, set(available)))
        for job_name in phase_jobs:
            available.update(JOBS[job_name].produces)
    return result


def validate_job_subset(subset: list[str]) -> None:
    """Raise ValueError if any selected job's `consumes` type is not produced
    by an earlier selected job (and is not the pre-seeded Domain root)."""
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
