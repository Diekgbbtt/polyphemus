"""The hunter's tool surface (#164, W4): the five tools the ReAct engine exposes.

The surface replicates the orchestrator's minimalised tool contract
(`docs/design/hunting-orchestrator-candidates-rewrite-spec.md` 3.4): `hunts_store`
/ `notes` / `graph_view`, read/write cmds, no back-edge tool, no budget tool,
tool names reused verbatim (R3). The hunter adds `kb_query` and `exec` (GP8d).
The tools are `BaseTool` subclasses per the pod's tool pattern
(`pod/tools.py` on `feat/hunting-84-test-executor-pod`: `KbRetrieveTool` /
`ExecTool`, `extra="forbid"` args schemas). Every tool is a seam holder: the
injected collaborator (the `HunterMemoryStore`, the `graph_view` / `kb_query` /
`exec` callables) is what the W5 harness binds per hunt - this module wires
nothing into `hunting_agent.py` (W5 does the wiring, plus the `symptom_kb.py`
retirement).

Contract + degradation (spec 5, spec 9):
- `hunts_store` / `notes` - the status-bearing write/read seam over
  `HunterMemoryStore` (G8): `write` carries the fault/spec object with the
  `status` verbatim; a duplicate `create` FAILS with the denoted `duplicate_spec`
  dedup signal the model interprets (G4); re-authoring `update`s in place (G5);
  both tools are BOUND to the hunt's OWN config key (`fault_key`, #298 - the
  3-part config key, derived from the dispatched `HuntConfig` and never a
  request field) with optional filters/projection on the read,
  never the whole surface. Reads degrade to an empty set on failure (O4); genuine
  write failures raise to the harness, which warns and keeps serving (O3).
- `graph_view` - the read-only L0/L1 view tool: the ONE shared tool
  (`graph_view_tool.py`), bound via `build_graph_view_tool(graph_view_fn)`
  with the full usage contract in its description. Absent or raising -> a
  denoted fail-open error, never a raise into the turn; write-shaped calls are
  rejected (the single-sourced `_WRITE_SHAPED` guard).
- `kb_query` - the LightRAG tool (R1): the args schema is the REAL `QuerySpecV1`
  (the lightrag branch's query contract, imported - never a local mirror) and
  the response a dict shaped like `AnswerBundleV1`, WIRED from scratch onto the
  real `query_lightrag` tool (the lightrag branch's single KB tool, always-bound
  as of #197 - the `HUNTING_LIGHTRAG_TOOL` opt-in flag is REMOVED). The local
  `KbQuerySpec` mirror is RETIRED (#322): it lacked `expected_no_hypothesis`, so
  the shared usage skill (which documents `QuerySpecV1`) sent fields the mirror
  forbade and every `kb_query` degraded. One contract now serves the hunter, the
  pod, and the real tool. An injected `kb_query` seam (the contract tier) is used
  when the real tool is unavailable; empty/raising
  -> a denoted degraded bundle (C2/C3). The `lightrag.tool` description
  constant is imported at module top (I/O-free); the real tool is built lazily.
- `exec` - the Kali-container exec tool (R2): `EXEC_TIMEOUT_S` per call (the
  shared `recon.config.EXEC_TIMEOUT_S`, default 300), args `command` + optional
  `timeout_s`; calls an injected `exec_fn(command, timeout_s) -> ExecResult`
  seam (absent -> a denoted fail-open error). UNBOUNDED at the harness level -
  the model decides when to probe (R2b).
  The PARTITION GUARD (Q8): exec never produces the hypothesis verdict; the pod
  remains the only source of experimental evidence for the committed hypothesis.

Exposed as the `BaseTool` subclasses `HuntsStoreTool` / `NotesTool` /
`KbQueryTool` / `ExecTool` (plus the shared `graph_view` tool from
`graph_view_tool.py`); `build_hunter_tools(...)` returns the
bound `HUNTER_TOOLS` list for the W5 `create_agent` binding. This module imports
no driver and performs no I/O at import (CODING_STANDARD section 6).
"""
from __future__ import annotations

import json
from typing import Any, Callable, Literal

from langchain_core.tools import BaseTool
from lightrag.query_spec import QuerySpecV1
from lightrag.tool import QUERY_LIGHTRAG_DESCRIPTION
from pydantic import BaseModel, ConfigDict, Field

from .conciseness import append_conciseness_directive
from .hunter_memory import (
    DuplicateSpecError,
    HunterMemoryStore,
)
from .http_history_contract import (
    GET_HTTP_ARTIFACT_DESCRIPTION,
    SEARCH_HTTP_HISTORY_DESCRIPTION,
)
from .hunter_state import FAULT_STATUSES
from .hunting_status import TARGET_UNAVAILABLE_DIRECTIVE
from .tool_contract import (
    NotesFieldMap,
    StoreNotesTool,
    StoreToolBase,
    build_notes_tool,
)
from polymerhus.recon.config import EXEC_TIMEOUT_S
from polymerhus.recon.domain.types import ExecResult

