"""Integration tier: the hunt-orchestrator LLM-local artifacts catalogue C13-C22
(hunting-orchestrator-llm-artifacts-spec.md sections 3-7).

The contract predicates exercise the four LLM-local artifact surfaces the spec
owns, with every out-of-tree collaborator injected: the reason stretch's
symbolic render (projection / materialisation / fold family -> `GateInput` ->
`_compose_gate_prompt`), the tool surface bound onto the orchestrator turn
(`build_orchestrator_tool_surface` -> the six D67-04 tools, fail-open per
seam), the skill mounts (`_gate_skill` / `_rematch_skill` -> the mounted
SKILL.md files), the observability (`orchestrator_tracing`, fake langfuse), and
the ORDER/topology invariants (no new graph nodes, no schema change). The
reason stretch's materialisation / fold-family maps resolve from the REAL
fault-KB catalogue (`data/fault-kb.yaml`, 170 entries) where the predicate is
success, exactly as `arun_orchestration` loads them; the read seams are spy
read_fns and the gate is a fixture `reason_fn` - the tier touches no live model
and no live database.
"""
import asyncio
import sys
import types
import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver

from polymerhus.attack.hunting.actors import (
    HuntOrchestratorActor,
    build_orchestrator_tool_surface,
)
from polymerhus.attack.hunting.fault_kb import load_fold_families, load_materialisation
from polymerhus.attack.hunting.hunt_orchestrator import (
    DeliveredCandidate,
    DispatchResult,
    EnvisionedDirection,
    GateDecision,
    GateInput,
    HuntConfig,
    MatchVerdict,
    OrchestratorReport,
    OrchestratorTools,
    ReadOnlyGraphView,
    ReadOnlyGraphViewError,
    TOOL_SURFACE,
    Witness,
    mint_hunt_config,
    revival_key,
    run_orchestration,
)
from polymerhus.attack.hunting.hunt_store import HuntStore
from polymerhus.attack.hunting.llm import (
    _GATE_SKILL_FALLBACK,
    _REMATCH_SKILL_FALLBACK,
    _compose_gate_prompt,
    _gate_skill,
    _rematch_skill,
    _render_fold_family,
)
from polymerhus.attack.hunting.orchestrator_graph import build_hunting_graph
from polymerhus.attack.hunting.orchestrator_tracing import (
    flush_orchestrator_traces,
    orchestrator_gate_span,
    trace_gate_step,
)
from polymerhus.attack.hunting.unit_projection import EdgeInfo, SystemInfo, UnitProjection, build_projection
from polymerhus.recon.control.targeted import (
    AnalyserReconRequest,
    ReconScope,
    TargetedReconResult,
)

SERVICE_A = "Service:slug:a"

RUN_ID = "run-" + uuid.uuid4().hex[:8]


def _candidate(unit_id: str, fault_class: str, *, verdict: str = "applies",
               llm_witness: str | None = "clause x holds",
               deterministic_witness: str | None = None) -> DeliveredCandidate:
    return DeliveredCandidate(
        unit_id=unit_id,
        fault_class=fault_class,
        applies_witnesses=Witness(deterministic=deterministic_witness, llm=llm_witness),
        match_verdict=verdict,
    )


def _carry(candidate: DeliveredCandidate, *, carried: bool = True) -> EnvisionedDirection:
    return EnvisionedDirection(
        unit_id=candidate.unit_id,
        fault_class=candidate.fault_class,
        carried=carried,
        rationale="fixture rationale from the spec's H1 gate",
        assumptions=["fixture assumption"],
        envisioned_test_primitives=["fixture probe"],
    )


def _ok_dispatch(calls: list | None = None):
    """The fixture hunting agent (IA-2): returns a successful result each call."""
    record = calls if calls is not None else []

    def dispatch(config: HuntConfig, routed=()):
        record.append((config, tuple(routed)))
        return DispatchResult(
            spec_ref=f"spec-{len(record)}",
            pod_result_ref=f"pod-{len(record)}",
            hypothesis_verdict="successful",
            feedback="fixture feedback",
        )

    return dispatch


def _tools(store: HuntStore, *, read_fn=None) -> OrchestratorTools:
    return OrchestratorTools(
        store_reads=store,
        graph_view=ReadOnlyGraphView("project-1", read_fn=read_fn or (lambda cy, p: [])),
    )


def _run(store: HuntStore, candidates, *, dispatch=None, tools=None,
         **kwargs) -> OrchestratorReport:
    return run_orchestration(
        project_id="project-1",
        run_id=RUN_ID,
        candidates=candidates,
        tools=tools or _tools(store),
        dispatch_fn=dispatch or _ok_dispatch(),
        **kwargs,
    )


def _service_a_row() -> dict:
    """One typed Service row behind the read_fn seam: kind Service, a non-empty
    spine, one outgoing Service->System edge (EXPOSED_VIA -> WebPresentation)."""
    return {
        "labels": ["L1Service"],
        "props": {"business_function_slug": "a", "exposure": "public",
                  "service_contract": "a's contract"},
        "edges": [
            {"family": "EXPOSED_VIA", "tlabels": ["L1System"],
             "tprops": {"kind": "WebPresentation"}, "rprops": {}},
        ],
    }


