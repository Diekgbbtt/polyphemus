"""The shared hunting tool contract (#293, building on #209).

The hunting module binds a store-writing tool surface at THREE agent seams -
the orchestrator, the hunting agent, and the test-executor pod - and the three
had drifted: the orchestrator's `hunts_store` / `notes` were prose-only `@tool`
closures with an INFERRED schema and no coded rejection, so an empty-argument
call surfaced a bare `1 validation error for hunts_store` (#286); every seam
carried its own copy of the teaching-rejection helper. THIS module is the one
home for the discipline:

- `coded_teaching_rejection` - the shared translation of a known schema-drift
  `ValidationError` (a missing required discriminator, or an out-of-enum value)
  into a CODED JSON rejection the model can act on, instead of the generic
  validation error (the D84-22 refinement).
- `StoreToolBase` - the shared binding base: it validates through the tool's
  own `args_schema` and translates the known drift before the turn ever sees a
  raise; `_run` dispatches read/write on the declared discriminator.
- `build_notes_tool` / `StoreNotesTool` - ONE `notes` implementation, bound at
  the orchestrator and hunter seams through a caller-bound `NotesStoreHandle`.
  The filesystem destination (orchestrator `memory.yaml` via `HuntStore`,
  hunter `notes.yaml` via `HunterMemoryStore`) is derived from the HANDLE and
  is never encoded as a request field; the typed surface stays loose (shared
  minimal fields) so each seam keeps its own schema while sharing the algorithm.

Import performs no I/O (CODING_STANDARD section 6).
"""
from __future__ import annotations

import json
import types
from dataclasses import dataclass
from typing import Any, Literal, Protocol, Sequence, Union, get_args, get_origin

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ValidationError

_READ = "read"
_WRITE = "write"
_WRITE_OPTIONS = ("append", "update", "delete")


# --- the coded teaching rejection (#209, generalised) -------------------------


def _missing_discriminator(errors: Sequence[dict], discriminator: str) -> bool:
    return any(
        e.get("type") == "missing"
        and list(e.get("loc") or ()) == [discriminator]
        for e in errors
    )


def _literal_choices(annotation: Any) -> tuple[str, ...] | None:
    """The `Literal` choices of an annotation (union-aware), else None. Used to
    derive the emitted enum's values for the teaching rejection, so the schema
    and the rejection can never disagree."""
    origin = get_origin(annotation)
    if origin is Literal:
        return tuple(str(a) for a in get_args(annotation))
    if origin in (Union, types.UnionType):
        for arg in get_args(annotation):
            if get_origin(arg) is Literal:
                return tuple(str(a) for a in get_args(arg))
    return None


def _enum_violation(
    errors: Sequence[dict], args_schema: type[BaseModel] | None,
) -> tuple[str, tuple[str, ...]] | None:
    """The first out-of-enum field error (`literal_error`) whose `Literal`
    choices can be read from the schema, else None."""
    if args_schema is None:
        return None
    fields = getattr(args_schema, "model_fields", None) or {}
    for error in errors:
        if error.get("type") != "literal_error":
            continue
        loc = list(error.get("loc") or ())
        if len(loc) != 1:
            continue
        model_field = fields.get(loc[0])
        if model_field is None:
            continue
        choices = _literal_choices(model_field.annotation)
        if choices:
            return loc[0], choices
    return None


def coded_teaching_rejection(
    *,
    tool_name: str,
    tool_input: Any,
    exc: ValidationError,
    discriminator: str = "command",
    known_commands: Sequence[str] = (_READ, _WRITE),
    write_intent_fields: Sequence[str] = (),
    require_write_intent: bool = True,
    args_schema: type[BaseModel] | None = None,
    extra_rules=None,
) -> dict | None:
    """Translate a KNOWN schema-drift `ValidationError` into a coded teaching
    rejection, else None (the call keeps failing as a rejected call - the
    D84-22 canon for a genuinely unknown parameter).

    Known shapes:
    - the required `discriminator` is missing (when `require_write_intent` is
      False, ANY omission; otherwise only an omission accompanied by a
      write-intent field), and
    - a `Literal` discriminator/option field carries an out-of-enum value.
    """
    if not isinstance(tool_input, dict):
        return None
    errors = list(exc.errors())
    if _missing_discriminator(errors, discriminator) and (
        not require_write_intent
        or any(k in tool_input for k in write_intent_fields)
    ):
        known = ", ".join(known_commands)
        return {
            "ok": False,
            "error": f"{tool_name}_args_rejected",
            "detail": (
                f"{discriminator} is required: known commands {known}; "
                f"a write needs {discriminator}=\"write\"; a read needs "
                f"{discriminator}=\"read\""
            ),
        }
    enum = _enum_violation(errors, args_schema)
    if enum is not None:
        field, choices = enum
        return {
            "ok": False,
            "error": f"{tool_name}_args_rejected",
            "detail": f"{field} must be one of: {', '.join(choices)}",
        }
    if extra_rules is not None:
        return extra_rules(tool_input, errors)
    return None


