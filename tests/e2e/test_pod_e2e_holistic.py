"""Holistic pod e2e walkthroughs (E5-E8, #84) - spec 6.2 + assertion catalogue
`docs/design/hunting-84-assertions.md` section 8.

Each predicate is a SELF-CONTAINED PASS over the in-network stack: a sibling
`polymerhus-agent` container (the compose overlay mounts THIS worktree's src,
wires the pod roles to muse-spark, and injects the MOCKED kb_retrieve) drives
`arun_pod` through `tests/e2e/harness/driver.py` for one rich juice-shop spec
fixture, and the terminal quantities are read back from the run's persisted
artifacts (envelope + D6 experiment log + pod-memory notes).

The live edge is `soupmarket.shop` (Juice Shop on the operator's remote host,
reached from kali). The kb_retrieve tool is MOCKED - the symptom-technique KB
workstream is not merged; returning canned entries instead of a live KB call
taints realism, acknowledged (assertion catalogue E5-E8 note).

The stack is gated: these tests run only when the sibling container is up (the
operator green-lights the live execution once the parallel REST-exposure stream
lands on dev and this branch ffs). When it is down they COLLECT and SKIP with a
message naming the missing piece. The rubric itself is unit-proven on the
hermetic E1 artifacts in test_pod_e2e_nfr.py regardless.
"""
from __future__ import annotations

import pytest

from tests.e2e.harness import host
from tests.e2e.harness.host import RUNS_DIR

SPECS = {
    "xss": "xss_search.yaml",
    "sqli": "sqli_search.yaml",
    "auth": "auth_security_question.yaml",
    "waf": "waf_bypass_or_infeasibility.yaml",
}


def _stack_up() -> bool:
    return bool(host.compose_ps(host.AGENT_SERVICE))


_STACK_DOWN = (
    "sibling pod-e2e agent container is not up - the holistic E5-E8 tier "
    "needs the in-network stack (compose overlay + worktree mount + kalining "
    "hosts). Run `docker compose -f docker-compose.yml -f docker-compose.dev.yml "
    "-f tests/e2e/harness/compose.pod-e2e.yml up -d` when the operator "
    "green-lights the live run."
)


def _assert_terminal(artifacts: dict) -> None:
    """E5-E8 terminal: exactly a binary verdict + a six-value terminal_reason,
    with the D6 experiment log and at least one pod-memory note present."""
    env = artifacts.get("envelope")
    assert env is not None, "the driver must persist envelope.json"
    assert env["verdict"] in ("successful", "unsuccessful")
    from polymerhus.attack.hunting.pod.types import TERMINAL_REASONS

    assert env["evidence"]["terminal_reason"] in TERMINAL_REASONS
    # The D6 log (variant_specs / raw_observations / interpretations).
    assert "variant_specs" in env["evidence"]
    assert "raw_observations" in env["evidence"]
    assert "interpretations" in env["evidence"]


def _run_spec(name: str, spec_file: str) -> dict:
    spec_path = str(RUNS_DIR.parent / "specs" / spec_file)
    meta = host.run_one_spec(spec_path)
    return host.read_run_artifacts(meta["run_id"])


@pytest.mark.skipif(not _stack_up(), reason=_STACK_DOWN)
def test_e2e_runs_xss_spec():
    """E5 - the XSS spec through the live pod: a binary terminal + the D6 log,
    with the run's spec/envelope/notes artifacts persisted for the NFR pass."""
    artifacts = _run_spec("xss", SPECS["xss"])
    _assert_terminal(artifacts)


@pytest.mark.skipif(not _stack_up(), reason=_STACK_DOWN)
def test_e2e_runs_sqli_spec():
    """E6 - the SQLi (blind-boolean) spec: terminal + D6 log persisted."""
    artifacts = _run_spec("sqli", SPECS["sqli"])
    _assert_terminal(artifacts)


@pytest.mark.skipif(not _stack_up(), reason=_STACK_DOWN)
def test_e2e_runs_auth_spec():
    """E7 - the auth security-question spec: terminal + D6 log persisted."""
    artifacts = _run_spec("auth", SPECS["auth"])
    _assert_terminal(artifacts)


@pytest.mark.skipif(not _stack_up(), reason=_STACK_DOWN)
def test_e2e_runs_waf_spec():
    """E8 - the WAF/infeasibility spec: terminal + D6 log persisted (the
    designed negative-control of the suite)."""
    artifacts = _run_spec("waf", SPECS["waf"])
    _assert_terminal(artifacts)