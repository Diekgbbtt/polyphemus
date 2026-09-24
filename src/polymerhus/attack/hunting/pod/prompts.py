"""The pod's role prompts (A1: plain Markdown in the module's `prompts/` dir).

Two agents, two roles, two sessions: the `pod_runner` (actor) and the
`pod_triager` (critic). Per ADR A1
(`docs/design/progressive-skill-lifecycle-adr.md`), a role's system prompt lives
as plain Markdown read directly by its owning module, memoized on first call and
FAIL-CLOSED on a missing file - never a `SKILL.md` mount, never an inline Python
string. The prompt text lives in the hunting module's single prompts directory
(`attack/hunting/prompts/pod-runner.md` and `pod-triager.md`); this module is the
thin reader.

The system prompts are the STABLE layer, repeated every turn as the
`create_agent` `system_prompt` (D84-10): role, paradigm, the P0-P3 stretch plan,
tools, meta-reasoning primitives, constraints, and the output contract. The
per-turn INSTANCE data (the spec variant, the filtered experiment-log slice, the
feedback, the memory key-list + reading guidance) is assembled into the USER
delta by the graph (`context.py` `compose_runner_delta` / `compose_triager_delta`)
- deliberately NOT in the system prompt.

The Runner is a pure ReAct plan designer (D84-16): it perceives a tool result,
interprets, and reasons the next step INSIDE `create_agent`; the plan is the
probe phase of the kill chain, decomposed into P0-P3. The Triager is a
THIRD-PARTY variant miner (D84-23): it reads the Runner's consolidated
experiment note, classifies, and either terminates or mints a NEW falsifiable
variant that changes a fundamental parameter - never a per-lap re-derivation.
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
    `prompts/` dir. Memoized on first call; FAIL-CLOSED."""
    global _RUNNER_SKILL
    if _RUNNER_SKILL is None:
        _RUNNER_SKILL = (_PROMPTS_DIR / "pod-runner.md").read_text(encoding="utf-8")
    return _RUNNER_SKILL


def load_pod_triager_skill() -> str:
    """The `pod_triager` system prompt, read directly from the module's
    `prompts/` dir. Memoized on first call; FAIL-CLOSED."""
    global _TRIAGER_SKILL
    if _TRIAGER_SKILL is None:
        _TRIAGER_SKILL = (_PROMPTS_DIR / "pod-triager.md").read_text(encoding="utf-8")
    return _TRIAGER_SKILL
