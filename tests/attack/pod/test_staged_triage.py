"""Unit tier: the staged triage decision tree.

The pod's triager is staged into four decisions, in order:

1. failure and symptom confirmation (compact, no tools);
2. divergence (typed procedure + executed trail, no tools);
3. bounded variant mining (the full context and tool surface, only when the
   spec carries a populated procedure);
4. terminal verdict (compact, no variant).

These tests drive `arun_pod` with four fake stage callables injected through
`triager_stages`, so the ORDER and the SHORT-CIRCUIT are observed at the pod's
public seam without a live model. The production stage turns are covered
hermetically in `test_react_seams.py`.
"""
from __future__ import annotations

import asyncio

import pytest

from polymerhus.attack.hunting.pod import arun_pod
from polymerhus.attack.hunting.pod.agents import symbolic_runner_step_fn
from polymerhus.attack.hunting.pod.triage import TriageStages
from polymerhus.recon.domain.types import ExecResult

SEMANTIC_SPEC = {
    "target_identity": {"url": "http://soupmarket.shop/",
                        "unit_id": "service:web:soupmarket"},
    "verification_symptoms": ["reflects the injected marker"],
    "assumptions": ["the session cookie is the only auth factor"],
    "rationale": "reflected XSS on the search field",
    "provenance": {"loop_id": "loop-1", "unit_id": "service:web:soupmarket",
                   "canonical_class": "XSS", "web_vulnerability_class": "xss"},
}

PROCEDURE = {
    "recon_action": "crawl the search parameter",
    "bypass_technique": "swap the marker for an event handler",
    "technology_grounding": "the app is a Django template",
    "pro_tips": "compare the reflected encoding",
    "advanced_technique": "chain the stored form",
    "preliminary_chaining": "mint a low-privilege session first",
    "interpretation_pitfalls": "a 404 is not proof the field is absent",
}

PROCEDURE_SPEC = {
    **SEMANTIC_SPEC,
    "provenance": {**SEMANTIC_SPEC["provenance"],
                   "skill_procedure": PROCEDURE},
}

ABSENT = "not found\n__POD_HTTP_STATUS__:404\n__POD_HTTP_TIME__:0.02"


def _exec(command, timeout_s):
    return ExecResult(stdout=ABSENT, stderr="", returncode=0, duration_ms=1)


def _no_trace(_run_id):
    return []


def _run(coro):
    return asyncio.run(coro)


def _assessment(**overrides):
    value = {"runner_failed": False, "symptom_confirmed": False,
             "clean": False, "note": "not confirmed"}
    value.update(overrides)
    return value


def _stages(*, assess, diverge, mine=None, terminal=None, calls=None):
    """Build the four stage callables. `calls` records the stage names in order."""

    def _wrap(name, fn, default):
        def stage(spec, observation, messages, log):
            if calls is not None:
                calls.append(name)
            return fn(spec, observation, messages, log) if fn is not None else default
        return stage

    return TriageStages(
        assess=_wrap("assess", assess, _assessment()),
        diverge=_wrap("diverge", diverge, {"runner_diverged": False, "note": ""}),
        mine=_wrap("mine", mine, {"action": "terminate", "verdict": "unsuccessful",
                                  "terminal_reason": "no-symptom-evidence",
                                  "clean": False, "note": "no variant"}),
        terminal=_wrap("terminal", terminal, {"verdict": "unsuccessful",
                                              "terminal_reason": "no-symptom-evidence",
                                              "clean": False, "note": "no gap"}),
    )


# --- the order and the short-circuits -----------------------------------------

def test_staged_confirmed_short_circuits_to_the_export():
    calls = []
    env = _run(arun_pod(
        SEMANTIC_SPEC, exec_fn=_exec, runner_step_fn=symbolic_runner_step_fn,
        triager_stages=_stages(
            assess=lambda s, o, m, l: _assessment(symptom_confirmed=True, clean=True,
                                                  note="the marker is reflected"),
            diverge=lambda s, o, m, l: pytest.fail("divergence must not run"),
            calls=calls),
        trace_fn=_no_trace))

    assert calls == ["assess"]
    assert env["verdict"] == "successful"
    assert env["evidence"]["terminal_reason"] == "symptom-confirmed"
    assert env["evidence"]["clean"] is True
    assert env["evidence"]["iterations"] == 1
    assert env["evidence"]["interpretations"][0]["note"] == "the marker is reflected"


