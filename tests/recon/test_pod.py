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