class _FakeGraph:
    """A tiny in-memory L1 behind the graph view's read_fn: the typed Service
    row for the projection reads, an empty surface for the index-cards read,
    and the option to raise on every read (the C16 projection degradation)."""

    def __init__(self, unit_row: dict | None = None, *, raise_on_read: bool = False):
        self._unit_row = unit_row
        self._raise_on_read = raise_on_read

    def read(self, cypher, params):
        if self._raise_on_read:
            raise RuntimeError("graph read failed (fixture)")
        if "type(dr) AS family" in cypher:
            return []
        if "collect({family: type(r)" in cypher:
            return [self._unit_row] if self._unit_row is not None else []
        return []  # the index-cards surface read: an empty project view


def _gate_input() -> GateInput:
    return GateInput(candidates=[
        DeliveredCandidate(
            unit_id=SERVICE_A, fault_class="CWE-352",
            applies_witnesses=Witness(deterministic="clause-1", llm="matches"),
            match_verdict="applies",
        ),
    ])


# --- C13: the gate skill mount resolves (success) -----------------------------

def test_gate_skill_mount_serves_the_cognitive_architecture():
    """`_gate_skill()` serves the mounted SKILL.md (frontmatter stripped), not
    the fallback, and the body carries the spec 3.2 cognitive-architecture
    markers: backward-from-end, the four consecutive sub-problems,
    hypothesise-and-verify, prune-only-on-positive, the emit contract."""
    body = _gate_skill()
    assert not body.startswith("---")                      # frontmatter stripped
    assert len(body) > len(_GATE_SKILL_FALLBACK)           # the mount, not the fallback
    assert "work backward" in body                         # 3.2.1 orient from the end
    assert "four consecutive sub-problems" in body         # 3.2.2 fixed decomposition
    assert "Hypothesise, then verify" in body              # 3.2.3 hypothesise-and-verify
    assert "Prune ONLY on positive grounds" in body        # 3.2.5 prune-only-on-positive
    assert "Emit the structured GateDecision" in body      # 3.2.6 the emit contract


# --- C14: the rematch skill mount resolves (success) ---------------------------

def test_rematch_skill_mount_serves_the_d2_discipline():
    """`_rematch_skill()` serves the rematch mount, distinct from the gate
    body, pinning the D2 three-valued verdict and the hard depth-1 cap."""
    body = _rematch_skill()
    assert not body.startswith("---")
    assert len(body) > len(_REMATCH_SKILL_FALLBACK)
    assert body != _gate_skill()                           # a distinct mount
    assert "three-valued" in body                          # the D2 verdict
    assert "depth-1 cap" in body                           # the hard cap


def test_actor_composes_system_message_plus_turn():
    """The composed-turn pattern (spec 5): the actor serves each gate / re-match
    turn as [SystemMessage(skill), HumanMessage(per-pair render)]."""
    from langchain_core.messages import HumanMessage, SystemMessage

    from polymerhus.attack.hunting.actors import _GATE_KIND, _REMATCH_KIND
    from polymerhus.app.llm.actor import AgentMessage

    actor = HuntOrchestratorActor("c14-run-1", tools=_tools(HuntStore("/tmp/irrelevant")))
    inp = _gate_input()
    gate_turn = actor._on_message(AgentMessage(kind=_GATE_KIND, payload={"input": inp}), None)
    assert len(gate_turn) == 2
    assert isinstance(gate_turn[0], SystemMessage)
    assert gate_turn[0].content == _gate_skill()
    assert isinstance(gate_turn[1], HumanMessage)
    assert gate_turn[1].content == _compose_gate_prompt(inp)

    rematch_turn = actor._on_message(AgentMessage(kind=_REMATCH_KIND, payload={
        "unit_id": SERVICE_A, "fault_class": "CWE-352",
        "result": TargetedReconResult(correlation_id="c", requester_id="r",
                                      origin="hunting", status="success"),
    }), None)
    assert len(rematch_turn) == 2
    assert isinstance(rematch_turn[0], SystemMessage)
    assert rematch_turn[0].content == _rematch_skill()
    assert isinstance(rematch_turn[1], HumanMessage)


# --- C15: the per-pair render carries projection + materialisation + fold family

def test_reason_stretch_render_carries_projection_materialisation_fold_family(tmp_path):
    """The reason stretch hands the gate a GateInput carrying the unit's typed
    projection, the fault's real materialisation, and the real fold family -
    all resolved from the symbolic layer before the gate fires, and
    `_compose_gate_prompt` renders all three deterministically."""
    store = HuntStore(tmp_path)
    fake = _FakeGraph(_service_a_row())
    seen = {}

    def reason_fn(inp):
        seen["input"] = inp
        return GateDecision(directions=[_carry(inp.candidates[0])])

    report = _run(store, [_candidate(SERVICE_A, "CWE-266")],
                  reason_fn=reason_fn, tools=_tools(store, read_fn=fake.read))
    assert report.hunts_dispatched == 1

    # the real catalogue is the grounding (170 entries, real CWE ids)
    materialisations = load_materialisation()
    assert "CWE-1021" in materialisations and "CWE-352" in materialisations
    assert materialisations["CWE-352"].name == "Cross-Site Request Forgery (CSRF)"

    inp = seen["input"]
    assert len(inp.candidates) == 1                        # one pair per gate turn
    proj = inp.projection
    assert isinstance(proj, UnitProjection)
    assert proj.kind == "Service"                          # typed spine + one edge
    assert proj.spine
    assert proj.edges["EXPOSED_VIA"] == (
        EdgeInfo("EXPOSED_VIA", "WebPresentation",
                 target=SystemInfo(kind="WebPresentation",
                                   props={"kind": "WebPresentation"})),)
    assert inp.materialisation == {"CWE-266": materialisations["CWE-266"]}
    assert inp.fold_family == {"CWE-266": ("CWE-520", "CWE-9")}  # real folded variants

    text = _compose_gate_prompt(inp)
    assert "unit kind: Service" in text
    assert "fault: Incorrect Privilege Assignment" in text
    assert "CWE-520, CWE-9" in text                        # sorted fold ids


