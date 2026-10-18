"""#236 unit tier - the `load_skill` descriptions command (the listing mode).

The ONE shared `load_skill` tool gains the description-only listing mode: called
with no name it lists the catalogue's skill descriptions, optionally narrowed by
a `pattern` regex. The listing is the same tool's surface (no fork of the load
path), it excludes the meta-family skills and respects the cap, and a
description-only binding refuses a named load loudly - never a body.

The listing is what the hunt-orchestrator's grant is: read all descriptions,
never skill bodies, never lesson writing.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from polymerhus.app.llm import skills
from polymerhus.app.llm.skills import SkillStore


@pytest.fixture(autouse=True)
def _clear_skill_cache():
    skills.clear_cache()
    yield
    skills.clear_cache()


def _skill(root: Path, name: str, description: str) -> None:
    bundle = root / name
    bundle.mkdir(parents=True)
    (bundle / "SKILL.md").write_text(
        f"---\nname: {name.split('/')[-1]}\ndescription: {description}\n"
        "metadata:\n  version: '1.0'\n---\n\n# Body of " + name + "\n",
        encoding="utf-8",
    )


@pytest.fixture
def catalogue(tmp_path, monkeypatch) -> Path:
    root = tmp_path / "cat"
    _skill(root, "alpha", "Alpha does alpha things.")
    _skill(root, "beta", "Beta does beta things.")
    _skill(root, "meta/meta-usage-skill", "The usage protocol.")
    _skill(root, "meta/meta-write-skill", "The authoring discipline.")
    monkeypatch.setattr(skills, "_SKILLS_ROOT", root)
    return root


def test_listing_all_descriptions_sorted_and_meta_excluded(catalogue) -> None:
    out = skills.build_load_skill_tool().invoke({})

    assert skills.SKILL_LIST_HEADER in out
    assert "- alpha: Alpha does alpha things." in out
    assert "- beta: Beta does beta things." in out
    assert "- meta" not in out
    lines = [l for l in out.splitlines() if l.startswith("- ")]
    assert lines == [
        "- alpha: Alpha does alpha things.",
        "- beta: Beta does beta things.",
    ]


def test_listing_filters_by_a_name_pattern(catalogue) -> None:
    out = skills.build_load_skill_tool().invoke({"pattern": "^alpha$"})

    assert "- alpha: Alpha does alpha things." in out
    assert "- beta:" not in out


def test_listing_filters_by_a_description_pattern(catalogue) -> None:
    out = skills.build_load_skill_tool().invoke({"pattern": "beta things"})

    assert "- beta: Beta does beta things." in out
    assert "- alpha:" not in out


def test_a_pattern_matching_nothing_says_so(catalogue) -> None:
    out = skills.build_load_skill_tool().invoke({"pattern": "no-such-discipline"})

    assert "no-such-discipline" in out
    assert "no skill matches" in out


def test_an_invalid_pattern_is_loud_never_a_raise(catalogue) -> None:
    out = skills.build_load_skill_tool().invoke({"pattern": "("})

    assert "invalid pattern" in out
    assert "- alpha:" not in out


def test_the_listing_respects_the_cap_and_states_the_omitted_count(
    tmp_path, monkeypatch
) -> None:
    root = tmp_path / "cat"
    total = skills.MAX_SKILL_LISTING + 3
    for i in range(total):
        _skill(root, f"skill-{i:03d}", f"Discipline {i}.")
    monkeypatch.setattr(skills, "_SKILLS_ROOT", root)

    out = skills.build_load_skill_tool().invoke({})

    listed = [l for l in out.splitlines() if l.startswith("- skill-")]
    assert len(listed) == skills.MAX_SKILL_LISTING
    assert f"- (3 more skills match; narrow with `pattern`)" in out


def test_listing_includes_a_project_bundle(tmp_path, catalogue) -> None:
    store = SkillStore(root_dir=tmp_path / "data")
    bundle = tmp_path / "data" / "proj-1" / "skills" / "authn"
    bundle.mkdir(parents=True)
    (bundle / "SKILL.md").write_text(
        "---\nname: authn\ndescription: Authenticate against this target.\n"
        "metadata:\n  version: '1.0'\n---\n\n# Procedure\n",
        encoding="utf-8",
    )

    out = skills.build_load_skill_tool("proj-1", store=store).invoke({})

    assert "- authn: Authenticate against this target." in out
    # the scaffold-owned reserved directories are never listed
    (tmp_path / "data" / "proj-1" / "skills" / "lessons").mkdir()
    out = skills.build_load_skill_tool("proj-1", store=store).invoke({})
    assert "lessons" not in out


def test_a_description_only_binding_lists_but_refuses_a_named_load(catalogue) -> None:
    tool = skills.build_load_skill_tool(description_only=True)

    listed = tool.invoke({})
    assert "- alpha: Alpha does alpha things." in listed

    refused = tool.invoke({"name": "alpha"})
    assert "description-only" in refused
    assert "# Body of alpha" not in refused


def test_the_default_binding_still_loads_bodies(catalogue) -> None:
    out = skills.build_load_skill_tool().invoke({"name": "alpha"})

    assert out.startswith("# Body of alpha")


def test_both_modes_carry_the_one_contract(catalogue) -> None:
    for tool in (
        skills.build_load_skill_tool(),
        skills.build_load_skill_tool(description_only=True),
    ):
        assert skills.SKILL_LOAD_CONTRACT in tool.description
        assert "LISTING MODE" in tool.description


# --- the description-only BINDING (the hunt-orchestrator's grant) --------------


def test_the_description_only_binding_is_the_exempt_roles_grant() -> None:
    binding = skills.skill_agent_binding(
        "hunting_orchestrator", description_only=True
    )

    assert binding.middleware == []
    assert binding.context == {}
    assert [t.name for t in binding.tools] == ["load_skill"]
    tool = binding.tools[0]
    # the listing works (narrowed here: the live catalogue exceeds the cap)
    assert "- ssrf: " in tool.invoke({"pattern": "^ssrf$"})
    assert "description-only" in tool.invoke({"name": "ssrf"})  # no bodies


def test_the_description_only_binding_is_refused_on_a_bound_role() -> None:
    """Swapping a considered bounded set for the listing would silently drop
    the role's declared discipline: a wiring defect, refused at construction."""
    with pytest.raises(ValueError, match="BOUND role"):
        skills.skill_agent_binding("pod_runner", description_only=True)


def test_the_auth_wrapper_returns_the_description_only_binding_unchanged() -> None:
    """The orchestrator carries no auth capability and no `authn` skill: the
    description-only grant is capability-free."""
    from polymerhus.app.auth.seams import auth_capable_binding

    binding = auth_capable_binding("hunting_orchestrator", description_only=True)

    assert [t.name for t in binding.tools] == ["load_skill"]
    assert binding.context == {}
    assert binding.middleware == []