def test_staged_runner_failure_mints_the_recovery_basis():
    calls = []
    laps = {"n": 0}

    def assess(spec, observation, messages, log):
        laps["n"] += 1
        if laps["n"] == 1:
            return _assessment(runner_failed=True, note="the runner execution failed")
        return _assessment(symptom_confirmed=True, clean=True, note="recovered")

    env = _run(arun_pod(
        SEMANTIC_SPEC, exec_fn=_exec, runner_step_fn=symbolic_runner_step_fn,
        triager_stages=_stages(
            assess=assess,
            diverge=lambda s, o, m, l: pytest.fail("divergence must not run"),
            calls=calls),
        trace_fn=_no_trace))

    assert calls[:1] == ["assess"]
    variants = env["evidence"]["variant_specs"]
    assert [v["ref"] for v in variants] == ["v0", "v1"]
    assert variants[1]["declined_attribute"] == "runner-failure"
    assert env["verdict"] == "successful"


def test_staged_divergence_mints_the_recovery_basis():
    calls = []
    laps = {"n": 0}

    def assess(spec, observation, messages, log):
        laps["n"] += 1
        if laps["n"] == 1:
            return _assessment(note="the marker is not reflected")
        return _assessment(symptom_confirmed=True, clean=True, note="recovered")

    def diverge(spec, observation, messages, log):
        return {"runner_diverged": True, "note": "the runner ignored the typed procedure"}

    env = _run(arun_pod(
        SEMANTIC_SPEC, exec_fn=_exec, runner_step_fn=symbolic_runner_step_fn,
        triager_stages=_stages(assess=assess, diverge=diverge, calls=calls),
        trace_fn=_no_trace))

    assert calls[:2] == ["assess", "diverge"]
    variants = env["evidence"]["variant_specs"]
    assert [v["ref"] for v in variants] == ["v0", "v1"]
    assert variants[1]["declined_attribute"] == "runner-divergence"
    assert env["verdict"] == "successful"


def test_staged_populated_procedure_calls_the_miner():
    calls = []
    laps = {"n": 0}

    def assess(spec, observation, messages, log):
        laps["n"] += 1
        if laps["n"] == 1:
            return _assessment(note="the marker is not reflected")
        return _assessment(symptom_confirmed=True, clean=True, note="recovered")

    def mine(spec, observation, messages, log):
        return {"classification": "symptom-absent", "action": "variant",
                "declined_attribute": "technology-grounding",
                "covered_gap_classes": ["recon-action", "bypass-technique"],
                "variant_spec": {**spec, "rationale": "ground the template stack"},
                "feedback": "ground the stack"}

    env = _run(arun_pod(
        PROCEDURE_SPEC, exec_fn=_exec, runner_step_fn=symbolic_runner_step_fn,
        triager_stages=_stages(
            assess=assess,
            diverge=lambda s, o, m, l: {"runner_diverged": False, "note": ""},
            mine=mine, calls=calls),
        trace_fn=_no_trace))

    assert calls[:3] == ["assess", "diverge", "mine"]
    variants = env["evidence"]["variant_specs"]
    assert [v["ref"] for v in variants] == ["v0", "v1"]
    assert variants[1]["declined_attribute"] == "technology-grounding"
    assert env["verdict"] == "successful"


def test_staged_no_populated_procedure_calls_the_terminal_not_the_miner():
    calls = []
    env = _run(arun_pod(
        SEMANTIC_SPEC, exec_fn=_exec, runner_step_fn=symbolic_runner_step_fn,
        triager_stages=_stages(
            assess=lambda s, o, m, l: _assessment(note="the marker is not reflected"),
            diverge=lambda s, o, m, l: {"runner_diverged": False, "note": ""},
            mine=lambda s, o, m, l: pytest.fail("the miner must not run without a procedure"),
            terminal=lambda s, o, m, l: {"verdict": "unsuccessful",
                                         "terminal_reason": "space-exhausted",
                                         "clean": True, "note": "no populated gap"},
            calls=calls),
        trace_fn=_no_trace))

    assert calls == ["assess", "diverge", "terminal"]
    assert env["verdict"] == "unsuccessful"
    assert env["evidence"]["terminal_reason"] == "space-exhausted"
    assert env["evidence"]["clean"] is True
    assert env["evidence"]["iterations"] == 1


def test_staged_all_empty_procedure_calls_the_terminal_not_the_miner():
    """An excerpt with every field empty is a skipped procedure, not a gap: the
    miner is not paid and the compact terminal decides."""
    from polymerhus.attack.hunting.pod.variant_basis import PROCEDURE_GAP_FIELD

    empty = {field: "" for field in PROCEDURE_GAP_FIELD.values()}
    spec = {**SEMANTIC_SPEC, "provenance": {
        **SEMANTIC_SPEC["provenance"], "skill_procedure": empty}}
    calls = []
    env = _run(arun_pod(
        spec, exec_fn=_exec, runner_step_fn=symbolic_runner_step_fn,
        triager_stages=_stages(
            assess=lambda s, o, m, l: _assessment(note="the marker is not reflected"),
            diverge=lambda s, o, m, l: {"runner_diverged": False, "note": ""},
            mine=lambda s, o, m, l: pytest.fail("the miner must not run on an empty procedure"),
            terminal=lambda s, o, m, l: {"verdict": "unsuccessful",
                                         "terminal_reason": "no-symptom-evidence",
                                         "clean": False, "note": "no populated gap"},
            calls=calls),
        trace_fn=_no_trace))

    assert calls == ["assess", "diverge", "terminal"]
    assert env["evidence"]["terminal_reason"] == "no-symptom-evidence"


