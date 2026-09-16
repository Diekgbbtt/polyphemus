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
  `read` is by the config identifier (`fault_key` - the 3-part config key of
  the hunt's own config) + optional filters/projection,
  never the whole surface. Reads degrade to an empty set on failure (O4); genuine
  write failures raise to the harness, which warns and keeps serving (O3).
- `graph_view` - the read-only L0/L1 view tool: the ONE shared tool
  (`graph_view_tool.py`), bound via `build_graph_view_tool(graph_view_fn)`
  with the full usage contract in its description. Absent or raising -> a
  denoted fail-open error, never a raise into the turn; write-shaped calls are
  rejected (the single-sourced `_WRITE_SHAPED` guard).
- `kb_query` - the LightRAG tool (R1): the args schema is a LOCAL minimal mirror
  of `QuerySpecV1` and the response a dict shaped like `AnswerBundleV1` (copied
  from the `lightrag-probe` worktree's `query_spec.py` / `generation.py`),
  WIRED from scratch onto the real `query_lightrag` tool (the lightrag branch's
  single KB tool, always-bound as of #197 - the `HUNTING_LIGHTRAG_TOOL` opt-in
  flag is REMOVED). An injected `kb_query` seam (the contract tier) is used when
  the real tool is unavailable; empty/raising
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
from lightrag.tool import QUERY_LIGHTRAG_DESCRIPTION
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .hunter_memory import (
    DuplicateSpecError,
    HunterMemoryStore,
    config_key_from_fault_key,
)
from .hunter_state import FAULT_STATUSES
from .hunt_store import HuntStore, config_file_name, semantic_key
from polymerhus.recon.config import EXEC_TIMEOUT_S
from polymerhus.recon.domain.types import ExecResult

# The per-call exec cap (R2), derived from the shared canonical constant
# (`recon.config.EXEC_TIMEOUT_S`, default 300) - never a local literal, so the
# hunter never drifts from the pod's cap. The pod's caps are pod-internal
# (D67-09); the hunter exposes an optional per-call `timeout_s` defaulting
# here, while the HARNESS-level probe frequency stays unbounded (R2b).


# --- the kb_query local mirrors of the LightRAG types (R1) --------------------

# Local minimal mirrors of `lightrag-probe`'s `QuerySpecV1` / `AnswerBundleV1`
# (`lightrag/query_spec.py` / `generation.py`). The `lightrag` package lives at
# the repo root; the mirror stays the local args/response contract - when the
# opt-in flag is on, `KbQueryTool` invokes the real `build_lightrag_tool`. The
# mirror copies the field shapes verbatim so the swap is mechanical.


class HunterRetrievalConfig(BaseModel):
    """Mirror of `RetrievalConfigV1`: per-mode retrieval parameters."""

    mode: Literal["naive", "mix"] = "naive"
    chunk_top_k: int = Field(default=20, ge=1, le=100)
    top_k: int = Field(default=20, ge=1, le=100)
    max_total_tokens: int = Field(default=8000, ge=1000, le=32000)


class HunterEvidenceRef(BaseModel):
    """Mirror of `EvidenceRefV1`: one evidence-backed observation reference."""

    ref: str
    summary: str


class KbQuerySpec(BaseModel):
    """The `kb_query` args contract: a LOCAL minimal mirror of `QuerySpecV1`.

    Replicates the QuerySpecV1 shape (`scenario_id`, `attack_goal`, `concern`,
    `technology_stack`, `target_refs`, `input_vectors`, `known_facts`,
    `acceptable_technique_families`, `unsupported_claims`, `evidence`,
    `retrieval`) so the seam is typed until the LightRAG integration lands and
    the real `QuerySpecV1` swaps in (R1). `extra="forbid"` (the pod's D84-22
    discipline): a parameter outside this contract FAILS before `_run`.
    """

    scenario_id: str
    attack_goal: str
    concern: str
    technology_stack: list[str] = Field(default_factory=list)
    target_refs: list[str] = Field(default_factory=list)
    input_vectors: list[str] = Field(default_factory=list)
    known_facts: list[str] = Field(default_factory=list)
    acceptable_technique_families: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    evidence: list[HunterEvidenceRef] = Field(default_factory=list)
    retrieval: HunterRetrievalConfig = Field(default_factory=HunterRetrievalConfig)

    model_config = ConfigDict(extra="forbid")


class KbAnswerBundle(BaseModel):
    """The `kb_query` response mirror of `AnswerBundleV1` (a dict-shaped bundle).

    Tolerant of the real bundle's sub-shapes (`ontology_explanations` entries
    are kept as dicts); the top-level scalar fields must be present or the seam
    result degrades (C2/C3). Swapped for the real `AnswerBundleV1` when the
    LightRAG integration lands.
    """

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

# The `kb_query` seam: (KbQuerySpec) -> AnswerBundleV1-shaped dict. Empty/raising
# -> the degraded bundle (C2/C3).
KbQueryFn = Callable[[KbQuerySpec], dict]

# The `exec` seam, reused verbatim from the pod (`pod/tools.py::ExecFn`):
# (command, timeout_s) -> ExecResult. Absent -> fail-open.
ExecFn = Callable[[str, int], ExecResult]


# --- the harness-owned fault_key gate (#199) -----------------------------------

# The ONE fault_key the model may address on a hunt is the hunt's own config
# identity (the 3-part config key, G4/ADR Q13): the canonical `_`-joined
# `<unit_id>_<CWE_ID>_<vulnerability_class>` file-name stem with the class's
# spaces preserved (example `Service:account-registration_CWE-1220_Privilege
# Escalation`) or its `::`-joined semantic twin. The write boundary NEVER
# trusts the model's string: the harness-owned gate (embedded in the typed
# layer of `hunts_store` / `notes`, applied to writes AND reads) validates the
# naming convention AND a literal `:`-split part-match against the persisted
# hunt-config identities in the `HuntStore` - no cross-form resolution of the
# model's key (operator ruling, #199).


def _fault_key_violation(
    fault_key: str, *, hunt_store: HuntStore | None, project_id: str,
) -> str | None:
    """The harness-owned gate: return a detail string when the model-emitted
    `fault_key` violates the pinned contract, else None.

    Convention - the fault_key must be a well-formed 3-part config key (checked
    through `config_key_from_fault_key`, which round-trips the `_`-joined
    canonical form and its `::`-semantic twin). Existence - the fault_key's
    `:`-split parts must match the parts of a persisted hunt-config identity in
    the `HuntStore` (config ids in the huntstore), matched literally with no
    cross-form resolution. An absent `hunt_store` degrades to convention-only
    (fail-open, the O3/O4 canon): the store's `_validate_fault_key` remains the
    form-level defense in depth."""
    try:
        config_key_from_fault_key(fault_key)
    except ValueError as exc:
        return str(exc)
    if hunt_store is None:
        return None
    parts = fault_key.split(":")
    for config in hunt_store.read_configs(project_id):
        unit_id = str(config.get("unit_id") or "")
        fault_class = str(config.get("fault_class") or "")
        vulnerability_class = str(config.get("vulnerability_class") or "")
        if not unit_id:
            continue
        identities = (
            config_file_name(unit_id, fault_class, vulnerability_class)[:-len(".yaml")],
            semantic_key(unit_id, fault_class, vulnerability_class),
        )
        if any(parts == identity.split(":") for identity in identities):
            return None
    return (
        f"fault_key {fault_key!r} references no persisted hunt config; the key "
        f"must be the hunt's own 3-part config key "
        f"<unit_id>_<CWE_ID>_<vulnerability_class> (the config_id:spec_id "
        f"composition) with the class's spaces preserved"
    )


# --- the coded teaching rejection (#209) --------------------------------------

# The D84-22 refinement: a schema failure on the store/notes tools is a CODED
# teaching rejection (never a bare ValidationError the harness turns into
# `tool_failed`). The helper inspects the raw call + the pydantic error list and
# translates the known drift shapes; anything else re-raises (the D84-22
# rejected-call canon for an unknown parameter).

_WRITE_INTENT_FIELDS = {
    "notes": ("action", "fault_key", "note_name", "kind", "body"),
    "hunts_store": ("mode", "spec", "fault_keyword", "strategy_keyword"),
}


def _coded_teaching_rejection(
    name: str, tool_input: Any, exc: ValidationError,
) -> str | None:
    """Translate a known schema-drift `ValidationError` into a coded teaching
    rejection JSON, else None (the call keeps failing as a rejected call)."""
    if not isinstance(tool_input, dict):
        return None
    errors = exc.errors()
    missing_command = any(
        e.get("type") == "missing" and list(e.get("loc") or ()) == ["command"]
        for e in errors
    )
    if missing_command and any(
        k in tool_input for k in _WRITE_INTENT_FIELDS[name]
    ):
        return json.dumps({
            "ok": False, "error": f"{name}_args_rejected",
            "detail": "command is required: a write needs command=\"write\" "
                      f"(action {tool_input.get('action', '')!r} is the write "
                      f"option, not the command); a read needs command=\"read\"",
        })
    evidence_error = any(
        e.get("type") == "string_type" and list(e.get("loc") or ()) == ["evidence"]
        for e in errors
    )
    if evidence_error:
        return json.dumps({
            "ok": False, "error": "notes_args_rejected",
            "detail": "evidence must be a string (prose); put structured refs "
                      "in provenance (source/run_id/verdict_stub/probe_refs)",
        })
    provenance_error = any(
        list(e.get("loc") or ())[:1] == ["provenance"] for e in errors
    )
    if provenance_error:
        return json.dumps({
            "ok": False, "error": "notes_args_rejected",
            "detail": "provenance is the typed NoteProvenance "
                      "(source/run_id/verdict_stub/probe_refs, extra=forbid): "
                      + "; ".join(e.get("msg", "") for e in errors),
        })
    return None


# --- the tool args schemas (extra="forbid", the pod's D84-22 discipline) -------


class HuntsStoreArgs(BaseModel):
    """The `hunts_store` tool's ARGS contract: `read` / `write` cmds.

    `write` takes the fault/spec object carrying the `status` verbatim
    (`hypothesised | verified | dropped | specified`); `mode="create"` FAILS on
    a duplicate (the novelty gate, G4), `mode="update"` overwrites in place
(G5). `read` is by the config identifier (`fault_key` - the hunt's OWN
    3-part config key, G4/ADR Q13) + optional `statuses`/`attributes`, never
    the whole surface (spec 5). The fault_key is pinned canonical (#199): the
    `_`-joined `<unit_id>_<CWE_ID>_<vulnerability_class>` file-name stem with
    the class's spaces preserved (example
    `Service:account-registration_CWE-1220_Privilege Escalation`) or its
    `::`-semantic twin; a fault_key that does not reference a persisted config
    is rejected with the denoted `fault_key_mismatch` error.

    The authored `spec` carries a `TestImplementationSpec` (the D4 handoff).
    Its `target_identity` is the target's identity object - `{"url": <base
    url>, "unit_id": <L1 identity>}` (#197): the `url` is the base URL the pod
    probes (author it from the projected L0 attack surface), `unit_id` the
    kind-qualified L1 service/system identity that surfaces alongside it.
    A spec whose `target_identity.url` is absent is INIT-rejected by the pod."""

    command: Literal["read", "write"]
    # -- read path -----------------------------------------------------------
    fault_key: str = ""
    statuses: list[str] = Field(default_factory=list)
    attributes: list[str] = Field(default_factory=list)
    # -- write path ----------------------------------------------------------
    mode: Literal["create", "update"] = "create"
    spec: dict = Field(default_factory=dict)
    fault_keyword: str = ""
    strategy_keyword: str = ""

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
    read is the grep-match read (by the fault_key - the 3-part config key -
    parent / key / body keyword), read-latest.

    #209: `command` is the REQUIRED discriminator - `action` is the write
    option, never the command. `evidence` is prose `str`; `provenance` is the
    TYPED `NoteProvenance` structured slot."""

    command: Literal["read", "write"]
    # -- read path -----------------------------------------------------------
    parent_key: str = ""
    key_keyword: str = ""
    body_keyword: str = ""
    attributes: list[str] = Field(default_factory=list)
    # -- write path ----------------------------------------------------------
    action: Literal["append", "update", "delete"] = "append"
    fault_key: str = ""
    note_name: str = ""
    kind: str = "freeform"
    body: str = ""
    evidence: str | None = None
    provenance: NoteProvenance | None = None

    model_config = ConfigDict(extra="forbid")


class ExecArgs(BaseModel):
    """The `exec` tool's ARGS contract: the exact command + an optional per-call
    `timeout_s` (defaults to `EXEC_TIMEOUT_S`, R2). The harness-level probe
    frequency is UNBOUNDED - the model decides when to probe (R2b)."""

    command: str
    timeout_s: int = EXEC_TIMEOUT_S

    model_config = ConfigDict(extra="forbid")


# --- the tools ----------------------------------------------------------------


class HuntsStoreTool(BaseTool):
    """The status-bearing write/read seam over `HunterMemoryStore` (spec 5): the
    transition verbatim lives here (`status` on the write). A duplicate `create`
    FAILS with the denoted `duplicate_spec` dedup signal the model reflects on
    (G4); `update` re-authors in place (G5). Reads degrade to an empty set (O4);
    genuine write failures raise to the harness (O3); an absent store degrades
    fail-open. #209: a call omitting the required `command` with write-intent
    fields is a CODED teaching rejection (never a bare validation error)."""

    name: str = "hunts_store"
    description: str = (
        "The hunt's status-bearing memory seam. Commands: read / write.\n"
        "write takes the fault/spec object carrying the status verbatim "
        "(hypothesised | verified | dropped | specified), plus the fault_key "
"- the hunt's OWN config identity, the 3-part config key "
        "<unit_id>_<CWE_ID>_<vulnerability_class> of the hunt's own config, "
        "with the class's spaces preserved (example "
        "Service:account-registration_CWE-1220_Privilege Escalation; the "
        "::-joined semantic twin is accepted too) - and the fault_keyword / "
        "strategy_keyword that "
        "name the produced spec file. A fault_key that does not reference a "
        "persisted config returns the fault_key_mismatch error - correct the "
        "key to the canonical form and retry. The authored spec's target_identity is "
        "the target identity object: {'url': <base url>, 'unit_id': <L1 "
        "service/system identity>} - author the url from the projected L0 "
        "attack surface (read via graph_view); the pod probes that url and "
        "INIT-rejects a spec without it. mode=create FAILS with a duplicate_spec "
        "dedup signal when the spec file already exists (reflect on overlap and "
        "merge or refresh - do not duplicate); mode=update re-authors the "
        "existing file in place. read takes the fault_key plus optional "
        "statuses / attributes filters and returns the fault's produced specs - "
        "never the whole surface."
    )
    args_schema: type[BaseModel] = HuntsStoreArgs

    def __init__(self, *, store: HunterMemoryStore | None = None,
                 project_id: str = "", hunt_store: HuntStore | None = None,
                 **kwargs):
        super().__init__(**kwargs)
        self._store = store
        self._project_id = project_id
        self._hunt_store = hunt_store

    def invoke(self, input, config=None, **kwargs):
        """#209: translate the known schema drift (missing `command` with
        write-intent) into a coded teaching rejection; everything else keeps
        the D84-22 rejected-call canon."""
        try:
            return super().invoke(input, config=config, **kwargs)
        except ValidationError as exc:
            coded = _coded_teaching_rejection("hunts_store", input, exc)
            if coded is not None:
                return coded
            raise

    def _run(self, **kwargs: Any) -> str:
        args = HuntsStoreArgs(**kwargs)
        if self._store is None:
            degraded = {
                "command": args.command,
                "error": "store_unavailable",
                "degraded": True,
            }
            return json.dumps(degraded)
        if args.command == "read":
            return self._read(args)
        return self._write(args)

    def _read(self, args: HuntsStoreArgs) -> str:
        if not args.fault_key:
            return json.dumps({"specs": [], "error": "invalid_args",
                               "detail": "read needs the fault_key identifier"})
        violation = _fault_key_violation(
            args.fault_key, hunt_store=self._hunt_store, project_id=self._project_id)
        if violation is not None:
            return json.dumps({"specs": [], "error": "fault_key_mismatch",
                               "fault_key": args.fault_key, "detail": violation})
        try:
            specs = self._store.read_specs(
                self._project_id, args.fault_key,
                sides=("produced",),
                statuses=args.statuses or None,
                attributes=args.attributes or None,
            )
        except Exception as exc:  # noqa: BLE001 - O4: read failure -> empty set
            return json.dumps({"specs": [], "error": "read_failed",
                               "detail": str(exc)})
        return json.dumps({"specs": specs})

    def _write(self, args: HuntsStoreArgs) -> str:
        if not args.fault_key or not args.fault_keyword or not args.strategy_keyword:
            return json.dumps({"ok": False, "error": "invalid_args",
                               "detail": "write needs fault_key, fault_keyword, "
                                         "strategy_keyword"})
        violation = _fault_key_violation(
            args.fault_key, hunt_store=self._hunt_store, project_id=self._project_id)
        if violation is not None:
            return json.dumps({"ok": False, "error": "fault_key_mismatch",
                               "fault_key": args.fault_key, "detail": violation})
        spec = args.spec
        if not isinstance(spec, dict) or not spec:
            return json.dumps({"ok": False, "error": "invalid_args",
                               "detail": "write needs the fault/spec object "
                                         "carrying the status attribute"})
        if spec.get("status") not in FAULT_STATUSES:
            return json.dumps({
                "ok": False, "error": "invalid_args",
                "detail": f"status must be one of {FAULT_STATUSES}; got "
                          f"{spec.get('status')!r}",
            })
        try:
            path = self._store.write_spec(
                self._project_id, args.fault_key,
                fault_keyword=args.fault_keyword,
                strategy_keyword=args.strategy_keyword,
                spec=spec, mode=args.mode,
            )
        except DuplicateSpecError as exc:
            # The denoted dedup signal (G4): the model reflects and merges or
            # refreshes instead of duplicating - never a raise into the turn.
            return json.dumps({"ok": False, "error": "duplicate_spec",
                               "fault_key": args.fault_key, "detail": str(exc)})
        except ValueError as exc:
            return json.dumps({"ok": False, "error": "invalid_args",
                               "detail": str(exc)})
        # O3: any other write failure (e.g. OSError) raises to the harness, which
        # warns and keeps serving - never a silent corruption.
        return json.dumps({"ok": True, "path": str(path),
                           "status": spec.get("status")})


class NotesTool(BaseTool):
    """The notes body read/write over the store's `notes.yaml` (G6, spec 5): the
    SAME data contract as `hunts_store`, write options `append` / `update` /
    `delete`. Reads degrade to an empty set (O4); genuine write failures raise
    to the harness (O3); an absent store degrades fail-open. #209: a call
    omitting the required `command` with write-intent, passing a dict-valued
    `evidence`, or a stray provenance key is a CODED teaching rejection."""

    name: str = "notes"
    description: str = (
        "The hunt's notes seam - one note per fault covering all decisions that "
        "concern it, more detailed than the rationale. Commands: read / write.\n"
        "A write MUST set command=\"write\" (action is the write option - "
        "append | update | delete - not the command); a read sets "
        "command=\"read\".\n"
        "write takes an action (append | update | delete), the fault_key "
        "- the hunt's OWN config identity, the 3-part config key "
        "<unit_id>_<CWE_ID>_<vulnerability_class> of "
        "the hunt's own config (spaces preserved; a fault_key that does not "
        "reference a persisted config returns the fault_key_mismatch error), a "
        "note_name, the note kind (hypothesis_refusal | implicit_test_primitive "
        "| freeform), and the body. evidence is a plain string (prose); "
        "structured refs go in provenance, the typed object with source, run_id, "
        "verdict_stub, and probe_refs (extra=forbid - a stray provenance key is "
        "rejected). "
        "update/delete on a missing note returns a denoted note_missing. read "
        "is the grep-match read, latest-first, by the fault_key parent / key / "
        "body keyword, optionally projected onto attributes."
    )
    args_schema: type[BaseModel] = NotesArgs

    def __init__(self, *, store: HunterMemoryStore | None = None,
                 project_id: str = "", hunt_store: HuntStore | None = None,
                 **kwargs):
        super().__init__(**kwargs)
        self._store = store
        self._project_id = project_id
        self._hunt_store = hunt_store

    def invoke(self, input, config=None, **kwargs):
        """#209: translate the known schema drift (missing `command` with
        write-intent, dict-valued `evidence`, stray provenance key) into a coded
        teaching rejection; everything else keeps the D84-22 rejected-call
        canon."""
        try:
            return super().invoke(input, config=config, **kwargs)
        except ValidationError as exc:
            coded = _coded_teaching_rejection("notes", input, exc)
            if coded is not None:
                return coded
            raise

    def _run(self, **kwargs: Any) -> str:
        args = NotesArgs(**kwargs)
        if self._store is None:
            return json.dumps({"command": args.command,
                               "error": "store_unavailable", "degraded": True})
        if args.command == "read":
            return self._read(args)
        return self._write(args)

    def _read(self, args: NotesArgs) -> str:
        if args.parent_key:
            violation = _fault_key_violation(
                args.parent_key, hunt_store=self._hunt_store,
                project_id=self._project_id)
            if violation is not None:
                return json.dumps({"notes": [], "error": "fault_key_mismatch",
                                   "fault_key": args.parent_key,
                                   "detail": violation})
        try:
            notes = self._store.read_notes(
                self._project_id,
                parent_key=args.parent_key or None,
                key_keyword=args.key_keyword or None,
                body_keyword=args.body_keyword or None,
                attributes=args.attributes or None,
            )
        except Exception as exc:  # noqa: BLE001 - O4: read failure -> empty set
            return json.dumps({"notes": [], "error": "read_failed",
                               "detail": str(exc)})
        return json.dumps({"notes": notes})

    def _write(self, args: NotesArgs) -> str:
        if not args.fault_key or not args.note_name:
            return json.dumps({"ok": False, "error": "invalid_args",
                               "detail": "write needs fault_key and note_name"})
        violation = _fault_key_violation(
            args.fault_key, hunt_store=self._hunt_store, project_id=self._project_id)
        if violation is not None:
            return json.dumps({"ok": False, "error": "fault_key_mismatch",
                               "fault_key": args.fault_key, "detail": violation})
        try:
            key = self._store.write_note(
                self._project_id,
                action=args.action, fault_key=args.fault_key,
                note_name=args.note_name, kind=args.kind, body=args.body,
                evidence=args.evidence,
                provenance=(args.provenance.model_dump()
                            if args.provenance is not None else None),
            )
        except ValueError as exc:
            return json.dumps({"ok": False, "error": "invalid_args",
                               "detail": str(exc)})
        # O3: any other write failure raises to the harness, which warns and
        # keeps serving.
        if key is None:
            return json.dumps({"ok": False, "error": "note_missing",
                               "fault_key": args.fault_key,
                               "note_name": args.note_name})
        return json.dumps({"ok": True, "key": key})


class KbQueryTool(BaseTool):
    """The LightRAG knowledge-base tool (R1, spec 5): a typed `QuerySpecV1`-shaped
    query -> an `AnswerBundleV1`-shaped bundle, consumed directly in the author
    lane. The KB is a testing-METHODOLOGY knowledge base (WSTG + writeups) - the
    tool's single canonical description (`QUERY_LIGHTRAG_DESCRIPTION`, imported
    from `lightrag.tool`) emphasises retrieving methodology, never adjudicating
    a bug. WIRED from scratch onto the real `query_lightrag` tool (the lightrag
    branch's single KB tool, ALWAYS attempted as of #197 - the
    `HUNTING_LIGHTRAG_TOOL` opt-in flag is REMOVED): the real tool is built
    lazily and invoked (fail-open to a degraded bundle); when unavailable the
    injected `kb_fn` seam (the contract tier) is used.
    Empty/raising -> a denoted degraded bundle (C2/C3), never a raise into the
    turn."""

    name: str = "kb_query"
    description: str = QUERY_LIGHTRAG_DESCRIPTION
    args_schema: type[BaseModel] = KbQuerySpec

    def __init__(self, *, kb_fn: KbQueryFn | None = None, **kwargs):
        super().__init__(**kwargs)
        self._kb_fn = kb_fn

    @staticmethod
    def _degraded_bundle(spec: KbQuerySpec, reason: str) -> dict:
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

        spec = KbQuerySpec(**kwargs)
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

    def _kb_query_text(self, spec: KbQuerySpec) -> str:
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
        "original traffic) - the pod's replay path is what preserves it."
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
    description: str = (
        "Search this project's recorded HTTP request/response history. Filters "
        "are conjunctive: {side, namespace, key, op, value} with side in "
        "request|response|connection|context|timing, namespace in core|header|"
        "cookie|query|form|body|tls, op in eq|contains|prefix|gte|lte|absent "
        "(absent = the transaction does NOT carry that key: use it for the "
        "control group). Returns sanitized summaries: a list of candidates, not "
        "a verification. Use the returned artifact_id as "
        "payload_vector_space.request_ref to replay a baseline."
    )
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
    description: str = (
        "Fetch one recorded HTTP transaction by artifact_id from this project. "
        "Use it to inspect a candidate before committing it as a request_ref "
        "(header names are visible here, values of sensitive headers are "
        "redacted) and to check request.body.capture_state: only `captured` is "
        "replayable. The view is sanitized: no body content is returned. "
        "Cross-project ids are not found."
    )
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
    hunt_store: HuntStore | None = None,
    graph_view_fn: GraphViewFn | None = None,
    kb_fn: KbQueryFn | None = None,
    exec_fn: ExecFn | None = None,
    http_search_fn=None,
    http_get_fn=None,
) -> list[BaseTool]:
    """Assemble the bound `HUNTER_TOOLS` list for the W5 `create_agent` binding.

    `store` is the per-project `HunterMemoryStore` and `project_id` the hunt's
    project (both bound here - the tool surface is per-hunt, W5); `hunt_store`
    is the per-project `HuntStore` the fault_key gate's existence check reads
    the persisted config identities from (#199; absent -> the gate degrades to
    convention-only, fail-open); `graph_view_fn`
    / `kb_fn` / `exec_fn` are the injected seam bodies (each absent degrades
    fail-open). Returns the five tools in the spec's surface order: `hunts_store`
    / `notes` / `graph_view` / `kb_query` / `exec`. `graph_view` is the ONE
    shared read-only L0/L1 tool (#197, `graph_view_tool.build_graph_view_tool`)
    whose contract (schema + query-language primitives + guard + return shape +
    example) rides its description - the old local `GraphViewTool` is REMOVED."""
    from polymerhus.attack.hunting.graph_view_tool import (  # noqa: PLC0415
        build_graph_view_tool,
    )

    return [
        HuntsStoreTool(store=store, project_id=project_id, hunt_store=hunt_store),
        NotesTool(store=store, project_id=project_id, hunt_store=hunt_store),
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
    "HunterRetrievalConfig",
    "HunterEvidenceRef",
    "KbQuerySpec",
    "KbAnswerBundle",
    "HuntsStoreArgs",
    "NoteProvenance",
    "NotesArgs",
    "ExecArgs",
    "HuntsStoreTool",
    "NotesTool",
    "KbQueryTool",
    "ExecTool",
    "HttpHistorySearchTool",
    "HttpHistoryGetTool",
    "build_hunter_tools",
]