# The per-call exec cap (R2), derived from the shared canonical constant
# (`recon.config.EXEC_TIMEOUT_S`, default 300) - never a local literal, so the
# hunter never drifts from the pod's cap. The pod's caps are pod-internal
# (D67-09); the hunter exposes an optional per-call `timeout_s` defaulting
# here, while the HARNESS-level probe frequency stays unbounded (R2b).


# --- the kb_query response envelope (R1) --------------------------------------

# The args contract is the REAL `lightrag.query_spec.QuerySpecV1` (#322) - the
# same schema the pod's `query_lightrag` wrapper and the real tool bind - so the
# hunter, the pod, the shared usage skill, and the canonical description can
# never disagree about the KB query fields. Only the response keeps a local
# tolerant envelope (`KbAnswerBundle`, below): it accepts the injected seam's
# dict and the real tool's `AnswerBundleV1` JSON alike.


class KbAnswerBundle(BaseModel):
    """The `kb_query` response mirror of `AnswerBundleV1` (a dict-shaped bundle).

    Tolerant of the real bundle's sub-shapes (`ontology_explanations` entries
    are kept as dicts); the top-level scalar fields must be present or the seam
    result degrades (C2/C3). The args contract is the real `QuerySpecV1`; only
    the response shape keeps a tolerant local envelope."""

    schema_version: str = "lightrag-answer/v2"
    scenario_id: str = ""
    summary: str = ""
    ontology_explanations: list[dict] = Field(default_factory=list)
    provenance_references: list[str] = Field(default_factory=list)
    knowledge_gaps: list[str] = Field(default_factory=list)
    notes: str = ""

    model_config = ConfigDict(extra="ignore")


# --- the injected seam types --------------------------------------------------

# The `graph_view` seam: the orchestrator's `ReadOnlyGraphView.read` shape,
# (cypher, params) -> rows. Absent/raising -> fail-open (G8a, spec 9).
GraphViewFn = Callable[[str, dict], list[dict]]

# The `kb_query` seam: (QuerySpecV1) -> AnswerBundleV1-shaped dict. Empty/raising
# -> the degraded bundle (C2/C3).
KbQueryFn = Callable[[QuerySpecV1], dict]

# The `exec` seam, reused verbatim from the pod (`pod/tools.py::ExecFn`):
# (command, timeout_s) -> ExecResult. Absent -> fail-open.
ExecFn = Callable[[str, int], ExecResult]


# --- the harness-bound fault_key (#298, supersedes the #199 request-field gate)

# The hunt's own config identity is NOT a request field: it is BOUND at the
# tool/handle construction (the harness holds it at dispatch) so the hunter's
# store tools can only ever address the hunt's own config. The model authors the
# spec's `fault_keyword` / `strategy_keyword` (the produced file's identity
# axes, flagged `vulnerability_class`-like by the operator) but never the
# destination config key. A tool constructed without a bound key degrades to a
# denoted invalid_args, never a silent degenerate path.

# --- the coded teaching rejection (#209, shared in tool_contract) --------------

# The D84-22 refinement: a schema failure on the store/notes tools is a CODED
# teaching rejection (never a bare ValidationError the harness turns into
# `tool_failed`). The shared translation lives in `tool_contract`; the hunter's
# seam-specific extras (`_notes_extra_rejection` below: the `command` omission
# clause, a wrong-typed `evidence`, a stray `provenance` key) are passed to it
# as the `extra_rejection=` callback.

_HUNTER_WRITE_INTENT_FIELDS = ("spec",)
_NOTES_WRITE_INTENT_FIELDS = ("action", "note_name", "kind", "body")


def _notes_extra_rejection(tool_input: dict, errors: list) -> dict | None:
    """The hunter's seam-specific teaching rejections: the `command` omission
    (which names `action` as the write option, restoring the #209 clause), a
    dict-valued `evidence` (structured refs belong in `provenance`), and a
    stray `provenance` key. Runs BEFORE the shared translation."""
    missing_command = any(
        e.get("type") == "missing" and list(e.get("loc") or ()) == ["command"]
        for e in errors
    )
    if missing_command:
        return {
            "ok": False, "error": "notes_args_rejected",
            "detail": "command is required: a write needs command=\"write\" "
                      f"(action {tool_input.get('action', '')!r} is the write "
                      "option, not the command); a read needs command=\"read\"",
        }
    evidence_error = any(
        e.get("type") == "string_type" and list(e.get("loc") or ()) == ["evidence"]
        for e in errors
    )
    if evidence_error:
        return {
            "ok": False, "error": "notes_args_rejected",
            "detail": "evidence must be a string (prose); put structured refs "
                      "in provenance (source/run_id/verdict_stub/probe_refs)",
        }
    provenance_error = any(
        list(e.get("loc") or ())[:1] == ["provenance"] for e in errors
    )
    if provenance_error:
        return {
            "ok": False, "error": "notes_args_rejected",
            "detail": "provenance is the typed NoteProvenance "
                      "(source/run_id/verdict_stub/probe_refs, extra=forbid): "
                      + "; ".join(e.get("msg", "") for e in errors),
        }
    return None


# --- the tool args schemas (extra="forbid", the pod's D84-22 discipline) -------


