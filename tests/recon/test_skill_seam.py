"""Unit tier - the shared agent skill seam.

The seam is the one place agent owners collect the skill surface:

- #234: the read-only `load_skill` for every BOUND agent, plus the project-bound
  `write_skill` only for agents whose procedure evolves a skill - so agents that
  execute no evolving procedure keep the read-only surface and the write blast
  radius stays explicit.
- #221: `skill_agent_binding(role_id)` returns that tool surface TOGETHER with
  the L1 index middleware and the invocation context carrying the role's
  bounded skill set (`ROLE_SKILLS`), so the bounded set can never be half-wired
  and the frontmatter description of every skill a role may load is rendered
  into its system message, never hand-written.

Two severities (the D4 split): at runtime an unknown declared name is skipped
fail-open by `render_skill_index`; in repo hygiene a stale or forgotten binding
fails the sweep below.

The roster has three states, and the sweep pins all three:
a role with a bounded set (the surface is bound), a role DECLARED EXEMPT with an
empty tuple (nothing is bound - the analysis proposers are the operator-ruled
example), and an UNDECLARED role (a wiring defect, refused at construction).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain_core.messages import SystemMessage

from polymerhus.app.llm import skills
from polymerhus.app.llm.providers import HUNTING_ROLES, ROLES
from polymerhus.app.llm.skills import (
    ROLE_SKILLS,
    SkillAgentBinding,
    list_skills,
    skill_agent_binding,
    skill_meta,
    skills_for_role,
)

# The roles deliberately given NO skill surface: their turns interact with local
# context (the published L0/L1 substrate, their own prompts, steering signals)
# and never with an external environment, so no catalogue skill bears on them.
# Pinned exactly, so adding or removing an exemption is a deliberate edit here
# and in `ROLE_SKILLS`. `job_orchestrator` is auth-only again: the pipeline owns
# rate mapping, so the gateway loads only the project `authn` skill.
EXEMPT_ROLES = {
    "job_orchestrator",
    "assigner",
    "mechanism_typist",
    "data_modeller",
    "hunting_orchestrator",
}

BOUND_ROLES = {
    "triager": ("webpage-analysis", "webpage-profile"),
    "configurator": ("rate-aware-recon-configuration",),
    "hunting_hunter": ("lightrag-query", "steel-browser"),
    "pod_runner": ("lightrag-query", "steel-browser"),
    "pod_triager": ("lightrag-query",),
}

# The generic bypass procedure remains in the catalogue for explicit future
# workflows, but no baseline role binds it after the gateway is auth-only.
BYPASS_SKILL = "performing-api-rate-limiting-bypass"


class _FakeRequest:
    """The minimum `ModelRequest` surface the index middleware touches: the
    current system prompt, the runtime context, and `override`."""

    def __init__(self, system_prompt: str = "BASE", context=None):
        self.system_prompt = system_prompt
        self.runtime = SimpleNamespace(context=context)
        self.system_message = None

    def override(self, **kwargs):
        self.system_message = kwargs.get("system_message")
        return self


def _render(middleware, *, system_prompt="BASE", context=None) -> str:
    """Drive the middleware's real `wrap_model_call` hook and return the system
    prompt the wrapped handler would see."""
    request = _FakeRequest(system_prompt, context)
    middleware.wrap_model_call(request, lambda req: "unused")
    assert isinstance(request.system_message, SystemMessage)
    return request.system_message.content


# --- the #234 read/write tool surface -----------------------------------------


def test_read_only_agent_gets_load_skill_alone() -> None:
    tools = skills.build_skill_tools()

    assert [t.name for t in tools] == ["load_skill"]


def test_write_capable_agent_gets_load_skill_plus_bound_write_skill(tmp_path) -> None:
    store = skills.SkillStore(root_dir=tmp_path)

    tools = skills.build_skill_tools("proj-1", with_write_skill=True, store=store)

    assert [t.name for t in tools] == ["load_skill", "write_skill"]
    write_tool = tools[1]
    out = write_tool.invoke(
        {
            "skill": "auth_workflow",
            "target": "references/r",
            "content": "# R\n",
        }
    )
    assert out["ok"] is True
    assert (
        tmp_path / "proj-1" / "skills" / "auth_workflow" / "references" / "r.md"
    ).is_file()


def test_write_tool_defaults_to_the_deployment_project(monkeypatch) -> None:
    from polymerhus.app.config import config

    monkeypatch.setattr(config, "PROJECT_ID", "proj-cfg")
    tools = skills.build_skill_tools(with_write_skill=True)
    assert [t.name for t in tools] == ["load_skill", "write_skill"]


# --- the #221 per-role binding ------------------------------------------------


def test_binding_carries_the_roles_bounded_skill_set(monkeypatch) -> None:
    from polymerhus.app.config import config

    monkeypatch.setattr(config, "PROJECT_ID", "proj-cfg")
    binding = skill_agent_binding("pod_runner")

    assert isinstance(binding, SkillAgentBinding)
    assert binding.role_id == "pod_runner"
    assert [t.name for t in binding.tools] == ["load_skill"]
    assert len(binding.middleware) == 1
    # The project scope is tool-owned: unset -> the deployment's single project.
    assert binding.context == {
        "skills": ["lightrag-query", "steel-browser"],
        "project_id": "proj-cfg",
    }
    assert skills_for_role("pod_runner") == ("lightrag-query", "steel-browser")


def test_binding_defaults_to_read_only_and_can_carry_the_write_tool(
    tmp_path, monkeypatch
) -> None:
    from polymerhus.app.config import config

    monkeypatch.setattr(config, "PROJECT_ID", "proj-cfg")
    read_only = skill_agent_binding("pod_runner")
    assert [t.name for t in read_only.tools] == ["load_skill"]
    # Unset project -> the tool-owned deployment default.
    assert read_only.context["project_id"] == "proj-cfg"

    write_capable = skill_agent_binding(
        "pod_runner",
        project_id="proj-1",
        with_write_skill=True,
        store=skills.SkillStore(root_dir=tmp_path),
    )
    assert [t.name for t in write_capable.tools] == ["load_skill", "write_skill"]
    # The bounded set is the role's, independent of the write capability.
    assert write_capable.context["skills"] == read_only.context["skills"]
    # An explicit project overrides the deployment default.
    assert write_capable.context["project_id"] == "proj-1"


def test_an_exempt_role_binds_no_skill_surface_at_all() -> None:
    """An exempt role pays nothing: no tool, no index middleware, no
    context-carried set - not merely an empty render."""
    binding = skill_agent_binding("assigner")

    assert binding.role_id == "assigner"
    assert binding.middleware == []
    assert binding.tools == []
    assert binding.context == {}
    # Composing an exempt binding is safe with no branch at the site.
    assert list(("compaction",)) + binding.middleware == ["compaction"]
    assert list(("exec",)) + binding.tools == ["exec"]


def test_an_undeclared_role_is_refused_as_a_wiring_defect() -> None:
    """The roster is the considered decision for every role: a typo or a new
    role must be declared (bounded or exempt), never silently unbound."""
    for role_id in ("no-such-role", "pod_runnerr", "crawlerx"):
        with pytest.raises(ValueError, match="ROLE_SKILLS"):
            skill_agent_binding(role_id)


def test_the_roster_is_exactly_the_bound_plus_the_exempt_roles() -> None:
    assert {
        role: names for role, names in ROLE_SKILLS.items() if names
    } == BOUND_ROLES
    assert {role for role, names in ROLE_SKILLS.items() if not names} == EXEMPT_ROLES


def test_the_orchestrator_is_exempt_and_the_bypass_procedure_stays_dormant() -> None:
    """The Auth Gateway loads only the project `authn` procedure through the
    write-capable auth binding. The generic bypass skill remains catalogue
    knowledge for explicit future workflows but is bound to no role."""
    assert skills_for_role("job_orchestrator") == ()
    assert BYPASS_SKILL in list_skills()


def test_the_configurator_binds_only_the_rate_aware_configuration_skill() -> None:
    """Phase pod selection is the Configurator's one product discipline."""
    assert skills_for_role("configurator") == ("rate-aware-recon-configuration",)


