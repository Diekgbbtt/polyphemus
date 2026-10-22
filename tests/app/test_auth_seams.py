"""The auth capability's agent binding (#220 x #221 x #222).

`auth_capable_binding` is the auth-capable extension of `skill_agent_binding`:
a bound role additionally carries the `auth_store` tool and the per-project
`authn` procedure in its bounded skill set; an exempt role (no skill surface)
gains nothing unless a flag arms it. Scope rules: the analysis-domain agents
never arm the authenticate/write capability - since #364 they arm the project
`authn` procedure as their whole skill set plus the READ-ONLY auth-store data
view through `with_readonly_auth_store` (D223-5 forbids the write capability,
not the read).
"""
from __future__ import annotations

from polymerhus.app.auth.seams import AUTHN_SKILL, auth_capable_binding
from polymerhus.app.auth.store import AuthStore
from polymerhus.app.auth.tool import AUTH_STORE_READ_CONTRACT
from polymerhus.app.llm.skills import SkillStore

PROJECT = "proj-seam-read-1"


def test_bound_role_carries_the_auth_tool_and_the_authn_skill() -> None:
    binding = auth_capable_binding("pod_runner")

    tool_names = [t.name for t in binding.tools]
    assert "load_skill" in tool_names
    assert "auth_store" in tool_names
    assert AUTHN_SKILL in binding.context["skills"]


