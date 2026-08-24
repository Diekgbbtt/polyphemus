"""The pod `note` tool (T7, D84-20/27/32; T1 rides the per-project store).

The Runner calls `note` at P3 to write ONE consolidated `experiment_summary` as
the FINAL tool call of an exhausted stretch (D84-17/19); the Triager calls it to
READ that verbatim note (D84-23). BOTH operations share one tool with one
`args_schema` (`NoteToolSpec`), discriminated by `operation`.

D84-22: the tool's OWN contract is the validator. `NoteToolSpec` sets
`extra="forbid"`, so a wrong parameter FAILS as a REJECTED tool call (the
create_agent ToolMessage carries the pydantic detail; `_run` never executes).
The tool additionally returns CODED contract rejections for the semantics that
only the run can judge (`NOTES_EMPTY_BODY` / `NOTES_BAD_KIND` /
`NOTES_NO_STORE` / `NOTES_ARGS_REJECTED`).

Fail-open (O10): a `None` store never raises - writes return `NOTES_NO_STORE`,
reads return a graceful empty result, so the ReAct loop survives an unwired
store. A read returns the note bodies prompt-verbatim and un-truncated
(D84-19.2) - the summary is a different object from a raw tool body slice.

T1: the tool rides the per-project deterministic-key store. The write's
`variant_ref` becomes the integer `order` (the variant ordinal), notes are keyed
`<spec_id>:<order>:<note_name>` (D84-36), and the read surface gains the typed
attribute filters (`order`, `kind`, `classification`, `symptom_status`) beside
the retained substring filters. The VALUE fields stored match the D84-32
CANONICAL set (the D84-30/31 removals applied; `_seq`/`_ref` gone).
"""
from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from polymerhus.attack.hunting.pod.pod_memory import (
    POD_NOTE_KINDS,
    PodMemoryStore,
    note_key,
)

# The coded contract rejections (D84-22: the error explains the semantic
# explicitly; the prefix is the short machine code).
NOTES_ARGS_REJECTED = "NOTES_ARGS_REJECTED: the note call could not be honoured as requested"
NOTES_EMPTY_BODY = "NOTES_EMPTY_BODY: a note write needs a non-empty body"
NOTES_BAD_KIND = "NOTES_BAD_KIND: unknown note kind"
NOTES_NO_STORE = "NOTES_NO_STORE: no pod memory store is bound"

NOTE_KINDS_DECLARED = list(POD_NOTE_KINDS)


class NoteToolSpec(BaseModel):
    """The `note` tool's contract (D84-32, T1): `operation` discriminates
    write/read.

    Write fields carry the consolidation attributes, with `order` (the variant
    ordinal) replacing the old `variant_ref` string per D84-36. The read filters
    are the store's typed attribute filters (`order`, `kind`, `classification`,
    `symptom_status`) plus the substring filters (`parent_key` / `key_keyword` /
    `body_keyword`), nullable and combinable. `extra="forbid"` (D84-22) rejects a
    parameter outside this contract BEFORE `_run`.
    """

    operation: str = "write"
    # write (order/kind required on a write; None on a read = no filter):
    order: int | None = None
    note_name: str = ""
    kind: str | None = None
    body: str = ""
    classification: str | None = None
    symptom_status: str | None = None
    kb_primitives_used: list[str] = Field(default_factory=list)
    exhaustion_evidence: str = ""
    # read filters:
    parent_key: str = ""
    key_keyword: str = ""
    body_keyword: str = ""

    model_config = ConfigDict(extra="forbid")


