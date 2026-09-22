"""The auth capability's agent binding (#220 x #221 x #222).

`auth_capable_binding` is the auth-capable extension of `skill_agent_binding`:
a bound role additionally carries the `auth_store` tool and the per-project
`authn` procedure in its bounded skill set; an exempt role (no skill surface)
gains nothing. Scope rules: the analysis-domain agents are exempt, so they
never gain authentication capability.
"""
from __future__ import annotations

from polymerhus.app.auth.seams import AUTHN_SKILL, auth_capable_binding


def test_bound_role_carries_the_auth_tool_and_the_authn_skill() -> None:
    binding = auth_capable_binding("pod_runner")

    tool_names = [t.name for t in binding.tools]
    assert "load_skill" in tool_names
    assert "auth_store" in tool_names
    assert AUTHN_SKILL in binding.context["skills"]


def test_analysis_role_gains_no_auth_capability() -> None:
    """The analysis proposers are exempt in the roster: no skill surface, and
    therefore no auth capability either - they never touch the target."""
    binding = auth_capable_binding("assigner")

    assert binding.tools == []
    assert binding.middleware == []
    assert binding.context == {}


def test_exempt_role_gains_no_auth_capability() -> None:
    # configurator is signal-only (exempt); it waits for #223 for its binding.
    binding = auth_capable_binding("configurator")

    assert binding.tools == []
    assert binding.context == {}


def test_orchestrator_arms_the_write_capable_auth_surface() -> None:
    """#223 D223-13: the recon orchestrator's roster exemption is lifted
    through the write-capable binding - `auth_store`, `load_skill`,
    `write_skill`, and the per-project `authn` procedure in the bounded set.
    The catalogue roster still declares it exempt (no catalogue skill bears),
    so the arming rides `with_write_skill`, never the roster."""
    binding = auth_capable_binding(
        "job_orchestrator", project_id="p1", with_write_skill=True)

    tool_names = [t.name for t in binding.tools]
    assert tool_names == ["load_skill", "write_skill", "auth_store"]
    assert binding.context["skills"] == [AUTHN_SKILL]
    assert binding.context["project_id"] == "p1"
    assert len(binding.middleware) == 1  # the L1 index middleware


def test_write_capability_never_leaks_onto_other_roles() -> None:
    """The default binding stays read-only everywhere: a bound role without
    the flag carries exactly `load_skill` + `auth_store` (the hunting
    skill-judging loop is the orchestrator's, D223-11)."""
    binding = auth_capable_binding("pod_runner")

    assert [t.name for t in binding.tools] == ["load_skill", "auth_store"]
