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
_TRIAGER_CONTRACT: str | None = None
_ASSESS_VERBATIM: str | None = None
_DECIDE_VERBATIM: str | None = None


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


def load_pod_triager_contract() -> str:
    """The lifecycle v2 `pod_triager` system prompt: the STATIC contract only -
    role, third-party stance, what you read, surgical conciseness, observation
    integrity, evidence sufficiency, and output discipline. It never carries a
    spec, a skill name, a phase verbatim, or a stage label, so the provider can
    cache the token prefix from position 0 across every turn and lap. Memoized
    on first call; FAIL-CLOSED."""
    global _TRIAGER_CONTRACT
    if _TRIAGER_CONTRACT is None:
        _TRIAGER_CONTRACT = _compose("pod-triager-contract.md")
    return _TRIAGER_CONTRACT


def load_pod_assess_verbatim() -> str:
    """The ASSESS phase verbatim: the confirmation rule, the divergence rule,
    the clean rule, and the note rule. It rides the first human message (no
    prior tool call exists to answer), never the system prompt. Memoized;
    FAIL-CLOSED."""
    global _ASSESS_VERBATIM
    if _ASSESS_VERBATIM is None:
        _ASSESS_VERBATIM = _compose("pod-triage-assess.md")
    return _ASSESS_VERBATIM


def load_pod_decide_verbatim() -> str:
    """The DECIDE phase verbatim: the variant-minting algorithm, the duplicate
    rule, the terminal vocabulary, and the exhaustion rule. It rides the
    `submit_assessment` gate response as the phase packet, never the system
    prompt. Memoized; FAIL-CLOSED."""
    global _DECIDE_VERBATIM
    if _DECIDE_VERBATIM is None:
        _DECIDE_VERBATIM = _compose("pod-triage-decide.md")
    return _DECIDE_VERBATIM


