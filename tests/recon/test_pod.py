from agent.recon.types import JobSpec, ExecResult, Observation
from agent.recon import pod
from agent.recon.curator import curate
from agent.recon.jobs import JOBS

HTTPX_JOB = JobSpec(tool="httpx", skill="http_probe",
                    command_template="httpx -u {target} -json -silent",
                    produces=["BaseURL", "Endpoint"], consumes="Subdomain")

FIX_LINE = '{"url":"https://app.example.com","input":"app.example.com","status_code":200,"scheme":"https","host":"1.2.3.4","tech":["nginx"]}'

FIX_LINE_FULL = (
    '{"url":"https://app.example.com","input":"app.example.com","status_code":200,'
    '"title":"Example App","webserver":"nginx","content_type":"text/html",'
    '"content_length":1024,"scheme":"https","host":"93.184.216.34","tech":["nginx","React"],'
    '"tls":{"subject_cn":"app.example.com","issuer_dn":"CN=R3","not_before":"2026-01-01T00:00:00Z",'
    '"not_after":"2026-04-01T00:00:00Z","subject_an":["app.example.com"]}}'
)

def test_exec_result_from_artifact_reads_structured_dict():
    artifact = {"stdout": "x", "stderr": "", "returncode": 2, "duration_ms": 9}
    result = pod._exec_result_from_artifact(artifact)
    assert result.returncode == 2
    assert result.stdout == "x"
    assert result.stderr == ""
    assert result.duration_ms == 9


def test_exec_result_from_artifact_wrapped_structured_content():
    artifact = {"structured_content": {"stdout": "y", "stderr": "e", "returncode": 3, "duration_ms": 4}}
    result = pod._exec_result_from_artifact(artifact)
    assert result.returncode == 3
    assert result.stdout == "y"


def test_exec_result_from_artifact_missing_is_failure_not_success():
    result = pod._exec_result_from_artifact(None)
    assert result.returncode == 1  # missing structured result is FAILURE, never assumed success

    result2 = pod._exec_result_from_artifact("not a mapping")
    assert result2.returncode == 1


def test_fill_template_substitutes_target():
    cmd = pod.fill_template("httpx -u {target} -json", {"name": "app.example.com"}, {})
    assert "app.example.com" in cmd


def test_fill_template_substitutes_session():
    cmd = pod.fill_template(
        "subzy run --target {target} --output /work/{session}/out.json",
        {"name": "old.example.com"},
        {},
        session_id="run42-pod7",
    )
    assert "/work/run42-pod7/out.json" in cmd
    assert "{session}" not in cmd


def test_fill_template_auth_header_httpx_serializes_cookie_string_not_dict_repr():
    cmd = pod.fill_template(
        "httpx -u {target} -json {auth_header}",
        {"name": "app.example.com"},
        {"auth_context": {"cookies": [{"name": "session", "value": "abc"}]}, "_use_auth": True},
        tool="httpx",
    )
    assert 'Cookie: session=abc' in cmd
    assert '-H "Cookie: session=abc"' in cmd
    assert "{" not in cmd  # no residual placeholder, no dict repr


def test_fill_template_auth_header_arjun_uses_headers_flag():
    cmd = pod.fill_template(
        "arjun -u {target} {auth_header}",
        {"name": "app.example.com"},
        {"auth_context": {"cookies": [{"name": "session", "value": "abc"}]}, "_use_auth": True},
        tool="arjun",
    )
    assert '--headers "Cookie: session=abc"' in cmd


def test_fill_template_auth_header_multi_cookie():
    cmd = pod.fill_template(
        "httpx -u {target} {auth_header}",
        {"name": "app.example.com"},
        {
            "auth_context": {
                "cookies": [
                    {"name": "session", "value": "abc"},
                    {"name": "csrf", "value": "xyz"},
                ]
            },
            "_use_auth": True,
        },
        tool="httpx",
    )
    assert '-H "Cookie: session=abc; csrf=xyz"' in cmd


def test_fill_template_auth_header_empty_when_no_use_auth():
    cmd = pod.fill_template(
        "httpx -u {target} {auth_header}",
        {"name": "app.example.com"},
        {"auth_context": {"cookies": [{"name": "session", "value": "abc"}]}, "_use_auth": False},
        tool="httpx",
    )
    assert "Cookie" not in cmd
    assert "-H" not in cmd
    assert "{" not in cmd


