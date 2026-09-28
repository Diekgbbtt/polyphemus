"""The assessment dispatch seam and the eval-close verification phase (#271).

Dispatch is fire-and-forget (D6): the trial never blocks on the assessment
subagent. The eval-close phase checks `verdicts.yaml` presence and schema, re-
dispatches at most twice, then micro-diagnoses: a bounded configuration-layer
re-dispatch (D28) or a named escalation. Every attempt lands in the trial
record, which stays backward-compatible.
"""
from __future__ import annotations

import pytest
import yaml

from orchestrator import assessment, evidence, trial, verdicts
from orchestrator.files import (
    FileStore,
    hunt_configs_dir,
    hunter_test_specs_dir,
    pod_experiment_logs_dir,
    pod_spec_dir,
)

SHA = "eval-sha-1"
FINGERPRINT = "fp-1"


# --- fixtures -----------------------------------------------------------------


def seed_chain(tmp_path, *, project: str = "pid"):
    files = FileStore()
    root = tmp_path / "data"
    files.write_text(
        hunt_configs_dir(root, project, "produced") / "unit_CWE-89_sqli.yaml",
        "id: unit_CWE-89_sqli\n",
    )
    spec_dir = hunter_test_specs_dir(root, project) / "unit_CWE-89_sqli"
    files.write_text(spec_dir / "produced" / "sqli_error.yaml", "id: sqli_error\n")
    files.write_text(pod_experiment_logs_dir(root, project, "sqli_error") / "0.yaml", "o: 0\n")
    files.write_text(pod_spec_dir(root, project, "sqli_error") / "run1.yaml", "v: s\n")
    chain = evidence.resolve_evidence(
        root,
        evidence.EvidenceTarget(
            project_id=project,
            hunt_config="unit_CWE-89_sqli",
            fault_key="unit_CWE-89_sqli",
            spec_id="sqli_error",
            pod_export="run1",
        ),
        files=files,
    )
    return files, root, chain


def valid_payload(chain) -> list[dict]:
    return [
        {
            "vuln_id": "comfyui-004",
            "identified": "identified",
            "confidence": 0.9,
            "matched": {"unit": "viewer", "fault_class": "CWE-22", "symptom": "read"},
            "evidence_chain": chain.to_dict(),
            "eval_sha": SHA,
            "stack_fingerprint": FINGERPRINT,
        }
    ]


def write_trial_record(files, trial_dir, *, project="pid", sha=SHA, fingerprint=FINGERPRINT,
                       assessment_payload=None) -> None:
    payload = {
        "trial_id": "trial-1",
        "instance_id": "arm-a",
        "target_id": "comfyui",
        "project_id": project,
        "start_phase": "recon",
        "terminal": "complete",
        "phases": [],
        "started_at": "2026-09-28T00:00:00+00:00",
        "finished_at": "2026-09-28T01:00:00+00:00",
        "eval_sha": sha,
        "stack_fingerprint": fingerprint,
    }
    if assessment_payload is not None:
        payload["assessment"] = assessment_payload
    files.write_text(trial_dir / "trial.yaml", yaml.safe_dump(payload, sort_keys=False))


def make_request(tmp_path, files, chain, *, trial_record=None):
    root = tmp_path / "data"
    trial_dir = tmp_path / "runs" / "comfyui" / "trial-1"
    if trial_record is None:
        write_trial_record(files, trial_dir)
    gt = tmp_path / "gt" / "comfyui"
    gt.mkdir(parents=True, exist_ok=True)
    return assessment.AssessmentRequest(
        prompt=assessment.ASSESSMENT_PROMPT,
        trial_record=trial_record or (trial_dir / "trial.yaml"),
        ground_truth=gt,
        data_root=root,
        destination=trial_dir / "verdicts.yaml",
    )


class FakeDispatcher:
    def __init__(self, action=None):
        self.requests = []
        self.action = action

    def __call__(self, request):
        self.requests.append(request)
        if self.action is not None:
            self.action(request)


class FakeRepair:
    def __init__(self, supported=("dispatcher_process", "empty_file", "schema_invalid")):
        self.supported = set(supported)
        self.applied = []

    def supports(self, cause: str) -> bool:
        return cause in self.supported

    def apply(self, cause: str) -> None:
        self.applied.append(cause)


# --- the dispatch seam ---------------------------------------------------------