class HuntsStoreArgs(BaseModel):
    """The `hunts_store` tool's ARGS contract: `read` / `write` cmds.

    The WRITE payload is the ONE `spec` object (converged on the hunt
    orchestrator's single-payload `hunt_config` contract, #164/#298): it
    carries the `status` verbatim (`hypothesised | verified | dropped |
    specified`) and the file-name identity attributes `fault_keyword` /
    `strategy_keyword`. The symbolic layer DERIVES
    `<fault_keyword>_<strategy_keyword>.yaml` from them, so they are never
    separate request fields whose requiredness the surface could omit.
    `status="hypothesised"` creates the draft (a duplicate FAILS - the novelty
    gate, G4); every other status re-authors in place (G5). A payload missing a
    derivation input is a coded `hunts_store_write_rejected` naming the field.

    `read` filters by optional `statuses`/`attributes`, never the whole surface
    (spec 5). The hunt's OWN config identity (its 3-part config key, G4/ADR
    Q13) is BOUND at the tool construction (#298) - it is never a request field,
    so the hunter can only address its own config.

    The authored `spec` carries a `TestImplementationSpec` (the D4 handoff).
    Its `target_identity` is the target's identity object - `{"url": <base
    url>, "unit_id": <L1 identity>}` (#197): the `url` is the base URL the pod
    probes (author it from the projected L0 attack surface), `unit_id` the
    kind-qualified L1 service/system identity that surfaces alongside it.
    A spec whose `target_identity.url` is absent is INIT-rejected by the pod."""

    command: Literal["read", "write"] = Field(
        description="The operation: 'read' or 'write' (required).")
    # -- read path -----------------------------------------------------------
    statuses: list[str] = Field(
        default_factory=list,
        description="Read filter: keep only specs with one of these statuses.")
    attributes: list[str] = Field(
        default_factory=list,
        description="Read projection: return only these attributes per spec.")
    # -- write path (ONE payload) --------------------------------------------
    spec: dict = Field(
        default_factory=dict,
        description="Write payload: the authored spec object. It MUST carry "
                    "`status` (hypothesised | verified | dropped | specified) "
                    "and the file-name identity attributes `fault_keyword` and "
                    "`strategy_keyword`; the spec file name "
                    "`<fault_keyword>_<strategy_keyword>.yaml` is DERIVED from "
                    "them. A payload missing one is rejected with a coded "
                    "`hunts_store_write_rejected` error naming the field.")

    model_config = ConfigDict(extra="forbid")


class NoteProvenance(BaseModel):
    """The TYPED provenance slot of a notes write (#209).

    Mirrors the canonical record the code itself writes
    (`surfer.py::_record_durable_pod_export`: `source` / `run_id` /
    `verdict_stub`) plus `probe_refs` (the model's structured evidence refs,
    e.g. `exec:SPA shell`, ratified by #209) - so the tool-calling schema and
    the store-writer's record cannot drift. `extra="forbid"` (D84-22): a stray
    key is a rejected call, never silently stored. `source` is the
    design-pinned home of the pod session id (`hunting-164-state-graph-spec.md`
    §6); `evidence` stays PROSE and structured refs never go there.
    """

    source: str = ""
    run_id: str = ""
    verdict_stub: bool = False
    probe_refs: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class NotesArgs(BaseModel):
    """The `notes` tool's ARGS contract: `read` / `write` cmds, the SAME data
    contract as `hunts_store` (G6). Write options `append` / `update` / `delete`;
    read is the grep-match read (by key / body keyword), read-latest. The
    hunt's OWN config key is BOUND at the tool construction (#298), never a
    request field.

    #209: `command` is the REQUIRED discriminator - `action` is the write
    option, never the command. `evidence` is prose `str`; `provenance` is the
    TYPED `NoteProvenance` structured slot."""

    command: Literal["read", "write"] = Field(
        description="The operation: 'read' or 'write' (required); `action` is "
                    "the write option, never the command.")
    # -- read path -----------------------------------------------------------
    key_keyword: str = Field(
        default="", description="Read filter: substring over the note keys.")
    body_keyword: str = Field(
        default="", description="Read filter: substring over the note bodies.")
    attributes: list[str] = Field(
        default_factory=list,
        description="Read projection: return only these attributes per note.")
    # -- write path ----------------------------------------------------------
    action: Literal["append", "update", "delete"] = Field(
        default="append",
        description="The write option: 'append' a new note, 'update' or "
                    "'delete' an existing one.")
    note_name: str = Field(
        default="",
        description="The note's name, unique within the fault_key (required on "
                    "a write; ignored on a read).")
    kind: str = Field(
        default="freeform",
        description="The note kind: hypothesis_refusal | "
                    "implicit_test_primitive | freeform.")
    body: str = Field(default="", description="The note body.")
    evidence: str | None = Field(
        default=None,
        description="Prose evidence; structured refs go in provenance.")
    provenance: NoteProvenance | None = Field(
        default=None,
        description="The typed structured provenance (source/run_id/"
                    "verdict_stub/probe_refs).")

    model_config = ConfigDict(extra="forbid")


