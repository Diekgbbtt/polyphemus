import re

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
    assert "-H 'Cookie: session=abc'" in cmd
    assert "{" not in cmd  # no residual placeholder, no dict repr


def test_fill_template_auth_header_arjun_uses_headers_flag():
    cmd = pod.fill_template(
        "arjun -u {target} {auth_header}",
        {"name": "app.example.com"},
        {"auth_context": {"cookies": [{"name": "session", "value": "abc"}]}, "_use_auth": True},
        tool="arjun",
    )
    assert "--headers 'Cookie: session=abc'" in cmd


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
    assert "-H 'Cookie: session=abc; csrf=xyz'" in cmd


def test_fill_template_auth_header_arbitrary_headers_httpx():
    # Header-agnostic: Authorization + X-Api-Key emit as their own repeatable
    # -H flags alongside the Cookie header; reserved keys are not emitted.
    cmd = pod.fill_template(
        "httpx -u {target} {auth_header}",
        {"name": "app.example.com"},
        {
            "auth_context": {
                "cookies": [{"name": "session", "value": "abc"}],
                "Authorization": "Bearer eyJx.y.z",
                "X-Api-Key": "k-123",
                "scope": "/app",
            }
        },
        tool="httpx",
    )
    assert "-H 'Cookie: session=abc'" in cmd
    assert "-H 'Authorization: Bearer eyJx.y.z'" in cmd
    assert "-H 'X-Api-Key: k-123'" in cmd
    # reserved structural key is never emitted as a header
    assert "scope" not in cmd


def test_fill_template_auth_header_arbitrary_headers_no_cookies():
    # Authorization alone (no cookies key at all) still emits.
    cmd = pod.fill_template(
        "httpx -u {target} {auth_header}",
        {"name": "app.example.com"},
        {"auth_context": {"Authorization": "Bearer t0ken"}},
        tool="httpx",
    )
    assert "-H 'Authorization: Bearer t0ken'" in cmd
    assert "Cookie" not in cmd


def test_fill_template_auth_header_arjun_joins_headers_with_newline():
    # arjun's --headers takes all headers in one newline-separated argument.
    cmd = pod.fill_template(
        "arjun -u {target} {auth_header}",
        {"name": "app.example.com"},
        {
            "auth_context": {
                "cookies": [{"name": "session", "value": "abc"}],
                "Authorization": "Bearer t0ken",
            }
        },
        tool="arjun",
    )
    assert "--headers 'Cookie: session=abc\nAuthorization: Bearer t0ken'" in cmd


def test_fill_template_applies_auth_header_whenever_auth_context_present():
    # C1 single-owner: fill_template trusts the pipeline's decision. auth_context
    # in extra (which the pipeline only ever sets for a use_auth job) => header.
    cmd = pod.fill_template(
        "httpx -u {target} {auth_header}",
        {"name": "app.example.com"},
        {"auth_context": {"cookies": [{"name": "session", "value": "abc"}]}},
        tool="httpx",
    )
    assert 'Cookie: session=abc' in cmd
    assert "{" not in cmd


def test_fill_template_auth_header_kiterunner_uses_default_h_flag():
    # kiterunner (`kr`) takes repeated -H "k: v" flags, same as httpx/katana/ffuf.
    cmd = pod.fill_template(
        "kr scan {target} -w /opt/localbin/routes-small.kite {auth_header}",
        {"name": "app.example.com"},
        {
            "auth_context": {
                "cookies": [{"name": "session", "value": "abc"}],
                "Authorization": "Bearer t0ken",
            }
        },
        tool="kiterunner",
    )
    assert "-H 'Cookie: session=abc'" in cmd
    assert "-H 'Authorization: Bearer t0ken'" in cmd