def test_fold_family_renders_sorted():
    """The fold-family render is deterministic: ids sorted lexicographically
    whatever order the loader handed them in; an absent family is UNKNOWN."""
    assert _render_fold_family(("fault-x2", "fault-x1", "fault-x10")) == \
        "fault-x1, fault-x10, fault-x2"
    assert _render_fold_family(("CWE-9", "CWE-520")) == "CWE-520, CWE-9"
    assert _render_fold_family(()) == \
        "UNKNOWN (no sub-fault fold family captured under this fault)"


# --- C16: absent / raising symbolic reads degrade per-slot, never abort --------

def test_absent_projection_degrades_to_unknown(tmp_path):
    """A raising projection read_fn degrades ONLY the projection slot: the
    render marks it UNKNOWN (never FALSE), the surviving materialisation /
    fold-family slots stay populated, and the pass still dispatches."""
    store = HuntStore(tmp_path)
    fake = _FakeGraph(_service_a_row(), raise_on_read=True)
    seen = {}

    def reason_fn(inp):
        seen["input"] = inp
        seen["text"] = _compose_gate_prompt(inp)
        return GateDecision(directions=[_carry(inp.candidates[0])])

    report = _run(store, [_candidate(SERVICE_A, "CWE-266")],
                  reason_fn=reason_fn, tools=_tools(store, read_fn=fake.read))
    assert report.hunts_dispatched == 1
    inp = seen["input"]
    assert inp.projection is None
    assert inp.materialisation["CWE-266"] is not None      # surviving slots
    assert inp.fold_family["CWE-266"] == ("CWE-520", "CWE-9")
    assert "UNKNOWN (projection read failed or absent)" in seen["text"]
    assert "FALSE" not in seen["text"]


def test_materialisation_failure_degrades_to_unknown(tmp_path, monkeypatch):
    """A fault_class absent from the materialisation map renders UNKNOWN for
    that slot alone; the fold family still renders and the run completes."""
    import polymerhus.attack.hunting.fault_kb as fault_kb

    real_families = load_fold_families()
    monkeypatch.setattr(
        fault_kb, "load_fold_families",
        lambda path=None: {**real_families, "fault-x": ("sub-a", "sub-b")})
    store = HuntStore(tmp_path)
    fake = _FakeGraph(_service_a_row())
    seen = {}

    def reason_fn(inp):
        seen["input"] = inp
        seen["text"] = _compose_gate_prompt(inp)
        return GateDecision(directions=[_carry(inp.candidates[0])])

    report = _run(store, [_candidate(SERVICE_A, "fault-x")],
                  reason_fn=reason_fn, tools=_tools(store, read_fn=fake.read))
    assert report.hunts_dispatched == 1
    inp = seen["input"]
    assert inp.materialisation == {"fault-x": None}        # absent -> degraded slot
    assert inp.fold_family == {"fault-x": ("sub-a", "sub-b")}  # surviving slot
    assert "UNKNOWN (materialisation unavailable for this fault_class)" in seen["text"]
    assert "sub-a, sub-b" in seen["text"]
    assert "FALSE" not in seen["text"]


def test_fold_family_failure_degrades_to_unknown(tmp_path):
    """A folded-variant fault id (a real materialisation-tier entry, no fold
    family captured under it) degrades only the fold-family slot: the
    materialisation still renders and the pass still runs."""
    store = HuntStore(tmp_path)
    fake = _FakeGraph(_service_a_row())
    seen = {}

    def reason_fn(inp):
        seen["input"] = inp
        seen["text"] = _compose_gate_prompt(inp)
        return GateDecision(directions=[_carry(inp.candidates[0])])

    report = _run(store, [_candidate(SERVICE_A, "CWE-647")],
                  reason_fn=reason_fn, tools=_tools(store, read_fn=fake.read))
    assert report.hunts_dispatched == 1
    inp = seen["input"]
    assert inp.materialisation["CWE-647"] is not None      # surviving slot
    assert inp.fold_family == {"CWE-647": None}            # absent key -> degraded
    assert "UNKNOWN (no sub-fault fold family captured under this fault)" in seen["text"]
    assert "FALSE" not in seen["text"]


def test_all_slots_degraded_still_runs(tmp_path):
    """All three symbolic slots degraded at once still assembles the turn, the
    run completes, and the carried direction is dispatched on the reduced
    evidence - each slot renders UNKNOWN, never FALSE, never a prune signal."""
    store = HuntStore(tmp_path)
    fake = _FakeGraph(_service_a_row(), raise_on_read=True)
    seen = {}

    def reason_fn(inp):
        seen["text"] = _compose_gate_prompt(inp)
        return GateDecision(directions=[_carry(inp.candidates[0])])

    report = _run(store, [_candidate(SERVICE_A, "fault-x")],
                  reason_fn=reason_fn, tools=_tools(store, read_fn=fake.read))
    assert report.hunts_dispatched == 1
    assert "UNKNOWN (projection read failed or absent)" in seen["text"]
    assert "UNKNOWN (materialisation unavailable for this fault_class)" in seen["text"]
    assert "UNKNOWN (no sub-fault fold family captured under this fault)" in seen["text"]
    assert "FALSE" not in seen["text"]