class ExecArgs(BaseModel):
    """The `exec` tool's ARGS contract: the exact command + an optional per-call
    `timeout_s` (defaults to `EXEC_TIMEOUT_S`, R2). The harness-level probe
    frequency is UNBOUNDED - the model decides when to probe (R2b)."""

    command: str
    timeout_s: int = EXEC_TIMEOUT_S

    model_config = ConfigDict(extra="forbid")


# --- the tools ----------------------------------------------------------------


class HuntsStoreTool(StoreToolBase):
    """The status-bearing write/read seam over `HunterMemoryStore` (spec 5): the
    transition verbatim lives here (`status` on the write). A duplicate `create`
    FAILS with the denoted `duplicate_spec` dedup signal the model reflects on
    (G4); `update` re-authors in place (G5). Reads degrade to an empty set (O4);
    genuine write failures raise to the harness (O3); an absent store degrades
    fail-open. #209: a call omitting the required `command` with write-intent
    fields is a CODED teaching rejection (never a bare validation error) - the
    binding and translation are the shared `tool_contract.StoreToolBase`."""

    name: str = "hunts_store"
    description: str = (
        "The hunt's status-bearing memory seam, bound to THIS hunt's own "
        "config (you never supply the config key). Commands: read / write.\n"
        "write takes ONE payload, `spec` - the authored spec object. It MUST "
        "carry the status verbatim (hypothesised | verified | dropped | "
        "specified) and the file-name identity attributes `fault_keyword` / "
        "`strategy_keyword`; the spec file name is DERIVED from them, never "
        "authored as a file name. status=hypothesised creates the draft - a "
        "duplicate FAILS with a duplicate_spec dedup signal when the spec file "
        "already exists (reflect on overlap and merge or refresh - do not "
        "duplicate); verified / dropped / specified re-author the existing file "
        "in place. A payload missing a required attribute is rejected with a "
        "coded hunts_store_write_rejected error naming the field. "
        "The authored spec's target_identity is "
        "the target identity object: {'url': <base url>, 'unit_id': <L1 "
        "service/system identity>} - author the url from the projected L0 "
        "attack surface (read via graph_view); the pod probes that url and "
        "INIT-rejects a spec without it. read takes optional "
        "statuses / attributes filters and returns the fault's produced specs - "
        "never the whole surface."
    )
    args_schema: type[BaseModel] = HuntsStoreArgs
    _discriminator: str = "command"
    _rejection_name: str = "hunts_store"
    _write_intent_fields: tuple[str, ...] = _HUNTER_WRITE_INTENT_FIELDS
    _require_write_intent: bool = True
    _as_json: bool = True

    def __init__(self, *, store: HunterMemoryStore | None = None,
                 project_id: str = "", fault_key: str = "", **kwargs):
        super().__init__(**kwargs)
        self._store = store
        self._project_id = project_id
        self._fault_key = fault_key
        self.description = append_conciseness_directive(self.description)

    def _unavailable(self, args: HuntsStoreArgs) -> str:
        return json.dumps({
            "command": args.command,
            "error": "store_unavailable",
            "degraded": True,
        })

    def _unbound(self) -> str:
        return json.dumps({
            "ok": False,
            "error": "invalid_args",
            "detail": "no fault_key is bound to this hunt tool (#298)",
        })

    def _read(self, args: HuntsStoreArgs) -> str:
        if self._store is None:
            return self._unavailable(args)
        if not self._fault_key:
            return json.dumps({"specs": [], "error": "invalid_args",
                               "detail": "no fault_key is bound to this hunt "
                                         "tool (#298)"})
        try:
            specs = self._store.read_specs(
                self._project_id, self._fault_key,
                sides=("produced",),
                statuses=args.statuses or None,
                attributes=args.attributes or None,
            )
        except Exception as exc:  # noqa: BLE001 - O4: read failure -> empty set
            return json.dumps({"specs": [], "error": "read_failed",
                               "detail": str(exc)})
        return json.dumps({"specs": specs})

    @staticmethod
    def _write_rejected(fields: list[str], detail: str) -> str:
        """The coded contract rejection (#164): a machine error code plus the
        field name(s) the agent must supply - never a silent degenerate-name
        write, never a bare pydantic error (the `coded_teaching_rejection`
        convention, shared with the orchestrator's `hunts_store`)."""
        return json.dumps({
            "ok": False, "error": "hunts_store_write_rejected",
            "fields": list(fields), "detail": detail, "rejected": True,
        })

    def _write(self, args: HuntsStoreArgs) -> str:
        if self._store is None:
            return self._unavailable(args)
        if not self._fault_key:
            return self._unbound()
        spec = args.spec
        if not isinstance(spec, dict) or not spec:
            return self._write_rejected(
                ["spec"],
                "write needs the spec object carrying status + fault_keyword "
                "+ strategy_keyword")
        # The file-name identity is derived from the payload's own attributes
        # (the symbolic layer owns the symbol, #164): a missing derivation
        # input is a coded contract rejection, never a degenerate-name write.
        missing = [f for f in ("fault_keyword", "strategy_keyword")
                   if not spec.get(f)]
        if missing:
            return self._write_rejected(
                missing,
                f"the spec payload must carry the file-name identity "
                f"attribute(s) {', '.join(missing)}; the spec file name "
                f"<fault_keyword>_<strategy_keyword>.yaml is DERIVED from them")
        if spec.get("status") not in FAULT_STATUSES:
            return self._write_rejected(
                ["status"],
                f"status must be one of {FAULT_STATUSES}; got "
                f"{spec.get('status')!r}")
        # The write mode is derived from the status (the orchestrator's
        # status-driven write): hypothesised creates the draft (the novelty
        # gate), every other lifecycle state re-authors in place.
        mode = "create" if spec["status"] == "hypothesised" else "update"
        try:
            path = self._store.write_spec(
                self._project_id, self._fault_key,
                fault_keyword=spec["fault_keyword"],
                strategy_keyword=spec["strategy_keyword"],
                spec=spec, mode=mode,
            )
        except DuplicateSpecError as exc:
            # The denoted dedup signal (G4): the model reflects and merges or
            # refreshes instead of duplicating - never a raise into the turn.
            return json.dumps({"ok": False, "error": "duplicate_spec",
                               "fault_key": self._fault_key, "detail": str(exc)})
        except ValueError as exc:
            return json.dumps({"ok": False, "error": "invalid_args",
                               "detail": str(exc)})
        # O3: any other write failure (e.g. OSError) raises to the harness, which
        # warns and keeps serving - never a silent corruption.
        return json.dumps({"ok": True, "path": str(path),
                           "status": spec.get("status")})