def test_fill_template_auth_header_empty_when_not_use_auth_job():
    # non-auth job: extra carries no auth_context at all (pipeline never
    # threads it for jobs where job.use_auth is False).
    cmd = pod.fill_template(
        "subfinder -d {domain} -all -json -silent",
        {"name": "example.com"},
        {"_use_auth": False},
        tool="subfinder",
    )
    assert "Cookie" not in cmd
    assert "-H" not in cmd
    assert "{" not in cmd


# Representative asset for each Layer-0 consumes type a JOBS entry might
# declare, keyed by identity + (for Endpoint) the `url` PROP that a real
# curated/read-back asset would carry (design §10.3) - fill_template's
# {target} falls back to a "url"/"address" key when "name" is absent, so
# Endpoint needs its url PROP present to be single-asset-runnable, exactly
# the F4 fidelity gap the e2e fake must also model.
_REPRESENTATIVE_ASSETS = {
    "Domain": {"name": "example.com"},
    "Subdomain": {"name": "www.example.com"},
    "BaseURL": {"url": "https://app.example.com"},
    "Endpoint": {
        "path": "/api/v1/users",
        "method": "GET",
        "baseurl": "https://app.example.com",
        "url": "https://app.example.com/api/v1/users",
    },
}


def test_no_job_command_template_leaves_a_residual_placeholder():
    """F1 guard rail: every JOBS entry's command_template must be fully
    fillable by `fill_template` for a representative asset of its `consumes`
    type (+ session_id, + an auth extra for use_auth jobs) - no `{...}`
    placeholder may survive. Regresses the whole class of "literal
    {placeholder} shipped to the shell" bugs fleet-wide, not just per-tool."""
    for name, job in JOBS.items():
        asset = _REPRESENTATIVE_ASSETS[job.consumes]
        extra = {"_use_auth": job.use_auth}
        if job.use_auth:
            extra["auth_context"] = {"cookies": [{"name": "session", "value": "abc"}]}
        cmd = pod.fill_template(
            job.command_template, asset, extra, session_id="sess-guard", tool=job.tool
        )
        assert "{" not in cmd and "}" not in cmd, (
            f"job '{name}' left a residual placeholder in: {cmd!r}"
        )


def test_pod_happy_path_success():
    captured = {}
    def exec_fn(cmd, sid, t): return ExecResult(stdout=FIX_LINE, stderr="", returncode=0, duration_ms=3)
    def curate_fn(assets, obs, pid): captured["n"] = len(assets); return (len(assets), len(obs))
    def triage_fn(er, assets, job): return []
    g = pod.build_pod_graph(exec_fn=exec_fn, curate_fn=curate_fn, triage_fn=triage_fn)
    out = g.invoke({"job": HTTPX_JOB, "input_asset": {"name": "app.example.com"},
                    "asset_context": "", "extra": {}, "session_id": "run-pod1",
                    "iteration": 0, "project_id": "proj1"})
    assert out["export"].verdict == "success"
    assert captured["n"] >= 1

def test_pod_retries_then_fails_on_nonzero():
    attempts = {"n": 0}
    def exec_fn(cmd, sid, t):
        attempts["n"] += 1
        return ExecResult(stdout="", stderr="boom", returncode=1, duration_ms=1)
    def curate_fn(a, o, p): return (0, 0)
    def triage_fn(er, a, j): return []
    g = pod.build_pod_graph(exec_fn=exec_fn, curate_fn=curate_fn, triage_fn=triage_fn)
    out = g.invoke({"job": HTTPX_JOB, "input_asset": {"name": "x"}, "asset_context": "",
                    "extra": {}, "session_id": "s", "iteration": 0, "project_id": "p"})
    assert out["export"].verdict == "failed"
    assert attempts["n"] >= 2  # retried