def test_staged_duplicate_basis_still_degrades_honestly():
    calls = []
    laps = {"n": 0}

    def assess(spec, observation, messages, log):
        return _assessment(note="the marker is not reflected")

    def mine(spec, observation, messages, log):
        laps["n"] += 1
        return {"classification": "symptom-absent", "action": "variant",
                "declined_attribute": "technology-grounding",
                "covered_gap_classes": ["recon-action", "bypass-technique"],
                "variant_spec": {**spec, "rationale": "ground the template stack"},
                "feedback": "ground the stack"}

    env = _run(arun_pod(
        PROCEDURE_SPEC, exec_fn=_exec, runner_step_fn=symbolic_runner_step_fn,
        triager_stages=_stages(
            assess=assess,
            diverge=lambda s, o, m, l: {"runner_diverged": False, "note": ""},
            mine=mine, calls=calls),
        trace_fn=_no_trace))

    assert laps["n"] >= 2
    variants = env["evidence"]["variant_specs"]
    assert [v["ref"] for v in variants] == ["v0", "v1"]
    assert env["verdict"] == "unsuccessful"
    assert env["evidence"]["terminal_reason"] == "no-symptom-evidence"
    assert env["evidence"]["clean"] is False
    assert any("duplicate" in i["note"].lower()
               for i in env["evidence"]["interpretations"])


def test_staged_stage_failure_degrades_to_a_safe_terminal():
    def assess(spec, observation, messages, log):
        raise RuntimeError("stage exploded")

    env = _run(arun_pod(
        SEMANTIC_SPEC, exec_fn=_exec, runner_step_fn=symbolic_runner_step_fn,
        triager_stages=_stages(
            assess=assess,
            diverge=lambda s, o, m, l: pytest.fail("must not run"),
            calls=None),
        trace_fn=_no_trace))

    assert env["verdict"] == "unsuccessful"
    assert env["evidence"]["terminal_reason"] == "no-symptom-evidence"
    assert any("degraded" in i["note"].lower()
               for i in env["evidence"]["interpretations"])


def test_staged_provider_failure_propagates():
    """A provider failure is infrastructure, never a domain verdict - the staged
    orchestrator re-raises the typed error through `arun_pod`."""
    from polymerhus.app.llm.provider_failure import ProviderUnavailableError

    def assess(spec, observation, messages, log):
        raise ProviderUnavailableError("quota exhausted", status_code=429,
                                       quota_exhausted=True)

    with pytest.raises(ProviderUnavailableError):
        _run(arun_pod(
            SEMANTIC_SPEC, exec_fn=_exec, runner_step_fn=symbolic_runner_step_fn,
            triager_stages=_stages(
                assess=assess,
                diverge=lambda s, o, m, l: pytest.fail("must not run")),
            trace_fn=_no_trace))


# --- the first-call occupancy proof -------------------------------------------

def test_stage_a_receives_the_compact_delta_and_stage_c_the_full_delta():
    """The graph hands Stage A the compact delta (no procedure, no variants, no
    probe trail, no memory key-list); the orchestrator hands the miner the full
    triager delta. The compact delta is strictly smaller - the structural half
    of the first-call token claim."""
    seen = {}

    def assess(spec, observation, messages, log):
        seen["compact"] = messages[0]["content"]
        return _assessment(note="the marker is not reflected")

    def diverge(spec, observation, messages, log):
        return {"runner_diverged": False, "note": "the procedure was followed"}

    def mine(spec, observation, messages, log):
        seen["full"] = messages[0]["content"]
        return {"classification": "symptom-absent", "action": "terminate",
                "verdict": "unsuccessful",
                "terminal_reason": "no-symptom-evidence", "clean": False,
                "note": "no further variant"}

    env = _run(arun_pod(
        PROCEDURE_SPEC, exec_fn=_exec, runner_step_fn=symbolic_runner_step_fn,
        triager_stages=_stages(assess=assess, diverge=diverge, mine=mine),
        trace_fn=_no_trace))

    compact, full = seen["compact"], seen["full"]
    assert "## Verification symptoms" in compact
    assert "## Target identity" in compact
    assert "## Latest observation" in compact
    assert "## Skill procedure" not in compact
    assert "## Variants already tried" not in compact
    assert "## Probes executed" not in compact
    assert "Pod experiment memory" not in compact
    assert "## Skill procedure" in full
    assert "## Variants already tried" in full
    assert "## Probes executed" in full
    assert "Pod experiment memory" in full
    assert len(compact) < len(full)
    assert env["evidence"]["terminal_reason"] == "no-symptom-evidence"