# --- the shared store-tool binding base ----------------------------------------


class StoreToolBase(BaseTool):
    """The shared binding + read/write-dispatch base for the store tools.

    A subclass declares its own `args_schema` and `_args_model` (they are the
    same), its `_discriminator` (the required read/write field) and its
    `_reject_as_json` output convention, then implements `_read` / `_write`.
    `invoke` translates the known schema drift (the missing discriminator, an
    out-of-enum value) into the coded teaching rejection; every other
    `ValidationError` keeps the D84-22 rejected-call canon.
    """

    _args_model: type[BaseModel] | None = None
    _discriminator: str = "command"
    _known_commands: tuple[str, ...] = (_READ, _WRITE)
    _write_intent_fields: tuple[str, ...] = ()
    _require_write_intent: bool = True
    _rejection_name: str = ""
    _as_json: bool = False

    def invoke(self, input, config=None, **kwargs):
        try:
            return super().invoke(input, config=config, **kwargs)
        except ValidationError as exc:
            coded = coded_teaching_rejection(
                tool_name=self._rejection_name or self.name,
                tool_input=input,
                exc=exc,
                discriminator=self._discriminator,
                known_commands=self._known_commands,
                write_intent_fields=self._write_intent_fields,
                require_write_intent=self._require_write_intent,
                args_schema=self.args_schema,
                extra_rules=self._extra_rejection,
            )
            if coded is None:
                raise
            return json.dumps(coded) if self._as_json else coded

    def _extra_rejection(self, tool_input: dict, errors: list) -> dict | None:
        """Seam-specific rejection rules (default: none)."""
        return None

    def _run(self, **kwargs: Any):
        args = self._args_model(**kwargs) if self._args_model is not None else None
        if args is not None and getattr(args, self._discriminator) == _READ:
            return self._read(args)
        return self._write(args)

    def _read(self, args: BaseModel):
        raise NotImplementedError

    def _write(self, args: BaseModel):
        raise NotImplementedError


# --- the shared notes implementation -------------------------------------------


@dataclass(frozen=True)
class NotesRead:
    """A notes read request, routed through the caller-bound handle. The
    destination is the handle, never a field here."""

    command: str = _READ
    key: str = ""
    attributes: tuple[str, ...] = ()
    key_keyword: str = ""
    body_keyword: str = ""


@dataclass(frozen=True)
class NoteWrite:
    """A notes write request, routed through the caller-bound handle. `key` is
    the revival key (orchestrator) or the fault_key (hunter); the handle owns
    the mapping to its own store's write method."""

    command: str = _WRITE
    action: str = "append"
    key: str = ""
    note: str | None = None
    note_id: str = ""
    note_name: str = ""
    kind: str = "freeform"
    body: str = ""
    evidence: str | None = None
    provenance: dict | None = None


class NotesStoreHandle(Protocol):
    """The caller-bound store handle the shared notes tool routes through."""

    def read(self, query: NotesRead) -> dict: ...

    def write(self, request: NoteWrite) -> dict: ...


def _pick(args: BaseModel, *names: str) -> str:
    for name in names:
        value = getattr(args, name, "")
        if value:
            return value
    return ""


