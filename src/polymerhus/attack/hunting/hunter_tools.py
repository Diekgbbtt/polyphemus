"""The hunter's tool surface (S3 8.7, T6 #379): the loop-driven hunter's tools.

The surface replicates the orchestrator's minimalised tool contract
(`docs/design/hunting-orchestrator-candidates-rewrite-spec.md` 3.4): `hunts_store`
/ `notes` / `graph_view`, read/write cmds, no back-edge tool, no budget tool,
tool names reused verbatim (R3). The hunter adds `kb_query`, `exec` (GP8d), the
web-vulnerability suite pair `skill_list` / `skill_load` (S3 8.7), and the two
HTTP-history reads. The tools are `BaseTool` subclasses per the pod's tool
pattern (`pod/tools.py`: `KbRetrieveTool` / `ExecTool`, `extra="forbid"` args
schemas). Every tool is a seam holder: the injected collaborator (the
`HunterMemoryStore`, the `graph_view` / `kb_query` / `exec` callables, the suite
seam) is what the harness binds per hunt - this module wires nothing into
`hunting_agent.py`.

Contract + degradation (spec 5, spec 9):
- `hunts_store` / `notes` - the spec-set write/read seam over
  `HunterMemoryStore` (S3 8.6-8.7): `write` carries the WHOLE `specs` list,
  each entry with its `status` (`hypothesised | ratified | dropped`) and the
  file-name keywords; the store derives `<fault_keyword>_<strategy_keyword>`.
  A duplicate identity inside the set is the denoted `duplicate_spec` dedup
  signal the model interprets. Both tools are BOUND to the hunt's OWN loop
  dispatch id (`hunt_key` = `<unit_name>__<loop_id>`, S3 8.9 - never a request
  field) with optional filters/projection on the read, never the whole
  surface. Reads degrade to an empty set on failure (O4); genuine write
  failures raise to the harness, which warns and keeps serving (O3).
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
  The PARTITION GUARD (Q8): exec probes inform the assumption check and never
  manufacture a symptom; the pod remains the only source of experimental
  evidence for a ratified spec.

Exposed as the `BaseTool` subclasses `HuntsStoreTool` / `NotesTool` /
`KbQueryTool` / `ExecTool` (plus the shared `graph_view` tool from
`graph_view_tool.py`); `build_hunter_tools(...)` returns the
bound `HUNTER_TOOLS` list for the W5 `create_agent` binding. This module imports
no driver and performs no I/O at import (CODING_STANDARD section 6).
"""
from __future__ import annotations

import json
import types
import typing
from collections.abc import Callable, Sequence
from typing import Any, Literal