_NOTES_DESCRIPTION = append_conciseness_directive((
    "The hunt's notes seam - one note per fault covering all decisions that "
    "concern it, more detailed than the rationale. Commands: read / write. "
    "Bound to THIS hunt's own config (you never supply the config key).\n"
    "A write MUST set command=\"write\" (action is the write option - "
    "append | update | delete - not the command); a read sets "
    "command=\"read\".\n"
    "write takes an action (append | update | delete), a "
    "note_name, the note kind (hypothesis_refusal | implicit_test_primitive "
    "| freeform), and the body. evidence is a plain string (prose); "
    "structured refs go in provenance, the typed object with source, run_id, "
    "verdict_stub, and probe_refs (extra=forbid - a stray provenance key is "
    "rejected). "
    "update/delete on a missing note returns a denoted note_missing. read "
    "is the grep-match read, latest-first, by the key / "
    "body keyword, optionally projected onto attributes."
))


class HunterMemoryNotesHandle:
    """The hunter seam's store handle for the shared `notes` tool.

    It owns the `notes.yaml` destination (via `HunterMemoryStore`) and the
    hunt's OWN config key, BOUND at construction (#298). The shared algorithm
    never sees a path or a store: the destination is derived from THIS handle,
    never a request field."""

    def __init__(self, store: HunterMemoryStore | None, project_id: str,
                 fault_key: str = ""):
        self._store = store
        self._project_id = project_id
        self._fault_key = fault_key

    def read(self, query) -> dict:
        if self._store is None:
            return {"command": query.command, "error": "store_unavailable",
                    "degraded": True}
        if not self._fault_key:
            return {"notes": [], "error": "invalid_args",
                    "detail": "no fault_key is bound to this hunt tool (#298)"}
        try:
            notes = self._store.read_notes(
                self._project_id,
                parent_key=self._fault_key,
                key_keyword=query.key_keyword or None,
                body_keyword=query.body_keyword or None,
                attributes=query.attributes or None,
            )
        except Exception as exc:  # noqa: BLE001 - O4: read failure -> empty set
            return {"notes": [], "error": "read_failed", "detail": str(exc)}
        return {"notes": notes}

    def write(self, request) -> dict:
        if self._store is None:
            return {"command": request.command, "error": "store_unavailable",
                    "degraded": True}
        if not self._fault_key or not request.note_name:
            return {"ok": False, "error": "invalid_args",
                    "detail": "write needs a bound fault_key and note_name"}
        try:
            key = self._store.write_note(
                self._project_id, action=request.action, fault_key=self._fault_key,
                note_name=request.note_name, kind=request.kind, body=request.body,
                evidence=request.evidence, provenance=request.provenance)
        except ValueError as exc:
            return {"ok": False, "error": "invalid_args", "detail": str(exc)}
        # O3: any other write failure raises to the harness, which warns and
        # keeps serving.
        if key is None:
            return {"ok": False, "error": "note_missing",
                    "fault_key": self._fault_key, "note_name": request.note_name}
        return {"ok": True, "key": key}


# The explicit notes field map (#293): the hunter's schema names, checked
# against `NotesArgs` at construction - no alias guessing. `key`/`read_key` are
# None because the hunt's config key is BOUND on the handle (#298), never a
# request field, so neither role names a schema field.
_HUNTER_NOTES_FIELD_MAP = NotesFieldMap(
    key=None,
    read_key=None,
    action="action",
    note="body",
    note_id=None,
    attributes="attributes",
    key_keyword="key_keyword",
    body_keyword="body_keyword",
    passthrough=("note_name", "kind", "evidence", "provenance"),
)


