"""The analyser pod — a compiled LangGraph subgraph implementing the analyser as
a pure function `f(L0-slice + observations) -> L1-deltas`, written by idempotent
MERGE through `l1_curator` (L1D-22). Mirrors the STYLE of `build_pod_graph`
(agent/recon/pod.py): typed state, node functions, and three injected
side-effecting collaborators so the graph is unit/integration testable without a
live LLM.

The recon pod's `configurator/execute/gate/parser` tool-invocation machinery has
no analog here (the analyser runs no external tool — its "execute" is a read of
the L0 slice), so the graph is the focused `read -> analyse -> curate` flow the
pure-function contract implies. Phase-B reflection and backward-recon requests
(interface B) slot in later as additional edges without re-cutting this.

Fail-open throughout (mirrors orchestrator_agent / steel_client degrade): a read,
LLM, or curate error degrades that node to an empty result and never crashes the
caller — an LLM error yields an empty delta batch, so nothing is written but the
run still completes.
"""
from __future__ import annotations

import logging
from typing import TypedDict

from langgraph.graph import StateGraph, START, END
from pydantic import BaseModel

from agent.recon.analysis.analyser_types import L1DeltaBatch
from agent.recon.analysis.l1_types import Provenance

logger = logging.getLogger(__name__)

# Cap on L0 nodes serialized into the analyser prompt, mirroring pod._MAX_TRIAGE_ASSETS:
# a huge project graph would otherwise blow the model's context window.
import os
_MAX_L0_NODES = int(os.environ.get("MAX_ANALYSER_L0_NODES", "400"))


class AnalyserExport(BaseModel):
    """The analyser pod's result: how many L1 deltas were written, plus an error
    string when a node degraded (fail-open). `enrichment` carries the per-category
    FR-ENRICH counts when the analyser proposed enrichment deltas."""

    services_written: int = 0
    systems_written: int = 0
    aggregates_written: int = 0
    enrichment: dict | None = None
    error: str | None = None


class AnalyserState(TypedDict, total=False):
    project_id: str
    run_id: str
    observations: list[dict]
    l0_slice: dict
    model: str | None
    batch: L1DeltaBatch
    export: AnalyserExport


def _provenance(state: AnalyserState) -> Provenance:
    """System-supplied provenance for every L1 write of this run (the LLM never
    sets it). `job` names the analyser + its run; `model` is the resolved
    analyser model when known."""
    return Provenance(job=f"analyser:{state.get('run_id', '')}", model=state.get("model"), prompt_id=None)


def build_analyser_graph(*, read_fn, analyse_fn, curate_fn):
    """Compile the analyser subgraph, injecting the three collaborators:
      read_fn(project_id) -> l0_slice dict,
      analyse_fn(l0_slice, observations) -> L1DeltaBatch,
      curate_fn(batch, project_id, provenance) -> AnalyserExport.
    The curate collaborator receives the whole proposal `batch` + the system
    `provenance`, so it maps + writes the core deltas AND the enrichment deltas in
    one place (the LLM never sets provenance). Each node is fail-open: an
    exception degrades to an empty result carrying the error, never propagating
    out of the compiled graph.
    """

    def read(state: AnalyserState) -> dict:
        try:
            l0_slice = read_fn(state["project_id"])
        except Exception as exc:  # degrade: analyse an empty slice rather than crash
            logger.warning("analyser.read failed for project=%s", state.get("project_id"), exc_info=True)
            return {"l0_slice": {"nodes": [], "links": []}, "export": AnalyserExport(error=f"read: {exc}")}
        return {"l0_slice": l0_slice}

    def analyse(state: AnalyserState) -> dict:
        try:
            batch = analyse_fn(state.get("l0_slice") or {}, state.get("observations") or [])
        except Exception as exc:  # the key fail-open: an LLM error -> empty batch -> no L1 write
            logger.warning("analyser.analyse (LLM) failed; degrading to empty deltas", exc_info=True)
            return {"batch": L1DeltaBatch(), "export": AnalyserExport(error=f"analyse: {exc}")}
        return {"batch": batch}

    def curate(state: AnalyserState) -> dict:
        batch = state.get("batch") or L1DeltaBatch()
        try:
            export = curate_fn(batch, state["project_id"], _provenance(state))
        except Exception as exc:  # degrade: a write failure never crashes the run
            logger.warning("analyser.curate failed for project=%s", state.get("project_id"), exc_info=True)
            return {"export": AnalyserExport(error=f"curate: {exc}")}
        # preserve an upstream (read/analyse) error note if one was set
        prior = state.get("export")
        if prior is not None and prior.error and not export.error:
            export = export.model_copy(update={"error": prior.error})
        return {"export": export}

    g = StateGraph(AnalyserState)
    g.add_node("read", read)
    g.add_node("analyse", analyse)
    g.add_node("curate", curate)
    g.add_edge(START, "read")
    g.add_edge("read", "analyse")
    g.add_edge("analyse", "curate")
    g.add_edge("curate", END)
    return g.compile()


