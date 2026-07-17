"""FR-SKILLIF unit tier — the generalised skill loader `skill_for` and the two
retro-pointed loaders (_load_triager_skill / _load_analyser_skill).

Each test names the assertion it encodes (docs/design/L1-MVP-plan.md FR-SKILLIF ledger).
"""
import pytest

from agent.recon import skills


@pytest.fixture(autouse=True)
def _clear_skill_cache():
    skills.clear_cache()
    yield
    skills.clear_cache()


# --- AST-SKILLIF-01: loads the SKILL.md body, frontmatter stripped ---

def test_skill_for_loads_and_strips_frontmatter(tmp_path, monkeypatch):
    d = tmp_path / "some" / "skill"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: x\ndescription: y\n---\n\n# Body\nreal content here\n", encoding="utf-8")
    monkeypatch.setattr(skills, "_SKILLS_ROOT", tmp_path)

    out = skills.skill_for("some/skill")
    assert not out.startswith("---")  # frontmatter stripped
    assert out.startswith("# Body")
    assert "real content here" in out


def test_skill_for_no_frontmatter_returns_body_asis(tmp_path, monkeypatch):
    d = tmp_path / "plain"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("no frontmatter here", encoding="utf-8")
    monkeypatch.setattr(skills, "_SKILLS_ROOT", tmp_path)
    assert skills.skill_for("plain") == "no frontmatter here"


# --- AST-SKILLIF-02: caches; clear_cache resets ---

def test_skill_for_caches(tmp_path, monkeypatch):
    d = tmp_path / "cached"
    d.mkdir(parents=True)
    f = d / "SKILL.md"
    f.write_text("v1", encoding="utf-8")
    monkeypatch.setattr(skills, "_SKILLS_ROOT", tmp_path)

    first = skills.skill_for("cached")
    f.write_text("v2", encoding="utf-8")  # change on disk
    second = skills.skill_for("cached")
    assert first is second  # cached: not re-read despite the on-disk change
    assert second == "v1"

    skills.clear_cache()
    assert skills.skill_for("cached") == "v2"  # re-read after clear


# --- AST-SKILLIF-03: fail-open to the provided fallback ---

def test_skill_for_degrades_to_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(skills, "_SKILLS_ROOT", tmp_path)  # empty dir -> file missing
    assert skills.skill_for("does/not/exist") == ""  # default fallback
    skills.clear_cache()
    assert skills.skill_for("does/not/exist", fallback="FALLBACK") == "FALLBACK"


def test_skill_for_never_raises_on_unreadable(monkeypatch):
    import pathlib

    def boom(self, *a, **k):
        raise OSError("mount gone")

    monkeypatch.setattr(pathlib.Path, "read_text", boom)
    # must not raise; degrades to the fallback
    assert skills.skill_for("anything", fallback="fb") == "fb"


# --- AST-SKILLIF-04: triager loader retro-pointed at skill_for ---

def test_triager_loader_retropointed():
    from agent.recon.pod import _load_triager_skill
    skill = _load_triager_skill()
    # the real writing-observations skill (frontmatter stripped); non-empty here
    # because the skills/ mount is present in the repo
    assert isinstance(skill, str)
    assert skill  # the real writing-observations skill is present (mount is in the repo)
    assert not skill.startswith("---")
    # it resolves to the same object skill_for returns for that name (single source)
    assert skill is skills.skill_for("recon/triager/writing-observations")


def test_triager_loader_degrades_to_empty(monkeypatch):
    import pathlib

    def boom(self, *a, **k):
        raise OSError("no mount")

    monkeypatch.setattr(pathlib.Path, "read_text", boom)
    skills.clear_cache()
    from agent.recon.pod import _load_triager_skill
    assert _load_triager_skill() == ""  # triager fallback is '' (no system prompt)


# --- AST-SKILLIF-05: analyser loader retro-pointed with the inline fallback ---

def test_analyser_loader_retropointed():
    from agent.recon.analysis.pod import _load_analyser_skill
    skill = _load_analyser_skill()
    assert skill  # the real analyser skill is present (mount is in the repo)
    assert not skill.startswith("---")
    assert skill is skills.skill_for("analysis/analyser")  # single source


def test_analyser_loader_degrades_to_inline_fallback(monkeypatch):
    import pathlib
    from agent.recon.analysis import pod as analyser_pod

    def boom(self, *a, **k):
        raise OSError("no mount")

    monkeypatch.setattr(pathlib.Path, "read_text", boom)
    skills.clear_cache()
    skill = analyser_pod._load_analyser_skill()
    assert skill == analyser_pod._ANALYSER_SYSTEM_PROMPT  # inline fallback, not ''
