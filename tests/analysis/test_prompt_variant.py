"""Unit tier: the analysis prompt-variant selector (T0 of the batched L1-unit-first
change).

The `service_sourced` mode keeps its value but gains a NEW default behaviour behind
`ANALYSIS_PROMPT_VARIANT`: `batched_l1unit_first` (default) loads the
`<base>-batched-l1unit-first.md` file per role, `legacy` the original `<base>.md`.
The selector is read ON CALL (never at import; importing these modules performs no
I/O and reads no env var, CODING_STANDARD section 6) and the role loaders memoize
PER VARIANT, so the system prefix stays byte-identical across a run.

These tests pin the seam, not the prompt content: T1-T3 rewrite the three new
prompt files, so the bats here compare each loader to whatever the selected file
currently holds.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from polymerhus.analysis import prompt_variant
from polymerhus.analysis.prompt_variant import prompt_path, resolve_prompt_variant

_ROLE_BASES = {
    "assigner": "assigner",
    "mechanism_typist": "technical-system",
    "data_modeller": "data-plane",
}


def _prompts_dir() -> Path:
    return Path(prompt_variant.__file__).resolve().parent / "prompts"


def _read(name: str) -> str:
    return (_prompts_dir() / name).read_text(encoding="utf-8")


# --- the selector -----------------------------------------------------------------

def test_default_selects_batched_l1unit_first(monkeypatch):
    """No env var -> the NEW behaviour is the default, and every role resolves to
    its `-batched-l1unit-first.md` file."""
    monkeypatch.delenv("ANALYSIS_PROMPT_VARIANT", raising=False)
    assert resolve_prompt_variant() == "batched_l1unit_first"
    for role, base in _ROLE_BASES.items():
        assert prompt_path(role) == _prompts_dir() / f"{base}-batched-l1unit-first.md"


def test_legacy_selects_the_original_file(monkeypatch):
    """`legacy` is the rollback: each role resolves to the ORIGINAL `<base>.md`."""
    monkeypatch.setenv("ANALYSIS_PROMPT_VARIANT", "legacy")
    assert resolve_prompt_variant() == "legacy"
    for role, base in _ROLE_BASES.items():
        assert prompt_path(role) == _prompts_dir() / f"{base}.md"


def test_unknown_value_warns_and_coerces_to_the_default(monkeypatch, caplog):
    """An unknown value must NOT silently select nothing; it warns with the known
    values and lands on the default, or the deployed behaviour depends on a typo."""
    monkeypatch.setenv("ANALYSIS_PROMPT_VARIANT", "no-such-variant")
    with caplog.at_level(logging.WARNING, logger=prompt_variant.logger.name):
        assert resolve_prompt_variant() == "batched_l1unit_first"
    assert "ANALYSIS_PROMPT_VARIANT" in caplog.text
    assert "batched_l1unit_first" in caplog.text
    assert "legacy" in caplog.text


def test_an_unknown_role_raises():
    """A role_id the map does not know is a programming error, not a silent path."""
    with pytest.raises(KeyError):
        prompt_path("not_a_role")


def test_prompt_path_honours_an_explicit_variant(monkeypatch):
    """The `variant` argument overrides the env read (the loaders resolve once and
    pass it down)."""
    monkeypatch.setenv("ANALYSIS_PROMPT_VARIANT", "legacy")
    assert prompt_path("assigner", "batched_l1unit_first") == (
        _prompts_dir() / "assigner-batched-l1unit-first.md"
    )
    assert prompt_path("data_modeller", "legacy") == _prompts_dir() / "data-plane.md"


# --- the three role loaders -------------------------------------------------------

def test_default_loaders_read_the_batched_file(monkeypatch):
    """With no env var each of the three role loaders returns the batched file's
    bytes verbatim."""
    monkeypatch.delenv("ANALYSIS_PROMPT_VARIANT", raising=False)
    from polymerhus.analysis import assigner, data_modeller, mechanism_typist

    assert assigner._load_assigner_skill() == _read("assigner-batched-l1unit-first.md")
    assert mechanism_typist._load_skill() == _read("technical-system-batched-l1unit-first.md")
    assert data_modeller._load_skill() == _read("data-plane-batched-l1unit-first.md")


def test_legacy_loaders_read_the_original_file(monkeypatch):
    """Under `ANALYSIS_PROMPT_VARIANT=legacy` each loader returns the original file,
    and the memo is PER VARIANT (the default's bytes are not resurrected)."""
    monkeypatch.setenv("ANALYSIS_PROMPT_VARIANT", "legacy")
    from polymerhus.analysis import assigner, data_modeller, mechanism_typist

    assert assigner._load_assigner_skill() == _read("assigner.md")
    assert mechanism_typist._load_skill() == _read("technical-system.md")
    assert data_modeller._load_skill() == _read("data-plane.md")


def test_the_memo_is_per_variant(monkeypatch):
    """The SAME process serves both variants without cross-contamination - the
    per-variant memo is what keeps the prefix byte-stable within a run."""
    from polymerhus.analysis import assigner

    monkeypatch.setenv("ANALYSIS_PROMPT_VARIANT", "legacy")
    legacy = assigner._load_assigner_skill()
    monkeypatch.setenv("ANALYSIS_PROMPT_VARIANT", "batched_l1unit_first")
    batched = assigner._load_assigner_skill()
    assert legacy == _read("assigner.md")
    assert batched == _read("assigner-batched-l1unit-first.md")
    # memoized: a second call under the same variant returns the same object
    assert assigner._load_assigner_skill() is batched


# --- the copied files exist -------------------------------------------------------

def test_the_three_batched_files_exist_and_are_non_empty():
    for base in _ROLE_BASES.values():
        path = _prompts_dir() / f"{base}-batched-l1unit-first.md"
        assert path.is_file(), f"{path} is missing"
        assert path.read_text(encoding="utf-8").strip(), f"{path} is empty"


def test_the_default_assigner_prompt_is_rewritten_not_the_legacy_copy(monkeypatch):
    """T1: the default variant's assigner file is the L1-unit-first rewrite, not a
    verbatim copy of the legacy file. The rewrite carries the harvest/falsify
    discipline the old L0chunk-first text never had, and the legacy file is retained
    verbatim for the rollback."""
    from polymerhus.analysis import assigner

    monkeypatch.delenv("ANALYSIS_PROMPT_VARIANT", raising=False)
    monkeypatch.setattr(assigner, "_ASSIGNER_SKILLS", {})
    batched = assigner._load_assigner_skill()
    legacy = _read("assigner.md")
    assert batched != legacy
    assert "HARVEST" in batched and "FALSIFY" in batched
    assert "Work each Endpoint in four moves" in legacy


def test_the_default_data_modeller_prompt_is_rewritten_not_the_legacy_copy(monkeypatch):
    """T3: the default variant's data-modeller file is the L1-unit-first rewrite, not
    a verbatim copy of the legacy file. The rewrite reasons DOWN from the Service
    unit; the legacy file still opens on a streamed Parameter/Header/Secret slice."""
    from polymerhus.analysis import data_modeller

    monkeypatch.delenv("ANALYSIS_PROMPT_VARIANT", raising=False)
    monkeypatch.setattr(data_modeller, "_DATA_PLANE_SKILLS", {})
    batched = data_modeller._load_skill()
    legacy = _read("data-plane.md")
    assert batched != legacy
    assert "streamed slice of Parameter/Header/Secret" in legacy
    assert "streamed slice of Parameter/Header/Secret" not in batched
    assert "L1 Service unit" in batched