# --- C17: exactly five tools bound; no HuntConfig writer ----------------------

def test_actor_binds_exactly_the_five_tools(tmp_path, monkeypatch):
    """The agent the actor builds binds EXACTLY the five tool names of
    `TOOL_SURFACE` - never a sixth HuntConfig-writing tool."""
    store = HuntStore(tmp_path)
    seen = {}

    async def fake_run_session_agent(*args, **kwargs):
        seen["tools"] = list(kwargs.get("tools") or [])
        return None

    monkeypatch.setattr("polymerhus.app.llm.actor.run_session_agent",
                        fake_run_session_agent)

    async def _drive():
        actor = HuntOrchestratorActor(
            RUN_ID, tools=_tools(store), project_id="project-1",
            checkpointer=InMemorySaver(), observe=False,
        )
        await actor._ensure_started()
        await actor._task
        return actor

    asyncio.run(_drive())
    names = {t.name for t in seen["tools"]}
    assert names == set(TOOL_SURFACE)                      # exactly the five, no sixth
    assert len(seen["tools"]) == 5
    assert all(hasattr(t, "invoke") for t in seen["tools"])  # real tool callables


def test_no_hunt_config_writing_tool_on_the_surface(tmp_path):
    """The built surface is exactly `TOOL_SURFACE`: every tool's reply shape is
    a recon / store / graph / acknowledgment object, never a `HuntConfig`
    dump - no tool writes or fabricates a `HuntConfig` (the mint stays
    deterministic at dispatch, downstream of the `mint_hunt_config` tool, which
    only carries the model's emission)."""
    store = HuntStore(tmp_path)
    fake = _FakeGraph(_service_a_row())
    tools = _tools(store, read_fn=fake.read)
    surface = build_orchestrator_tool_surface(tools, run_id=RUN_ID,
                                              project_id="project-1")
    by_name = {t.name: t for t in surface}
    assert set(by_name) == set(TOOL_SURFACE)
    # each tool's reply is a store/graph/acknowledgment shape, never a HuntConfig
    out = by_name["read_memory_hunts"].invoke(
        {"revival_key": revival_key(SERVICE_A, "CWE-352")})
    assert "configs" in out
    out = by_name["read_memory_notes"].invoke(
        {"revival_key": revival_key(SERVICE_A, "CWE-352")})
    assert "notes" in out
    out = by_name["record_note"].invoke(
        {"revival_key": revival_key(SERVICE_A, "CWE-352"), "note": "n"})
    assert out["recorded"] is True
    out = by_name["mint_hunt_config"].invoke(
        {"unit_id": SERVICE_A, "vulnerability_classes": [], "research_direction": "csrf"})
    assert out["acknowledged"] is True
    out = by_name["graph_view"].invoke({"cypher": "MATCH (u) RETURN u"})
    assert "rows" in out


# --- C18: a missing seam body degrades the surface, never raises ---------------

def test_absent_graph_view_degrades_the_surface():
    """With the graph-view seam absent the graph_view tool returns a denoted
    error instead of raising; the memory-read and note tools keep real bodies,
    and the actor turn still yields a GateDecision."""
    store = HuntStore("/tmp/irrelevant")
    tools = OrchestratorTools(
        store_reads=store, graph_view=None)
    surface = build_orchestrator_tool_surface(tools, run_id=RUN_ID,
                                              project_id="project-1")
    by_name = {t.name: t for t in surface}
    assert set(by_name) == set(TOOL_SURFACE)
    out = by_name["graph_view"].invoke({"cypher": "MATCH (u) RETURN u"})
    assert out["error"] == "no graph view configured; reading degraded"
    out = by_name["read_memory_hunts"].invoke(
        {"revival_key": revival_key(SERVICE_A, "CWE-352")})
    assert out["configs"] == []


def test_absent_hunt_store_degrades_the_surface(tmp_path):
    """With the hunt-store seam absent the memory-read and note tools all
    return denoted errors instead of raising; the graph-view tool keeps its real
    body."""
    fake = _FakeGraph(_service_a_row())
    tools = OrchestratorTools(
        store_reads=None,
        graph_view=ReadOnlyGraphView("project-1", read_fn=fake.read))
    surface = build_orchestrator_tool_surface(tools, run_id=RUN_ID,
                                              project_id="project-1")
    by_name = {t.name: t for t in surface}
    assert set(by_name) == set(TOOL_SURFACE)
    out = by_name["read_memory_hunts"].invoke(
        {"revival_key": revival_key(SERVICE_A, "CWE-352")})
    assert out["error"] == "no hunt store configured; prior configs unavailable"
    assert out["revival_key"] == revival_key(SERVICE_A, "CWE-352")
    out = by_name["read_memory_notes"].invoke(
        {"revival_key": revival_key(SERVICE_A, "CWE-352")})
    assert out["error"] == "no notes seam configured; notes unavailable"
    out = by_name["record_note"].invoke(
        {"revival_key": revival_key(SERVICE_A, "CWE-352"), "note": "n"})
    assert out["error"] == "no notes seam configured; note not recorded"
    out = by_name["graph_view"].invoke({"cypher": "MATCH (u) RETURN u"})
    assert "rows" in out


