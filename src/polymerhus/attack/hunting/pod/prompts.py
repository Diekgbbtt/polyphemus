"""The pod roles' served system prompts (the typed surface).

The `pod_runner` and `pod_triager` base prompts live as plain markdown in the
hunting module's `prompts/` directory and are read directly here (fail-closed,
memoized, no import-time I/O). Each loader appends the shared cortex through the
ONE composition helper, so every hunting agent carries the same map.

The pod's `pod_runner` and `pod_triager` roles are BOUND roles: `load_skill`
and `record_skill_lesson` reach their production seams through the universal
`build_skill_tools` binding, while the base prompts stay in the module's
`prompts/` dir (no SKILL.md mount). The skills read and usage discipline is
delivered by the `meta-usage-skill` protocol appended on every `load_skill`
call, never duplicated in the prompt.
"""
from __future__ import annotations

from pathlib import Path

# The hunting module's single prompts directory (A1), one level above `pod/`.
_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

# Memoized on first call (no import-time I/O, CODING_STANDARD section 6). A
# missing prompt file is a defect: reads FAIL CLOSED (raise), so a pod role never
# reasons without its prompt.
_RUNNER_SKILL: str | None = None
_TRIAGER_SKILL: str | None = None


def load_pod_runner_skill() -> str:
    """The `pod_runner` system prompt, read directly from the module's
    `prompts/` dir and carrying the shared cortex (C1). Memoized on first call;
    FAIL-CLOSED."""
    global _RUNNER_SKILL
    if _RUNNER_SKILL is None:
        from polymerhus.attack.hunting.cortex import with_cortex  # noqa: PLC0415

        _RUNNER_SKILL = with_cortex(
            (_PROMPTS_DIR / "pod-runner.md").read_text(encoding="utf-8")
        )
    return _RUNNER_SKILL


def load_pod_triager_skill() -> str:
    """The `pod_triager` system prompt, read directly from the module's
    `prompts/` dir and carrying the shared cortex (C1). Memoized on first call;
    FAIL-CLOSED."""
    global _TRIAGER_SKILL
    if _TRIAGER_SKILL is None:
        from polymerhus.attack.hunting.cortex import with_cortex  # noqa: PLC0415

        _TRIAGER_SKILL = with_cortex(
            (_PROMPTS_DIR / "pod-triager.md").read_text(encoding="utf-8")
        )
    return _TRIAGER_SKILL