class PodNoteTool(BaseTool):
    """Write/read the pod's experiment-memory notes (D84-20/27). `store=None`
    fails open (O10): writes are a coded rejection, reads return an empty
    result, and the loop never raises."""

    name: str = "note"
    description: str = (
        "Write or read a pod experiment note in the pod's memory store. "
        f"Kinds: {', '.join(POD_NOTE_KINDS)}. "
        "operation=write persists a note for the current variant order "
        "(kind experiment_summary is the consolidated stretch summary written as "
        "the FINAL tool call when the probe space is exhausted); "
        "operation=read returns matching notes newest-first with the order, kind, "
        "classification, symptom_status, parent_key, key_keyword, or body_keyword "
        "filters, each note's body verbatim."
    )
    args_schema: type[BaseModel] = NoteToolSpec

    def __init__(self, *, store: PodMemoryStore | None, spec_id: str, **kwargs):
        super().__init__(**kwargs)
        self.__store = store
        self.__spec_id = spec_id

    # ------------------------------------------------------------------
    # the rejections carry the semantic + the machine code (D84-22)
    # ------------------------------------------------------------------

    def _write(self, spec: NoteToolSpec) -> str:
        if self.__store is None:
            return NOTES_NO_STORE
        body = (spec.body or "").strip()
        if not body:
            return NOTES_EMPTY_BODY
        kind = spec.kind or "freeform"
        if kind not in POD_NOTE_KINDS:
            return f"{NOTES_BAD_KIND}: {kind!r}; known: {', '.join(POD_NOTE_KINDS)}"
        if spec.order is None:
            return NOTES_ARGS_REJECTED + ": a note write needs the variant order"
        try:
            if kind == "experiment_summary":
                # D84-35: the P3 consolidated summary is the TERMINAL record of
                # the variant's experiment-log slice - NOT a note in notes.yaml.
                key = self.__store.write_variant_summary(
                    self.__spec_id, spec.order, body)
            else:
                # kb_insight / freeform accumulate in notes.yaml (D84-35).
                key = self.__store.append(
                    self.__spec_id,
                    order=spec.order,
                    note_name=spec.note_name or "",
                    kind=kind,
                    body=body,
                    classification=spec.classification or "",
                    symptom_status=spec.symptom_status or "",
                    kb_primitives_used=spec.kb_primitives_used or [],
                    exhaustion_evidence=spec.exhaustion_evidence or "",
                )
        except Exception as exc:  # noqa: BLE001 - fail-open: never raise into the loop
            return f"NOTES_WRITE_FAILED: {exc}"
        return (f"NOTES_WRITTEN {key}: {kind} note {spec.note_name!r} for "
                f"order {spec.order} persisted")

    def _read(self, spec: NoteToolSpec) -> str:
        if self.__store is None:
            return NOTES_NO_STORE
        try:
            # D84-35: an experiment_summary read ranges the variant's log slice
            # (its terminal record), not notes.yaml.
            if spec.kind == "experiment_summary":
                if spec.order is None:
                    return NOTES_ARGS_REJECTED + ": an experiment_summary read needs the variant order"
                from polymerhus.attack.hunting.pod.pod_memory import read_variant_summary
                body = read_variant_summary(self.__store, self.__spec_id, spec.order)
                if not body:
                    return "NOTES_EMPTY: no experiment_summary on file for this variant"
                return (f"NOTE key={note_key(self.__spec_id, spec.order, 'experiment_summary')}"
                        f" kind=experiment_summary order={spec.order}\nbody:\n{body}")
            notes = self.__store.read_notes(
                self.__spec_id,
                order=spec.order,
                kind=spec.kind,
                classification=spec.classification,
                symptom_status=spec.symptom_status,
                parent_key=spec.parent_key or None,
                key_keyword=spec.key_keyword or None,
                body_keyword=spec.body_keyword or None,
            )
        except Exception as exc:  # noqa: BLE001 - fail-open read (O4 caller degrades)
            return f"NOTES_READ_FAILED: {exc}"
        if not notes:
            return "NOTES_EMPTY: no notes matched the read filters"
        blocks = []
        for n in notes:
            fields = []
            for f in ("classification", "symptom_status", "kb_primitives_used",
                      "exhaustion_evidence", "evidence"):
                if n.get(f):
                    rendered = n[f]
                    if isinstance(rendered, list):
                        rendered = json.dumps(rendered)
                    fields.append(f"{f}: {rendered}")
            meta = (f"NOTE key={n.get('key')} kind={n.get('kind')}"
                    f" order={n.get('order')}")
            body = str(n.get("body", ""))
            block = f"{meta}\n" + ("\n".join(fields) + "\n" if fields else "") + f"body:\n{body}"
            blocks.append(block)
        return "\n\n---\n\n".join(blocks)

    # ------------------------------------------------------------------

    def _run(self, **kwargs: Any) -> str:
        # The args schema already validated the call (extra="forbid", D84-22);
        # `_run` reconstructs the spec from the validated kwargs, defending the
        # coded rejection for a malformed call that somehow leaks past it.
        try:
            spec = NoteToolSpec(**kwargs)
        except Exception:  # noqa: BLE001 - defensive coded rejection
            return NOTES_ARGS_REJECTED
        if spec.operation == "read":
            return self._read(spec)
        return self._write(spec)

    # The tools' args go through pydantic (extra="forbid") before `_run`, so the
    # tool node's ToolMessage carries the pydantic detail verbatim - the harness
    # does not re-validate (D84-22).


def note_tool_for(store: PodMemoryStore | None, spec_id: str) -> PodNoteTool:
    """Build a bound `note` tool (handy for graph wiring + tests)."""
    return PodNoteTool(store=store, spec_id=spec_id)