def _hunter_notes_kwargs(handle: HunterMemoryNotesHandle) -> dict:
    """The one config for the hunter's shared `notes` binding, shared by the
    `notes_tool_for` production builder and the `NotesTool` compatibility
    constructor so the two can never drift."""
    return dict(
        handle=handle,
        args_schema=NotesArgs,
        field_map=_HUNTER_NOTES_FIELD_MAP,
        name="notes",
        description=_NOTES_DESCRIPTION,
        discriminator="command",
        as_json=True,
        rejection_name="notes",
        write_intent_fields=_NOTES_WRITE_INTENT_FIELDS,
        require_write_intent=True,
        extra_rejection=_notes_extra_rejection,
    )


def notes_tool_for(*, store: HunterMemoryStore | None = None,
                   project_id: str = "",
                   fault_key: str = "") -> StoreNotesTool:
    """The production builder for the hunter's bound `notes` tool: the shared
    `build_notes_tool` over the hunter's store handle. The `notes.yaml`
    destination and the hunt's own config key are derived from the handle,
    never a request field."""
    return build_notes_tool(
        **_hunter_notes_kwargs(HunterMemoryNotesHandle(store, project_id, fault_key))
    )


class NotesTool(StoreNotesTool):
    """The notes body read/write over the store's `notes.yaml` (G6, spec 5): the
    SAME data contract as `hunts_store`, write options `append` / `update` /
    `delete`. Reads degrade to an empty set (O4); genuine write failures raise
    to the harness (O3); an absent store degrades fail-open. #209: a call
    omitting the required `command` with write-intent, passing a dict-valued
    `evidence`, or a stray provenance key is a CODED teaching rejection.

    This is the class-shaped compatibility constructor for the ONE shared
    implementation (`tool_contract.StoreNotesTool`); production binds the tool
    through `notes_tool_for` (the named `build_notes_tool` path). Both share
    `_hunter_notes_kwargs`, so they cannot drift."""

    name: str = "notes"
    description: str = _NOTES_DESCRIPTION
    args_schema: type[BaseModel] = NotesArgs

    def __init__(self, *, store: HunterMemoryStore | None = None,
                 project_id: str = "", fault_key: str = "",
                 **kwargs):
        super().__init__(
            **_hunter_notes_kwargs(
                HunterMemoryNotesHandle(store, project_id, fault_key)),
            **kwargs,
        )


class KbQueryTool(BaseTool):
    """The LightRAG knowledge-base tool (R1, spec 5): a typed `QuerySpecV1`-shaped
    query -> an `AnswerBundleV1`-shaped bundle, consumed directly in the author
    lane. The args schema IS the real `lightrag.query_spec.QuerySpecV1` (#322) -
    the same contract the pod and the real tool bind, so the usage skill and the
    canonical description cannot drift. The KB is a testing-METHODOLOGY knowledge
    base (WSTG + writeups) - the tool's single canonical description
    (`QUERY_LIGHTRAG_DESCRIPTION`, imported from `lightrag.tool`) emphasises
    retrieving methodology, never adjudicating a bug. WIRED from scratch onto the
    real `query_lightrag` tool (the lightrag branch's single KB tool, ALWAYS
    attempted as of #197 - the `HUNTING_LIGHTRAG_TOOL` opt-in flag is REMOVED):
    the real tool is built lazily and invoked (fail-open to a degraded bundle);
    when unavailable the injected `kb_fn` seam (the contract tier) is used.
    Empty/raising -> a denoted degraded bundle (C2/C3), never a raise into the
    turn."""

    name: str = "kb_query"
    description: str = QUERY_LIGHTRAG_DESCRIPTION
    args_schema: type[BaseModel] = QuerySpecV1

    def __init__(self, *, kb_fn: KbQueryFn | None = None, **kwargs):
        super().__init__(**kwargs)
        self._kb_fn = kb_fn

    @staticmethod
    def _degraded_bundle(spec: QuerySpecV1, reason: str) -> dict:
        return {
            "schema_version": "lightrag-answer/v2",
            "scenario_id": spec.scenario_id,
            "summary": "kb_query degraded - grounded on the HuntConfig alone",
            "ontology_explanations": [],
            "provenance_references": [],
            "knowledge_gaps": [f"knowledge base unavailable ({reason})"],
            "notes": "degraded",
        }

    @staticmethod
    def _lightrag_tool():
        """The real `query_lightrag` tool, built lazily (the lightrag branch's
        single KB tool). ALWAYS attempted as of #197 - the `HUNTING_LIGHTRAG_TOOL`
        opt-in gate is REMOVED. Fail-open to None (the injected `kb_fn` seam or
        the degraded bundle then serves)."""
        try:
            from lightrag.tool import build_lightrag_tool  # noqa: PLC0415
            return build_lightrag_tool()
        except Exception:  # noqa: BLE001 - fail-open to the seam/degraded bundle
            return None

    def _run(self, **kwargs: Any) -> str:
        from lightrag.observability import kb_observation_span

        spec = QuerySpecV1(**kwargs)
        entity_names: list[str] = []
        provenance: list[str] = []
        with kb_observation_span(
            query=spec.concern, scenario_id=spec.scenario_id
        ) as observation:
            text = self._kb_query_text(spec)
            try:
                bundle = json.loads(text)
                entity_names = [
                    str(x.get("entity_name") or x.get("entity_type") or "")
                    for x in (bundle.get("ontology_explanations") or [])
                    if isinstance(x, dict)
                ]
                provenance = [
                    str(x) for x in (bundle.get("provenance_references") or [])
                ]
            except (ValueError, TypeError, AttributeError):
                entity_names = []
                provenance = []
            observation.record(
                entity_names=entity_names,
                provenance_references=provenance,
            )
        return text

    def _kb_query_text(self, spec: QuerySpecV1) -> str:
        """Resolve one `kb_query` to its AnswerBundle-shaped JSON text (the real
        tool when available, else the injected seam, else the degraded bundle).
        Fail-open (C2/C3): never raises into the turn."""
        real = self._lightrag_tool()
        if real is not None:
            try:
                # The real tool takes QuerySpecV1 kwargs and returns the
                # AnswerBundle JSON string; keep the response inside the pod's
                # KbAnswerBundle-shaped envelope (tolerant of the real shape).
                text = real.invoke(spec.model_dump())
                bundle = KbAnswerBundle.model_validate_json(text or "{}")
                if not bundle.scenario_id or not bundle.summary:
                    return json.dumps(self._degraded_bundle(spec, "empty bundle"))
                return json.dumps(bundle.model_dump())
            except Exception as exc:  # noqa: BLE001 - C2/C3: degrade, never raise
                return json.dumps(self._degraded_bundle(spec, str(exc)))
        if self._kb_fn is None:
            return json.dumps(self._degraded_bundle(spec, "seam absent"))
        try:
            raw = self._kb_fn(spec)
            bundle = KbAnswerBundle.model_validate(raw or {})
        except Exception as exc:  # noqa: BLE001 - C2/C3: degrade, never raise
            return json.dumps(self._degraded_bundle(spec, str(exc)))
        if not bundle.scenario_id or not bundle.summary:
            return json.dumps(self._degraded_bundle(spec, "empty bundle"))
        return json.dumps(bundle.model_dump())

    async def _arun(self, **kwargs: Any) -> str:
        return self._run(**kwargs)