def test_command_dispatcher_formats_each_request_path_into_the_argv(recording_runner) -> None:
    runner = recording_runner()
    argv = (
        "agent",
        "assess",
        "--prompt",
        "{prompt}",
        "--trial",
        "{trial_record}",
        "--gt",
        "{ground_truth}",
        "--data",
        "{data_root}",
        "--out",
        "{destination}",
    )
    request = assessment.AssessmentRequest(
        prompt=assessment.ASSESSMENT_PROMPT,
        trial_record="/runs/trial.yaml",
        ground_truth="/gt/comfyui",
        data_root="/data",
        destination="/runs/verdicts.yaml",
    )

    assessment.CommandDispatcher(runner, argv)(request)

    rendered = runner.argv_texts[0]
    assert "assessment.md" in rendered
    assert "/runs/trial.yaml" in rendered
    assert "/gt/comfyui" in rendered
    assert "/data" in rendered
    assert "/runs/verdicts.yaml" in rendered


def test_command_dispatcher_raises_on_a_nonzero_exit(recording_runner, fake_result) -> None:
    runner = recording_runner(default=fake_result(2, stderr="agent exploded"))
    dispatcher = assessment.CommandDispatcher(runner, ("agent", "{prompt}"))

    with pytest.raises(assessment.AssessmentError, match="agent"):
        dispatcher(
            assessment.AssessmentRequest(
                prompt=assessment.ASSESSMENT_PROMPT,
                trial_record="/r/trial.yaml",
                ground_truth="/gt",
                data_root="/data",
                destination="/r/verdicts.yaml",
            )
        )


def test_dispatch_is_fire_and_forget_and_records_an_attempt(tmp_path) -> None:
    files, _root, chain = seed_chain(tmp_path)
    request = make_request(tmp_path, files, chain)
    dispatcher = FakeDispatcher()

    record = assessment.dispatch(request, dispatcher=dispatcher, now=lambda: "t")

    assert dispatcher.requests == [request]
    assert record.status == "dispatched"
    assert [a.outcome for a in record.attempts] == ["dispatched"]
    # Fire-and-forget: no verdict file is required (and none was written).
    assert not request.destination.exists()


def test_assessment_prompt_is_a_file_and_state_the_write_only_contract() -> None:
    assert assessment.ASSESSMENT_PROMPT.exists()
    text = assessment.ASSESSMENT_PROMPT.read_text(encoding="utf-8")
    assert "verdicts.yaml" in text
    assert "only" in text.lower()
    assert "eval_sha" in text
    assert "stack_fingerprint" in text
    assert "ground truth" in text.lower()


# --- close verification --------------------------------------------------------


def test_close_verify_accepts_a_present_valid_verdict_without_dispatch(tmp_path) -> None:
    files, root, chain = seed_chain(tmp_path)
    request = make_request(tmp_path, files, chain)
    verdicts.write_verdicts(
        request.destination,
        valid_payload(chain),
        files=files,
        data_root=root,
        eval_sha=SHA,
        stack_fingerprint=FINGERPRINT,
    )
    dispatcher = FakeDispatcher()

    record = assessment.verify_trial(
        request,
        dispatcher=dispatcher,
        files=files,
        eval_sha=SHA,
        stack_fingerprint=FINGERPRINT,
    )

    assert record.status == "present"
    assert dispatcher.requests == []
    assert record.verdicts_path == str(request.destination)


def test_close_verify_redispatches_twice_then_escalates(tmp_path) -> None:
    files, _root, chain = seed_chain(tmp_path)
    request = make_request(tmp_path, files, chain)
    dispatcher = FakeDispatcher()  # never produces a verdict

    record = assessment.verify_trial(
        request,
        dispatcher=dispatcher,
        files=files,
        eval_sha=SHA,
        stack_fingerprint=FINGERPRINT,
    )

    assert record.status == "escalated"
    assert record.failure == "assessment_empty_file"
    assert len(dispatcher.requests) == 2
    assert [a.outcome for a in record.attempts] == ["dispatched", "dispatched"]


def test_close_verify_classifies_and_repairs_a_schema_invalid_verdict(tmp_path) -> None:
    files, root, chain = seed_chain(tmp_path)
    request = make_request(tmp_path, files, chain)

    def write_invalid(req):
        files.write_text(req.destination, yaml.safe_dump([{"vuln_id": "x"}]))

    def write_valid(req):
        files.write_text(req.destination, yaml.safe_dump(valid_payload(chain)))

    calls = {"n": 0}

    def action(req):
        calls["n"] += 1
        (write_invalid if calls["n"] <= 2 else write_valid)(req)

    dispatcher = FakeDispatcher(action)
    repair = assessment.ReDispatchRepair(dispatcher, request)

    record = assessment.verify_trial(
        request,
        dispatcher=dispatcher,
        repair=repair,
        files=files,
        eval_sha=SHA,
        stack_fingerprint=FINGERPRINT,
    )

    assert record.status == "present"
    assert "repaired" in [a.outcome for a in record.attempts]
    # Two failed dispatches, then the bounded repair's single re-dispatch.
    assert len(dispatcher.requests) == 3