def test_auth_capable_binding_scopes_the_armed_surface_to_its_explicit_project(
    tmp_path, monkeypatch
) -> None:
    """The auth-only gateway returns to the write-capable exempt branch, whose
    explicit project scope must bind the project-authored `authn` surface and
    `auth_store` to `p2`, never the deployment-wide default."""
    from polymerhus.app.auth.seams import auth_capable_binding
    from polymerhus.app.auth.store import AuthStore
    from polymerhus.app.config import config
    from polymerhus.app.llm.skills import SkillStore

    monkeypatch.setattr(config, "PROJECT_ID", "global-project")
    auth_root = tmp_path / "authroot"
    data_root = tmp_path / "dataroot"

    binding = auth_capable_binding(
        "job_orchestrator", project_id="p2", with_write_skill=True,
        store=AuthStore(auth_root), skill_store=SkillStore(data_root),
    )

    assert binding.context["project_id"] == "p2"
    assert binding.context["skills"] == ["authn"]
    assert [t.name for t in binding.tools] == [
        "load_skill", "write_skill", "auth_store"
    ]

    tools = {t.name: t for t in binding.tools}
    assert tools["auth_store"].invoke(
        {"command": "write", "path": "overview.login_endpoint",
         "value": "https://x/login"}
    )["ok"] is True
    assert (auth_root / "p2" / "auth" / "overview.yaml").is_file()
    assert not (auth_root / "global-project").exists()

    # The project-authored `authn` bundle resolves at p2, not at the deployment
    # project: write both and prove the loaded body is p2's.
    for project_id, body in (("p2", "p2 procedure"), ("global-project", "global procedure")):
        bundle = data_root / project_id / "skills" / "authn" / "SKILL.md"
        bundle.parent.mkdir(parents=True, exist_ok=True)
        bundle.write_text(
            "---\nname: authn\ndescription: authn procedure.\n"
            f"metadata:\n  version: '1.0'\n---\n\n{body}\n",
            encoding="utf-8",
        )
    assert tools["load_skill"].invoke({"name": "authn"}).startswith("p2 procedure")