class ExecTool(BaseTool):
    """The Kali-container exec tool (R2, spec 5): the back-edge replacement for
    cheap claim-verification probes inside VERIFY-CLAIMS. `EXEC_TIMEOUT_S` per
    call; the model chooses the command and an optional shorter `timeout_s`.
    UNBOUNDED at the harness level - the model decides when to probe (R2b). The
    PARTITION GUARD: exec never produces the hypothesis verdict - the pod remains
    the ONLY source of experimental evidence for the committed hypothesis."""

    name: str = "exec"
    description: str = (
        "Run a command on the target's Kali execution surface: cheap "
        "claim-verification probes inside the ReAct loop (curl for HTTP probes, "
        "read-only inspection). Each call is bounded by EXEC_TIMEOUT_S (an "
        "optional shorter timeout_s is accepted). The probe frequency is "
        "unbounded - you decide when to probe. PARTITION GUARD: exec never "
        "produces the hypothesis verdict - the pod remains the only source of "
        "experimental evidence for the committed hypothesis; exec results only "
        "inform your reasoning, never the committed hypothesis's evidence. If "
        "the spec's payload_vector_space carries a request_ref, do NOT re-create "
        "that request by hand here: a hand-written curl loses the replay lineage "
        "(derived_from / replay_kind stay null and the artifact looks like "
        "original traffic) - the pod's replay path is what preserves it.\n\n"
        f"{TARGET_UNAVAILABLE_DIRECTIVE}"
    )
    args_schema: type[BaseModel] = ExecArgs

    def __init__(self, *, exec_fn: ExecFn | None = None, **kwargs):
        super().__init__(**kwargs)
        self._exec_fn = exec_fn

    def _run(self, **kwargs: Any) -> str:
        args = ExecArgs(**kwargs)
        if self._exec_fn is None:
            return json.dumps({"ok": False, "error": "exec_unavailable",
                               "degraded": True, "command": args.command})
        try:
            result = self._exec_fn(args.command, args.timeout_s)
        except Exception as exc:  # noqa: BLE001 - fail-open, never into the turn
            return json.dumps({"ok": False, "error": "exec_failed",
                               "detail": str(exc), "command": args.command})
        return json.dumps({
            "stdout": result.stdout, "stderr": result.stderr,
            "returncode": result.returncode, "duration_ms": result.duration_ms,
        })


class HttpHistorySearchArgs(BaseModel):
    """The read-only search contract (#196): conjunctive filters over the
    recorded transactions of the hunter's project. Raw bodies are never
    returned - the rows are sanitized summaries."""

    filters: list[dict] = Field(default_factory=list)
    cursor: str | None = None
    limit: int = 50
    text: str | None = None

    model_config = ConfigDict(extra="forbid")


