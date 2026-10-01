"""The hunting-artifact surgical-conciseness directive (#292).

The single-sourced binding cap on the load-bearing prose a hunting agent
writes. It is a WRITING directive only - there is deliberately no
validation-time length enforcement.

This module exists as the ENV-FREE home of the constant so the tool modules
(`actors.py`, `hunter_tools.py`, `pod/note_tool.py`) can import at module top,
exactly like the #207 `http_history_contract.py` single-description pattern.
`llm.py` re-exports both names to preserve the public home beside the other
phase constants; it never hosts the definition, so importing this module pulls
no `app.config` and reads no env (CODING_STANDARD section 6).
"""
from __future__ import annotations

# The four role prompts embed this text verbatim; the store/notes/note tool
# descriptions append it through `append_conciseness_directive`. The drift guard
# (`tests/attack/test_hunting_llm.py` and the per-tool tests) asserts the exact
# string in every one of those sites.
HUNTING_CONCISENESS_DIRECTIVE = (
    "Hunting-artifact conciseness (binding): cap every config `rationale` and "
    "every note body (`note` / `body`) at roughly 500 characters, and write "
    "assertive, specific prose carrying only the essential information in "
    "meaningful concrete language - no filler, no restated context, no "
    "hedging, no narrative around the load-bearing fact."
)


def append_conciseness_directive(description: str) -> str:
    """Append the single-sourced conciseness directive to a store/notes/note
    tool description (#292), so no caller ever hand-copies the text."""
    return f"{description}\n\n{HUNTING_CONCISENESS_DIRECTIVE}"


__all__ = ["HUNTING_CONCISENESS_DIRECTIVE", "append_conciseness_directive"]
