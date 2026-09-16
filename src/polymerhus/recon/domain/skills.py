"""DEPRECATED re-export shim (ADR A2, 2026-09-11).

The skills-access domain - the loader, the `load_skill` tool, the per-project
skill store, and the `write_skill` tool - moved to `polymerhus.app.llm.skills`,
co-located with the session seam, its primary consumer. Import from there.

This shim is removed after one cycle; no new imports of this path.
"""
from polymerhus.app.llm.skills import (  # noqa: F401
    META_USAGE_SKILL,
    META_WRITE_SKILL,
    PROTOCOL_SEPARATOR,
    SKILL_INDEX_HEADER,
    SKILL_LOAD_CONTRACT,
    WRITE_SKILL_CONTRACT,
    SkillInvalidError,
    SkillStore,
    SkillTargetError,
    StoreUnavailableError,
    build_load_skill_tool,
    build_skill_tools,
    build_write_skill_tool,
    clear_cache,
    list_skills,
    render_skill_index,
    skill_agent_seams,
    skill_for,
    skill_index_middleware,
    skill_meta,
    validate_skill,
)

__all__ = [
    "META_USAGE_SKILL",
    "META_WRITE_SKILL",
    "PROTOCOL_SEPARATOR",
    "SKILL_INDEX_HEADER",
    "SKILL_LOAD_CONTRACT",
    "WRITE_SKILL_CONTRACT",
    "SkillInvalidError",
    "SkillStore",
    "SkillTargetError",
    "StoreUnavailableError",
    "build_load_skill_tool",
    "build_skill_tools",
    "build_write_skill_tool",
    "clear_cache",
    "list_skills",
    "render_skill_index",
    "skill_agent_seams",
    "skill_for",
    "skill_index_middleware",
    "skill_meta",
    "validate_skill",
]