from langchain_core.tools import BaseTool
from lightrag.query_spec import QuerySpecV1
from lightrag.tool import QUERY_LIGHTRAG_DESCRIPTION
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .conciseness import append_conciseness_directive
from .hunter_memory import (
    DuplicateSpecError,
    HunterMemoryStore,
    IncompleteSpecSetError,
)
from .hunter_state import SPEC_STATUSES
from .http_history_contract import (
    GET_HTTP_ARTIFACT_DESCRIPTION,
    SEARCH_HTTP_HISTORY_DESCRIPTION,
)
from .spec_contract import (
    MAX_DISCRIMINATORS,
    MIN_DISCRIMINATORS,
    SKILL_CONCRETISED_PROCEDURE_FIELDS,
    Discriminator,
    SkillConcretisedProcedure,
    SpecProvenance,
    TargetIdentity,
    spec_identifier,
)
from polymerhus.app.memory.tool_contract import (
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
    # #304: an unaccepted/unavailable KB answer is marked degraded. Kept on the
    # tolerant local envelope so the real tool's `degraded` flag is not dropped
    # (extra="ignore" would otherwise strip it) and the model sees it.
    degraded: bool = False

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


# --- the harness-bound hunt key (S3 8.9, supersedes the #298 config key) ------

# The hunt's own memory identity is NOT a request field: it is BOUND at the
# tool/handle construction (the harness holds the loop payload at dispatch) so
# the hunter's store tools can only ever address the hunt's own loop. The key is
# the loop dispatch id `<unit_name>__<loop_id>` (S3 8.9). The model authors each
# spec's `fault_keyword` / `strategy_keyword` (the derived file-name identity
# axes) but never the destination hunt key. A tool constructed without a bound
# key degrades to a denoted invalid_args, never a silent degenerate path.

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


class SpecWrite(BaseModel):
    """The `TestImplementationSpec` write payload (#236, F-015, F-025).

    The persisted shape is the pod's canonical `TestImplementationSpec`: the
    nested `target_identity`, `provenance`, and `skill_concretised_procedure`
    are the SAME typed models the pod reads, not open dictionaries.
    `extra="forbid"` makes an invented field a coded rejection instead of a
    silently dropped value, so the tool schema and the stored record cannot
    drift.

    F-025: ONE spec per `hunts_store` write. `status` and `discriminators` are
    REQUIRED. `discriminators` is the ordered tuple of the instance values the
    hunter separated this slot on; the store derives the identity
    `<class>__<value>__<value>` from it. The target identity is BOUND by the
    tool from the dispatch context; the hunter may author it only as a
    degraded-path override. The remaining fields are optional.
    """

    status: str = Field(
        description="The lifecycle verbatim: 'hypothesised' | 'ratified' | "
                    "'dropped'. Required.")
    discriminators: list[Discriminator] = Field(
        min_length=MIN_DISCRIMINATORS,
        max_length=MAX_DISCRIMINATORS,
        description="The ordered discrimination instances, most discriminating "
                    "first: two to four {axis, value} entries in DISCRIMINATE "
                    "order. The store derives the spec identity from the values "
                    "and the class. Required on the first write.")
    target_identity: TargetIdentity | None = Field(
        default=None,
        description="Optional: the target identity {'url', 'unit_id'}. The "
                    "symbolic layer binds it from the dispatch context; author it "
                    "only when the symbolic layer could not resolve a URL. The pod "
                    "INIT-rejects an empty `url`.")
    verification_symptoms: list[str] = Field(
        default_factory=list,
        description="Optional: the observable symptoms that verify the fault.")
    assumptions: list[str] = Field(
        default_factory=list,
        description="Optional: the technical assumptions the pod may falsify.")
    rationale: str = Field(
        default="", description="Optional: the vulnerability-level rationale.")
    parent_spec_ref: str | None = Field(
        default=None,
        description="Optional: the parent spec id when this entry is a "
                    "triager-minted variant; null for an original spec.")
    skills: list[str] = Field(
        default_factory=list,
        description="Optional: flat skill names the downstream pod should carry "
                    "for this test spec. Never a path or a meta skill.")
    skill_concretised_procedure: SkillConcretisedProcedure | None = Field(
        default=None,
        description="Optional: the target-specific concretisation of the loaded "
                    "abstract procedure. The triager diffs the executed probe "
                    "against it.")
    provenance: SpecProvenance = Field(
        default_factory=SpecProvenance,
        description="Optional: the typed dispatch provenance (loop_id, unit_id, "
                    "the two classes, baseline_ref, source_recon_refs, "
                    "assumption_ref, playbook).")
    merged_from: list[str] = Field(
        default_factory=list,
        description="Optional: the derived identities this survivor absorbed in "
                    "WELL-FORMEDNESS. The absorbed identities are dropped; the "
                    "survivor's own discriminators stay unchanged.")

    @model_validator(mode="after")
    def _unique_discrimination_axes(self):
        axes = [item.axis for item in self.discriminators]
        if len(set(axes)) != len(axes):
            raise ValueError(
                f"duplicate discrimination axis in {axes!r}; each axis names "
                "one separation dimension")
        return self

    model_config = ConfigDict(extra="forbid")


def _contract_type(field) -> str:
    """A compact, human-readable type for one pydantic field."""
    annotation = field.annotation
    origin = typing.get_origin(annotation)
    if origin is list:
        args = typing.get_args(annotation)
        inner = _contract_type_name(args[0]) if args else "Any"
        return f"list[{inner}]"
    if origin in (typing.Union, types.UnionType):
        args = typing.get_args(annotation)
        return " / ".join(_contract_type_name(arg) for arg in args)
    return _contract_type_name(annotation)


def _contract_type_name(annotation) -> str:
    if annotation is str:
        return "str"
    if annotation is type(None):
        return "null"
    name = getattr(annotation, "__name__", None)
    if name:
        return name
    return str(annotation).replace("typing.", "")


def _contract_row(field, name: str) -> str:
    """One markdown row for a pydantic field, with the field's own description."""
    required = "required" if field.is_required() else "optional"
    description = str(field.description or "").strip()
    for prefix in ("Optional: ", "Required. "):
        if description.startswith(prefix):
            description = description[len(prefix):]
    description = description.replace(" Required.", "").replace("|", "\\|")
    if len(description) > 140:
        description = description[:137].rstrip() + "..."
    return f"| `{name}` | `{_contract_type(field)}` | {required} | {description} |"


def render_spec_contract() -> str:
    """The human projection of the writable spec contract.

    The pydantic models are the single source. The prompt names every field,
    its type, its requiredness, and its own description; the request schema
    remains the machine contract. `run_id` and `target_identity` are bound by
    the tool and `spec_id` is derived from the class and the discriminator
    values, so none is model-authored on the normal path.
    """
    lines = [
        "Write exactly one `spec` object per `hunts_store` call. The request "
        "schema is the machine contract; this table is its human projection.",
        "`spec_id` is derived as `<class>__<value>__<value>` from "
        "`provenance.web_vulnerability_class` and the ordered "
        "`discriminators[].value` list; it is never authored. `run_id` and the "
        "target identity are bound by the tool.",
        "",
        "The nested `discriminators`, `target_identity`, "
        "`skill_concretised_procedure`, and `provenance` objects are expanded "
        "below.",
        "",
        "| field | type | required | meaning |",
        "|---|---|---|---|",
    ]
    for name, field in SpecWrite.model_fields.items():
        if name == "status":
            lines.append("| `status` | `\"hypothesised\" / \"ratified\" / "
                         "\"dropped\"` | required | The lifecycle verbatim. |")
            continue
        if name == "discriminators":
            lines.append(
                "| `discriminators` | `list[Discriminator]` | required | The "
                "ordered 2-4 discrimination instances, most discriminating "
                "first. |")
            for dname, dfield in Discriminator.model_fields.items():
                lines.append(_contract_row(dfield, f"discriminators[].{dname}"))
            continue
        if name == "target_identity":
            lines.append(
                "| `target_identity` | `TargetIdentity` | bound / optional | "
                "Bound by the symbolic layer from the dispatch context. |")
            for tname, tfield in TargetIdentity.model_fields.items():
                lines.append(_contract_row(tfield, f"target_identity.{tname}"))
            continue
        if name == "skill_concretised_procedure":
            lines.append(
                "| `skill_concretised_procedure` | "
                "`SkillConcretisedProcedure` | optional | The target-specific "
                "concretisation of the loaded abstract procedure. |")
            for sname, sfield in SkillConcretisedProcedure.model_fields.items():
                lines.append(_contract_row(
                    sfield, f"skill_concretised_procedure.{sname}"))
            continue
        if name == "provenance":
            lines.append(
                "| `provenance` | `SpecProvenance` | optional | The typed "
                "dispatch provenance. |")
            for pname, pfield in SpecProvenance.model_fields.items():
                row = _contract_row(pfield, f"provenance.{pname}")
                if pname == "run_id":
                    row = row.replace("| optional |", "| bound |")
                lines.append(row)
            continue
        lines.append(_contract_row(field, name))
    return "\n".join(lines)


class HuntsStoreArgs(BaseModel):
    """The `hunts_store` tool's ARGS contract: `read` / `write` / `finalize`.

    F-025: the WRITE payload is exactly ONE `spec` object, never a batch. The
    spec carries its `status` (`hypothesised | ratified | dropped`) and the
    ordered `discriminators` (two to four `{axis, value}` instances); the
    symbolic layer DERIVES `<class>__<value>__<value>.yaml` from them, so they
    are never separate request fields whose requiredness the surface could
    omit. A payload missing a derivation input, a `spec_id`, or a resolvable
    target identity is a coded `hunts_store_write_rejected` naming the field.
    The write upserts the identity in place; a re-author is not a duplicate.

    FINALIZE closes the set: it requires every produced spec to be `ratified`
    or `dropped`, then writes the durable terminal-set record. A zero-spec
    hunt finalizes with no spec. A write after finalize is rejected.

    `read` filters by optional `statuses`/`attributes`, never the whole surface
    (spec 5). The hunt's OWN loop dispatch id (`hunt_key`,
    `<unit_name>__<loop_id>`, S3 8.9) is BOUND at the tool construction - it is
    never a request field, so the hunter can only address its own loop.

    The authored spec body is the reduced D4 surface at every status (S3 8.6).
    Its `target_identity` is the target's identity object - `{"url": <base
    url>, "unit_id": <L1 identity>}`: the `url` is the base URL the pod probes
    (author it from the projected L0 attack surface), `unit_id` the
    kind-qualified L1 service/system identity that surfaces alongside it.
    A spec whose `target_identity.url` is absent is INIT-rejected by the pod."""

    command: Literal["read", "write", "finalize"] = Field(
        description="The operation: 'read', 'write', or 'finalize' (required).")
    # -- read path -----------------------------------------------------------
    statuses: list[str] = Field(
        default_factory=list,
        description="Read filter: keep only specs with one of these statuses.")
    attributes: list[str] = Field(
        default_factory=list,
        description="Read projection: return only these attributes per spec.")
    # -- write path (exactly one spec) ---------------------------------------
    spec: SpecWrite | None = Field(
        default=None,
        description="Write payload: exactly ONE spec object. Required on "
                    "`write`; omit on `read` and `finalize`. The spec's "
                    "`status` and `discriminators` are required; all other "
                    "SpecWrite fields are optional. The file name "
                    "`<class>__<value>__<value>.yaml` is DERIVED (do not author "
                    "`spec_id`).")

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
                    "implicit_test_primitive | freeform | phase_summary "
                    "(the interposed pass exit; name the note phase:<state>, "
                    "e.g. phase:well_formedness).")
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
    """The one-spec write/read/finalize seam over `HunterMemoryStore`.

    F-025: each `write` carries exactly ONE `spec`; the tool upserts it by its
    derived identity. `finalize` is the one whole-set gate: it checks every
    produced spec is `ratified` or `dropped` and writes the durable terminal
    record, even for a zero-spec hunt. Reads degrade to an empty set (O4);
    genuine write failures raise to the harness (O3); an absent store degrades
    fail-open. #209: a call omitting the required `command` with write-intent
    fields is a CODED teaching rejection (never a bare validation error) - the
    binding and translation are the shared `tool_contract.StoreToolBase`."""

    name: str = "hunts_store"
    description: str = (
        "The hunt's spec-set seam, bound to THIS hunt. Commands: read / write / "
        "finalize.\n"
        "write carries exactly ONE spec object. `status` and `discriminators` "
        "(two to four ordered {axis, value} entries) are required on the first "
        "write. The identity is derived as `<class>__<value>__<value>`; never "
        "send `spec_id`. The target identity is bound; author it only when the "
        "layer could not resolve a URL.\n"
        "finalize requires every produced spec to be ratified or dropped, then "
        "writes the terminal record. A write after finalize is rejected.\n"
        "read takes optional statuses/attributes filters and returns its specs."
    )
    args_schema: type[BaseModel] = HuntsStoreArgs
    _discriminator: str = "command"
    _known_commands: tuple[str, ...] = ("read", "write", "finalize")
    _rejection_name: str = "hunts_store"
    _write_intent_fields: tuple[str, ...] = _HUNTER_WRITE_INTENT_FIELDS
    _require_write_intent: bool = True
    _as_json: bool = True

    def __init__(self, *, store: HunterMemoryStore | None = None,
                 project_id: str = "", hunt_key: str = "",
                 run_id: str = "",
                 target_identity: TargetIdentity | None = None,
                 **kwargs):
        super().__init__(**kwargs)
        self._store = store
        self._project_id = project_id
        self._hunt_key = hunt_key
        self._run_id = run_id
        # The symbolic target identity: bound at dispatch from the loop payload
        # and the project's canonical origin, so the hunter never authors it.
        self._target_identity = target_identity
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
            "detail": "no hunt key is bound to this hunt tool (S3 8.9)",
        })

    def _run(self, **kwargs: Any):
        """Dispatch the third command (`finalize`) alongside read/write.

        The shared base knows only read/write; this seam adds the one durable
        whole-set gate. The typed schema still validates every call first."""
        schema = self.args_schema
        args = schema(**kwargs)
        command = getattr(args, self._discriminator)
        if command == "read":
            return self._read(args)
        if command == "finalize":
            return self._finalize(args)
        return self._write(args)

    def _read(self, args: HuntsStoreArgs) -> str:
        if self._store is None:
            return self._unavailable(args)
        if not self._hunt_key:
            return json.dumps({"specs": [], "error": "invalid_args",
                               "detail": "no hunt key is bound to this hunt "
                                         "tool (S3 8.9)"})
        try:
            specs = self._store.read_specs(
                self._project_id, self._hunt_key,
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
        if not self._hunt_key:
            return self._unbound()
        if args.spec is None:
            return self._write_rejected(
                ["spec"],
                "write takes exactly ONE spec object in `spec` (never a "
                "batch). A set is built by repeated one-spec writes, then "
                "closed by command=finalize. Each spec requires status and "
                "two to four ordered discriminators.")
        try:
            if self._store.has_terminal_set(self._project_id, self._hunt_key):
                return json.dumps({
                    "ok": False,
                    "error": "spec_set_finalized",
                    "detail": "this hunt's spec set is already finalized; a "
                              "late write is not admitted. Read the set to "
                              "inspect it.",
                    "rejected": True,
                })
        except OSError as exc:  # O4: a corrupt terminal record must not be ignored
            return json.dumps({"ok": False, "error": "read_failed",
                               "detail": str(exc)})
        spec = args.spec.model_dump(exclude_unset=True)
        if spec.get("spec_id"):
            return self._write_rejected(
                ["spec_id"],
                "`spec_id` is a DERIVED symbol (the "
                "<class>__<value>__<value> stem); remove it")
        if not spec.get("discriminators"):
            return self._write_rejected(
                ["spec.discriminators"],
                "the spec must carry two to four ordered {axis, value} "
                "discriminator entries; the identity is DERIVED from their "
                "values and the class")
        if spec["status"] not in SPEC_STATUSES:
            return self._write_rejected(
                ["spec.status"],
                f"status must be one of {SPEC_STATUSES}; got "
                f"{spec['status']!r}")
        # The symbolic target identity: the bound value wins. The model may
        # author one only as the degraded-path override when the harness could
        # not resolve a URL.
        if self._target_identity is not None:
            spec["target_identity"] = self._target_identity.model_dump()
        target = spec.get("target_identity")
        if not isinstance(target, dict) or not str(target.get("url") or "").strip():
            return self._write_rejected(
                ["spec.target_identity.url"],
                "no target URL is bound to this hunt and the spec authored "
                "none; the symbolic layer must resolve the project origin before the "
                "first write")
        # F-017: bind the current hunting run id into the spec's typed
        # provenance, so a consumed spec with no terminal PodExport can be
        # attributed to THIS run on resume. The model never authors it.
        provenance = spec.get("provenance")
        if not isinstance(provenance, dict):
            provenance = {}
        if self._run_id:
            provenance.setdefault("run_id", self._run_id)
        spec["provenance"] = provenance
        # Pre-validate the derived identity so a bad tuple is a teaching
        # rejection naming the discriminators, not a bare store ValueError.
        try:
            spec_identifier(
                str(provenance.get("web_vulnerability_class")
                    or provenance.get("canonical_class") or ""),
                spec.get("discriminators") or [],
            )
        except ValueError as exc:
            return self._write_rejected(["spec.discriminators"], str(exc))
        try:
            written = self._store.write_specs(
                self._project_id, self._hunt_key, [spec],
                enforce_complete=False)
        except DuplicateSpecError as exc:
            return json.dumps({"ok": False, "error": "duplicate_spec",
                               "hunt_key": self._hunt_key, "detail": str(exc)})
        except ValueError as exc:
            return json.dumps({"ok": False, "error": "invalid_args",
                               "detail": str(exc)})
        # O3: any other write failure (e.g. OSError) raises to the harness, which
        # warns and keeps serving - never a silent corruption.
        return json.dumps({
            "ok": True,
            "specs": [
                {"spec_id": spec_id, "status": spec["status"], "path": str(path)}
                for (spec_id, path) in written
            ],
        })

    def _finalize(self, args: HuntsStoreArgs) -> str:
        """Close the set, or return the coded missing-identity list."""
        if self._store is None:
            return self._unavailable(args)
        if not self._hunt_key:
            return self._unbound()
        if args.spec is not None:
            return self._write_rejected(
                ["spec"], "finalize takes no spec; it closes the whole set")
        try:
            marker = self._store.finalize_specs(
                self._project_id, self._hunt_key, run_id=self._run_id)
        except IncompleteSpecSetError as exc:
            return json.dumps({
                "ok": False,
                "error": "incomplete_spec_set",
                "fields": ["spec"],
                "missing": list(exc.missing),
                "detail": str(exc),
                "rejected": True,
            })
        except ValueError as exc:
            return json.dumps({"ok": False, "error": "invalid_args",
                               "detail": str(exc)})
        return json.dumps({
            "ok": True,
            "finalized": True,
            "terminal": marker,
            "specs": [
                {"spec_id": spec_id, "status": status}
                for spec_id, status in marker["spec_statuses"].items()
            ],
        })


_NOTES_DESCRIPTION = append_conciseness_directive((
    "The hunt's notes seam, bound to THIS hunt's loop. Commands: read / "
    "write.\n"
    "write sets command=\"write\"; `action` is append | update | delete. "
    "Supply `note_name`, `kind` (hypothesis_refusal | "
    "implicit_test_primitive | freeform | phase_summary), and `body`. "
    "phase_summary is the pass exit: phase:<state>, one per pass; re-iteration "
    "rewrites it with update. `evidence` is prose; structured refs in "
    "`provenance` {source, run_id, verdict_stub, probe_refs}. Missing note -> "
    "note_missing. read matches key/body keyword, latest first."
))


class HunterMemoryNotesHandle:
    """The hunter seam's store handle for the shared `notes` tool.

    It owns the `notes.yaml` destination (via `HunterMemoryStore`) and the
    hunt's OWN loop dispatch id, BOUND at construction (S3 8.9). The shared
    algorithm never sees a path or a store: the destination is derived from
    THIS handle, never a request field."""

    def __init__(self, store: HunterMemoryStore | None, project_id: str,
                 hunt_key: str = ""):
        self._store = store
        self._project_id = project_id
        self._hunt_key = hunt_key

    def read(self, query) -> dict:
        if self._store is None:
            return {"command": query.command, "error": "store_unavailable",
                    "degraded": True}
        if not self._hunt_key:
            return {"notes": [], "error": "invalid_args",
                    "detail": "no hunt key is bound to this hunt tool (S3 8.9)"}
        try:
            notes = self._store.read_notes(
                self._project_id,
                parent_key=self._hunt_key,
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
        if not self._hunt_key or not request.note_name:
            return {"ok": False, "error": "invalid_args",
                    "detail": "write needs a bound hunt key and note_name"}
        try:
            key = self._store.write_note(
                self._project_id, action=request.action, hunt_key=self._hunt_key,
                note_name=request.note_name, kind=request.kind, body=request.body,
                evidence=request.evidence, provenance=request.provenance)
        except ValueError as exc:
            return {"ok": False, "error": "invalid_args", "detail": str(exc)}
        # O3: any other write failure raises to the harness, which warns and
        # keeps serving.
        if key is None:
            return {"ok": False, "error": "note_missing",
                    "hunt_key": self._hunt_key, "note_name": request.note_name}
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
    note_name="note_name",
    kind="kind",
    evidence="evidence",
    passthrough=("provenance",),
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
                   hunt_key: str = "") -> StoreNotesTool:
    """The production builder for the hunter's bound `notes` tool: the shared
    `build_notes_tool` over the hunter's store handle. The `notes.yaml`
    destination and the hunt's own loop dispatch id are derived from the
    handle, never a request field."""
    return build_notes_tool(
        **_hunter_notes_kwargs(HunterMemoryNotesHandle(store, project_id, hunt_key))
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
                 project_id: str = "", hunt_key: str = "",
                 **kwargs):
        super().__init__(
            **_hunter_notes_kwargs(
                HunterMemoryNotesHandle(store, project_id, hunt_key)),
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
            "summary": "kb_query degraded - grounded on the loop payload alone",
            "ontology_explanations": [],
            "provenance_references": [],
            "knowledge_gaps": [f"knowledge base unavailable ({reason})"],
            "notes": "degraded",
            "degraded": True,
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


def _note_seam_gap(tool, detail: str) -> None:
    """Record one degraded live-seam call on a tool's OPTIONAL gap sink (the
    modeller's run-scoped log, S1 5.7). A tool with no sink - the hunter's - is
    unchanged; recording never raises into the turn."""
    sink = getattr(tool, "_gap_sink", None)
    if sink is None:
        return
    try:
        sink.record(detail)
    except Exception:  # noqa: BLE001 - a report must never break a turn
        pass


class ExecTool(BaseTool):
    """The Kali-container exec tool (R2, spec 5): cheap assumption-falsification
    probes inside VERIFY-CLAIMS. `EXEC_TIMEOUT_S` per call; the model chooses
    the command and an optional shorter `timeout_s`. UNBOUNDED at the harness
    level - the model decides when to probe (R2b). The PARTITION GUARD: exec
    probes inform the assumption check and never manufacture a symptom - the
    pod remains the ONLY source of experimental evidence for a ratified spec."""

    name: str = "exec"
    description: str = (
        "Run a target-surface command for assumption-falsification probes in "
        "VERIFY-CLAIMS: curl HTTP probes and read-only inspection. Each call "
        "is bounded by EXEC_TIMEOUT_S; timeout_s may be shorter. A probe "
        "contradicts a load-bearing assumption (technique feasibility, chained "
        "preliminary-vulnerability feasibility, technology-configuration "
        "evidence); it never probes a payload vector and never manufactures a "
        "symptom. With `provenance.baseline_ref`, use the pod replay; a "
        "hand-written curl loses lineage.\n"
        "The target front 5xx rule in your role prompt binds every call."
    )
    args_schema: type[BaseModel] = ExecArgs

    def __init__(self, *, exec_fn: ExecFn | None = None, gap_sink=None,
                 **kwargs):
        super().__init__(**kwargs)
        self._exec_fn = exec_fn
        # The OPTIONAL seam-gap sink: the modeller hands its run-scoped log, so a
        # dead probe seam reaches the run's report. The hunter passes none.
        self._gap_sink = gap_sink

    def _run(self, **kwargs: Any) -> str:
        args = ExecArgs(**kwargs)
        if self._exec_fn is None:
            _note_seam_gap(
                self, "exec_unavailable: the Kali probe seam is not wired")
            return json.dumps({"ok": False, "error": "exec_unavailable",
                               "degraded": True, "command": args.command})
        try:
            result = self._exec_fn(args.command, args.timeout_s)
        except Exception as exc:  # noqa: BLE001 - fail-open, never into the turn
            _note_seam_gap(self, f"exec_failed: {exc}")
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

    def __init__(self, *, http_search_fn=None, project_id: str = "",
                 gap_sink=None, **kwargs):
        super().__init__(**kwargs)
        self._fn = http_search_fn
        self._project_id = project_id
        self._gap_sink = gap_sink

    def _run(self, **kwargs: Any) -> str:
        args = HttpHistorySearchArgs(**kwargs)
        if self._fn is None:
            _note_seam_gap(
                self,
                "http_history_unavailable: the history search seam is not wired")
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
            _note_seam_gap(self, f"http_history_failed: {exc}")
            return json.dumps({"ok": False, "error": "http_history_failed", "detail": str(exc)})
        return json.dumps(result)


class HttpHistoryGetTool(BaseTool):
    """Read-only fetch of one sanitized artifact by id."""

    name: str = "get_http_artifact"
    description: str = GET_HTTP_ARTIFACT_DESCRIPTION
    args_schema: type[BaseModel] = HttpHistoryGetArgs

    def __init__(self, *, http_get_fn=None, project_id: str = "",
                 gap_sink=None, **kwargs):
        super().__init__(**kwargs)
        self._fn = http_get_fn
        self._project_id = project_id
        self._gap_sink = gap_sink

    def _run(self, **kwargs: Any) -> str:
        args = HttpHistoryGetArgs(**kwargs)
        if self._fn is None:
            _note_seam_gap(
                self,
                "http_history_unavailable: the history get seam is not wired")
            return json.dumps({"ok": False, "error": "http_history_unavailable", "degraded": True})
        try:
            result = self._fn(self._project_id, args.artifact_id, False)
        except Exception as exc:  # noqa: BLE001 - fail-open, never into the turn
            _note_seam_gap(self, f"http_history_failed: {exc}")
            return json.dumps({"ok": False, "error": "http_history_failed", "detail": str(exc)})
        return json.dumps(result)


def build_hunter_tools(
    *,
    store: HunterMemoryStore | None = None,
    project_id: str = "",
    hunt_key: str = "",
    run_id: str = "",
    target_identity: TargetIdentity | None = None,
    graph_view_fn: GraphViewFn | None = None,
    kb_fn: KbQueryFn | None = None,
    exec_fn: ExecFn | None = None,
    http_search_fn=None,
    http_get_fn=None,
    suite_tools: Sequence[BaseTool] = (),
    suite_classes: Sequence[str] = (),
    suite_read_fn: Callable[[str], str] | None = None,
    suite=None,
) -> list[BaseTool]:
    """Assemble the bound hunter tool list for the harness `create_agent`
    binding.

    `store` is the per-project `HunterMemoryStore` and `project_id` the hunt's
    project (both bound here - the tool surface is per-hunt); `hunt_key` is the
    hunt's OWN loop dispatch id (`<unit_name>__<loop_id>`, S3 8.9), BOUND here
    (the harness holds it at dispatch, so it is never a request field);
    `graph_view_fn` / `kb_fn` / `exec_fn` are the injected seam bodies (each
    absent degrades fail-open). The suite pair (`skill_list` / `skill_load`,
    S3 8.7) rides the web-vulnerability suite seam: an injected `suite_tools`
    pair wins, else the pair is built over `suite` / `suite_classes` +
    `suite_read_fn` (an empty seam still binds the pair in its fail-open mode,
    so the role is always enabled with an honest class-mapping contract).
    Returns the tools in the spec's surface order: `hunts_store` / `notes` /
    `graph_view` / `kb_query` / `exec` / `skill_list` / `skill_load` /
    `search_http_history` / `get_http_artifact`. `graph_view` is the ONE
    shared read-only L0/L1 tool (#197, `graph_view_tool.build_graph_view_tool`)
    whose contract (schema + query-language primitives + guard + return shape +
    example) rides its description - the old local `GraphViewTool` is REMOVED."""
    from polymerhus.attack.hunting.graph_view_tool import (  # noqa: PLC0415
        build_graph_view_tool,
    )
    from polymerhus.attack.hunting.threat_modeller_tools import (  # noqa: PLC0415
        build_vulnerability_suite_tools,
    )

    if suite_tools:
        skills: list[BaseTool] = list(suite_tools)
    else:
        skills = build_vulnerability_suite_tools(
            classes=suite_classes, read_fn=suite_read_fn, suite=suite)

    return [
        HuntsStoreTool(store=store, project_id=project_id, hunt_key=hunt_key,
                       run_id=run_id, target_identity=target_identity),
        notes_tool_for(store=store, project_id=project_id, hunt_key=hunt_key),
        build_graph_view_tool(graph_view_fn),
        KbQueryTool(kb_fn=kb_fn),
        ExecTool(exec_fn=exec_fn),
        *skills,
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
