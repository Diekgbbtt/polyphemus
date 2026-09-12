"""#196: the pod exec surface links D6 observations to HTTP artifacts."""
from __future__ import annotations

from polymerhus.attack.hunting.pod.context import ExperimentLog
from polymerhus.attack.hunting.pod.tools import (
    ExecTool,
    _accepts_capture_context,
    command_signature,
)
from polymerhus.attack.hunting.pod.types import RawObservation
from polymerhus.recon.domain.types import CaptureContext, ExecResult

_OK = "<html>market</html>\n__POD_HTTP_STATUS__:200\n__POD_HTTP_TIME__:0.05"


def test_raw_observation_carries_http_artifact_refs():
    obs = RawObservation()
    assert obs.http_artifact_refs == []
    obs = RawObservation(http_artifact_refs=["http_01J0000000000000000000000A"])
    assert obs.http_artifact_refs == ["http_01J0000000000000000000000A"]


def test_exec_tool_records_artifact_refs_and_keeps_probe_ref():
    async def fake(command, timeout_s):
        return ExecResult(
            stdout=_OK,
            stderr="",
            returncode=0,
            duration_ms=1,
            exec_id="01JEXEC",
            http_artifact_refs=["http_01J0000000000000000000000A"],
        )

    log = ExperimentLog()
    tool = ExecTool(exec_fn=fake, log=log, variant_ref="v0")
    tool.invoke({"command": "curl -k -sS https://t/"})
    obs = log.raw_observations[0]
    assert obs.http_artifact_refs == ["http_01J0000000000000000000000A"]
    # probe_ref remains the variant-scoped command dedup key (#191/D6)
    assert obs.probe_ref == command_signature("v0", "curl -k -sS https://t/")
    assert obs.request["exec_id"] == "01JEXEC"


def test_exec_tool_does_not_copy_artifact_contents():
    async def fake(command, timeout_s):
        return ExecResult(
            stdout=_OK,
            stderr="",
            returncode=0,
            duration_ms=1,
            http_artifact_refs=["http_01J0000000000000000000000A"],
        )

    log = ExperimentLog()
    tool = ExecTool(exec_fn=fake, log=log, variant_ref="v0")
    tool.invoke({"command": "curl -k -sS https://t/"})
    dumped = log.raw_observations[0].model_dump_json()
    # The D6 record links by id only - no artifact record is copied in.
    assert "http_artifact_refs" in dumped
    assert "body_ref" not in dumped
    assert "http-artifact/v1" not in dumped


def test_a_two_arg_exec_fn_still_works():
    def fake(command, timeout_s):
        return ExecResult(returncode=0)

    # A two-arg terminal never receives capture_context, so existing fakes keep
    # working untouched.
    assert _accepts_capture_context(fake) is False


def test_a_capture_aware_seam_is_detected():
    def fake(command, timeout_s, capture_context=None):
        return ExecResult(returncode=0)

    assert _accepts_capture_context(fake) is True


def test_capture_context_is_forwarded_when_the_seam_accepts_it():
    seen = {}

    async def fake(command, timeout_s, capture_context=None):
        seen["ctx"] = capture_context
        return ExecResult(stdout=_OK, stderr="", returncode=0, duration_ms=1)

    tool = ExecTool(
        exec_fn=fake,
        log=ExperimentLog(),
        variant_ref="v0",
        capture_context=CaptureContext(project_id="proj-1", run_id="r1", variant_ref="v0"),
    )
    tool.invoke({"command": "curl -k -sS https://t/"})
    assert seen["ctx"].project_id == "proj-1"
    assert seen["ctx"].run_id == "r1"
