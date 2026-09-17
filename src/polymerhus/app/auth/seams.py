"""The auth capability's agent binding (#220 x #221 x #222).

`auth_capable_binding` is the auth-capable extension of the shared
`skill_agent_binding`: the same L1 index middleware, skill tools, and
invocation context, plus the `auth_store` tool and the per-project `authn`
procedure in the bounded skill set. It follows the established bounding
patterns exactly - a declared, minimal surface attached by its owner through
the native `tools=` / `middleware=` / `context=` seams, never a per-site
reimplementation of either the tool or the skill surface.

Scope rules (operator rulings): the analysis-domain agents never bind
authentication capability; a recon job-specific agent takes the binding when
#223 lands; every other stateful agent (the roster's bound roles) binds it.
Project scope is tool-owned (`config.AUTH_STORE`-independent - the tools read
`config.PROJECT_ID` themselves), so no agent harness threads identity.

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


def auth_capable_binding(role_id: str, *, store=None, skill_store=None):
    """Wrap `skill_agent_binding(role_id)` with the auth capability.

    An exempt role (no bound skill surface) is returned unchanged - it pays
    nothing and gains no authentication capability. A bound role additionally
    carries the `auth_store` tool and `AUTHN_SKILL` in its bounded skill set.
    `store`/`skill_store` are the injectable seams (tests); production resolves
    the project scope tool-owned, so neither the site nor the harness passes an
    identity.
    """
    from polymerhus.app.auth.tool import build_auth_store_tool  # noqa: PLC0415
    from polymerhus.app.llm.skills import skill_agent_binding  # noqa: PLC0415

    binding = skill_agent_binding(role_id, store=skill_store)
    if not binding.tools:
        # An exempt role binds no skill surface: no auth capability either.
        return binding
    context = dict(binding.context)
    context["skills"] = [*context.get("skills", ()), AUTHN_SKILL]
    return replace(
        binding,
        tools=[*binding.tools, build_auth_store_tool(store=store)],
        context=context,
    )


__all__ = ["AUTHN_SKILL", "auth_capable_binding"]
