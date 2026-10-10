"""Historical path for the store-tool contract, now defined in `app.memory`.

The contract (`StoreToolBase`, the coded teaching rejection, and the shared
`notes` implementation) was lifted to the shared `app.memory.tool_contract`
module (the service-sourced-analysis lift, ADR D27/D28) so the analysis memory
store can reuse it without importing `attack.hunting`. This module is kept as a
thin re-export for the hunting seams' historical import path; new code should
import from `polymerhus.app.memory.tool_contract` directly.

Import performs no I/O (CODING_STANDARD section 6).
"""
from __future__ import annotations

from polymerhus.app.memory.tool_contract import (
    NoteWrite,
    NotesFieldMap,
    NotesRead,
    NotesStoreHandle,
    RejectionRule,
    StoreNotesTool,
    StoreToolBase,
    build_notes_tool,
    coded_teaching_rejection,
)

__all__ = [
    "NoteWrite",
    "NotesFieldMap",
    "NotesRead",
    "NotesStoreHandle",
    "RejectionRule",
    "StoreNotesTool",
    "StoreToolBase",
    "build_notes_tool",
    "coded_teaching_rejection",
]
