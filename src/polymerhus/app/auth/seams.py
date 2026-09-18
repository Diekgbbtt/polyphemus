"""The auth capability's agent binding (#220 x #221 x #222).

`auth_capable_binding` is the auth-capable extension of the shared
`skill_agent_binding`: the same L1 index middleware, skill tools, and
invocation context, plus the `auth_store` tool and the per-project `authn`
procedure in the bounded skill set. It follows the established bounding
patterns exactly - a declared, minimal surface attached by its owner through
the native `tools=` / `middleware=` / `context=` seams, never a per-site
reimplementation of either the tool or the skill surface.

Scope rules (operator rulings): the analysis-domain agents never bind
authentication capability; since #223 the recon orchestrator (`job_orchestrator`)
arms the write-capable auth surface (the roster still declares it exempt - no
catalogue skill bears - so the arming rides `with_write_skill`, never the roster,
D223-13); the recon job-specific agents deliberately never take the binding
(D223-5); every other stateful agent (the roster's bound roles) binds the
read-only surface. Project scope is tool-owned (`config.AUTH_STORE`-independent -
the tools read `config.PROJECT_ID` themselves), so no agent harness threads identity.

Import performs no I/O and touches no env (CODING_STANDARD section 6): the
collaborators resolve lazily inside the call.
"""
from __future__ import annotations

from dataclasses import replace

# The per-project authentication-procedure skill (the meta skill
# `meta/authn-skill-writing` authors it). It is project-authored - no canonical
# catalogue copy - so the L1 index renders it only when its bundle exists at
# `<data_root>/<project_id>/skills/authn/SKILL.md`.
AUTHN_SKILL = "authn"


def auth_capable_binding(
    role_id: str, *, store=None, skill_store=None, project_id: str | None = None,
    with_write_skill: bool = False,
):
    """Wrap `skill_agent_binding(role_id)` with the auth capability.

    A bound role additionally carries the `auth_store` tool and `AUTHN_SKILL`
    in its bounded skill set. An exempt role (no bound skill surface) is
    returned unchanged - it pays nothing and gains no authentication
    capability - UNLESS `with_write_skill` is set: that arms the #223 gateway
    surface (`load_skill`, `write_skill`, `auth_store`, the `authn`-only skill
    context), the D223-5 write capability the orchestrator's outer
    skill-judging loop needs. The flag is compositional on bound roles too
    (it appends `write_skill` there); no caller passes it today except the
    gateway. `store`/`skill_store` are the injectable seams (tests);
    `project_id` scopes the armed surface explicitly (default: the tool-owned
    project, resolved lazily), production resolves the project scope
    tool-owned, so neither the site nor the harness passes an identity.
    """
    from polymerhus.app.auth.tool import build_auth_store_tool  # noqa: PLC0415
    from polymerhus.app.llm.skills import (  # noqa: PLC0415
        SkillAgentBinding,
        build_skill_tools,
        build_write_skill_tool,
        skill_agent_binding,
        skill_index_middleware,
    )

    binding = skill_agent_binding(role_id, store=skill_store)
    if not binding.tools:
        if not with_write_skill:
            # An exempt role binds no skill surface: no auth capability either.
            return binding
        # The gateway arming (D223-13): the roster exemption is lifted here,
        # not in ROLE_SKILLS (no catalogue skill bears on this role, so the
        # roster still declares it exempt). Composed from the same skill
        # primitives every bound site uses - never reimplemented per site.
        if project_id is None:
            from polymerhus.app.config import config  # noqa: PLC0415 - lazy, no env at import
            project_id = config.PROJECT_ID
        return SkillAgentBinding(
            role_id=role_id,
            middleware=[skill_index_middleware(store=skill_store)],
            tools=[*build_skill_tools(
                project_id, with_write_skill=True, store=skill_store),
                build_auth_store_tool(project_id=project_id, store=store)],
            context={"skills": [AUTHN_SKILL], "project_id": project_id},
        )
    context = dict(binding.context)
    context["skills"] = [*context.get("skills", ()), AUTHN_SKILL]
    tools = list(binding.tools)
    if with_write_skill:
        tools.append(build_write_skill_tool(context.get("project_id"), store=skill_store))
    return replace(
        binding,
        tools=[*tools, build_auth_store_tool(store=store)],
        context=context,
    )


__all__ = ["AUTHN_SKILL", "auth_capable_binding"]