class StoreNotesTool(StoreToolBase):
    """The ONE notes implementation (read/append/update/delete), bound at each
    seam by a `build_notes_tool` call over a caller-bound `NotesStoreHandle`.

    The typed surface is loose: the algorithm reads the shared field names
    (`key`/`fault_key`, `option`/`action`, ...) through getattr, so each seam
    keeps its own `args_schema` (the orchestrator's `cmd`/`option`/`key`/`note`,
    the hunter's `command`/`action`/`fault_key`/`note_name`/`kind`/`body`)."""

    name: str = "notes"
    description: str = ""
    args_schema: type[BaseModel] = BaseModel

    def __init__(
        self,
        *,
        handle: NotesStoreHandle | None = None,
        args_schema: type[BaseModel] | None = None,
        name: str = "notes",
        description: str = "",
        discriminator: str = "command",
        as_json: bool = False,
        rejection_name: str = "notes",
        write_intent_fields: Sequence[str] = (),
        require_write_intent: bool = True,
        **data: Any,
    ):
        resolved = args_schema or type(self).args_schema
        data["name"] = name
        data["description"] = description
        data["args_schema"] = resolved
        super().__init__(**data)
        self._handle = handle
        self._args_model = resolved
        self._discriminator = discriminator
        self._as_json = as_json
        self._rejection_name = rejection_name
        self._write_intent_fields = tuple(write_intent_fields)
        self._require_write_intent = require_write_intent

    def _read(self, args: BaseModel):
        query = NotesRead(
            command=getattr(args, self._discriminator),
            key=_pick(args, "key", "fault_key", "parent_key"),
            attributes=tuple(getattr(args, "attributes", None) or ()),
            key_keyword=getattr(args, "key_keyword", "") or "",
            body_keyword=getattr(args, "body_keyword", "") or "",
        )
        try:
            result = (self._handle.read(query) if self._handle is not None
                      else {"error": "no notes store handle is bound"})
        except Exception as exc:  # noqa: BLE001 - fail-open, never into the turn
            result = {"error": f"notes read degraded: {exc}"}
        return self._finish(result)

    def _write(self, args: BaseModel):
        command = getattr(args, self._discriminator)
        # `option` is the orchestrator's write discriminator (no default: a
        # write MUST state it); `action` is the hunter's (defaulting to
        # `append`). A call that states neither is a rejected call.
        action = getattr(args, "option", None)
        if action is None:
            action = getattr(args, "action", None)
        if action not in _WRITE_OPTIONS:
            return self._finish(
                {"error": "notes write needs an option: append, update, or delete"})
        provenance = getattr(args, "provenance", None)
        if isinstance(provenance, BaseModel):
            provenance = provenance.model_dump()
        request = NoteWrite(
            command=command,
            action=action,
            key=_pick(args, "key", "fault_key"),
            note=getattr(args, "note", None),
            note_id=getattr(args, "note_id", "") or "",
            note_name=getattr(args, "note_name", "") or "",
            kind=getattr(args, "kind", "freeform") or "freeform",
            body=getattr(args, "body", "") or "",
            evidence=getattr(args, "evidence", None),
            provenance=provenance,
        )
        try:
            result = (self._handle.write(request) if self._handle is not None
                      else {"error": "no notes store handle is bound"})
        except Exception as exc:  # noqa: BLE001 - fail-open, never into the turn
            result = {"error": f"notes {action} degraded: {exc}"}
        return self._finish(result)

    def _finish(self, result: dict):
        return json.dumps(result) if self._as_json else result


def build_notes_tool(
    handle: NotesStoreHandle | None,
    *,
    args_schema: type[BaseModel],
    name: str = "notes",
    description: str = "",
    discriminator: str = "command",
    as_json: bool = False,
    rejection_name: str = "notes",
    write_intent_fields: Sequence[str] = (),
    require_write_intent: bool = True,
) -> StoreNotesTool:
    """Build the shared `notes` tool over a caller-bound store handle.

    The handle derives the filesystem destination; no request field names it.
    """
    return StoreNotesTool(
        handle=handle,
        args_schema=args_schema,
        name=name,
        description=description,
        discriminator=discriminator,
        as_json=as_json,
        rejection_name=rejection_name,
        write_intent_fields=write_intent_fields,
        require_write_intent=require_write_intent,
    )


__all__ = [
    "NoteWrite",
    "NotesRead",
    "NotesStoreHandle",
    "StoreNotesTool",
    "StoreToolBase",
    "build_notes_tool",
    "coded_teaching_rejection",
]
