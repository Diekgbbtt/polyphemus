"""#236 unit tier - the `load_skill` descriptions command (the listing mode).

The ONE shared `load_skill` tool gains the listing mode: called with no name it
lists the catalogue's skill descriptions, optionally narrowed by a `pattern`
regex. The listing is the same tool's surface (no fork of the load path), it
excludes the meta-family skills and respects the cap, and a named call still
loads the body - one tool, both moves.

The hunt-orchestrator's grant is this same tool: it lists freely, loads any
body, and writes nothing (no lesson, no skill revision).
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
    assert "- (3 more skills match; narrow with `pattern`)" in out


def test_listing_includes_a_project_bundle(tmp_path, catalogue) -> None:
    store = SkillStore(root_dir=tmp_path / "data")
    bundle = tmp_path / "data" / "target-specific-procedure" / "proj-1" / "authn"
    bundle.mkdir(parents=True)
    (bundle / "SKILL.md").write_text(
        "---\nname: authn\ndescription: Authenticate against this target.\n"
        "metadata:\n  version: '1.0'\n---\n\n# Procedure\n",
        encoding="utf-8",
    )

    out = skills.build_load_skill_tool("proj-1", store=store).invoke({})

    assert "- authn: Authenticate against this target." in out
    # the scaffold-owned reserved directories are never listed
    (tmp_path / "data" / "target-specific-procedure" / "proj-1" / "lessons").mkdir()
    out = skills.build_load_skill_tool("proj-1", store=store).invoke({})
    assert "lessons" not in out


def test_the_default_binding_still_loads_bodies(catalogue) -> None:
    out = skills.build_load_skill_tool().invoke({"name": "alpha"})

    assert out.startswith("# Body of alpha")


def test_the_tool_carries_the_one_contract(catalogue) -> None:
    tool = skills.build_load_skill_tool()
    assert skills.SKILL_LOAD_CONTRACT in tool.description
    assert "LISTING MODE" in tool.description
