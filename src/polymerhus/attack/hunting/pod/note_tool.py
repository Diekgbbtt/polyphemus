"""The pod `notes` tool: the ONE shared notes implementation over pod memory.

The Runner writes one consolidated `experiment_summary` as the FINAL tool call
of an exhausted stretch; the Triager reads the verbatim note. Both operations go
through the SAME `tool_contract.StoreNotesTool` the hunter and the orchestrator
use, bound here by a `PodNotesHandle` and an explicit `NotesFieldMap`.

The tool NAME is `notes` everywhere (the old pod-only `note` name is retired),
so the agent census, the prompt, and the store contract name one tool. The pod's
typed fields (`order`, `kind`, `classification`, ...) are its store's contract;
the shared algorithm reads them through the field map and never guesses.

Fail-open (O10): a `None` store never raises - writes return a coded
`NOTES_NO_STORE`, reads return a graceful empty result.
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from polymerhus.attack.hunting.conciseness import append_conciseness_directive
from polymerhus.app.memory.tool_contract import (
    NotesFieldMap,
    NoteWrite,
    NotesRead,
    StoreNotesTool,
    build_notes_tool,
)
from polymerhus.attack.hunting.pod.pod_memory import (
    POD_NOTE_KINDS,
    PodMemoryStore,
    note_key,
    read_variant_summary,
)

NOTES_ARGS_REJECTED = "NOTES_ARGS_REJECTED: the note call could not be honoured as requested"
NOTES_EMPTY_BODY = "NOTES_EMPTY_BODY: a note write needs a non-empty body"
NOTES_BAD_KIND = "NOTES_BAD_KIND: unknown note kind"
NOTES_NO_STORE = "NOTES_NO_STORE: no pod memory store is bound"

NOTE_KINDS_DECLARED = list(POD_NOTE_KINDS)


class NoteToolSpec(BaseModel):
    """The pod `notes` args: the shared read/write verb plus the pod's filters.

    `command` is the discriminator (`read` / `write`); `action` is the write
    option (`append` / `update` / `delete`). The write fields carry the
    consolidation attributes; `order` is the variant ordinal. The read filters
    are the store's typed attribute filters plus the substring filters.
    `extra="forbid"` makes a stray parameter a coded rejection.
    """

    command: str = Field(
        default="read",
        description="The operation: 'read' or 'write' (required).")
    action: str = Field(
        default="append",
        description="The write option: 'append', 'update', or 'delete'.")
    # write (order/kind required on a write):
    order: int | None = Field(
        default=None, description="The variant ordinal; required on a write.")
    note_name: str = Field(
        default="", description="The note's name; ignored on a read.")
    kind: str | None = Field(
        default=None,
        description="The note kind; required on a write (defaults to "
                    "freeform).")
    body: str = Field(
        default="", description="The note body; required on a write.")
    classification: str | None = None
    symptom_status: str | None = None
    kb_primitives_used: list[str] = Field(default_factory=list)
    exhaustion_evidence: str = ""
    # read filters:
    parent_key: str = ""
    key_keyword: str = ""
    body_keyword: str = ""

    model_config = ConfigDict(extra="forbid")


class PodNotesHandle:
    """The pod store handle the shared notes tool routes through.

    It owns the spec id and the per-project `PodMemoryStore`, so the request
    never carries a destination. The `experiment_summary` and `experiment_log`
    reads are the pod's store-specific branches; every other read ranges the
    per-project `notes.yaml` with the typed filters."""

    def __init__(self, store: PodMemoryStore | None, spec_id: str):
        self._store = store
        self._spec_id = spec_id

    def read(self, query: NotesRead) -> dict:
        if self._store is None:
            return {"ok": False, "error": NOTES_NO_STORE}
        try:
            if query.kind == "experiment_log":
                if query.order is None:
                    return {"ok": False, "error": (
                        NOTES_ARGS_REJECTED
                        + ": an experiment_log read needs the variant order")}
                slice = self._store.read_experiment_log(
                    self._spec_id, query.order)
                if not slice:
                    return {"ok": True, "notes": [],
                            "detail": "no experiment log on file"}
                return {"ok": True, "kind": "experiment_log",
                        "identifier": f"{self._spec_id}/{query.order}",
                        "order": query.order, "value": slice}
            if query.kind == "experiment_summary":
                if query.order is None:
                    return {"ok": False, "error": (
                        NOTES_ARGS_REJECTED
                        + ": an experiment_summary read needs the variant order")}
                body = read_variant_summary(
                    self._store, self._spec_id, query.order)
                if not body:
                    return {"ok": True, "notes": [],
                            "detail": "no experiment summary on file"}
                return {
                    "ok": True,
                    "key": note_key(
                        self._spec_id, query.order, "experiment_summary"),
                    "kind": "experiment_summary", "order": query.order,
                    "body": body,
                }
            notes = self._store.read_notes(
                self._spec_id,
                order=query.order,
                kind=query.kind,
                classification=query.classification,
                symptom_status=query.symptom_status,
                parent_key=query.parent_key,
                key_keyword=query.key_keyword,
                body_keyword=query.body_keyword,
            )
            if not notes:
                return {"ok": True, "notes": [],
                        "detail": "no notes matched the read filters"}
            return {"ok": True, "notes": notes}
        except Exception as exc:  # noqa: BLE001 - fail-open read
            return {"ok": False, "error": f"NOTES_READ_FAILED: {exc}"}

    def write(self, request: NoteWrite) -> dict:
        if self._store is None:
            return {"ok": False, "error": NOTES_NO_STORE}
        body = (request.body or "").strip()
        if not body:
            return {"ok": False, "error": NOTES_EMPTY_BODY}
        kind = request.kind or "freeform"
        if kind not in POD_NOTE_KINDS:
            return {"ok": False, "error": (
                f"{NOTES_BAD_KIND}: {kind!r}; known: "
                + ", ".join(POD_NOTE_KINDS))}
        if request.order is None:
            return {"ok": False, "error": (
                NOTES_ARGS_REJECTED
                + ": a note write needs the variant order")}
        try:
            if kind == "experiment_summary":
                key = self._store.write_variant_summary(
                    self._spec_id, request.order, body)
            else:
                key = self._store.append(
                    self._spec_id,
                    order=request.order,
                    note_name=request.note_name or "",
                    kind=kind,
                    body=body,
                    classification=request.classification or "",
                    symptom_status=request.symptom_status or "",
                    kb_primitives_used=list(request.kb_primitives_used or ()),
                    exhaustion_evidence=request.exhaustion_evidence or "",
                )
        except Exception as exc:  # noqa: BLE001 - fail-open write
            return {"ok": False, "error": f"NOTES_WRITE_FAILED: {exc}"}
        return {
            "ok": True,
            "key": key,
            "detail": (f"{kind} note {request.note_name!r} for order "
                       f"{request.order} persisted"),
        }


_POD_NOTES_FIELD_MAP = NotesFieldMap(
    action="action",
    note="body",
    read_key="parent_key",
    key=None,
    note_id=None,
    evidence=None,
    attributes=None,
    key_keyword="key_keyword",
    body_keyword="body_keyword",
    kind="kind",
    order="order",
    classification="classification",
    symptom_status="symptom_status",
    parent_key="parent_key",
    kb_primitives_used="kb_primitives_used",
    exhaustion_evidence="exhaustion_evidence",
    passthrough=("note_name",),
)


_POD_NOTES_DESCRIPTION = append_conciseness_directive((
    "Write or read a pod experiment note in the pod's memory store. "
    f"Kinds: {', '.join(POD_NOTE_KINDS)}. command=write persists a "
    "note for the current variant order (kind experiment_summary is the "
    "consolidated stretch summary written as the FINAL tool call when "
    "the probe space is exhausted); command=read returns matching "
    "notes newest-first with the order, kind, classification, "
    "symptom_status, parent_key, key_keyword, or body_keyword filters, "
    "each note's body verbatim."))


class PodNoteTool(StoreNotesTool):
    """The pod-shaped binding of the ONE shared notes tool.

    The class-shaped constructor is kept for the pod's wiring and tests; the
    implementation is `tool_contract.StoreNotesTool`, so the hunter, the
    orchestrator, and the pod share one read/write algorithm and one tool name.
    """

    name: str = "notes"
    args_schema: type[BaseModel] = NoteToolSpec

    def __init__(self, *, store: PodMemoryStore | None, spec_id: str, **kwargs):
        super().__init__(
            handle=PodNotesHandle(store, spec_id),
            args_schema=NoteToolSpec,
            field_map=_POD_NOTES_FIELD_MAP,
            name="notes",
            description=_POD_NOTES_DESCRIPTION,
            discriminator="command",
            as_json=True,
            rejection_name="notes",
            require_write_intent=False,
        )


def note_tool_for(store: PodMemoryStore | None, spec_id: str) -> PodNoteTool:
    """Build the pod's bound `notes` tool over the ONE shared implementation."""
    return PodNoteTool(store=store, spec_id=spec_id)


__all__ = [
    "NOTE_KINDS_DECLARED",
    "NOTES_ARGS_REJECTED",
    "NOTES_BAD_KIND",
    "NOTES_EMPTY_BODY",
    "NOTES_NO_STORE",
    "NoteToolSpec",
    "PodNoteTool",
    "PodNotesHandle",
    "note_tool_for",
]