# --- C18b: the split memory reads, the mint, and the note tool -----------------

def test_read_memory_hunts_returns_prior_dispatched_configs(tmp_path):
    """`read_memory_hunts` returns the prior dispatched `config` records for the
    revival key, rebuilt from the record's `unit_id` / `fault_class`; an absent
    store degrades to the denoted error."""
    store = HuntStore(tmp_path)
    key = revival_key(SERVICE_A, "CWE-352")
    store.append(RUN_ID, "config", {"unit_id": SERVICE_A, "fault_class": "CWE-352",
                                    "hunt_id": "h1"})
    tools = _tools(store)
    surface = build_orchestrator_tool_surface(tools, run_id=RUN_ID,
                                              project_id="project-1")
    by_name = {t.name: t for t in surface}
    out = by_name["read_memory_hunts"].invoke({"revival_key": key})
    assert out["revival_key"] == key
    assert [r["hunt_id"] for r in out["configs"]] == ["h1"]
    # a different key reads nothing on the same store
    other = by_name["read_memory_hunts"].invoke(
        {"revival_key": revival_key(SERVICE_A, "CWE-9")})
    assert other["configs"] == []


def test_read_memory_hunts_fails_open_when_store_absent():
    """Without the hunt store the `read_memory_hunts` tool returns the denoted
    error instead of raising."""
    tools = OrchestratorTools(back_edge=None, store_reads=None, graph_view=None)
    surface = build_orchestrator_tool_surface(tools, run_id=RUN_ID,
                                              project_id="project-1")
    by_name = {t.name: t for t in surface}
    out = by_name["read_memory_hunts"].invoke(
        {"revival_key": revival_key(SERVICE_A, "CWE-352")})
    assert out["error"] == "no hunt store configured; prior configs unavailable"


def test_read_memory_notes_returns_keyed_notes(tmp_path):
    """`read_memory_notes` returns the `notes` records on the same revival key;
    an absent store fails open to the denoted error."""
    store = HuntStore(tmp_path)
    key = revival_key(SERVICE_A, "CWE-352")
    store.append(RUN_ID, "notes", {"revival_key": key, "note": "track it"})
    tools = _tools(store)
    surface = build_orchestrator_tool_surface(tools, run_id=RUN_ID,
                                              project_id="project-1")
    by_name = {t.name: t for t in surface}
    out = by_name["read_memory_notes"].invoke({"revival_key": key})
    assert out["revival_key"] == key
    assert [r["note"] for r in out["notes"]] == ["track it"]
    other = by_name["read_memory_notes"].invoke(
        {"revival_key": revival_key(SERVICE_A, "CWE-9")})
    assert other["notes"] == []


def test_read_memory_notes_fails_open_when_store_absent():
    """Without the hunt store the `read_memory_notes` tool returns the denoted
    error instead of raising."""
    tools = OrchestratorTools(back_edge=None, store_reads=None, graph_view=None)
    surface = build_orchestrator_tool_surface(tools, run_id=RUN_ID,
                                              project_id="project-1")
    by_name = {t.name: t for t in surface}
    out = by_name["read_memory_notes"].invoke(
        {"revival_key": revival_key(SERVICE_A, "CWE-352")})
    assert out["error"] == "no notes seam configured; notes unavailable"


def test_mint_hunt_config_records_an_emission_not_a_config(tmp_path):
    """`mint_hunt_config` records the model's emission onto the run-local
    `mint_emissions` bucket (unit_id + research_direction + vulnerability_classes)
    and returns the acknowledgment - it never writes a `HuntConfig` object (the
    deterministic module mint stays downstream)."""
    store = HuntStore(tmp_path)
    tools = _tools(store)
    surface = build_orchestrator_tool_surface(tools, run_id=RUN_ID,
                                              project_id="project-1")
    by_name = {t.name: t for t in surface}
    out = by_name["mint_hunt_config"].invoke({
        "unit_id": SERVICE_A,
        "vulnerability_classes": ["CSRF", "IDOR"],
        "research_direction": "csrf on all authed POSTs",
    })
    assert out["acknowledged"] is True
    assert out["recorded_classes"] == 2
    assert len(tools.mint_emissions) == 1
    emission = tools.mint_emissions[0]
    assert emission["unit_id"] == SERVICE_A
    assert emission["research_direction"] == "csrf on all authed POSTs"
    assert emission["vulnerability_classes"] == ["CSRF", "IDOR"]
    # no HuntConfig ever landed in the store from the tool
    assert store.list_records(RUN_ID, "config") == []


def test_mint_hunt_config_fails_open_without_the_emission_seam():
    """With `mint_emissions=None` the `mint_hunt_config` tool returns the
    denoted error instead of raising."""
    tools = OrchestratorTools(back_edge=None, store_reads=None, graph_view=None,
                              mint_emissions=None)
    surface = build_orchestrator_tool_surface(tools, run_id=RUN_ID,
                                              project_id="project-1")
    by_name = {t.name: t for t in surface}
    out = by_name["mint_hunt_config"].invoke(
        {"unit_id": SERVICE_A, "vulnerability_classes": [], "research_direction": "csrf"})
    assert out["error"] == "no mint emissions seam configured; emission not recorded"


