"""The cognitive architecture map (the cortex, C1).

One shared, meaning-dense verbatim, single-sourced from
`prompts/COGNITIVE_ARCHITECTURE_MAP.md`, injected into every hunting agent's
stable system prompt - the hunt-orchestrator, the hunter, the pod runner, and
the pod triager - so all four reason through ONE map of the data layer.

Single-source discipline (the `L1_ONTOLOGY_PRIMER` / `QUERY_LIGHTRAG_DESCRIPTION`
precedent): the map lives in its own file, is read by ONE accessor
(`cognitive_architecture_map`), and is appended to each role's stable system
prompt by ONE composition helper (`with_cortex`). No role forks the map; a role
that currently lacks a surface is told the intended path and the pending grant,
never a different map.

No I/O at import (CODING_STANDARD section 6): the file is read lazily on the
first call and memoized. A missing file is a defect: FAIL-CLOSED (raise), so no
agent ever reasons without its map.
"""
from __future__ import annotations

from pathlib import Path

_MAP: str | None = None


def cognitive_architecture_map() -> str:
    """The cortex verbatim, read from the module's `prompts/` dir.

    Memoized on the first call; FAIL-CLOSED on a missing file, exactly like the
    role-prompt readers (`_gate_skill` / `_load_hunting_agent_skill`)."""
    global _MAP
    if _MAP is None:
        _MAP = (
            Path(__file__).resolve().parent
            / "prompts"
            / "COGNITIVE_ARCHITECTURE_MAP.md"
        ).read_text(encoding="utf-8").strip()
    return _MAP


def with_cortex(base_prompt: str) -> str:
    """Append the cortex to one role's stable system prompt, byte-separated.

    The ONE composition helper every hunting agent's served system prompt goes
    through, so the map is identical for all four roles and can never be
    half-injected. The base prompt is the role's own reasoning discipline; the
    cortex is additive, never a replacement."""
    return f"{base_prompt.rstrip()}\n\n{cognitive_architecture_map()}"


__all__ = ["cognitive_architecture_map", "with_cortex"]
