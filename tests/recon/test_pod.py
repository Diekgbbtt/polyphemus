from agent.recon.types import JobSpec, ExecResult, Observation
from agent.recon import pod

HTTPX_JOB = JobSpec(tool="httpx", skill="http_probe",
                    command_template="httpx -u {target} -json -silent",
                    produces=["BaseURL", "Endpoint"], consumes="Subdomain")

FIX_LINE = '{"url":"https://app.example.com","input":"app.example.com","status_code":200,"scheme":"https","host":"1.2.3.4","tech":["nginx"]}'

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
