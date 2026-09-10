"""FR-SKILLIF: the single skill loader `skill_for` (L1D-31, ratified door D4).

The recon substrate loads Markdown SKILL.md files as LLM system prompts (the
triager's writing-observations skill, the analyser's service-system-reasoning
skill, and - as the catalogue grows, NM-9 - the system-anatomy skills). Every
loader wants the same three behaviours: read `skills/<name>/SKILL.md`, strip the
YAML frontmatter, cache the result, and DEGRADE to a caller-supplied fallback if
the file is unavailable (a missing mount must never crash the pod). This module
is the one place that does it; `_load_triager_skill` and every per-role skill
loader (the Assigner, the mechanism-typist, the data-modeller, ...) retro-point
here, so hardening the loader hardens every consumer.

#222 makes the single loader agent-reachable: `build_load_skill_tool()` builds
the ONE shared `load_skill` tool, which calls `skill_for` internally, so
bake-time mounts and runtime loads return byte-identical bodies and can never
diverge. Every skill carries a machine-readable data section (`name`,
`description`, `version`, `inputs` frontmatter) that `skill_meta` reads,
`validate_skill` judges, and `list_skills` indexes; runtime loading is bounded
by the phase-gating convention (load at phase entry, once per thread, never
speculatively mid-reasoning - see `skills/README.md` and
`docs/design/skill-runtime-loading-222-decisions.md`).
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Repo-root `skills/` dir. This file is src/polymerhus/recon/domain/skills.py,
# so parents = [domain, recon, polymerhus, src, <repo root>] -> parents[4].
# The skills/ mount lives at the repo root (mounted at /srv/skills in dev, baked
# by the Dockerfile in prod), OUTSIDE the src/ package tree.
_SKILLS_ROOT = Path(__file__).resolve().parents[4] / "skills"

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


def list_skills() -> list[str]:
    """Index the skill catalogue: the sorted loader paths (`'<dir>/...'` under
    `skills/`) of every directory carrying a `SKILL.md`."""
    return sorted(
        str(p.parent.relative_to(_SKILLS_ROOT))
        for p in _SKILLS_ROOT.rglob("SKILL.md")
        if p.is_file()
    )


# The single usage contract, rendered verbatim into the tool description at
# every binding so no agent receives a divergent contract (#222, the #197
# graph_view precedent). Mirrors `skills/README.md` - update both together.
SKILL_LOAD_CONTRACT = (
    "Load a skill by name at runtime: returns the skill body with its YAML "
    "frontmatter stripped - identical semantics to the shared skill_for loader "
    "(cached, fail-open to '' on an unknown skill).\n\n"
    "EVERY skill carries a data section (frontmatter with name, description, "
    "version, inputs) so callers can tell what was loaded.\n\n"
    "PHASE-GATING CONVENTION - load at phase entry, once per thread, never "
    "speculatively mid-reasoning: call load_skill once when your phase starts "
    "for each skill your phase needs, then reason from the returned body. "
    "Repeat loads are cache-cheap but a second load buys nothing new. "
    "`refresh` is the development hot-reload path only - never set it mid-run."
)


def build_load_skill_tool():
    """Build the ONE shared `load_skill` agent-callable tool (#222).

    The tool is the single loader made agent-reachable: it calls `skill_for`
    internally (never a parallel implementation), so bake-time mounts and
    runtime loads can never diverge. `refresh=True` clears the skill cache
    first (the development hot-reload path). Import performs no I/O
    (CODING_STANDARD section 6)."""
    from langchain_core.tools import tool  # noqa: PLC0415

    @tool
    def load_skill(name: str, refresh: bool = False) -> str:
        """Placeholder - the real contract is assigned below (the `@tool`
        decorator reads the docstring at decoration time, so the interpolated
        `SKILL_LOAD_CONTRACT` is set on the returned tool explicitly)."""
        if refresh:
            clear_cache()
        return skill_for(name)

    tool_obj = load_skill
    if hasattr(tool_obj, "description"):
        tool_obj.description = SKILL_LOAD_CONTRACT
    return tool_obj


def skill_meta(name: str) -> dict:
    """Return the skill's data section: the parsed YAML frontmatter mapping at
    `skills/<name>/SKILL.md` (`{}` when the file is missing, has no frontmatter,
    or the frontmatter does not parse to a mapping - never a raise)."""
    import yaml  # noqa: PLC0415 - already a production dependency (hunt_store, ...)

    path = _SKILLS_ROOT / name / "SKILL.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    if not text.startswith("---"):
        return {}
    raw = text.split("---", 2)[1]
    try:
        meta = yaml.safe_load(raw)
    except Exception:  # noqa: BLE001 - unparseable frontmatter degrades to {}
        return {}
    return meta if isinstance(meta, dict) else {}


# The data-section contract (#222): every `skills/**/SKILL.md` carries these
# YAML frontmatter keys. `name`/`description`/`version` are non-empty strings;
# `inputs` is a list (possibly empty) of `{name, description?}` maps declaring
# the invocation context the skill expects. Presence and shape are validated;
# the `name` is deliberately NOT required to equal the loader path - the path
# argument is the index key, the frontmatter name the reported identity.
_REQUIRED_DATA_KEYS = ("name", "description", "version", "inputs")


def validate_skill(name: str) -> list[str]:
    """Judge one skill against the data-section contract. Returns the list of
    violations (`[]` when conforming) - never raises, so a validator can sweep
    the whole catalogue and report every offender."""
    meta = skill_meta(name)
    errors = []
    for key in _REQUIRED_DATA_KEYS:
        if key not in meta:
            errors.append(f"{name}: data section missing required key {key!r}")
    if "name" in meta and not isinstance(meta["name"], str):
        errors.append(f"{name}: data section 'name' must be a string")
    if "description" in meta and not isinstance(meta["description"], str):
        errors.append(f"{name}: data section 'description' must be a string")
    if "version" in meta and (not isinstance(meta["version"], str) or not meta["version"]):
        errors.append(f"{name}: data section 'version' must be a non-empty string")
    if "inputs" in meta:
        inputs = meta["inputs"]
        if not isinstance(inputs, list):
            errors.append(f"{name}: data section 'inputs' must be a list")
        else:
            for item in inputs:
                if isinstance(item, str):
                    continue
                if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                    errors.append(
                        f"{name}: data section 'inputs' items must be "
                        "strings or {name, ...} maps")
                    break
    return errors


__all__ = [
    "SKILL_LOAD_CONTRACT",
    "build_load_skill_tool",
    "clear_cache",
    "list_skills",
    "skill_for",
    "skill_meta",
    "validate_skill",
]