def test_fill_template_auth_header_graphql_cop_uses_comma_joined_headers_flag():
    # graphql-cop's --headers flag takes ALL headers as one comma-joined
    # "Key:Value,Key2:Value2" argument (its own CLI format, distinct from both
    # the default repeated -H flag and arjun's newline-joined --headers blob).
    cmd = pod.fill_template(
        "graphql-cop -t {target} -o json {auth_header}",
        {"name": "app.example.com"},
        {
            "auth_context": {
                "cookies": [{"name": "session", "value": "abc"}],
                "Authorization": "Bearer t0ken",
            }
        },
        tool="graphql-cop",
    )
    assert "--headers 'Cookie:session=abc,Authorization:Bearer t0ken'" in cmd


def test_fill_template_auth_header_empty_when_no_auth_context():
    # non-auth job: extra carries no auth_context at all (pipeline never threads
    # it for jobs where job.use_auth is False), so the header is empty.
    cmd = pod.fill_template(
        "subfinder -d {domain} -all -json -silent",
        {"name": "example.com"},
        {},
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
    type (+ session_id, + an auth extra for use_auth jobs) - no `{name}`
    placeholder may survive. Regresses the whole class of "literal
    {placeholder} shipped to the shell" bugs fleet-wide, not just per-tool.

    Matches named `{identifier}` placeholders only, so a legitimate literal
    like arjun's `printf '{}'` empty-JSON seed is not mistaken for an unfilled
    slot - every real placeholder ({target}, {session}, {auth_header}, ...) is
    a lowercase/underscore identifier in braces."""
    placeholder = re.compile(r"\{[a-z_]+\}")
    for name, job in JOBS.items():
        asset = _REPRESENTATIVE_ASSETS[job.consumes]
        extra = {"_use_auth": job.use_auth}
        if job.use_auth:
            extra["auth_context"] = {"cookies": [{"name": "session", "value": "abc"}]}
        cmd = pod.fill_template(
            job.command_template, asset, extra, session_id="sess-guard", tool=job.tool
        )
        residual = placeholder.search(cmd)
        assert residual is None, (
            f"job '{name}' left a residual placeholder {residual.group()!r} in: {cmd!r}"
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


def test_pod_zero_exit_empty_output_is_success_not_failure():
    """A clean exit (returncode 0) with EMPTY stdout is a successful run that
    found nothing (e.g. jsluice on a page with no JS URLs, subfinder with no
    subdomains) - it must reach a "success" export with 0 merges, NOT be
    mislabeled a failure. Regression for the Stream-B real-target loop, where
    jsluice/subfinder legitimately returned empty and were wrongly degraded.
    """
    attempts = {"n": 0}
    def exec_fn(cmd, sid, t):
        attempts["n"] += 1
        return ExecResult(stdout="", stderr="", returncode=0, duration_ms=1)
    def curate_fn(a, o, p): return (len(a), len(o))
    def triage_fn(er, a, j): return []
    g = pod.build_pod_graph(exec_fn=exec_fn, curate_fn=curate_fn, triage_fn=triage_fn)
    out = g.invoke({"job": HTTPX_JOB, "input_asset": {"name": "x"}, "asset_context": "",
                    "extra": {}, "session_id": "s", "iteration": 0, "project_id": "p"})
    assert out["export"].verdict == "success"
    assert out["export"].assets_merged == 0
    assert attempts["n"] == 1  # clean exit, no retry


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


def test_pod_graphql_findings_get_baseurl_anchor_from_input_asset_url_and_reach_curator():
    """SP2 F1: graphql-cop findings have no dedicated 'target url' field in
    their JSON output; the pod must thread the job's target (the input
    asset's URL) into `parse_findings` so the resulting Observation carries
    a BaseURL anchor (and therefore is NOT dropped by
    `finding_to_observation`, nor rejected by curator.ANCHOR_ALLOWLIST, which
    excludes Endpoint). This fixture has no `curl_verify` field at all, so
    the old regex-only fallback would yield no anchor - only target-url
    threading makes this pass."""
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
        "type": "BaseURL",
        "identity": {"url": "https://api.example.com"},
    }


def test_triage_caps_assets_to_avoid_llm_context_overflow(monkeypatch):
    """Regression: a high-volume tool (subfinder on a large org -> tens of
    thousands of Subdomain deltas) must not serialize every asset into the
    triager prompt. Doing so overflowed the model context (~2M tokens > 1M),
    400'd the triager, failed the pod BEFORE the curator, and silently dropped
    every parsed asset (0 nodes persisted). The prompt must be capped to a
    sample + the true total."""
    from agent.recon.types import AssetDelta

    captured = {}

    class FakeStructured:
        def invoke(self, prompt):
            captured["prompt"] = prompt
            return pod._ObservationBatch(observations=[])

    class FakeLLM:
        def with_structured_output(self, schema, method=None):
            return FakeStructured()

    import agent.app.llm.roles as roles
    monkeypatch.setattr(roles, "chat_model_for", lambda role: FakeLLM())

    n = pod._MAX_TRIAGE_ASSETS + 300
    assets = [AssetDelta(type="Subdomain", identity={"name": f"h{i}.x.com"}) for i in range(n)]
    exec_result = ExecResult(stdout="stdout", stderr="", returncode=0, duration_ms=1)

    obs = pod.default_triage_fn(exec_result, assets, JOBS["subfinder"])

    assert obs == []
    # default_triage_fn invokes the model with a message list ([SystemMessage
    # (skill)?, HumanMessage(prompt)]); the asset prompt is the last message.
    p = captured["prompt"][-1].content
    assert f"{n} total" in p                      # true total surfaced
    assert f"showing first {pod._MAX_TRIAGE_ASSETS}" in p
    assert "h0.x.com" in p                         # sample present
    assert f"h{pod._MAX_TRIAGE_ASSETS - 1}.x.com" in p
    assert f"h{pod._MAX_TRIAGE_ASSETS}.x.com" not in p   # capped beyond the sample
    assert f"h{n - 1}.x.com" not in p


def test_batched_jsluice_configurator_builds_batch_command_and_reaches_curator():
    """D17/Q6: for a batched job the configurator builds the command from the
    pod's `batch` list (NOT fill_template), executes it, and the jsluice JSONL
    the batch scanner emits flows through the real parser to the curator."""
    captured = {}

    def exec_fn(cmd, sid, t):
        captured["cmd"] = cmd
        # What scripts/jsluice_scan.py emits: a jsluice `urls` line + an
        # annotated `secrets` line, both anchored on the bundle origin.
        stdout = (
            '{"url":"https://h.example.com/api/hidden","base_url":"https://h.example.com"}\n'
            '{"kind":"aws-access-key","secret":"AKIAABCDEFGHIJKLMNOP","base_url":"https://h.example.com"}\n'
        )
        return ExecResult(stdout=stdout, stderr="", returncode=0, duration_ms=5)

    def triage_fn(er, assets, job):
        return []

    g = pod.build_pod_graph(exec_fn=exec_fn, curate_fn=lambda a, o, p: (len(a), len(o)), triage_fn=triage_fn)
    batch = ["https://h.example.com/static/app.js", "https://h.example.com/static/vendor.js"]
    out = g.invoke({
        "job": JOBS["jsluice"],
        "input_asset": {"batch": batch},
        "asset_context": "", "extra": {}, "session_id": "run-js1",
        "iteration": 0, "project_id": "proj1",
    })
    assert out["export"].verdict == "success"
    # command is the base64-embedded scanner over the batch URLs, not a template
    assert "python3 -" in captured["cmd"]
    assert "app.js" in captured["cmd"] and "vendor.js" in captured["cmd"]
    assert "{target}" not in captured["cmd"]
    # both an Endpoint (from urls) and a Secret (from secrets) were curated
    assert out["export"].assets_merged >= 2


def test_batched_jsluice_parser_emits_endpoint_and_redacted_secret():
    """The parser side already handles the batch scanner's interleaved output:
    a urls line -> Endpoint, a base_url-annotated secrets line -> redacted
    Secret with a HAS_SECRET edge to the bundle's BaseURL."""
    from agent.recon.parsers.jsluice_parser import parse

    stdout = (
        '{"url":"https://h.example.com/api/hidden","base_url":"https://h.example.com"}\n'
        '{"kind":"aws-access-key","secret":"AKIAABCDEFGHIJKLMNOP","base_url":"https://h.example.com"}\n'
    )
    deltas = parse(stdout)
    secrets = [d for d in deltas if d.type == "Secret"]
    endpoints = [d for d in deltas if d.type == "Endpoint"]
    assert len(secrets) == 1 and len(endpoints) == 1
    assert secrets[0].props["redacted"] is True
    assert any(e.rel == "HAS_SECRET" and e.node_identity == {"url": "https://h.example.com"}
               for e in secrets[0].edges)


def test_curator_node_forwards_scope_domain_from_extra():
    """The seed scope domain rides in extra and must reach curate as a kwarg so
    out-of-scope BaseURLs are dropped (D14/curator scope gate)."""
    seen = {}
    def exec_fn(cmd, sid, t): return ExecResult(stdout=FIX_LINE, stderr="", returncode=0, duration_ms=3)
    def curate_fn(assets, obs, pid, scope_domain=None):
        seen["scope_domain"] = scope_domain
        return (len(assets), len(obs))
    def triage_fn(er, assets, job): return []
    g = pod.build_pod_graph(exec_fn=exec_fn, curate_fn=curate_fn, triage_fn=triage_fn)
    g.invoke({"job": HTTPX_JOB, "input_asset": {"name": "app.example.com"},
              "asset_context": "", "extra": {"scope_domain": "example.com"},
              "session_id": "s", "iteration": 0, "project_id": "proj1"})
    assert seen["scope_domain"] == "example.com"


def test_curator_node_omits_scope_domain_when_absent():
    """No scope_domain in extra -> a 3-arg fake curate_fn is called unchanged
    (backward compatibility for the many pod tests that don't set scope)."""
    def exec_fn(cmd, sid, t): return ExecResult(stdout=FIX_LINE, stderr="", returncode=0, duration_ms=3)
    def curate_fn(assets, obs, pid): return (len(assets), len(obs))  # 3-arg, no scope
    def triage_fn(er, assets, job): return []
    g = pod.build_pod_graph(exec_fn=exec_fn, curate_fn=curate_fn, triage_fn=triage_fn)
    out = g.invoke({"job": HTTPX_JOB, "input_asset": {"name": "app.example.com"},
                    "asset_context": "", "extra": {}, "session_id": "s",
                    "iteration": 0, "project_id": "proj1"})
    assert out["export"].verdict == "success"


def test_pod_export_records_executed_command():
    from agent.recon.pod import build_pod_graph
    from agent.recon.types import ExecResult, JobSpec

    def fake_exec(command, session_id, timeout_s):
        return ExecResult(stdout="", stderr="", returncode=0)

    graph = build_pod_graph(
        exec_fn=fake_exec,
        curate_fn=lambda assets, obs, pid, **kw: (0, 0),
        triage_fn=lambda exec_result, assets, job: [],
    )
    job = JobSpec(tool="whois", skill="whois_lookup",
                  command_template="whois {domain}", produces=["Domain"], consumes="Domain")
    state = {"job": job, "input_asset": {"name": "example.com"}, "extra": {},
             "session_id": "s1", "project_id": "p1"}
    export = graph.invoke(state)["export"]
    assert export.stats is not None
    assert export.stats["command"] == "whois example.com"


def test_fill_template_rate_flags_gated_on_rate_profile():
    from agent.recon.pod import fill_template
    tmpl = "ffuf -u {target}/FUZZ -of json {rate_flags}"
    on = fill_template(tmpl, {"url": "https://x"}, {"rate_profile": "throttle"}, tool="ffuf")
    off = fill_template(tmpl, {"url": "https://x"}, {}, tool="ffuf")
    assert "-rate" in on and "{rate_flags}" not in on
    assert off.strip() == "ffuf -u https://x/FUZZ -of json"  # no profile -> today's string
