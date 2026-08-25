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
  `read` is by the config identifier (`fault_key`) + optional filters/projection,
  never the whole surface. Reads degrade to an empty set on failure (O4); genuine
  write failures raise to the harness, which warns and keeps serving (O3).
- `graph_view` - the read-only L0/L1 view tool: a TYPED SEAM (the injected
  `graph_view` callable; the live L0/L1 wiring is a separate workstream). Absent
  or raising -> a denoted fail-open error, never a raise into the turn; write-shaped
  calls are rejected (the orchestrator's `_WRITE_SHAPED` guard).
- `kb_query` - the LightRAG tool (R1): the args schema is a LOCAL minimal mirror
  of `QuerySpecV1` and the response a dict shaped like `AnswerBundleV1` (copied
  from the `lightrag-probe` worktree's `query_spec.py` / `generation.py`),
  WIRED from scratch onto the real `query_lightrag` tool (the lightrag branch's
  single KB tool, config-gated by `HUNTING_LIGHTRAG_TOOL`). When the opt-in flag
  is off, an injected `kb_query` seam (the contract tier) is used; empty/raising
  -> a denoted degraded bundle (C2/C3). The `polymerhus.lightrag` import is
  lazy (no I/O at import).
- `exec` - the Kali-container exec tool (R2): `EXEC_TIMEOUT_S` per call (the
  shared `recon.config.EXEC_TIMEOUT_S`, default 300), args `command` + optional
  `timeout_s`; calls an injected `exec_fn(command, timeout_s) -> ExecResult`
  seam (absent -> a denoted fail-open error). UNBOUNDED at the harness level -
  the model decides when to probe (R2b).
  The PARTITION GUARD (Q8): exec never produces the hypothesis verdict; the pod
  remains the only source of experimental evidence for the committed hypothesis.

Exposed as the five `BaseTool` subclasses `HuntsStoreTool` / `NotesTool` /
`GraphViewTool` / `KbQueryTool` / `ExecTool`; `build_hunter_tools(...)` returns the
bound `HUNTER_TOOLS` list for the W5 `create_agent` binding. This module imports
no driver and performs no I/O at import (CODING_STANDARD section 6).
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Literal

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from .hunter_memory import DuplicateSpecError, HunterMemoryStore
from .hunter_state import FAULT_STATUSES
from polymerhus.recon.config import EXEC_TIMEOUT_S
from polymerhus.recon.domain.types import ExecResult

# The per-call exec cap (R2), derived from the shared canonical constant
# (`recon.config.EXEC_TIMEOUT_S`, default 300) - never a local literal, so the
# hunter never drifts from the pod's cap. The pod's caps are pod-internal
# (D67-09); the hunter exposes an optional per-call `timeout_s` defaulting
# here, while the HARNESS-level probe frequency stays unbounded (R2b).

# The write-shaped tokens the read-only `graph_view` refuses to pass through,
# replicated from the orchestrator's `ReadOnlyGraphView` guard (D67-04).
_WRITE_SHAPED = re.compile(r"\b(?:MERGE|CREATE|DELETE|SET|REMOVE|FOREACH|LOAD\s+CSV)\b")


# --- the kb_query local mirrors of the LightRAG types (R1) --------------------

# Local minimal mirrors of `lightrag-probe`'s `QuerySpecV1` / `AnswerBundleV1`
# (`src/polymerhus/lightrag/query_spec.py` / `generation.py`). The `lightrag`
# package is NOT on this branch/dev - the integration is a SIMULTANEOUS
# workstream; the W5 harness swaps these for the real types when it lands. The
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


# --- the tool args schemas (extra="forbid", the pod's D84-22 discipline) -------


class HuntsStoreArgs(BaseModel):
    """The `hunts_store` tool's ARGS contract: `read` / `write` cmds.

    `write` takes the fault/spec object carrying the `status` verbatim
    (`hypothesised | verified | dropped | specified`); `mode="create"` FAILS on
    a duplicate (the novelty gate, G4), `mode="update"` overwrites in place
    (G5). `read` is by the config identifier (`fault_key`) + optional
    `statuses`/`attributes`, never the whole surface (spec 5)."""

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


class NotesArgs(BaseModel):
    """The `notes` tool's ARGS contract: `read` / `write` cmds, the SAME data
    contract as `hunts_store` (G6). Write options `append` / `update` / `delete`;
    read is the grep-match read (by the fault_key parent / key / body keyword),
    read-latest."""

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
    provenance: dict | None = None

    model_config = ConfigDict(extra="forbid")


class GraphViewArgs(BaseModel):
    """The `graph_view` tool's ARGS contract: a read-only L0/L1 inspection query.
    Write-shaped calls are rejected (spec 5)."""

    query: str
    params: dict = Field(default_factory=dict)

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
    fail-open."""

    name: str = "hunts_store"
    description: str = (
        "The hunt's status-bearing memory seam. Commands: read / write.\n"
        "write takes the fault/spec object carrying the status verbatim "
        "(hypothesised | verified | dropped | specified), plus the fault_key "
        "(the config identity) and the fault_keyword / strategy_keyword that "
        "name the produced spec file. mode=create FAILS with a duplicate_spec "
        "dedup signal when the spec file already exists (reflect on overlap and "
        "merge or refresh - do not duplicate); mode=update re-authors the "
        "existing file in place. read takes the fault_key plus optional "
        "statuses / attributes filters and returns the fault's produced specs - "
        "never the whole surface."
    )
    args_schema: type[BaseModel] = HuntsStoreArgs

    def __init__(self, *, store: HunterMemoryStore | None = None,
                 project_id: str = "", **kwargs):
        super().__init__(**kwargs)
        self._store = store
        self._project_id = project_id

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
    to the harness (O3); an absent store degrades fail-open."""

    name: str = "notes"
    description: str = (
        "The hunt's notes seam - one note per fault covering all decisions that "
        "concern it, more detailed than the rationale. Commands: read / write.\n"
        "write takes an action (append | update | delete), the fault_key, a "
        "note_name, the note kind (hypothesis_refusal | implicit_test_primitive "
        "| freeform), and the body (plus optional evidence / provenance); "
        "update/delete on a missing note returns a denoted note_missing. read "
        "is the grep-match read, latest-first, by the fault_key parent / key / "
        "body keyword, optionally projected onto attributes."
    )
    args_schema: type[BaseModel] = NotesArgs

    def __init__(self, *, store: HunterMemoryStore | None = None,
                 project_id: str = "", **kwargs):
        super().__init__(**kwargs)
        self._store = store
        self._project_id = project_id

    def _run(self, **kwargs: Any) -> str:
        args = NotesArgs(**kwargs)
        if self._store is None:
            return json.dumps({"command": args.command,
                               "error": "store_unavailable", "degraded": True})
        if args.command == "read":
            return self._read(args)
        return self._write(args)

    def _read(self, args: NotesArgs) -> str:
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
        try:
            key = self._store.write_note(
                self._project_id,
                action=args.action, fault_key=args.fault_key,
                note_name=args.note_name, kind=args.kind, body=args.body,
                evidence=args.evidence, provenance=args.provenance,
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


class GraphViewTool(BaseTool):
    """The read-only L0/L1 view tool (G8a, spec 5): the hunter's target-knowledge
    inspection. A TYPED SEAM - the injected `graph_view` callable; the live
    L0/L1 wiring is a separate workstream. Absent or raising -> a denoted
    fail-open error, never a raise into the turn; write-shaped calls rejected."""

    name: str = "graph_view"
    description: str = (
        "The read-only L0/L1 target-knowledge view: inspect the modelled target "
        "surface (services, systems, edges) to ground your hypotheses. Takes a "
        "read-only Cypher query plus optional params. Write-shaped calls "
        "(MERGE / CREATE / DELETE / SET / REMOVE / FOREACH / LOAD CSV) are "
        "rejected - this tool can never write the graph. An unavailable or "
        "failing view returns a denoted error; the hunt keeps serving."
    )
    args_schema: type[BaseModel] = GraphViewArgs

    def __init__(self, *, graph_view: GraphViewFn | None = None, **kwargs):
        super().__init__(**kwargs)
        self._graph_view = graph_view

    def _run(self, **kwargs: Any) -> str:
        args = GraphViewArgs(**kwargs)
        if self._graph_view is None:
            return json.dumps({"error": "graph_view_unavailable", "degraded": True,
                               "query": args.query[:200]})
        if _WRITE_SHAPED.search(args.query.upper()):
            return json.dumps({"error": "write_shaped_rejected",
                               "detail": f"the graph view is read-only; refusing "
                                         f"write-shaped cypher {args.query[:120]!r}"})
        try:
            rows = self._graph_view(args.query, args.params)
        except Exception as exc:  # noqa: BLE001 - fail-open, never into the turn
            return json.dumps({"error": "graph_view_failed", "degraded": True,
                               "detail": str(exc)})
        return json.dumps({"rows": list(rows or [])})


class KbQueryTool(BaseTool):
    """The LightRAG knowledge-base tool (R1, spec 5): a typed `QuerySpecV1`-shaped
    query -> an `AnswerBundleV1`-shaped bundle, consumed directly in the author
    lane. WIRED from scratch onto the real `query_lightrag` tool (the lightrag
    branch's single KB tool): when `HUNTING_LIGHTRAG_TOOL` is enabled the real
    tool is built lazily from app config and invoked (fail-open to a degraded
    bundle); otherwise the injected `kb_fn` seam (the contract tier) is used.
    Empty/raising -> a denoted degraded bundle (C2/C3), never a raise into the
    turn."""

    name: str = "kb_query"
    description: str = (
        "Query the fault knowledge base (LightRAG) to ground your reasoning: "
        "the scenario's attack_goal and concern, the technology stack, target "
        "references, input vectors, known facts, the acceptable technique "
        "families, any unsupported claims, observed evidence, and the retrieval "
        "config. Returns an AnswerBundleV1-shaped bundle: a summary, per-entity "
        "explanations with provenance references, and knowledge gaps. An empty "
        "or degraded result means the KB has nothing further - degrade to your "
        "HuntConfig grounding and continue."
    )
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
        """The real `query_lightrag` tool, built lazily when the opt-in flag is
        on (the lightrag branch's single KB tool). Fail-open to None."""
        try:
            from polymerhus.app.config import config  # noqa: PLC0415
            if not config.HUNTING_LIGHTRAG_TOOL:
                return None
            from polymerhus.lightrag.tool import build_lightrag_tool  # noqa: PLC0415
            return build_lightrag_tool()
        except Exception:  # noqa: BLE001 - fail-open to the seam/degraded bundle
            return None

    def _run(self, **kwargs: Any) -> str:
        spec = KbQuerySpec(**kwargs)
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
        "inform your reasoning, never the committed hypothesis's evidence."
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


def build_hunter_tools(
    *,
    store: HunterMemoryStore | None = None,
    project_id: str = "",
    graph_view_fn: GraphViewFn | None = None,
    kb_fn: KbQueryFn | None = None,
    exec_fn: ExecFn | None = None,
) -> list[BaseTool]:
    """Assemble the bound `HUNTER_TOOLS` list for the W5 `create_agent` binding.

    `store` is the per-project `HunterMemoryStore` and `project_id` the hunt's
    project (both bound here - the tool surface is per-hunt, W5); `graph_view_fn`
    / `kb_fn` / `exec_fn` are the injected seam bodies (each absent degrades
    fail-open). Returns the five tools in the spec's surface order: `hunts_store`
    / `notes` / `graph_view` / `kb_query` / `exec`."""
    return [
        HuntsStoreTool(store=store, project_id=project_id),
        NotesTool(store=store, project_id=project_id),
        GraphViewTool(graph_view=graph_view_fn),
        KbQueryTool(kb_fn=kb_fn),
        ExecTool(exec_fn=exec_fn),
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
    "NotesArgs",
    "GraphViewArgs",
    "ExecArgs",
    "HuntsStoreTool",
    "NotesTool",
    "GraphViewTool",
    "KbQueryTool",
    "ExecTool",
    "build_hunter_tools",
]