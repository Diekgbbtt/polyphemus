"""The recon pod's #196 capture wiring.

Before this, the recon exec seam never carried a capture context: every pod ran
its tools with no lease, so nothing the recon phase asked the targets was ever
recorded and nothing could be reproduced later. The plumbing already existed and
was proven on the hunting path; these tests pin the recon caller.

Two invariants matter as much as the happy path: a seam that does NOT declare
`capture_context` (every existing test fake, three positional args) must keep
working untouched, and the pod must declare the capture outcome in its export so
a run can never look fully captured when it was not.
"""
from __future__ import annotations

from polymerhus.recon.domain import pod
from polymerhus.recon.domain.types import ExecResult, JobSpec

HTTPX_JOB = JobSpec(
    tool="httpx",
    skill="http_probe",
    command_template="httpx -u {target} -json -silent",
    produces=["BaseURL", "Endpoint"],
    consumes="Subdomain",
)

FIX_LINE = (
    '{"url":"https://app.example.com","input":"app.example.com","status_code":200,'
    '"scheme":"https","host":"1.2.3.4","tech":["nginx"]}'
)


def _state(**overrides) -> dict:
    state = {
        "job": HTTPX_JOB,
        "input_asset": {"url": "http://172.28.0.20"},
        "asset_context": "",
        "extra": {},
        "session_id": "run-1-0-httpx-ab12cd34",
        "iteration": 0,
        "project_id": "proj1",
        "run_id": "run-1",
    }
    state.update(overrides)
    return state


def _graph(exec_fn):
    def curate_fn(assets, obs, pid):
        return (len(assets), len(obs), assets, obs)

    def triage_fn(exec_result, assets, job):
        return []

    return pod.build_pod_graph(exec_fn=exec_fn, curate_fn=curate_fn, triage_fn=triage_fn)


def test_context_aware_seam_receives_the_pod_capture_context():
    seen = {}

    def exec_fn(command, session_id, timeout_s, capture_context=None):
        seen["context"] = capture_context
        return ExecResult(stdout=FIX_LINE, stderr="", returncode=0, duration_ms=1)

    out = _graph(exec_fn).invoke(_state())

    assert out["export"].verdict == "success"
    context = seen["context"]
    assert context is not None, "the recon pod must request capture"
    assert context.project_id == "proj1"
    assert context.run_id == "run-1"
    assert context.session_id == "run-1-0-httpx-ab12cd34"
    # spec_id is the pod's unit of work: the asset it was dispatched for, so an
    # artifact can be traced back to "what did the pod that worked X ask?".
    assert context.spec_id == "http://172.28.0.20"
    # The MCP call carries these four; session_id rides as its own argument.
    assert context.as_mcp_args() == {
        "project_id": "proj1",
        "run_id": "run-1",
        "spec_id": "http://172.28.0.20",
        "variant_ref": "",
    }


def test_legacy_three_arg_seam_is_called_unchanged():
    calls = []

    def exec_fn(command, session_id, timeout_s):  # the shape every fake uses
        calls.append((command, session_id, timeout_s))
        return ExecResult(stdout=FIX_LINE, stderr="", returncode=0, duration_ms=1)

    out = _graph(exec_fn).invoke(_state())

    assert out["export"].verdict == "success"
    assert len(calls) == 1, calls


def test_a_pod_without_project_identity_does_not_request_capture():
    """Defensive: no project means the lease would be skipped anyway; never send
    a context that pretends otherwise."""
    seen = {}

    def exec_fn(command, session_id, timeout_s, capture_context=None):
        seen["context"] = capture_context
        return ExecResult(stdout=FIX_LINE, stderr="", returncode=0, duration_ms=1)

    _graph(exec_fn).invoke(_state(project_id=""))

    assert seen["context"] is None


def test_capture_can_be_killed_by_config(monkeypatch):
    seen = {"called": False}

    def exec_fn(command, session_id, timeout_s, capture_context=None):
        seen["called"] = True
        seen["context"] = capture_context
        return ExecResult(stdout=FIX_LINE, stderr="", returncode=0, duration_ms=1)

    monkeypatch.setattr(pod, "POD_HTTP_CAPTURE", False)
    _graph(exec_fn).invoke(_state())

    assert seen["called"] is True
    assert seen["context"] is None


def test_export_declares_the_capture_outcome():
    def exec_fn(command, session_id, timeout_s, capture_context=None):
        return ExecResult(
            stdout=FIX_LINE, stderr="", returncode=0, duration_ms=1,
            http_artifact_refs=["http_01EXAMPLEARTIFACT000000"],
            capture_warning=None,
        )

    out = _graph(exec_fn).invoke(_state())

    assert out["export"].stats["capture"] == {
        "sent": True,
        "refs": 1,
        "warning": None,
    }


def test_export_declares_an_uncaptured_exec_without_pretending():
    def exec_fn(command, session_id, timeout_s):
        return ExecResult(stdout=FIX_LINE, stderr="", returncode=0, duration_ms=1)

    out = _graph(exec_fn).invoke(_state())

    assert out["export"].stats["capture"] == {
        "sent": False,
        "refs": 0,
        "warning": None,
    }