def test_record_note_appends_to_the_keyed_notes_kind(tmp_path):
    """`record_note` persists a note to the store's `notes` kind keyed by the
    revival key; an absent store degrades to the denoted error."""
    store = HuntStore(tmp_path)
    tools = _tools(store)
    surface = build_orchestrator_tool_surface(tools, run_id=RUN_ID,
                                              project_id="project-1")
    by_name = {t.name: t for t in surface}
    key = revival_key(SERVICE_A, "CWE-352")
    out = by_name["record_note"].invoke({"revival_key": key, "note": "first"})
    assert out["recorded"] is True
    assert out["revival_key"] == key
    notes = store.list_records(RUN_ID, "notes")
    assert len(notes) == 1
    assert notes[0]["revival_key"] == key
    assert notes[0]["note"] == "first"


def test_record_note_fails_open_when_store_absent():
    """Without the hunt store the `record_note` tool returns the denoted error
    instead of raising."""
    tools = OrchestratorTools(back_edge=None, store_reads=None, graph_view=None)
    surface = build_orchestrator_tool_surface(tools, run_id=RUN_ID,
                                              project_id="project-1")
    by_name = {t.name: t for t in surface}
    out = by_name["record_note"].invoke(
        {"revival_key": revival_key(SERVICE_A, "CWE-352"), "note": "n"})
    assert out["error"] == "no notes seam configured; note not recorded"


# --- C19: the read-only graph view rejects writes through the bound tool -------

def test_graph_view_tool_rejects_write_shaped_requests():
    """A write-shaped cypher through the bound graph_view tool surfaces
    `ReadOnlyGraphViewError` and never reaches the read seam; the view's own
    `merge` still raises (extending C5); a read-shaped request still rides it."""
    def spy_read(cypher, params):
        raise AssertionError("no read should happen on a rejected write")

    view = ReadOnlyGraphView("project-1", read_fn=spy_read)
    tools = OrchestratorTools(back_edge=None, store_reads=None, graph_view=view)
    surface = build_orchestrator_tool_surface(tools, run_id=RUN_ID,
                                              project_id="project-1")
    by_name = {t.name: t for t in surface}
    with pytest.raises(ReadOnlyGraphViewError):
        by_name["graph_view"].invoke(
            {"cypher": "MERGE (n:Thing) SET n.x = 1 RETURN n"})
    with pytest.raises(ReadOnlyGraphViewError):
        view.merge("MATCH (n) MERGE (m) ...")  # write-shaped call through the view

    seen = {}

    def read_ok(cypher, params):
        seen["cypher"] = cypher
        return [{"u": "a"}]

    view2 = ReadOnlyGraphView("project-1", read_fn=read_ok)
    tools2 = OrchestratorTools(back_edge=None, store_reads=None, graph_view=view2)
    surface2 = build_orchestrator_tool_surface(tools2, run_id=RUN_ID,
                                               project_id="project-1")
    out = {t.name: t for t in surface2}["graph_view"].invoke(
        {"cypher": "MATCH (u) RETURN u"})
    assert out == {"rows": [{"u": "a"}]}
    assert seen["cypher"] == "MATCH (u) RETURN u"


# --- C20: the render is pure symbolic mapping before the gate turn -------------

def test_render_precedes_the_gate_turn(tmp_path):
    """The fully rendered GateInput (projection / materialisation / fold family
    populated) is what reaches the gate - the symbolic render completes before
    any model side-effect - and composing the render alone fires no gate."""
    store = HuntStore(tmp_path)
    fake = _FakeGraph(_service_a_row())
    calls: list[GateInput] = []

    def reason_fn(inp):
        calls.append(inp)
        return GateDecision(directions=[_carry(inp.candidates[0])])

    report = _run(store, [_candidate(SERVICE_A, "CWE-266")],
                  reason_fn=reason_fn, tools=_tools(store, read_fn=fake.read))
    assert report.hunts_dispatched == 1
    assert len(calls) == 1
    inp = calls[0]
    assert inp.projection is not None
    assert inp.materialisation["CWE-266"] is not None
    assert inp.fold_family["CWE-266"] == ("CWE-520", "CWE-9")
    # the render on its own never invokes the gate seam
    _compose_gate_prompt(inp)
    assert len(calls) == 1


