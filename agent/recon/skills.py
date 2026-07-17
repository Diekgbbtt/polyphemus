"""FR-SKILLIF: the single skill loader `skill_for` (L1D-31, ratified door D4).

The recon substrate loads Markdown SKILL.md files as LLM system prompts (the
triager's writing-observations skill, the analyser's service-system-reasoning
skill, and - as the catalogue grows, NM-9 - the system-anatomy skills). Every
loader wants the same three behaviours: read `skills/<name>/SKILL.md`, strip the
YAML frontmatter, cache the result, and DEGRADE to a caller-supplied fallback if
the file is unavailable (a missing mount must never crash the pod). This module
is the one place that does it; `_load_triager_skill` / `_load_analyser_skill`
retro-point here, so hardening the loader hardens every consumer.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Repo-root `skills/` dir: agent/recon/skills.py -> parents[2] is the repo root
# (mounted at /srv/skills in dev, baked by the Dockerfile in prod). Mirrors the
# path the two original loaders computed.
_SKILLS_ROOT = Path(__file__).resolve().parents[2] / "skills"

_CACHE: dict[str, str] = {}


def skill_for(name: str, *, fallback: str = "") -> str:
    """Return the skill body at `skills/<name>/SKILL.md`, YAML frontmatter
    stripped and cached. `name` is a path under `skills/` using '/' separators
    (e.g. 'recon/triager/writing-observations', 'analysis/analyser'). On a missing
    or unreadable file, degrade to `fallback` (default '') and cache that, so a
    missing mount degrades gracefully instead of crashing the caller."""
    if name in _CACHE:
        return _CACHE[name]
    path = _SKILLS_ROOT / name / "SKILL.md"
    try:
        text = path.read_text(encoding="utf-8")
        if text.startswith("---"):
            text = text.split("---", 2)[-1].lstrip()  # drop YAML frontmatter
    except OSError:
        logger.warning("skill_for: skill not found at %s; using fallback", path)
        text = fallback
    _CACHE[name] = text
    return text


def clear_cache() -> None:
    """Drop the skill cache (test/hot-reload seam)."""
    _CACHE.clear()
