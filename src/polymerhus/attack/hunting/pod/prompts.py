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
_TRIAGE_SKILL: str | None = None
_DIVERGENCE_SKILL: str | None = None
_TERMINAL_SKILL: str | None = None


def _compose(name: str) -> str:
    """Read one stage prompt and append the shared cortex (C1). The read is
    FAIL-CLOSED: a missing prompt file raises, so a pod role never reasons
    without its prompt.

    With the skill-evolution system disabled, the `record_skill_lesson` line
    is removed: the tool is not bound on that arm, and the prompt must never
    promise a tool the model cannot call."""
    from polymerhus.app.llm.skills import skill_evolution_enabled  # noqa: PLC0415
    from polymerhus.attack.hunting.cortex import with_cortex  # noqa: PLC0415

    text = (_PROMPTS_DIR / name).read_text(encoding="utf-8")
    if not skill_evolution_enabled():
        kept = [
            line for line in text.splitlines()
            if "record_skill_lesson" not in line
        ]
        text = "\n".join(kept)
        if text and not text.endswith("\n"):
            text += "\n"
    return with_cortex(text)


def load_pod_runner_skill() -> str:
    """The `pod_runner` system prompt, read directly from the module's
    `prompts/` dir and carrying the shared cortex (C1). Memoized on first call;
    FAIL-CLOSED."""
    global _RUNNER_SKILL
    if _RUNNER_SKILL is None:
        _RUNNER_SKILL = _compose("pod-runner.md")
    return _RUNNER_SKILL


def load_pod_triager_skill() -> str:
    """The `pod_triager` system prompt (the full bounded variant miner), read
    directly from the module's `prompts/` dir and carrying the shared cortex
    (C1). Memoized on first call; FAIL-CLOSED."""
    global _TRIAGER_SKILL
    if _TRIAGER_SKILL is None:
        _TRIAGER_SKILL = _compose("pod-triager.md")
    return _TRIAGER_SKILL


def load_pod_triage_skill() -> str:
    """Stage A's compact system prompt: failure and symptom confirmation only.
    Memoized; FAIL-CLOSED."""
    global _TRIAGE_SKILL
    if _TRIAGE_SKILL is None:
        _TRIAGE_SKILL = _compose("pod-triage.md")
    return _TRIAGE_SKILL


def load_pod_divergence_skill() -> str:
    """Stage B's compact system prompt: the typed-procedure divergence check.
    Memoized; FAIL-CLOSED."""
    global _DIVERGENCE_SKILL
    if _DIVERGENCE_SKILL is None:
        _DIVERGENCE_SKILL = _compose("pod-divergence.md")
    return _DIVERGENCE_SKILL


def load_pod_terminal_skill() -> str:
    """Stage D's compact system prompt: the terminal verdict when no procedure
    attribute can be bent into a variant. Memoized; FAIL-CLOSED."""
    global _TERMINAL_SKILL
    if _TERMINAL_SKILL is None:
        _TERMINAL_SKILL = _compose("pod-terminal.md")
    return _TERMINAL_SKILL