# --- default collaborators (real wiring) --------------------------------------

def default_read_fn(project_id: str) -> dict:
    """Read the project's L0 slice (the attack-surface graph). Reuses
    graph_read.fetch_project_graph (traversal-then-fetch is the analyser's job,
    not this coarse read; the MVP reads the project slice and lets the LLM focus
    it)."""
    from agent.recon.graph_read import fetch_project_graph
    return fetch_project_graph(project_id)


# Fallback analyser system prompt, used only if the skill file is unavailable
# (graceful degrade, mirroring _load_triager_skill's "" fallback).
_ANALYSER_SYSTEM_PROMPT = (
    "You are the attack-surface analyser. Given a Layer-0 slice (endpoints, "
    "parameters, headers, technologies, observations), propose Layer-1 service/"
    "system deltas: business-function Services, cross-cutting Systems, and "
    "AGGREGATES assignments (which Service owns which L0 element) with a "
    "confidence and verbatim evidence. Propose nothing you cannot evidence. "
    "Return empty lists if the slice supports no confident judgment."
)

# How to reference an L0 element in an `aggregates` / `surfaces_at` proposal. The
# analyser LLM must set `l0.label` to the node's TYPE and `l0.identity` to its key
# fields (both read straight off the provided slice nodes), NOT put a value in the
# label. Injected into the analyser prompt because the LLM otherwise mislabels
# (observed live: it put a URL in `label`, and the safe-label guard dropped the
# whole assignment).
_L0_REFERENCE_GUIDE = (
    "REFERENCING L0 ELEMENTS (for `aggregates` and `surfaces_at`):\n"
    "Each slice node has a `type` (its L0 label) and `properties` (its fields). "
    "To reference it, set `l0.label` = that node's `type` (e.g. 'Endpoint'), and "
    "`l0.identity` = ONLY the node's identity key fields (omit project_id). The L0 "
    "identity keys per label are:\n"
    "- BaseURL: {url}\n"
    "- Endpoint: {path, method, baseurl}\n"
    "- Parameter: {name, position, endpoint_path, baseurl}\n"
    "- Header: {name, value, baseurl}\n"
    "- Technology: {name, version}\n"
    "- Certificate: {subject_cn}\n"
    "NEVER put a value (like a URL string) in `l0.label`; the label is the node "
    "TYPE. Only reference L0 elements that actually appear in the provided slice."
)

_ANALYSER_SKILL: str | None = None


def _load_analyser_skill() -> str:
    """The analyser system prompt = the analyser-service-system-reasoning skill,
    which synthesises the `overthink` + `critical-thinking-logical-reasoning`
    disciplines for proposing L1 deltas. Single-sourced from
    skills/analysis/analyser/SKILL.md (mirrors _load_triager_skill, pod.py:415):
    YAML frontmatter stripped, cached, and degraded to the inline
    _ANALYSER_SYSTEM_PROMPT fallback if the file is unavailable, so a missing
    mount never crashes the analyser.

    (FR-SKILLIF will generalise this + _load_triager_skill into one skill_for.)"""
    global _ANALYSER_SKILL
    if _ANALYSER_SKILL is None:
        from pathlib import Path
        path = (Path(__file__).resolve().parents[3]
                / "skills" / "analysis" / "analyser" / "SKILL.md")
        try:
            text = path.read_text(encoding="utf-8")
            if text.startswith("---"):
                text = text.split("---", 2)[-1].lstrip()  # drop YAML frontmatter
            _ANALYSER_SKILL = text
        except OSError:
            import logging
            logging.getLogger(__name__).warning(
                "analyser skill not found at %s; using inline fallback prompt", path)
            _ANALYSER_SKILL = _ANALYSER_SYSTEM_PROMPT
    return _ANALYSER_SKILL