def test_degenerate_pass_renders_without_firing_the_gate(tmp_path):
    """A degenerate pass that assembles the symbolic render but never reasons
    does not fire the gate seam: the render is pure mapping, and a degraded
    `kb_degraded` state still rides the render while no gate turn happens."""
    from polymerhus.attack.hunting.orchestrator_graph import build_hunting_graph as _build

    store = HuntStore(tmp_path)
    fake = _FakeGraph(_service_a_row())
    gate_fired: list = []
    renders: list[str] = []
    materials = load_materialisation()
    families = load_fold_families()

    def reason_node(state):
        current = state["current"]
        projection = build_projection("project-1", current.unit_id, read_fn=fake.read)
        gate_input = GateInput(
            candidates=[current],
            kb_degraded=state.get("kb_degraded", False),
            kb_evidences=state.get("kb_evidences") or {},
            surface=state.get("surface") or [],
            projection=projection,
            materialisation={current.fault_class: materials.get(current.fault_class)},
            fold_family={current.fault_class: families.get(current.fault_class)},
        )
        renders.append(_compose_gate_prompt(gate_input))
        # degenerate: the render is assembled, the gate seam is never invoked
        return {"directions": [
            EnvisionedDirection(unit_id=current.unit_id, fault_class=current.fault_class)],
            "trail": []}

    def budget_node(state):
        return {"worklist": list(state["directions"]), "phase": "dispatch", "trail": []}

    def dispatch_node(state):
        direction = state["current_direction"]
        return {"trail": [{"kind": "hunt", "revival_key": revival_key(
            direction.unit_id, direction.fault_class)}]}

    initial = {
        "project_id": "project-1",
        "run_id": RUN_ID,
        "phase": "reason",
        "schedule": [_candidate(SERVICE_A, "CWE-266")],
        "current": None,
        "worklist": [],
        "current_direction": None,
        "directions": [],
        "trail": [],
        "kb_evidences": {},
        "kb_degraded": True,
        "surface": [],
        "exhausted_faults": (),
        "gate_fired": gate_fired,
    }
    final = asyncio.run(_build(
        reason_node=reason_node, budget_node=budget_node, dispatch_node=dispatch_node,
    ).compile().ainvoke(initial, {"configurable": {"thread_id": RUN_ID}}))
    assert gate_fired == []                                 # the gate never fired
    assert [t["kind"] for t in final["trail"]] == ["hunt"]  # the pass still completes
    assert len(renders) == 1
    assert "KB grounding: DEGRADED" in renders[0]           # the degraded state rides the render
    assert "CWE-520, CWE-9" in renders[0]


# --- C21: one span per gate turn, session=run_id, fail-open --------------------

def _fake_langfuse(calls):
    """The test_analyser_tracing recipe: a fake `langfuse` module recording
    propagate / observation / span-update / flush calls."""
    mod = types.ModuleType("langfuse")

    @contextmanager
    def propagate_attributes(**kw):
        calls.append(("propagate", kw))
        yield

    @contextmanager
    def _observation(**kw):
        calls.append(("observation", kw))
        span = MagicMock()
        span.update.side_effect = lambda **u: calls.append(("span-update", u))
        yield span

    client = MagicMock()
    client.start_as_current_observation.side_effect = _observation
    client.flush.side_effect = lambda: calls.append(("flush", {}))
    mod.propagate_attributes = propagate_attributes
    mod.get_client = lambda: client
    return mod


def test_orchestrator_gate_span_correlates_to_the_run(monkeypatch):
    """ONE agent span per gate turn named `orchestrator-<run_id[:8]>`,
    session-correlated to the run with the attack/hunting/orchestrator-gate
    tags."""
    calls = []
    monkeypatch.setitem(sys.modules, "langfuse", _fake_langfuse(calls))

    with orchestrator_gate_span("run-abc12345"):
        pass

    kinds = [c[0] for c in calls]
    assert kinds == ["propagate", "observation"]            # one span, no steps
    prop = dict(calls[0][1])
    assert prop["session_id"] == "run-abc12345"
    assert prop["tags"] == ["attack", "hunting", "orchestrator-gate"]
    obs = dict(calls[1][1])
    assert obs["name"] == "orchestrator-run-abc1"           # run_id[:8]
    assert obs["as_type"] == "agent"
    assert obs["input"] == {"run_id": "run-abc12345"}


def test_gate_step_records_pair_and_degraded_slots(monkeypatch):
    """The symbolic-render step nests under the gate span carrying the pair
    identity and the per-slot degraded markers; the gate-decision step carries
    the carried directions."""
    calls = []
    monkeypatch.setitem(sys.modules, "langfuse", _fake_langfuse(calls))

    with orchestrator_gate_span("run-12345678"):
        trace_gate_step("symbolic-render", input={
            "pair": revival_key(SERVICE_A, "CWE-352"),
            "projection": "ok",
            "materialisation": "UNKNOWN",
            "fold_family": "UNKNOWN",
            "kb_degraded": True,
        })
        trace_gate_step("gate-decision", output={
            "directions": [{
                "pair": revival_key(SERVICE_A, "CWE-352"),
                "carried": True,
                "rationale": "plausible",
                "assumptions": [],
                "envisioned_test_primitives": [],
                "vulnerability_classes": [],
            }],
        })

    obs = [c[1] for c in calls if c[0] == "observation"]
    assert [o["name"] for o in obs] == [
        "orchestrator-run-1234", "symbolic-render", "gate-decision"]
    render = obs[1]
    assert render["as_type"] == "span"
    assert render["input"]["pair"] == revival_key(SERVICE_A, "CWE-352")
    assert render["input"]["materialisation"] == "UNKNOWN"
    assert render["input"]["fold_family"] == "UNKNOWN"
    assert render["input"]["kb_degraded"] is True
    updates = [c[1] for c in calls if c[0] == "span-update"]
    assert updates[-1]["output"]["directions"][0]["carried"] is True


def test_orchestrator_tracing_fails_open_when_langfuse_absent(monkeypatch, tmp_path):
    """With Langfuse raising, every helper degrades to a no-op and a full pass
    traces nothing but completes."""
    broken = types.ModuleType("langfuse")

    def boom(*_a, **_k):
        raise RuntimeError("langfuse unavailable")

    broken.get_client = boom
    broken.propagate_attributes = boom
    monkeypatch.setitem(sys.modules, "langfuse", broken)

    with orchestrator_gate_span("run-x"):
        trace_gate_step("symbolic-render", input={})
    flush_orchestrator_traces()  # reaching here without raising is the assertion

    store = HuntStore(tmp_path)
    fake = _FakeGraph(_service_a_row())
    seen = {}

    def reason_fn(inp):
        seen["text"] = _compose_gate_prompt(inp)
        return GateDecision(directions=[_carry(inp.candidates[0])])

    report = _run(store, [_candidate(SERVICE_A, "CWE-266")],
                  reason_fn=reason_fn, tools=_tools(store, read_fn=fake.read))
    assert report.hunts_dispatched == 1
    assert "unit kind: Service" in seen["text"]