# --- the L1 index render ------------------------------------------------------


def test_index_renders_each_bound_skills_frontmatter_description_verbatim() -> None:
    binding = skill_agent_binding("pod_runner")

    rendered = _render(binding.middleware[0], context=binding.context)

    assert skills.SKILL_INDEX_HEADER in rendered
    for name in skills_for_role("pod_runner"):
        description = skill_meta(name)["description"]
        assert f"- {name}: {description}" in rendered


def test_index_passes_the_prompt_through_byte_identical_without_a_bound_set() -> None:
    middleware = skill_agent_binding("pod_runner").middleware[0]

    for context in (None, {}, {"skills": []}, {"other": ["x"]}):
        assert _render(middleware, system_prompt="BASE", context=context) == "BASE"


def test_an_unknown_declared_name_is_skipped_fail_open() -> None:
    middleware = skill_agent_binding("pod_runner").middleware[0]

    rendered = _render(
        middleware, context={"skills": ["steel-browser", "no-such-skill"]}
    )

    assert "- steel-browser:" in rendered
    assert "no-such-skill" not in rendered


# --- repo hygiene (the strict half of the D4 split) ---------------------------


def test_every_declared_role_skill_resolves_in_the_catalogue() -> None:
    catalogue = set(list_skills())
    assert catalogue, "the catalogue sweep is vacuous if it is empty"

    stale = {
        role: [name for name in names if name not in catalogue]
        for role, names in ROLE_SKILLS.items()
    }
    assert not {r: n for r, n in stale.items() if n}, (
        f"ROLE_SKILLS names must exist in skills/: {stale}"
    )


def test_every_tool_calling_role_declares_its_skill_set() -> None:
    """A new session-mode role cannot silently miss the roster."""
    tool_calling = {
        r.role_id for r in ROLES + HUNTING_ROLES if r.agent_mode == "session"
    }
    # `crawler` is the one known gap, recorded in `ROLE_SKILLS`: its loop is a
    # manual `bind_tools` ReAct loop, not `create_agent`, so no index middleware
    # renders for it (its delivery is the outstanding work item).
    known_gap = {"crawler"}

    assert tool_calling - known_gap <= set(ROLE_SKILLS)
    assert "crawler" not in ROLE_SKILLS


def test_the_two_meta_skills_are_never_advertised() -> None:
    """The protocol skills load through the read path itself; advertising them
    in an index would invite a pointless load."""
    advertised = {name for names in ROLE_SKILLS.values() for name in names}

    assert skills.META_USAGE_SKILL not in advertised
    assert skills.META_WRITE_SKILL not in advertised