def default_analyse_fn(l0_slice: dict, observations: list[dict]) -> L1DeltaBatch:
    """Real collaborator: ask the analyser LLM to propose L1 deltas. Mirrors
    default_triage_fn's structured-output pattern (function_calling tolerates the
    open-ended `dict` props/identity fields the strict json_schema path rejects)."""
    from langchain_core.messages import SystemMessage, HumanMessage

    from agent.app.llm.roles import chat_model_for

    llm = chat_model_for("analyser")
    structured_llm = llm.with_structured_output(L1DeltaBatch, method="function_calling")
    from agent.recon.analysis.l1_curator import vocabulary_prompt

    nodes = (l0_slice or {}).get("nodes", [])
    shown = nodes[:_MAX_L0_NODES]
    omitted = len(nodes) - len(shown)
    prompt = (
        f"{vocabulary_prompt()}\n\n"
        f"{_L0_REFERENCE_GUIDE}\n\n"
        f"L0 slice ({len(nodes)} nodes"
        + (f", showing first {len(shown)}, {omitted} omitted" if omitted else "")
        + f"): {shown}\n"
        f"Observations: {observations}\n"
        "Propose L1 deltas (services, systems, aggregates, and enrichment: "
        "data_items, surfaces_at, data_flows, data_relationships, system_edges)."
    )
    messages = [SystemMessage(content=_load_analyser_skill()), HumanMessage(content=prompt)]
    return structured_llm.invoke(messages)


def default_curate_fn(services, systems, aggregates, project_id: str) -> AnalyserExport:
    """Real collaborator: write the deltas through the L1 sole-writer (idempotent
    MERGE). Services/Systems first, then AGGREGATES edges (their MATCHed L0
    targets must already exist from recon)."""
    from agent.recon.analysis import l1_curator

    services_written, systems_written = l1_curator.l1_curate(services, systems, project_id)
    aggregates_written = l1_curator.write_aggregates(aggregates, project_id)
    return AnalyserExport(
        services_written=services_written,
        systems_written=systems_written,
        aggregates_written=aggregates_written,
    )


def default_curate_with_enrichment_fn(batch, project_id: str, provenance) -> AnalyserExport:
    """Full curate: the core deltas (services/systems/aggregates) plus the
    FR-ENRICH deltas (DataItems, SURFACES_AT, PRODUCES/CONSUMES, DataRelationships,
    System edges), all mapped from one analyser `batch` with system provenance and
    written through the L1 sole-writer. Used when the analyser proposes enrichment
    alongside assignment. Seeds the DataRelationship catalogue (idempotent)."""
    from agent.recon.analysis import l1_curator
    from agent.recon.analysis.analyser_types import (
        enrichment_proposals_to_deltas, proposals_to_deltas,
    )

    services, systems, aggregates = proposals_to_deltas(batch, provenance)
    export = default_curate_fn(services, systems, aggregates, project_id)

    enrich_deltas = enrichment_proposals_to_deltas(batch, provenance)
    if any(enrich_deltas.values()):
        l1_curator.seed_data_relationship_kinds(project_id)
        counts = l1_curator.enrich(project_id, **enrich_deltas)
        export = export.model_copy(update={"enrichment": counts})
    return export


# The default compiled analyser pod (real collaborators). The curate collaborator
# is the full one: it writes the core deltas AND the FR-ENRICH deltas.
analyser_graph = build_analyser_graph(
    read_fn=default_read_fn, analyse_fn=default_analyse_fn,
    curate_fn=default_curate_with_enrichment_fn,
)


def run_analyser(
    project_id: str,
    run_id: str,
    observations: list[dict] | None = None,
    *,
    graph=None,
) -> AnalyserExport:
    """Convenience: invoke the compiled analyser pod for a project and return its
    export. Synchronous (no async collaborators in the default wiring); a caller
    on the event loop should offload via asyncio.to_thread, like run_job."""
    graph = graph or analyser_graph
    result = graph.invoke(
        {"project_id": project_id, "run_id": run_id, "observations": observations or []}
    )
    return result["export"]