# --- C22: no new graph nodes, no schema change ---------------------------------

def test_no_new_graph_nodes():
    """The graph topology stays exactly {supervisor, reason, budget, dispatch}:
    the render lives INSIDE the reason stretch, never as its own node."""
    g = build_hunting_graph(
        reason_node=lambda state: {}, budget_node=lambda state: {},
        dispatch_node=lambda state: {},
    )
    assert set(g.nodes) == {"supervisor", "reason", "budget", "dispatch"}


def test_reason_node_seeds_prior_minted_keys_from_the_ledger(tmp_path):
    """T5 (spec 3.2/3.3 Q11): `_reason_node` seeds each fault's `GateInput` with
    the CURRENT `LoopLedger.minted_config_keys` - a pass whose first fault has
    minted nothing yet fails open to [], and once the first fault's mint lands
    at its unit boundary (strictly after `record_note`), the second distinct
    fault's gate input carries that revival key as the prior minted-config list
    the Loop protocol reflects on. The rendered prompt carries the list."""
    store = HuntStore(tmp_path)
    gate_inputs: list = []
    a = _candidate(SERVICE_A, "CWE-352")
    c = _candidate(SERVICE_A, "CWE-639")

    def reason_fn(inp):
        gate_inputs.append(inp)
        return GateDecision(directions=[_carry(x) for x in inp.candidates])

    report = _run(store, [a, c], reason_fn=reason_fn)

    assert len(gate_inputs) == 2
    assert gate_inputs[0].prior_minted_keys == []           # fresh ledger -> fail-open
    # the second-called fault carries the first fault's minted key as its prior
    # list. The schedule is risk-descending (fault_risk, f8b5203): CWE-639
    # (IDOR) always precedes CWE-352 (CSRF), so the first gate is 639 and the
    # second is 352 - assert the RELATIONSHIP, never the specific key.
    assert len(gate_inputs[1].prior_minted_keys) == 1
    first_key = f"{SERVICE_A}::{gate_inputs[0].candidates[0].fault_class}"
    assert gate_inputs[1].prior_minted_keys == [first_key]
    second_key = gate_inputs[1].prior_minted_keys[0]
    text = _compose_gate_prompt(gate_inputs[1])
    assert "Prior minted-config keys to reflect on" in text
    assert second_key in text
    assert "(none)" not in text.split("Prior minted-config keys")[1].splitlines()[0]
    assert report.ledger.units_done == 2


def test_structured_schemas_and_tool_surface_unchanged():
    """The structural-output schemas and the tool surface compile unchanged
    (the 110-vs-135 regression guard), the reworked `EnvisionedDirection` /
    `HuntConfig` carry the vulnerability-class identity and the hypothesised
    status, and the deterministic mint still attaches the folded sub-fault ids
    to the HuntConfig."""
    assert TOOL_SURFACE == frozenset({
        "read_memory_hunts", "read_memory_notes", "graph_view",
        "mint_hunt_config", "record_note",
    })

    direction = EnvisionedDirection(
        unit_id=SERVICE_A, fault_class="CWE-352", carried=True,
        rationale="r", assumptions=["a"],
        envisioned_test_primitives=["p"], vulnerability_classes=["CSRF"],
    )
    decision = GateDecision(directions=[direction])
    verdict = MatchVerdict(unit_id=SERVICE_A, fault_class="CWE-352", verdict="applies")
    dumped = decision.model_dump()
    assert dumped["directions"][0]["carried"] is True
    assert dumped["directions"][0]["assumptions"] == ["a"]
    assert dumped["directions"][0]["vulnerability_classes"] == ["CSRF"]
    assert verdict.model_dump()["verdict"] == "applies"

    config = mint_hunt_config(
        direction, _candidate(SERVICE_A, "CWE-352"), "hunt-1",
        surface_context={}, prior_hunt_insights=[], tool_registry=[],
        sub_fault_ids=["CWE-520", "CWE-9"],
    )[0]
    assert config.sub_fault_ids == ["CWE-520", "CWE-9"]
    assert config.status == "hypothesised"
    assert config.vulnerability_class == "CSRF"
    assert config.prompt_template.rationale == "r"
    assert config.adversarial_capabilities == []
    assert config.assumptions == []
    assert config.technique_primitives == []


class _ToolFake(BaseChatModel):
    """A one-reply scripted model emitting a NAMED tool call each turn - the
    shape `ToolStrategy(GateDecision | MatchVerdict)` consumes, so the session
    turn's `content` is the parsed pydantic object (test_hunting_actors)."""

    call_name: str
    args: dict = {}

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(
            content="",
            tool_calls=[{"name": self.call_name, "args": self.args,
                         "id": "c1", "type": "tool_call"}],
        ))])

    @property
    def _llm_type(self) -> str:
        return "fake"

    def bind_tools(self, tools, **kwargs):
        return self