def test_close_verify_escalates_when_the_bounded_repair_does_not_help(tmp_path) -> None:
    files, _root, chain = seed_chain(tmp_path)
    request = make_request(tmp_path, files, chain)
    dispatcher = FakeDispatcher()
    repair = FakeRepair()

    record = assessment.verify_trial(
        request,
        dispatcher=dispatcher,
        repair=repair,
        files=files,
        eval_sha=SHA,
        stack_fingerprint=FINGERPRINT,
    )

    assert record.status == "escalated"
    assert record.failure == "assessment_empty_file"
    # The bounded repair is applied exactly once, then the escalation is named.
    assert repair.applied == ["empty_file"]
    assert len(dispatcher.requests) == 2


def test_close_verify_repairs_a_dispatcher_process_failure_once(tmp_path) -> None:
    files, _root, chain = seed_chain(tmp_path)
    request = make_request(tmp_path, files, chain)
    calls = {"n": 0}

    def action(req):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise RuntimeError("agent crashed")
        files.write_text(req.destination, yaml.safe_dump(valid_payload(chain)))

    dispatcher = FakeDispatcher(action)
    repair = assessment.ReDispatchRepair(dispatcher, request)

    record = assessment.verify_trial(
        request,
        dispatcher=dispatcher,
        repair=repair,
        files=files,
        eval_sha=SHA,
        stack_fingerprint=FINGERPRINT,
    )

    assert record.status == "present"
    assert record.failure is None
    assert [a.outcome for a in record.attempts][:2] == ["error", "error"]
    assert len(dispatcher.requests) == 3


def test_classify_maps_each_cause_to_its_bounded_repair() -> None:
    assert assessment.classify_failure(verdict_state="missing", error=None).cause == "empty_file"
    assert (
        assessment.classify_failure(verdict_state="invalid", error=None).cause
        == "schema_invalid"
    )
    assert (
        assessment.classify_failure(verdict_state="missing", error=RuntimeError("x")).cause
        == "dispatcher_process"
    )
    unknown = assessment.classify_failure(verdict_state="present", error=None)
    assert unknown.cause == "unknown"
    assert unknown.repair is None


# --- the trial record ----------------------------------------------------------


def test_record_assessment_preserves_the_rest_of_the_trial_record(tmp_path) -> None:
    files = FileStore()
    trial_dir = tmp_path / "runs" / "comfyui" / "trial-1"
    write_trial_record(files, trial_dir)
    record = trial.AssessmentRecord(
        status="escalated",
        attempts=[trial.AssessmentAttempt(1, "dispatched", None, "t")],
        verdicts_path=str(trial_dir / "verdicts.yaml"),
        failure="assessment_empty_file",
    )

    assessment.record_assessment(trial_dir / "trial.yaml", record, files=files)

    payload = yaml.safe_load((trial_dir / "trial.yaml").read_text())
    assert payload["project_id"] == "pid"
    assert payload["eval_sha"] == SHA
    assert payload["assessment"]["status"] == "escalated"
    assert payload["assessment"]["attempts"][0]["outcome"] == "dispatched"
    assert payload["assessment"]["failure"] == "assessment_empty_file"


def test_trial_record_loads_backward_compatibly(tmp_path) -> None:
    files = FileStore()
    trial_dir = tmp_path / "runs" / "comfyui" / "trial-1"
    # An old #270 record: no eval_sha, no stack_fingerprint, no assessment key.
    files.write_text(
        trial_dir / "trial.yaml",
        yaml.safe_dump(
            {
                "trial_id": "old",
                "instance_id": "arm-a",
                "target_id": "comfyui",
                "project_id": "pid",
                "start_phase": "recon",
                "terminal": "complete",
                "phases": [],
                "started_at": "t",
                "finished_at": "t",
            }
        ),
    )

    payload = assessment.load_trial_record(trial_dir / "trial.yaml", files=files)

    assert payload["trial_id"] == "old"
    assert payload.get("eval_sha") is None
    assert payload.get("assessment") is None


def test_load_trial_record_missing_sha_is_an_error_for_verdicts(tmp_path) -> None:
    files = FileStore()
    trial_dir = tmp_path / "runs" / "comfyui" / "trial-1"
    files.write_text(
        trial_dir / "trial.yaml",
        yaml.safe_dump({"trial_id": "old", "project_id": "pid", "target_id": "comfyui"}),
    )

    with pytest.raises(assessment.AssessmentError, match="eval_sha"):
        assessment.trial_identity(trial_dir / "trial.yaml", files=files)