class HttpHistoryGetArgs(BaseModel):
    """The read-only get contract (#196). `include_body` is deliberately absent:
    the raw body is available only to the deterministic pod-side replay."""

    artifact_id: str

    model_config = ConfigDict(extra="forbid")


class HttpHistorySearchTool(BaseTool):
    """Read-only search over the project's HTTP history (sanitized summaries).

    The hunter may discover a baseline `request_ref` here; replaying it is the
    POD's job, so this tool exposes no mutation or execution capability.
    Fail-open: unwired or failing search degrades to a denoted error bundle."""

    name: str = "search_http_history"
    # The canonical contract + domain model, single-sourced with the pod's
    # `replay` (http_history_contract.py) so the hunter and the pod can never
    # describe the same artifact differently.
    description: str = SEARCH_HTTP_HISTORY_DESCRIPTION
    args_schema: type[BaseModel] = HttpHistorySearchArgs

    def __init__(self, *, http_search_fn=None, project_id: str = "", **kwargs):
        super().__init__(**kwargs)
        self._fn = http_search_fn
        self._project_id = project_id

    def _run(self, **kwargs: Any) -> str:
        args = HttpHistorySearchArgs(**kwargs)
        if self._fn is None:
            return json.dumps({"ok": False, "error": "http_history_unavailable", "degraded": True})
        try:
            result = self._fn(
                self._project_id,
                args.filters,
                args.cursor,
                args.limit,
                args.text,
            )
        except Exception as exc:  # noqa: BLE001 - fail-open, never into the turn
            return json.dumps({"ok": False, "error": "http_history_failed", "detail": str(exc)})
        return json.dumps(result)


class HttpHistoryGetTool(BaseTool):
    """Read-only fetch of one sanitized artifact by id."""

    name: str = "get_http_artifact"
    description: str = GET_HTTP_ARTIFACT_DESCRIPTION
    args_schema: type[BaseModel] = HttpHistoryGetArgs

    def __init__(self, *, http_get_fn=None, project_id: str = "", **kwargs):
        super().__init__(**kwargs)
        self._fn = http_get_fn
        self._project_id = project_id

    def _run(self, **kwargs: Any) -> str:
        args = HttpHistoryGetArgs(**kwargs)
        if self._fn is None:
            return json.dumps({"ok": False, "error": "http_history_unavailable", "degraded": True})
        try:
            result = self._fn(self._project_id, args.artifact_id, False)
        except Exception as exc:  # noqa: BLE001 - fail-open, never into the turn
            return json.dumps({"ok": False, "error": "http_history_failed", "detail": str(exc)})
        return json.dumps(result)


def build_hunter_tools(
    *,
    store: HunterMemoryStore | None = None,
    project_id: str = "",
    fault_key: str = "",
    graph_view_fn: GraphViewFn | None = None,
    kb_fn: KbQueryFn | None = None,
    exec_fn: ExecFn | None = None,
    http_search_fn=None,
    http_get_fn=None,
) -> list[BaseTool]:
    """Assemble the bound `HUNTER_TOOLS` list for the W5 `create_agent` binding.

    `store` is the per-project `HunterMemoryStore` and `project_id` the hunt's
    project (both bound here - the tool surface is per-hunt, W5); `fault_key` is
    the hunt's OWN config key, BOUND here (#298; the harness holds it at
    dispatch, so it is never a request field); `graph_view_fn`
    / `kb_fn` / `exec_fn` are the injected seam bodies (each absent degrades
    fail-open). Returns the tools in the spec's surface order: `hunts_store`
    / `notes` / `graph_view` / `kb_query` / `exec`. `graph_view` is the ONE
    shared read-only L0/L1 tool (#197, `graph_view_tool.build_graph_view_tool`)
    whose contract (schema + query-language primitives + guard + return shape +
    example) rides its description - the old local `GraphViewTool` is REMOVED."""
    from polymerhus.attack.hunting.graph_view_tool import (  # noqa: PLC0415
        build_graph_view_tool,
    )

    return [
        HuntsStoreTool(store=store, project_id=project_id, fault_key=fault_key),
        notes_tool_for(store=store, project_id=project_id, fault_key=fault_key),
        build_graph_view_tool(graph_view_fn),
        KbQueryTool(kb_fn=kb_fn),
        ExecTool(exec_fn=exec_fn),
        HttpHistorySearchTool(http_search_fn=http_search_fn, project_id=project_id),
        HttpHistoryGetTool(http_get_fn=http_get_fn, project_id=project_id),
    ]


__all__ = [
    "EXEC_TIMEOUT_S",
    "GraphViewFn",
    "KbQueryFn",
    "ExecFn",
    "KbAnswerBundle",
    "HuntsStoreArgs",
    "NoteProvenance",
    "NotesArgs",
    "ExecArgs",
    "HuntsStoreTool",
    "NotesTool",
    "HunterMemoryNotesHandle",
    "notes_tool_for",
    "KbQueryTool",
    "ExecTool",
    "HttpHistorySearchTool",
    "HttpHistoryGetTool",
    "build_hunter_tools",
]
