"""#234 unit tier - the reading-protocol injection seam.

`meta-usage-skill` is appended to every `load_skill` result by the skill read
path itself (the skills-domain output extension). Tests pin the composed
result with independent literals: the loader-identical body, then the
separator, then the protocol body.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from polymerhus.app.llm import skills
from polymerhus.app.llm.skills import SkillStore

BODY = "# Demo\n"
PROTOCOL = "# Skill usage protocol\nassess and report divergence\n"
SEPARATOR = "\n\n---\n\n"


@pytest.fixture(autouse=True)
def _clear_skill_cache():
    skills.clear_cache()
    yield
    skills.clear_cache()


def _catalogue(root: Path, *, with_protocol: bool = True) -> Path:
    demo = root / "demo"
    demo.mkdir(parents=True)
    (demo / "SKILL.md").write_text(
        "---\nname: demo\ndescription: D.\nmetadata:\n  version: '1'\n---\n\n" + BODY,
        encoding="utf-8",
    )
    if with_protocol:
        proto = root / "meta" / "meta-usage-skill"
        proto.mkdir(parents=True)
        (proto / "SKILL.md").write_text(
            "---\nname: meta-usage-skill\ndescription: P.\nmetadata:\n  version: '1'\n"
            "---\n\n" + PROTOCOL,
            encoding="utf-8",
        )
    return root


def test_load_skill_appends_the_usage_protocol(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path / "cat"))

    out = skills.build_load_skill_tool().invoke({"name": "demo"})

    assert out == BODY + SEPARATOR + PROTOCOL


def test_loading_the_protocol_itself_returns_the_bare_body(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path / "cat"))

    out = skills.build_load_skill_tool().invoke({"name": "meta/meta-usage-skill"})

    assert out == PROTOCOL  # no self-append, no doubling


def test_loading_meta_write_skill_returns_the_bare_body(
    tmp_path: Path, monkeypatch
) -> None:
    root = _catalogue(tmp_path / "cat")
    writer = root / "meta" / "meta-write-skill"
    writer.mkdir(parents=True)
    (writer / "SKILL.md").write_text(
        "---\nname: meta-write-skill\ndescription: W.\nmetadata:\n  version: '1'\n"
        "---\n\n# Write\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(skills, "_SKILLS_ROOT", root)

    out = skills.build_load_skill_tool().invoke({"name": "meta/meta-write-skill"})

    assert out == "# Write\n"  # meta-skills never carry the protocol: no blackloops


def test_missing_protocol_degrades_to_the_bare_body(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        skills, "_SKILLS_ROOT", _catalogue(tmp_path / "cat", with_protocol=False)
    )

    out = skills.build_load_skill_tool().invoke({"name": "demo"})

    assert out == BODY  # fail-open: a missing protocol never breaks a load


def test_unknown_skill_still_fails_open_to_empty(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path / "cat"))

    out = skills.build_load_skill_tool().invoke({"name": "does/not/exist"})

    assert out == ""  # the fail-open empty signal survives the injection


def test_project_bound_load_resolves_bundle_first_then_appends_protocol(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path / "cat"))
    store = SkillStore(root_dir=tmp_path / "data")
    store.write(
        "proj-1",
        "demo",
        "procedure",
        "---\nname: demo\ndescription: D.\nmetadata:\n  version: '1'\n---\n\n# Project\n",
    )

    out = skills.build_load_skill_tool("proj-1", store=store).invoke({"name": "demo"})

    assert out == "# Project\n" + SEPARATOR + PROTOCOL


def test_protocol_read_is_catalogue_pinned_no_project_shadowing(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path / "cat"))
    store = SkillStore(root_dir=tmp_path / "data")

    # The protocol path is nested under `meta/`, and a project bundle addresses
    # one flat path component only, so a project can never even name - let
    # alone shadow - a meta-family skill.
    with pytest.raises(ValueError):
        store.write(
            "proj-1",
            skills.META_USAGE_SKILL,
            "procedure",
            "---\nname: meta-usage-skill\ndescription: S.\nmetadata:\n  version: '1'\n"
            "---\n\n# Shadow\n",
        )

    out = skills.build_load_skill_tool("proj-1", store=store).invoke({"name": "demo"})

    assert out == BODY + SEPARATOR + PROTOCOL  # protocol always catalogue-pinned


def test_is_meta_skill_keys_on_the_meta_directory() -> None:
    assert skills.is_meta_skill("meta/meta-usage-skill")
    assert skills.is_meta_skill("meta/meta-write-skill")
    assert skills.is_meta_skill("meta/authn-skill-writing")
    assert skills.is_meta_skill("meta")
    assert not skills.is_meta_skill("recon/triager/writing-observations")
    assert not skills.is_meta_skill("metaplicity")  # not a path under meta/