def test_pod_real_parser_to_curator_seam():
    """N2: run the REAL compiled graph through the real parser -> curator seam
    (only exec_fn and triage_fn are fakes; curate_fn wraps the real `curate`
    with a captured merge_fn). Locks the real httpx-parser -> Cypher-builder
    path end-to-end, instead of faking curate entirely."""
    captured_cypher = []

    def capture_merge(cypher, params):
        captured_cypher.append(cypher)

    def exec_fn(cmd, sid, t):
        return ExecResult(stdout=FIX_LINE_FULL, stderr="", returncode=0, duration_ms=5)

    def curate_fn(assets, obs, pid):
        return curate(assets, obs, pid, merge_fn=capture_merge)

    def triage_fn(er, assets, job):
        return []

    g = pod.build_pod_graph(exec_fn=exec_fn, curate_fn=curate_fn, triage_fn=triage_fn)
    out = g.invoke({"job": HTTPX_JOB, "input_asset": {"name": "app.example.com"},
                    "asset_context": "", "extra": {}, "session_id": "run-seam",
                    "iteration": 0, "project_id": "proj-seam"})

    assert out["export"].verdict == "success"
    assert out["export"].assets_merged >= 4  # BaseURL + Endpoint + 2 Technology + Certificate

    assert any(":BaseURL" in cy for cy in captured_cypher)
    assert any(":Endpoint" in cy for cy in captured_cypher)
    assert any(":Technology" in cy for cy in captured_cypher)
    assert any(":Certificate" in cy for cy in captured_cypher)


TAKEOVER_JSON = (
    '[{"subdomain":"old.example.com","vulnerable":true,'
    '"service":"aws/s3","cname":"dangling-bucket.s3.amazonaws.com"}]'
)


def test_pod_takeover_findings_reach_curator_even_when_llm_triager_returns_nothing():
    """Findings-parser observations (deterministic, from `parse_findings`) must
    reach the curator even when the LLM triager (triage_fn) returns []."""
    captured = {}

    def exec_fn(cmd, sid, t):
        return ExecResult(stdout=TAKEOVER_JSON, stderr="", returncode=0, duration_ms=2)

    def curate_fn(assets, obs, pid):
        captured["observations"] = obs
        return (len(assets), len(obs))

    def triage_fn(er, assets, job):
        return []

    g = pod.build_pod_graph(exec_fn=exec_fn, curate_fn=curate_fn, triage_fn=triage_fn)
    out = g.invoke({
        "job": JOBS["subdomain_takeover"], "input_asset": {"name": "old.example.com"},
        "asset_context": "", "extra": {}, "session_id": "run-takeover",
        "iteration": 0, "project_id": "proj-takeover",
    })

    assert out["export"].verdict == "success"
    observations = captured["observations"]
    assert len(observations) >= 1
    obs = observations[0]
    assert isinstance(obs, Observation)
    assert obs.macro_kind == "potential_subdomain_takeover"
    assert obs.severity == "high"
    assert obs.anchor == {"type": "Subdomain", "identity": {"name": "old.example.com"}}


GRAPHQL_COP_JSON = (
    '[{"title": "Introspection", "severity": "MEDIUM", "result": true,'
    ' "description": "GraphQL Introspection is enabled"}]'
)


def test_pod_graphql_findings_get_endpoint_anchor_from_input_asset_url_and_reach_curator():
    """SP2 F1: graphql-cop findings have no dedicated 'target url' field in
    their JSON output; the pod must thread the job's target (the input
    asset's URL) into `parse_findings` so the resulting Observation carries
    an Endpoint anchor (and therefore is NOT dropped by
    `finding_to_observation`). This fixture has no `curl_verify` field at
    all, so the old regex-only fallback would yield no anchor - only
    target-url threading makes this pass."""
    captured = {}

    def exec_fn(cmd, sid, t):
        return ExecResult(stdout=GRAPHQL_COP_JSON, stderr="", returncode=0, duration_ms=2)

    def curate_fn(assets, obs, pid):
        captured["observations"] = obs
        return (len(assets), len(obs))

    def triage_fn(er, assets, job):
        return []

    g = pod.build_pod_graph(exec_fn=exec_fn, curate_fn=curate_fn, triage_fn=triage_fn)
    out = g.invoke({
        "job": JOBS["graphql-cop"],
        "input_asset": {"url": "https://api.example.com/graphql"},
        "asset_context": "", "extra": {}, "session_id": "run-graphql",
        "iteration": 0, "project_id": "proj-graphql",
    })

    assert out["export"].verdict == "success"
    observations = captured["observations"]
    assert len(observations) >= 1
    obs = observations[0]
    assert isinstance(obs, Observation)
    assert obs.macro_kind == "Introspection"
    assert obs.anchor == {
        "type": "Endpoint",
        "identity": {
            "path": "/graphql",
            "method": "POST",
            "baseurl": "https://api.example.com",
        },
    }
