"""#323: the target-front 5xx is an UPSTREAM-AVAILABILITY signal, not a route verdict.

A live comfyui hunt looped on intermittent 502s from the shared target front
(`ph-eval-front`). The 502 is EXPECTED nginx behaviour: the upstream restarts
(a hunter probe hit ComfyUI-Manager's `/api/manager/reboot`, which `os.execv`s
the ComfyUI process), so the front reports a genuinely-unavailable upstream.
The defect is behavioural: the hunter had no single-sourced rule that a 5xx from
the target front means "the target is down/restarting", so it retried and read
502 as route-absence.

This module is the ENV-FREE home of the canonical status rule, exactly like
`conciseness.py` (#292): the `exec` tool description and the hunting role
prompts embed the directive verbatim, and the pod's defence classifier reuses
the shared status set, so `502` can never drift between the tool, the prompts,
and the pod.
"""
from __future__ import annotations

from pathlib import Path

from polymerhus.attack.hunting import hunting_status


def test_target_unavailable_set_is_5xx_server_gateway_statuses():
    """The canonical set names the transient upstream-down 5xx family."""
    assert hunting_status.TARGET_UNAVAILABLE_STATUSES == frozenset({502, 503, 504})


def test_is_target_unavailable_matches_only_that_family():
    for code in (502, 503, 504):
        assert hunting_status.is_target_unavailable(code) is True
    for code in (200, 301, 400, 401, 403, 404, 500, None, "502"):
        assert hunting_status.is_target_unavailable(code) is False


def test_directive_names_the_upstream_unavailable_semantics():
    """The directive states the load-bearing rule: a 5xx from the target front is
    the upstream being down/restarting, NOT the route being absent, and the
    prober must stop rather than loop."""
    d = hunting_status.TARGET_UNAVAILABLE_DIRECTIVE
    assert "502" in d
    assert "upstream" in d
    assert "restart" in d or "down" in d
    assert "loop" in d or "retry" in d


def test_directive_appears_verbatim_in_the_exec_tool_description():
    """Drift guard: the `exec` claim-verification probe carries the rule verbatim
    so the hunter model sees it at the exact tool that produced the 502."""
    from polymerhus.attack.hunting.hunter_tools import ExecTool

    assert hunting_status.TARGET_UNAVAILABLE_DIRECTIVE in ExecTool.model_fields[
        "description"
    ].default


def test_directive_appears_verbatim_in_the_hunter_role_prompt():
    """Drift guard: the hunting-agent role prompt carries the same text, so the
    discipline reaches the reasoning loop and never drifts from the tool."""
    prompts_dir = Path(hunting_status.__file__).resolve().parent / "prompts"
    text = (prompts_dir / "hunting-agent.md").read_text(encoding="utf-8")
    assert hunting_status.TARGET_UNAVAILABLE_DIRECTIVE in text


def test_pod_defence_classifier_reuses_the_shared_status_set():
    """Single-source: the pod's `_defence_signal` classifies the target-front
    5xx family through the shared set, so the pod and the hunter agree."""
    from polymerhus.attack.hunting import hunting_pod

    for code in (502, 503, 504):
        assert hunting_pod._defence_signal(code) == "server-error"
    assert hunting_pod._defence_signal(429) == "rate-limited"
    assert hunting_pod._defence_signal(404) is None
