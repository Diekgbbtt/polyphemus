"""Unit tier - the mounted skill catalogue (W4: the nested-taxonomy loader).

The taxonomy and naming spec (`docs/design/skills-taxonomy.md` section 6) is the
contract this file pins, against its ratified rules R1-R4 and R8:

- R1: the suite mounts under the logical root `web-vulnerability-testing/`; the
  root is an identity and never appears in a reported skill name.
- R2/R9: discovery walks level 1 for group parents and level 2 for variants.
- R3: a skill resolves by its flat leaf name alone, whichever group holds it.
- R4: names are globally unique; a duplicate is a loud hard error naming both
  colliding paths, never a silent pick.
- R8: `references/` and `scripts/` stay skill-local, resolved under the leaf
  directory at either level.

The mount is an INDEX over an explicit root (`SkillCatalogue`): the live
catalogue root `skills/` is never repointed, so the default loader's semantics
stay exactly as they are (the meta family's names stay path-shaped). The last
test pins that boundary; the suite tests mount the real `skills-unspurious/`.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from polymerhus.app.llm import skills

# The suite as authored: `<group>/SKILL.md` (level 1) and
# `<group>/<variant>/SKILL.md` (level 2), beside the stream artefact dirs
# (`_analysis/`, `_authoring/`, `_completion/`, `_migration/`) that hold no
# SKILL.md and are not part of the taxonomy.
SUITE_ROOT = Path(__file__).resolve().parents[2] / "skills-unspurious"


@pytest.fixture(autouse=True)
def _clear_skill_cache():
    skills.clear_cache()
    yield
    skills.clear_cache()


@pytest.fixture()
def suite() -> skills.SkillCatalogue:
    """The suite mounted under its logical root, the way a consumer mounts it."""
    return skills.SkillCatalogue(SUITE_ROOT)


def _write_bundle(root: Path, *parts: str) -> Path:
    """Write one conformant SKILL.md-bearing directory (a fixture skill) and
    return its bundle directory."""
    bundle = root.joinpath(*parts)
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / "SKILL.md").write_text(
        f"---\nname: {bundle.name}\ndescription: {bundle.name} does things.\n"
        "metadata:\n  version: 1.0.0\n---\n\n# Fixture\n",
        encoding="utf-8",
    )
    return bundle


# --- R1/R2: the mount, the logical root, and the two levels --------------------


def test_the_suite_mounts_under_its_logical_root(suite) -> None:
    # R1/D-T1: the logical root names the whole catalogue; the mount is an
    # identity, and the suite tree itself is the explicit physical root.
    assert suite.logical_root == "web-vulnerability-testing"
    assert suite.logical_root == skills.LOGICAL_SUITE_ROOT
    assert suite.root == SUITE_ROOT
    assert suite.list_skills()  # a vacuous pass proves nothing


def test_the_logical_root_must_be_one_identity_component(tmp_path) -> None:
    # R1: the root is an identity, never a path.
    with pytest.raises(ValueError, match="logical_root"):
        skills.SkillCatalogue(tmp_path, logical_root="web-vulnerability-testing/")


def test_a_group_parent_and_its_variants_are_both_loadable(suite) -> None:
    # R2/R9: a level-1 directory carrying SKILL.md is the group parent (the
    # umbrella); a level-2 directory carrying SKILL.md is a variant. Both are
    # loadable skills (D-T7: parents stay indexable and loadable).
    parent = suite.read("authentication-jwt")
    variant = suite.read("jwt-claims-confusion")

    assert parent and variant and parent != variant
    # The parent's `## Variants` section links its child leaves (R9).
    assert "jwt-claims-confusion" in parent
    # R10: `graphql` does not decompose and stands as the level-1 skill alone.
    assert suite.read("graphql").startswith("# GraphQL")


# --- R3: the flat leaf is the loader-facing identity ---------------------------


def test_a_variant_resolves_by_its_flat_leaf_in_any_group(suite) -> None:
    # R3/D-T2: the leaf is the loader-facing identity, so a leaf resolves
    # whichever group holds it and no class segment enters the name. The three
    # leaves live under three different groups: `authentication-jwt`, `xss`, and
    # `subdomain-takeover`.
    for name, title in (
        ("jwt-claims-confusion", "# JWT Claims Confusion"),
        ("xss-dom", "# DOM XSS"),
        ("cdn-alternate-domain-binding", "# Cdn Alternate Domain Binding"),
    ):
        assert name in suite.list_skills()
        body = suite.read(name)
        assert not body.startswith("---")  # frontmatter stripped
        assert body.startswith(title)


def test_a_path_shaped_name_never_resolves_against_the_mount(suite) -> None:
    # R3: no class segment and no path appears in a loader name.
    path_shaped = "authentication-jwt/jwt-claims-confusion"

    assert suite.bundle_path(path_shaped) is None
    assert suite.read(path_shaped) == ""  # fail-open, like any unknown name
    assert path_shaped not in suite.list_skills()


def test_reported_names_are_leaves_only_and_complete(suite) -> None:
    names = suite.list_skills()
    assert names == sorted(names)
    # R1/R3: never a path, never the logical root.
    assert all("/" not in name for name in names)
    assert all(suite.logical_root not in name for name in names)
    # Every SKILL.md-bearing directory at level 1 or 2 is reported by the name
    # of its own directory: the mount drops nothing and invents nothing (R2).
    walked = {
        path.parent.name
        for path in SUITE_ROOT.rglob("SKILL.md")
        if len(path.parent.relative_to(SUITE_ROOT).parts) in (1, 2)
    }
    assert set(names) == walked
    assert len(names) == len(walked)  # a duplicate name is never collapsed


def test_the_loader_functions_resolve_through_the_mount(suite) -> None:
    assert skills.list_skills(catalogue=suite) == suite.list_skills()
    assert skills.skill_for("jwt-claims-confusion", catalogue=suite) == suite.read(
        "jwt-claims-confusion"
    )
    meta = skills.skill_meta("jwt-claims-confusion", catalogue=suite)
    assert meta["name"] == "jwt-claims-confusion"


def test_every_reported_suite_skill_carries_the_conformant_data_section(suite) -> None:
    # R3/R8: the frontmatter `name` equals the leaf the mount reports, and the
    # metadata version is uniform; `validate_skill` judges it through the same
    # mount, so a misplaced or non-conforming suite skill fails here.
    names = suite.list_skills()
    bad = {name: skills.validate_skill(name, catalogue=suite) for name in names}
    bad = {name: errors for name, errors in bad.items() if errors}

    assert not bad, f"non-conforming suite skills: {bad}"


# --- R4: global uniqueness, loud on the first duplicate ------------------------


def test_a_duplicate_name_is_a_hard_error_naming_both_collisions(tmp_path) -> None:
    # R4/D-T3: the mount indexes every name and fails on the first duplicate,
    # naming both colliding paths; it never resolves the collision silently.
    first = _write_bundle(tmp_path, "alpha", "shared-leaf")
    second = _write_bundle(tmp_path, "beta", "shared-leaf")

    with pytest.raises(skills.DuplicateSkillNameError) as excinfo:
        skills.SkillCatalogue(tmp_path)

    error = excinfo.value
    assert isinstance(error, ValueError)
    assert error.name == "shared-leaf"
    assert (error.first, error.second) == (first, second)  # first in walk order
    assert str(first) in str(error)
    assert str(second) in str(error)


def test_a_duplicate_across_levels_is_refused_too(tmp_path) -> None:
    # R4: uniqueness spans parents, family entries, and variant leaves alike.
    _write_bundle(tmp_path, "shared")  # a level-1 group parent
    _write_bundle(tmp_path, "group", "shared")  # a level-2 variant

    with pytest.raises(skills.DuplicateSkillNameError) as excinfo:
        skills.SkillCatalogue(tmp_path)

    assert excinfo.value.name == "shared"


def test_a_bundle_outside_the_two_catalogue_levels_is_refused(tmp_path) -> None:
    # R2: every SKILL.md sits at exactly level 1 or level 2 under the
    # catalogue; a deeper bundle would be invisible to the flat-leaf index, so
    # the mount refuses it loudly instead of dropping a skill silently.
    level_zero = tmp_path / "level-zero"
    _write_bundle(level_zero)
    with pytest.raises(skills.SkillLayoutError, match="level-zero"):
        skills.SkillCatalogue(level_zero)

    too_deep = tmp_path / "too-deep"
    _write_bundle(too_deep, "group", "variant", "too-deep")
    with pytest.raises(skills.SkillLayoutError, match="too-deep"):
        skills.SkillCatalogue(too_deep)


def test_a_bundle_named_the_logical_root_is_refused(tmp_path) -> None:
    # R1: no directory under the catalogue carries the logical root's name - a
    # skill named after the root would put the identity into a skill name.
    _write_bundle(tmp_path, skills.LOGICAL_SUITE_ROOT)

    with pytest.raises(skills.SkillLayoutError, match=skills.LOGICAL_SUITE_ROOT):
        skills.SkillCatalogue(tmp_path)


# --- R8: the skill-local bundle ------------------------------------------------


def test_bundles_resolve_inside_their_own_leaf_at_either_level(tmp_path) -> None:
    parent = _write_bundle(tmp_path, "group")
    variant = _write_bundle(tmp_path, "group", "variant")
    (parent / "references").mkdir()
    (parent / "references" / "rules.md").write_text("rules\n", encoding="utf-8")
    (variant / "scripts").mkdir()
    (variant / "scripts" / "probe.py").write_text("print('probe')\n", encoding="utf-8")
    catalogue = skills.SkillCatalogue(tmp_path)

    # R8: `references/` and `scripts/` stay skill-local, at either level.
    assert catalogue.bundle_path("group") == parent
    assert catalogue.bundle_path("group", "references/rules.md") == (
        parent / "references" / "rules.md"
    )
    assert catalogue.bundle_path("variant", "scripts/probe.py") == (
        variant / "scripts" / "probe.py"
    )
    assert catalogue.bundle_path("variant", "scripts/probe.py").is_file()
    # The variant resolves its own leaf, never its parent's directory.
    variant_rules = catalogue.bundle_path("variant", "references/rules.md")
    assert variant_rules == variant / "references" / "rules.md"
    assert variant_rules != parent / "references" / "rules.md"


def test_a_bundle_path_cannot_escape_the_leaf(tmp_path) -> None:
    _write_bundle(tmp_path, "group")
    _write_bundle(tmp_path, "group", "variant")
    catalogue = skills.SkillCatalogue(tmp_path)

    # The separator rule of `validate_path_component` applies here too: a
    # backslash target would traverse the bundle on Windows.
    for hostile in ("../SKILL.md", "../group/SKILL.md", "/etc/passwd", "..\\evil"):
        with pytest.raises(ValueError):
            catalogue.bundle_path("variant", hostile)
    # An unknown skill resolves nothing, whatever the artefact.
    assert catalogue.bundle_path("ghost", "references/rules.md") is None


# --- fail-open mounting and the untouched live root ---------------------------


def test_a_missing_root_mounts_empty_and_degrades(tmp_path) -> None:
    # The loader discipline holds at the mount too: a missing mount is an empty
    # catalogue, never a crash (no I/O at import; reads degrade to the fallback).
    catalogue = skills.SkillCatalogue(tmp_path / "no-such-mount")

    assert catalogue.list_skills() == []
    assert skills.list_skills(catalogue=catalogue) == []
    assert catalogue.read("anything") == ""
    assert catalogue.read("anything", fallback="FALLBACK") == "FALLBACK"
    assert catalogue.meta("anything") == {}
    assert catalogue.bundle_path("anything") is None


def test_mounting_the_suite_never_repoints_the_live_catalogue_root(suite) -> None:
    # The mount is an index over an explicit root: the default loader keeps
    # today's semantics, including the live catalogue's path-shaped meta
    # family, and `skills/` itself is never repointed.
    assert "meta/meta-usage-skill" in skills.list_skills()
    assert skills.skill_for("meta/meta-usage-skill")
    assert skills.LOGICAL_SUITE_ROOT not in skills.list_skills()
    # A name both catalogues carry resolves to each catalogue's OWN bundle: the
    # two mounts never serve each other's body (the cache is per catalogue
    # root), and the suite is reachable only through its mount.
    assert "authentication-jwt" in skills.list_skills()
    assert "authentication-jwt" in suite.list_skills()
    assert skills.skill_for("authentication-jwt") != skills.skill_for(
        "authentication-jwt", catalogue=suite
    )
