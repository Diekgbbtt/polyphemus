"""The threat modeller's tool layer (S1 5): the bound surface of the role.

Split out of `threat_modeller.py` in T2b (#386). The pass module keeps the gate
tracker, the unit cell, the degradation breaker, and the pass itself; this
module owns the tool surface built over those seams: `hunts_store` (the
threat-model read/write), `notes` (the shared notes tool with the bound
`<unit_name>:<note_name>` key), the HTTP-history read pair, the Kali `exec`
probe, and the web-vulnerability suite pair (`skill_list` / `skill_load`). The
auth store and the project skill arrive through the role's `load_skill` binding
(the recon-orchestrator coupling). Deliberately NOT bound here: `graph_view`
(the unit projection reaches the turn through the pass's context seam),
`kb_query`, the withdrawn fault-KB aid, and any back-edge-to-recon tool.

This module imports no driver and performs no I/O at import (CODING_STANDARD 6).
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from polymerhus.app.memory.tool_contract import (
    NotesFieldMap,
    StoreToolBase,
    build_notes_tool,
)

from .threat_model import GATE_SECTIONS, ModelSections, ModelState
from .threat_model_store import NOTE_KINDS, ThreatModelIdentityError
from .threat_modeller import (
    GATE_HINTS,
    ModellerUnit,
    PassiveGateTracker,
)

logger = logging.getLogger(__name__)

MODEL_SECTIONS: tuple[str, ...] = (
    "technical_sharpening", "trust_model", "assumptions",
    "vulnerabilities", "threats",
)


@dataclass
class ToolSeamGaps:
    """The RUN-scoped log of the modeller's DEGRADED live-tool calls (S1 5.7).

    The `exec` probe and the HTTP-history read pair record here when their live
    seam is unwired or fails (mirroring the web-vulnerability suite seam's
    `record_gap`), and the pass folds the unit's slice into
    `UnitOutcome.context_gaps` - so a run whose Kali seam is dead reports the
    gap instead of a clean model built from the projection alone. The hunter's
    tools carry no sink and are unaffected."""

    gaps: list[str] = field(default_factory=list)

    def record(self, detail: str) -> None:
        self.gaps.append(detail)
        logger.warning("threat modeller tool seam gap: %s", detail)


# --- the `hunts_store` tool for the threat model (S1 5.1) ---------------------

class ModellerHuntsStoreArgs(BaseModel):
    """The modeller's `hunts_store` args contract.

    A write carries `{state, sections}` ONLY: the unit identity, the file name,
    the model id, and every derived symbol are bound at construction and are
    never request fields. The read carries `{cmd, unit_id?, section?}` - no
    `unit_id` reads the bound unit, a `unit_id` reads another unit's model for
    prior insight, a `section` projects one section.
    """

    cmd: Literal["read", "write"] = Field(
        description="The operation: 'read' or 'write' (required).")
    state: str | None = Field(
        default=None,
        description="Write payload: the gate state, one of UNIT_TECHNICAL_SHARP, "
                    "TRUST_MODELLED, TRUST_ASSUMPTIONS_WRITTEN, "
                    "VULNERABILITIES_WRITTEN, COMPLETED.")
    sections: ModelSections | None = Field(
        default=None,
        description="Write payload: the typed section content for that gate. "
                    "Only the section(s) the gate accepts may be set; the store "
                    "rejects a section from another gate.")
    unit_id: str | None = Field(
        default=None,
        description="Read filter: read this unit's model instead of the bound one.")
    section: str | None = Field(
        default=None,
        description="Read projection: return only this section.")

    model_config = ConfigDict(extra="forbid")


_HUNTS_STORE_DESCRIPTION = (
    "Read or write the unit threat model through the per-project threat model "
    "store.\n"
    "cmd='write': pass the gate `state` and the `sections` that gate carries. "
    "The unit identity is BOUND: never pass a unit id, a file name, a model id, "
    "or a path. The states and their sections are: UNIT_TECHNICAL_SHARP "
    "(technical_sharpening), TRUST_MODELLED (trust_model), "
    "TRUST_ASSUMPTIONS_WRITTEN (assumptions), VULNERABILITIES_WRITTEN "
    "(vulnerabilities), COMPLETED (threats; the store computes the risk profile "
    "and runs the completion checker). A section outside the "
    "state's set is rejected; the model state is monotonic, so a later write for "
    "an earlier gate updates that section without regressing the state.\n"
    "cmd='read': pass an optional `unit_id` (default: the unit you are modelling) "
    "and an optional `section` to project one section. Reads are read-only.\n"
    "Every reference field carries an ID, never prose. "
    "`trust_model.trust_agreements[].interface_agreement_refs` names "
    "`technical_sharpening.interface_agreements[].id` (`IA-*`), and "
    "`trust_model.dynamic_state_trust.violations[].maps_to_fault` names an "
    "`assumptions[].fault.id` (`F-*`). The store resolves every reference and "
    "archives a model with an unresolved one."
)


class ModellerHuntsStoreTool(StoreToolBase):
    """The modeller's `hunts_store` binding: the shared store-tool base over the
    bound threat-model store and the harness-bound unit identity."""

    name: str = "hunts_store"
    description: str = _HUNTS_STORE_DESCRIPTION
    args_schema: type[BaseModel] = ModellerHuntsStoreArgs
    _discriminator: str = "cmd"
    _rejection_name: str = "hunts_store"
    _require_write_intent: bool = False
    _as_json: bool = False

    def __init__(self, *, store=None, project_id: str = "", unit_id: str = "",
                 run_id: str = "", unit: "ModellerUnit | None" = None, **data):
        super().__init__(**data)
        self._store = store
        self._project_id = project_id
        self._unit_id = unit_id
        self._run_id = run_id
        self._unit = unit

    @property
    def _bound_project(self) -> str:
        return self._unit.project_id if self._unit is not None else self._project_id

    @property
    def _bound_unit(self) -> str:
        return self._unit.unit_id if self._unit is not None else self._unit_id

    @property
    def _bound_run(self) -> str:
        return self._unit.run_id if self._unit is not None else self._run_id

    @staticmethod
    def _rejected(fields: list[str], detail: str) -> dict:
        """The coded contract rejection (the `coded_teaching_rejection`
        convention): a machine error code plus the field name(s) the model must
        supply - never a silent degenerate write and never a bare raise."""
        return {
            "ok": False, "error": "hunts_store_write_rejected",
            "fields": list(fields), "detail": detail, "rejected": True,
        }

    def _read(self, args: ModellerHuntsStoreArgs) -> dict:
        if self._store is None:
            return {"error": "threat model store unavailable", "degraded": True}
        unit_id = args.unit_id or self._bound_unit
        if not unit_id:
            return {"error": "no unit is bound to this tool and none was given"}
        try:
            if args.section:
                section = self._store.read_section(self._bound_project, unit_id,
                                                   args.section)
                return {"unit_id": unit_id, "section": section}
            model = self._store.read_model(self._bound_project, unit_id)
        except Exception as exc:  # noqa: BLE001 - fail-open read, never a raise
            logger.warning("hunts_store read degraded for %s (%s)", unit_id, exc)
            return {"error": f"hunts_store read degraded: {exc}", "unit_id": unit_id}
        if model is None:
            return {"unit_id": unit_id, "model": None, "sections": [],
                    "detail": "no threat model exists for this unit"}
        return {
            "unit_id": unit_id,
            "state": model.get("state"),
            "sections": [name for name in MODEL_SECTIONS if model.get(name)],
            "model": model,
            "risk_profile": model.get("risk_profile"),
            "validation": model.get("validation"),
        }

    def _write(self, args: ModellerHuntsStoreArgs) -> dict:
        if not self._bound_unit:
            return self._rejected(
                ["unit_id"],
                "no unit is bound to this tool; the gate write cannot derive the "
                "unit directory")
        if args.unit_id:
            return self._rejected(
                ["unit_id"],
                "the unit identity is BOUND to this tool; a write never carries "
                "a unit id - drop the field and retry")
        if args.state is None or str(args.state).strip() == "":
            return self._rejected(
                ["state"],
                "a write needs `state` (one of "
                f"{', '.join(state.value for state in ModelState)})")
        try:
            gate = ModelState(str(args.state).strip())
        except ValueError:
            return self._rejected(
                ["state"],
                f"unknown state {args.state!r}; known: "
                f"{', '.join(state.value for state in ModelState)}")
        sections = (
            args.sections.model_dump(exclude_none=True, mode="json")
            if args.sections is not None else {}
        )
        if not sections:
            return self._rejected(
                ["sections"],
                f"a write needs `sections` (the typed section for the "
                f"{gate.value} gate: {', '.join(GATE_SECTIONS[gate])})")
        allowed = GATE_SECTIONS[gate]
        unexpected = [key for key in sections if key not in allowed]
        if unexpected:
            return self._rejected(
                list(unexpected),
                f"state {gate.value} accepts only {', '.join(allowed)}; got "
                f"{', '.join(sorted(str(key) for key in unexpected))}")
        if self._store is None:
            return {"ok": False, "error": "hunts_store_unavailable",
                    "degraded": True, "state": gate.value}
        try:
            path = self._store.write_sections(
                self._bound_project, self._bound_unit, gate, sections,
                run_id=self._bound_run)
        except ThreatModelIdentityError as exc:
            # the store's coded teaching rejection, re-surfaced verbatim
            return self._rejected(list(exc.fields), str(exc))
        except ValueError as exc:  # pydantic / enum drift in the section body
            return self._rejected(
                ["sections"], f"the {gate.value} sections are unparseable: {exc}")
        # A store write failure (an OSError) raises to the harness (O3, warned
        # and counted), never into the turn silently.
        return {"ok": True, "state": gate.value, "sections": sorted(sections),
                "path": str(path), "hint": GATE_HINTS.get(gate)}


# --- the `notes` tool for the threat model (S1 5.2) --------------------------

_NOTE_ACTIONS = ("append", "update", "delete")

_NOTES_DESCRIPTION = (
    "Read or write the project's episodic notes through the per-project threat "
    "model store's notes file.\n"
    "The note key is BOUND to the current unit: `<unit_name>:<note_name>` - you "
    "supply only the note name, never the unit.\n"
    "Commands: read / write. A write MUST set cmd='write' and an `option` "
    "(append | update | delete); `kind` is one of "
    f"{', '.join(NOTE_KINDS)}. Each reasoning phase ends with ONE episodic note "
    "through this tool: the decision nodes and the rationales of the branches you "
    "took, in prose.\n"
    "A read with `key` (a note name or a `<unit_name>:<note_name>` key) filters "
    "to that note; a read with no key returns the unit's notes, latest-first."
)


class ModellerNotesArgs(BaseModel):
    """The modeller's `notes` args contract: the shared notes algorithm with the
    unit key bound on the handle, so no request field carries the unit."""

    cmd: Literal["read", "write"] = Field(
        description="The operation: 'read' or 'write' (required).")
    option: Literal["append", "update", "delete"] | None = Field(
        default=None, description="The write option.")
    key: str = Field(
        default="", description="Read filter: a note name or a full note key.")
    note_name: str = Field(
        default="", description="The note name (the second half of the key).")
    kind: str = Field(
        default="freeform",
        description=f"The note kind: {', '.join(NOTE_KINDS)}.")
    body: str | None = Field(default=None, description="The note body.")
    note_id: str | None = Field(
        default=None, description="The note identifier for update / delete.")
    evidence: str | None = Field(
        default=None, description="Short prose evidence for the note.")
    attributes: list[str] = Field(
        default_factory=list,
        description="Read projection: return only these attributes per note.")

    model_config = ConfigDict(extra="forbid")


_MODEL_NOTES_FIELD_MAP = NotesFieldMap(
    key=None,
    read_key="key",
    action="option",
    note="body",
    note_id="note_id",
    attributes="attributes",
    note_name="note_name",
    kind="kind",
    evidence="evidence",
)


class ModellerNotesHandle:
    """The modeller seam's store handle for the shared `notes` tool.

    It owns the notes destination (the threat model store's `notes.yaml`) and
    the BOUND unit identity: the shared algorithm derives the key
    `<unit_name>:<note_name>` from THIS handle, never from a request field. The
    hunter-only `phase_summary` kind is refused with a coded rejection - the note
    kinds are the store's, and the harness never raises for one."""

    def __init__(self, store, project_id: str, unit_id: str,
                 unit: "ModellerUnit | None" = None) -> None:
        self._store = store
        self._project_id = project_id
        self._unit_id = unit_id
        self._unit = unit

    @property
    def _bound_project(self) -> str:
        return self._unit.project_id if self._unit is not None else self._project_id

    @property
    def _bound_unit(self) -> str:
        return self._unit.unit_id if self._unit is not None else self._unit_id

    def _unit_name(self) -> str:
        from .threat_model_store import sanitise_unit_name  # noqa: PLC0415

        return sanitise_unit_name(self._bound_unit)

    def read(self, query) -> dict:
        if not self._bound_unit:
            # the sibling store tool returns a coded rejection for an unbound
            # identity; the handle must not raise where it does
            return {"notes": [], "error": "invalid_args",
                    "detail": "no unit is bound to this notes tool"}
        if self._store is None:
            return {"error": "threat model store unavailable", "degraded": True}
        key = query.key or ""
        prefix = self._unit_name()
        if key:
            full = key if key.startswith(f"{prefix}:") else f"{prefix}:{key}"
        else:
            full = prefix
        try:
            notes = list(self._store.read_notes(self._bound_project, full))
        except Exception as exc:  # noqa: BLE001 - O4: read failure -> empty set
            return {"notes": [], "error": "notes read degraded", "detail": str(exc)}
        requested = list(query.attributes)
        out = []
        for record in notes:
            projected = {attr: record.get(attr)
                         for attr in ("key", "note_name", "kind", "body")
                         if record.get(attr) is not None}
            for attr in requested:
                if attr in record:
                    projected[attr] = record[attr]
            out.append(projected)
        return {"key": full, "notes": out}

    def write(self, request) -> dict:
        if self._store is None:
            return {"ok": False, "error": "threat model store unavailable",
                    "degraded": True}
        if request.action not in _NOTE_ACTIONS:
            return {"ok": False, "error": "notes_write_rejected",
                    "fields": ["option"],
                    "detail": f"option must be one of {', '.join(_NOTE_ACTIONS)}"}
        if not request.note_name:
            return {"ok": False, "error": "notes_write_rejected",
                    "fields": ["note_name"],
                    "detail": "a note write needs a note_name; the key "
                              "<unit_name>:<note_name> is derived from it"}
        if request.kind not in NOTE_KINDS:
            # `phase_summary` is the hunter's kind and is NOT available here
            # (S1 5.2): a coded rejection the model can correct.
            return {"ok": False, "error": "notes_write_rejected",
                    "fields": ["kind"],
                    "detail": f"kind must be one of {', '.join(NOTE_KINDS)}; "
                              f"got {request.kind!r}"}
        try:
            key = self._store.write_note(
                self._bound_project, self._bound_unit,
                action=request.action, note_name=request.note_name,
                kind=request.kind, body=request.body,
                evidence=request.evidence)
        except ValueError as exc:
            return {"ok": False, "error": "notes_write_rejected",
                    "detail": str(exc)}
        if key is None:
            return {"ok": False, "error": "note_missing",
                    "note_name": request.note_name}
        return {"ok": True, "key": key}


def build_modeller_notes_tool(store, project_id: str, unit_id: str,
                              unit: "ModellerUnit | None" = None):
    """Build the modeller's bound `notes` tool: the ONE shared notes
    implementation over the unit-bound handle."""
    from .conciseness import append_conciseness_directive  # noqa: PLC0415

    return build_notes_tool(
        ModellerNotesHandle(store, project_id, unit_id, unit),
        args_schema=ModellerNotesArgs,
        field_map=_MODEL_NOTES_FIELD_MAP,
        name="notes",
        description=append_conciseness_directive(_NOTES_DESCRIPTION),
        discriminator="cmd",
        as_json=False,
        rejection_name="notes",
        write_intent_fields=("option", "body", "note_name"),
        require_write_intent=True,
    )


# --- the web-vulnerability suite pair (S1 5.5) --------------------------------

# The assumed suite contract: a skill directory per web-vulnerability class, the
# directory name IS the class the model stores in `web_vulnerability_class`
# (S1 3.4, workflow 3.4). The suite lands with the parallel skills workstream;
# until then this seam is written against the assumed names and degrades
# fail-open, recording the gap instead of breaking the class mapping.

SKILL_LIST_DESCRIPTION = (
    "List the web-vulnerability suite: class parents and variant leaves, with "
    "frontmatter descriptions. The class parent is the directory name for "
    "`web_vulnerability_class`; a variant leaf is assumption-check material. "
    "An unavailable suite degrades to `suite_gap`: keep the canonical name, "
    "leave `web_vulnerability_class` empty, never invent a class."
)

SKILL_LOAD_DESCRIPTION = (
    "Load one suite skill by name from `skill_list` (a class parent or a "
    "variant leaf). An unknown name degrades to a coded `suite_gap`; keep the "
    "canonical name and flag the gap."
)


@dataclass
class VulnerabilitySuiteSeam:
    """The web-vulnerability suite seam behind `skill_list` / `skill_load`.

    `classes` is the assumed suite's skill set (the class parents and the
    variant leaves); `read_fn` is the optional injected skill-body reader (the
    suite's own contract). A
    seam with no classes - the suite has not landed, or its store is empty -
    degrades fail-open: the listing returns an empty class set, the load returns
    the coded gap, and every gap is RECORDED on `gaps` so the run can report the
    degraded class mapping instead of silently inventing one."""

    classes: tuple[str, ...] = ()
    read_fn: Callable[[str], str] | None = None
    gaps: list[str] = field(default_factory=list)

    def record_gap(self, detail: str) -> None:
        self.gaps.append(detail)
        logger.warning("web-vulnerability suite gap: %s", detail)

    def available(self) -> bool:
        return bool(self.classes) and self.read_fn is not None

    def list_classes(self) -> dict:
        if not self.classes:
            self.record_gap("suite_unavailable: no suite class is resolvable")
            return {"skills": [], "suite_gap": True,
                    "error": "suite_unavailable",
                    "detail": "the web-vulnerability suite is not available; "
                              "keep the canonical classes and flag the gap"}
        entries = []
        for name in self.classes:
            description = ""
            if self.read_fn is not None:
                try:
                    description = _frontmatter_description(self.read_fn(name))
                except Exception:  # noqa: BLE001 - a per-entry degrade
                    description = ""
            entries.append({"name": name, "description": description})
        return {"skills": entries, "suite_gap": False}

    def load_class(self, name: str) -> dict:
        if not self.classes:
            self.record_gap("suite_unavailable: no suite class is resolvable")
            return {"ok": False, "error": "suite_unavailable", "suite_gap": True,
                    "detail": "the web-vulnerability suite is not available"}
        if name not in self.classes:
            self.record_gap(f"suite_class_missing: {name!r}")
            return {"ok": False, "error": "suite_class_missing", "suite_gap": True,
                    "detail": f"the suite carries no class {name!r}; keep the "
                              f"canonical name and flag the gap"}
        if self.read_fn is None:
            self.record_gap(f"suite_reader_unavailable: {name!r}")
            return {"ok": False, "error": "suite_reader_unavailable",
                    "suite_gap": True,
                    "detail": "the suite reader is not wired"}
        try:
            body = self.read_fn(name)
        except Exception as exc:  # noqa: BLE001 - fail-open load
            self.record_gap(f"suite_load_failed: {name!r} ({exc})")
            return {"ok": False, "error": "suite_load_failed", "suite_gap": True,
                    "detail": str(exc)}
        return {"ok": True, "name": name, "body": body, "suite_gap": False}


def _frontmatter_description(body: str) -> str:
    """The frontmatter `description` of one skill body, or "" - the listing
    reads each class's own frontmatter, never a hand-written index."""
    if not body or not body.startswith("---"):
        return ""
    end = body.find("\n---", 3)
    if end < 0:
        return ""
    for line in body[3:end].splitlines():
        if line.strip().startswith("description:"):
            return line.split(":", 1)[1].strip().strip("\"'")
    return ""


class _SuiteArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SkillListArgs(_SuiteArgs):
    pass


class SkillLoadArgs(_SuiteArgs):
    name: str = Field(description="The suite class directory name to load.")


class _SkillListTool(BaseTool):
    name: str = "skill_list"
    description: str = SKILL_LIST_DESCRIPTION
    args_schema: type[BaseModel] = SkillListArgs

    def __init__(self, *, suite: VulnerabilitySuiteSeam, **data):
        super().__init__(**data)
        self._suite = suite

    def _run(self, **kwargs: Any) -> dict:
        try:
            return self._suite.list_classes()
        except Exception as exc:  # noqa: BLE001 - fail-open, never into the turn
            self._suite.record_gap(f"suite_list_failed: {exc}")
            return {"skills": [], "suite_gap": True,
                    "error": "suite_list_failed", "detail": str(exc)}


class _SkillLoadTool(BaseTool):
    name: str = "skill_load"
    description: str = SKILL_LOAD_DESCRIPTION
    args_schema: type[BaseModel] = SkillLoadArgs

    def __init__(self, *, suite: VulnerabilitySuiteSeam, **data):
        super().__init__(**data)
        self._suite = suite

    def _run(self, **kwargs: Any) -> dict:
        name = str(kwargs.get("name") or "").strip()
        if not name:
            self._suite.record_gap("suite_load_rejected: empty class name")
            return {"ok": False, "error": "suite_load_rejected", "suite_gap": True,
                    "detail": "skill_load needs the suite class name"}
        return self._suite.load_class(name)


def build_vulnerability_suite_tools(
    *, classes: Sequence[str] = (), read_fn: Callable[[str], str] | None = None,
    suite: VulnerabilitySuiteSeam | None = None,
) -> list[BaseTool]:
    """Build the `skill_list` / `skill_load` pair over the suite seam.

    The suite is the parallel skills workstream's artifact; this binder is the
    client component written against its assumed names. A seam without classes
    binds the same tools in the fail-open mode (coded gaps, recorded), so the
    role is always enabled with an honest class-mapping contract instead of a
    missing tool."""
    seam = suite or VulnerabilitySuiteSeam(
        classes=tuple(classes), read_fn=read_fn)
    return [_SkillListTool(suite=seam), _SkillLoadTool(suite=seam)]


def suite_seam_from_tools(tools: Sequence[Any]) -> VulnerabilitySuiteSeam | None:
    """The suite seam behind an already-built pair (the injected-tools case)."""
    for tool in tools:
        seam = getattr(tool, "_suite", None)
        if isinstance(seam, VulnerabilitySuiteSeam):
            return seam
    return None


# --- the tool surface ---------------------------------------------------------

@dataclass
class ModellerTools:
    """The modeller's tool seams (S1 5).

    `threat_store` is the per-project `ThreatModelStore`; `tracker` is the
    RUN-scoped passive tracker, wrapped once around the store and reset at each
    unit's pass (the actor's captured tools share it); `unit_cell` is the
    retargetable unit identity; `exec_fn` / `http_search_fn` / `http_get_fn` are
    the live probe and HTTP-history seams (each absent degrades fail-open);
    `suite` / `suite_tools` / `suite_classes` / `suite_read_fn` are the
    web-vulnerability suite seam and its injectable pair; `context_provider`
    plus the explicit `projection` / `surface_overview` are the grounding-input
    seams (S1 4.6, 5.6). The auth store and the project skill are NOT seams
    here: they arrive through the role's `load_skill` binding (the
    recon-orchestrator coupling, `app/auth/seams.py`)."""

    threat_store: Any = None
    project_id: str = ""
    run_id: str = ""
    exec_fn: Any = None
    http_search_fn: Any = None
    http_get_fn: Any = None
    suite_tools: Sequence[Any] = ()
    suite_classes: Sequence[str] = ()
    suite_read_fn: Callable[[str], str] | None = None
    suite: VulnerabilitySuiteSeam | None = None
    unit_cell: ModellerUnit | None = None
    # The RUN-scoped passive tracker. The per-run actor captures its tool
    # surface once, so the tracker (and the store wrapper around it) must be
    # shared by every unit's pass and reset at each pass start - a per-pass
    # tracker would leave the captured tool writing through a stale seam.
    tracker: PassiveGateTracker | None = None
    # The grounding inputs (S1 4.6, 5.6): the L1 unit projection and the L1
    # application-surface overview. `context_provider(unit_id)` supplies them per
    # unit when a live source exists; the explicit fields are the direct seam.
    context_provider: Callable[[str], dict] | None = None
    projection: Any = None
    surface_overview: Any = None
    # The RUN-scoped log of the degraded live-tool calls (`exec`, the
    # HTTP-history reads): the surface builder attaches it to those tools and
    # the pass folds the unit's slice into the outcome's `context_gaps`.
    seam_gaps: ToolSeamGaps | None = None


def build_grounding_provider(project_id: str, *, read_fn=None):
    """The run bootstrap's live grounding seam for `ModellerTools` (S1 4.6, 5.6).

    `read_fn` is the raw L1 read seam in the `neo4j_client.read` shape - the
    bootstrap passes its read-only graph view's `read`. Each unit's `projection`
    is read live through `unit_projection.build_projection`, so the pass's turn
    carries the unit's typed facet surface instead of a gap.

    The L1 application-surface overview (R2-15) has no entity yet: the key is
    deliberately left unset, so the pass keeps its own
    "L1 application-surface overview unavailable" gap and the run reports the
    missing source honestly. When the entity lands, this provider reads it here
    and the gap path retires by itself.

    Fail-open: a raising read is the pass's own gap path to record (S1 5.7) -
    the provider never swallows the failure into a fabricated value."""
    def provider(unit_id: str) -> dict:
        from .unit_projection import build_projection  # noqa: PLC0415 - lazy seam

        return {
            "projection": build_projection(project_id, unit_id, read_fn=read_fn),
            # no "surface_overview": R2-15 has not landed (see docstring)
        }

    return provider


def build_modeller_tool_surface(
    project_id: str, unit_id: str, tools: ModellerTools,
) -> dict[str, BaseTool]:
    """Bind the modeller's tool surface for ONE unit (S1 5, 9.2).

    The unit identity and the harness-held run id are bound here, at
    construction: the store tool and the notes tool derive every symbol from
    them, and no request field can address another unit. Each tool is a seam
    holder; a missing seam degrades fail-open (a denoted error in the
    response), never a raise into the turn."""
    from .hunter_tools import (  # noqa: PLC0415
        ExecTool,
        HttpHistoryGetTool,
        HttpHistorySearchTool,
    )

    if tools.seam_gaps is None:
        # ONE sink per tools instance (the suite seam's pattern), so the actor's
        # captured surface records into the same log the pass reads
        tools.seam_gaps = ToolSeamGaps()
    surface: list[BaseTool] = [
        ModellerHuntsStoreTool(
            store=tools.threat_store, project_id=project_id, unit_id=unit_id,
            run_id=tools.run_id, unit=tools.unit_cell),
        build_modeller_notes_tool(tools.threat_store, project_id, unit_id,
                                  tools.unit_cell),
        HttpHistorySearchTool(http_search_fn=tools.http_search_fn,
                              project_id=project_id,
                              gap_sink=tools.seam_gaps),
        HttpHistoryGetTool(http_get_fn=tools.http_get_fn,
                           project_id=project_id, gap_sink=tools.seam_gaps),
        ExecTool(exec_fn=tools.exec_fn, gap_sink=tools.seam_gaps),
    ]
    if tools.suite_tools:
        surface.extend(tools.suite_tools)
        if tools.suite is None:
            # the injected pair carries its own seam: adopt it, so the pass can
            # still read the gaps that lane recorded
            tools.suite = suite_seam_from_tools(tools.suite_tools)
    else:
        if tools.suite is None:
            # ONE seam per tools instance, so the pass can read the gaps it
            # recorded (a fresh seam per surface build would lose them)
            tools.suite = VulnerabilitySuiteSeam(
                classes=tuple(tools.suite_classes),
                read_fn=tools.suite_read_fn)
        surface.extend(build_vulnerability_suite_tools(suite=tools.suite))
    if tools.suite is not None:
        setter = getattr(tools.threat_store, "set_class_names", None)
        if setter is not None:
            setter(tools.suite.classes)
    return {tool.name: tool for tool in surface}