def test_analysis_role_gains_no_auth_capability() -> None:
    """The analysis proposers are exempt in the roster, so the PLAIN auth
    binding arms nothing; their surface is the explicit #364 arming
    (`with_readonly_auth_store`), never a roster change."""
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
    `record_skill_lesson`, `write_skill`, and the per-project `authn`
    procedure in the bounded set. The catalogue roster still declares it
    exempt (no catalogue skill bears), so the arming rides
    `with_write_skill`, never the roster."""
    binding = auth_capable_binding(
        "job_orchestrator", project_id="p1", with_write_skill=True)

    tool_names = [t.name for t in binding.tools]
    assert tool_names == [
        "load_skill",
        "record_skill_lesson",
        "write_skill",
        "auth_store",
    ]
    assert binding.context["skills"] == [AUTHN_SKILL]
    assert binding.context["project_id"] == "p1"
    assert len(binding.middleware) == 1  # the L1 index middleware


def test_write_capability_never_leaks_onto_other_roles() -> None:
    """The default binding stays read-only everywhere: a bound role without
    the flag carries exactly the read-only pair `load_skill` +
    `record_skill_lesson` plus `auth_store` (the hunting skill-judging loop
    is the orchestrator's, D223-11)."""
    binding = auth_capable_binding("pod_runner")

    assert [t.name for t in binding.tools] == [
        "load_skill",
        "record_skill_lesson",
        "auth_store",
    ]


# --- #364: the authn-bounded skill surface + the READ-ONLY data view ----------

def test_the_authn_bounding_binds_the_project_procedure_and_the_read_only_view(tmp_path) -> None:
    """#364: the analysis proposers bind the project's `authn` procedure as
    their whole skill set - the L1 index header renderable, `load_skill` and
    `record_skill_lesson` bound, no other skill - plus the READ-ONLY
    auth-store DATA view, a project data context, never a skill."""
    store = AuthStore(tmp_path)
    store.write(PROJECT, "overview.mechanism", "session cookie", origin="operator")

    binding = auth_capable_binding(
        "assigner", store=store, project_id=PROJECT,
        with_readonly_auth_store=True)

    assert [t.name for t in binding.tools] == [
        "load_skill",
        "record_skill_lesson",
        "auth_store",
    ]
    assert len(binding.middleware) == 1, "the L1 index renders the authn header"
    assert binding.context == {"skills": [AUTHN_SKILL], "project_id": PROJECT}
    tool = binding.tools[-1]
    assert tool.description == AUTH_STORE_READ_CONTRACT
    assert set(tool.args) == {"command", "path", "view", "fields"}, (
        "no write field is expressible")
    assert tool.invoke({"command": "read", "path": "overview"})["value"] == {
        "mechanism": "session cookie"}


def test_the_authn_bounding_never_mints_a_write_capability(tmp_path) -> None:
    """D223-5 preserved at the seam: the analysis-domain arming carries no
    `write_skill` and no authenticate capability - a write command refuses
    in-band - and the only bound skill is the project `authn`."""
    binding = auth_capable_binding(
        "mechanism_typist", store=AuthStore(tmp_path), project_id=PROJECT,
        with_readonly_auth_store=True)

    tool = binding.tools[-1]
    out = tool.invoke({"command": "write", "path": "accounts.mallory",
                       "value": {"notes": "nope"}})
    assert out["ok"] is False
    assert out["error"] == "auth_readonly"
    names = {t.name for t in binding.tools}
    assert "write_skill" not in names
    assert binding.context["skills"] == [AUTHN_SKILL]


def test_the_read_only_arming_stays_read_only_on_a_bound_role() -> None:
    """Total flag semantics (D364-5): on a role that DOES carry a skill
    surface, the flag swaps the shared read/write `auth_store` for the
    read-only form, so a later roster change cannot silently re-arm the write
    path on a role that asked for the read view."""
    binding = auth_capable_binding(
        "pod_runner", project_id=PROJECT, with_readonly_auth_store=True)

    assert [t.name for t in binding.tools] == [
        "load_skill", "record_skill_lesson", "auth_store"]
    auth_tool = binding.tools[-1]
    assert set(auth_tool.args) == {"command", "path", "view", "fields"}
    assert auth_tool.description == AUTH_STORE_READ_CONTRACT


def test_the_gateway_arming_is_unchanged_and_still_write_capable() -> None:
    """The two flags meet on the gateway path: `with_write_skill` wins and the
    write-capable surface is exactly what D223-13 arms."""
    binding = auth_capable_binding(
        "job_orchestrator", project_id=PROJECT, with_write_skill=True,
        with_readonly_auth_store=True)

    assert [t.name for t in binding.tools] == [
        "load_skill", "record_skill_lesson", "write_skill", "auth_store"]
    assert set(binding.tools[-1].args) == {
        "command", "path", "value", "view", "fields"}


def test_auth_store_agents_can_list_and_load_the_project_authn_skill(tmp_path) -> None:
    """Every auth-store agent can discover and load the project `authn` skill.

    The canonical project bundle is
    `skills/target-specific-procedure/<project_id>/authn/SKILL.md`. The skill
    store resolves that branch; the data root is not a skill location."""
    skills_root = tmp_path / "skills"
    bundle = skills_root / "target-specific-procedure" / PROJECT / "authn"
    bundle.mkdir(parents=True)
    (bundle / "SKILL.md").write_text(
        "---\nname: authn\ndescription: Project authentication procedure\n---\n"
        "# Project authn\nUse the recorded login envelope.\n",
        encoding="utf-8",
    )
    skill_store = SkillStore(root_dir=skills_root)
    cases = (
        ("hunting_hunter", {}),
        ("pod_runner", {}),
        ("assigner", {"with_readonly_auth_store": True}),
        ("hunting_threat_modeller", {"arm_exempt_surface": True}),
    )
    for role, kwargs in cases:
        binding = auth_capable_binding(
            role, store=AuthStore(tmp_path / "auth"), skill_store=skill_store,
            project_id=PROJECT, **kwargs)
        load = next(t for t in binding.tools if t.name == "load_skill")
        listing = load.invoke({"pattern": "authn"})
        assert "authn" in listing, f"{role} listing: {listing}"
        body = load.invoke({"name": "authn"})
        assert "Project authn" in body, f"{role} body: {body[:200]}"
        assert AUTHN_SKILL in binding.context["skills"]


def test_auth_capable_bindings_use_direct_references_not_the_full_index() -> None:
    """The auth-capable system prompt names the bounded skills and points at
    the `load_skill` listing; it never renders the full description index."""
    from polymerhus.app.llm.skills import render_skill_references

    binding = auth_capable_binding("hunting_hunter", project_id=PROJECT)
    line = render_skill_references(binding.context["skills"])
    assert "SKILLS - direct references" in line
    assert "`authn`" in line
    assert "`lightrag-query`" in line
    assert "Skills available through the `load_skill` tool" not in line
    assert "when to use" not in line.lower()
    assert len(binding.middleware) == 1