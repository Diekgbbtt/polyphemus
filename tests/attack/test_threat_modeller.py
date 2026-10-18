"""Unit tier: the threat modeller pass, gates, tools, and tracker (T2, #375).

The harness contract of S1 5-6 and 9.3: the five gate writes, the monotonic
model state, the next-state hint injected in the tool response, the exact tool
surface (no `graph_view`, no `kb_query`, no fault-KB aid, no `replay`), the
coded write rejection, the notes binding with the hunter-only kind refused, the
completion validation call and the invalid-model archive, and the
web-vulnerability suite binding with its fail-open gap.

Every test drives the REAL `ThreatModelStore` on a temporary project root and
the REAL tool surface, through a scripted turn seam - the pass reads the states
passively from the gate writes, so a fake turn that calls the bound tool is the
whole contract.
"""
from __future__ import annotations

import asyncio

import pytest
import yaml

from polymerhus.attack.hunting.threat_model import ModelState
from polymerhus.attack.hunting.threat_model_store import ThreatModelStore
from polymerhus.attack.hunting.threat_modeller import (
    GATE_HINTS,
    TOOL_SURFACE,
    ModellerTools,
    UnitOutcome,
    arun_modeller_pass,
    build_modeller_tool_surface,
    build_vulnerability_suite_tools,
    suite_seam_from_tools,
)

PROJECT = "proj-1"
UNIT = "Service:catalogue-and-discovery"
RUN = "run-1"


@pytest.fixture(autouse=True)
def _no_degraded_backoff(monkeypatch):
    """The breaker's exponential backoff is a runtime protective delay, not a
    behaviour under test here: zero it so a no-decision script does not sleep."""
    monkeypatch.setenv("HUNT_TURN_DEGRADED_BACKOFF_BASE_S", "0")


def _evidence(ref: str = "GET /catalogue") -> dict:
    return {"kind": "request", "ref": ref}


def _payloads() -> dict[str, dict]:
    """The five gate payloads, the minimum the completion checker needs.

    The literal content is the T1 fixture shape (a known-good worked example),
    never derived from the code under test.
    """
    return {
        ModelState.UNIT_TECHNICAL_SHARP: {
            "technical_sharpening": {
                "interface_agreements": [{
                    "id": "ia-1",
                    "statement": "The catalogue endpoint reads the item id from the query.",
                    "confidence": "OBSERVED",
                    "evidences": [_evidence()],
                }],
                "control_flows": [{
                    "id": "cf-1",
                    "statement": "The handler authorises before the lookup.",
                    "confidence": "INFERRED",
                    "evidences": [_evidence("framework default")],
                }],
                "data_flows": [{
                    "id": "df-1",
                    "statement": "The item body is rendered into the product page.",
                    "confidence": "OBSERVED",
                    "evidences": [_evidence()],
                }],
            },
        },
        ModelState.TRUST_MODELLED: {
            "trust_model": {
                "trust_agreements": [{
                    "id": "ta-1",
                    "boundary": "anonymous caller -> catalogue lookup",
                    "interface_agreement_refs": ["ia-1"],
                    "statement": "The lookup trusts the caller's item id.",
                    "confidence": "INFERRED",
                    "evidences": [_evidence()],
                }],
                "dynamic_state_trust": {
                    "states": [{
                        "id": "ds-1",
                        "variables": ["item_id"],
                        "confidence": "OBSERVED",
                        "evidences": [_evidence()],
                    }],
                    "transitions": [{
                        "id": "tr-1",
                        "source": "ds-1",
                        "target": "ds-1",
                        "guard": "any item id",
                        "confidence": "INFERRED",
                        "evidences": [_evidence()],
                    }],
                    "violations": [{
                        "id": "vi-1",
                        "kind": "trust-transition",
                        "statement": "A caller can force the state before the owner check.",
                        "maps_to_fault": "fault-1",
                        "confidence": "ASSUMED",
                        "evidences": [_evidence()],
                    }],
                },
            },
        },
        ModelState.TRUST_ASSUMPTIONS_WRITTEN: {
            "assumptions": [{
                "id": "as-1",
                "statement": "The handler omits the ownership check.",
                "fault": {
                    "id": "fault-1",
                    "label": "improper authorisation on the item lookup",
                    "description": "The handler does not check item ownership.",
                },
                "boundary_ref": "ta-1",
                "confidence": "ASSUMED",
                "evidences": [_evidence("note:catalogue")],
            }],
        },
        ModelState.VULNERABILITIES_WRITTEN: {
            "vulnerabilities": [{
                "id": "v-1",
                "fault_ref": "fault-1",
                "canonical_class": "IDOR",
                "web_vulnerability_class": "idor",
                "characterisation": "An anonymous caller reads another user's item.",
                "confidence": "INFERRED",
                "evidences": [_evidence()],
            }],
        },
        ModelState.COMPLETED: {
            "failure_modes": [{
                "id": "fm-1",
                "vulnerability_ref": "v-1",
                "mode": "read of another tenant's item",
                "feasibility": "feasible",
                "feasibility_rationale": "The id is caller-supplied.",
                "confidence": "INFERRED",
                "evidences": [_evidence()],
            }],
            "loops": [{
                "fault_ref": "fault-1",
                "vulnerability_ref": "v-1",
                "failure_mode_refs": ["fm-1"],
                "canonical_class": "IDOR",
                "web_vulnerability_class": "idor",
                "likelihood": "high",
                "likelihood_rationale": "An anonymous caller controls the id.",
                "risk_factors": {
                    "attack_vector": "network",
                    "attack_requirements": "none",
                    "privileges_required": "none",
                    "complexity": "low",
                },
                "confidence": "INFERRED",
                "evidences": [_evidence()],
            }],
        },
    }


class _ScriptedTurns:
    """The fake turn seam: each state's turn writes its gate through the BOUND
    `hunts_store` tool (never the store directly), so the test drives exactly
    what the model drives. Returns the tool responses and the turn inputs."""

    def __init__(self, states=None, payloads=None):
        self.states = list(states or ModelState)
        self.payloads = payloads if payloads is not None else _payloads()
        self.turn_inputs: list = []
        self.responses: list = []

    def store_tool(self, turn):
        return next(tool for tool in turn.tools if tool.name == "hunts_store")

    def __call__(self, turn):
        self.turn_inputs.append(turn)
        if turn.state not in self.states:
            return None
        payload = self.payloads[turn.state]
        self.responses.append(self.store_tool(turn).invoke({
            "cmd": "write", "state": turn.state.value, "sections": payload,
        }))
        return None


def _tools(store, **kwargs) -> ModellerTools:
    return ModellerTools(threat_store=store, project_id=PROJECT, run_id=RUN,
                         **kwargs)


def test_a_scripted_pass_writes_all_five_gates_to_the_real_store(tmp_path):
    """A scripted modeller turn writes all five gates; the persisted model is
    COMPLETED with every section merged and the store-computed risk profile."""
    store = ThreatModelStore(root_dir=tmp_path)
    turns = _ScriptedTurns()

    outcome = asyncio.run(arun_modeller_pass(
        PROJECT, RUN, UNIT, _tools(store), turn_fn=turns))

    assert isinstance(outcome, UnitOutcome)
    assert outcome.status == "completed"
    assert outcome.state == ModelState.COMPLETED.value
    assert [write.state for write in outcome.gate_writes] == list(ModelState)
    model = store.read_model(PROJECT, UNIT)
    assert model["state"] == ModelState.COMPLETED.value
    assert model["technical_sharpening"]["interface_agreements"]
    assert model["trust_model"]["trust_agreements"]
    assert model["assumptions"]
    assert model["vulnerabilities"]
    assert model["failure_modes"]
    assert model["risk_profile"]["total"] == 3
    assert model["validation"]["valid"] is True
    # the loop file landed for the non-`none` loop
    assert [loop["loop_id"] for loop in store.read_loop_files(PROJECT, UNIT)] == ["loop-1"]


def test_the_pass_prompts_each_state_in_order_with_its_gate_instruction(tmp_path):
    """The pass asks for the five states in workflow order; each turn carries
    that state's gate section names and instruction (the prompt-level cadence)."""
    store = ThreatModelStore(root_dir=tmp_path)
    turns = _ScriptedTurns()

    asyncio.run(arun_modeller_pass(PROJECT, RUN, UNIT, _tools(store), turn_fn=turns))

    assert [turn.state for turn in turns.turn_inputs] == list(ModelState)
    first = turns.turn_inputs[0]
    assert first.unit_id == UNIT
    assert set(first.sections) == {"technical_sharpening"}
    assert "interface agreements" in first.instruction.lower()


def test_a_lower_gate_write_updates_the_section_without_regressing_the_state(tmp_path):
    """The model state is monotonic (S1 5.1, S2 5.3): a late write for an
    earlier gate merges its section content, records the trail entry, and never
    regresses the persisted state."""
    store = ThreatModelStore(root_dir=tmp_path)
    turns = _ScriptedTurns()
    asyncio.run(arun_modeller_pass(PROJECT, RUN, UNIT, _tools(store), turn_fn=turns))

    late = {"technical_sharpening": {
        "interface_agreements": [{
            "id": "ia-1",
            "statement": "amended after completion",
            "confidence": "OBSERVED",
            "evidences": [_evidence()],
        }],
        "control_flows": _payloads()[ModelState.UNIT_TECHNICAL_SHARP][
            "technical_sharpening"]["control_flows"],
        "data_flows": _payloads()[ModelState.UNIT_TECHNICAL_SHARP][
            "technical_sharpening"]["data_flows"],
    }}
    tool = build_modeller_tool_surface(PROJECT, UNIT, _tools(store))["hunts_store"]
    tool.invoke({"cmd": "write", "state": "UNIT_TECHNICAL_SHARP",
                 "sections": late})

    model = store.read_model(PROJECT, UNIT)
    assert model["state"] == ModelState.COMPLETED.value
    assert (model["technical_sharpening"]["interface_agreements"][0]["statement"]
            == "amended after completion")


def test_each_gate_write_response_carries_the_next_state_hint(tmp_path):
    """The hint table (S1 9.3) rides the tool response of every gate but the
    last; the COMPLETED write carries no hint."""
    store = ThreatModelStore(root_dir=tmp_path)
    turns = _ScriptedTurns()

    asyncio.run(arun_modeller_pass(PROJECT, RUN, UNIT, _tools(store), turn_fn=turns))

    hints = [response.get("hint") for response in turns.responses]
    assert hints == [GATE_HINTS[state] for state in list(ModelState)[:-1]] + [None]
    assert GATE_HINTS[ModelState.UNIT_TECHNICAL_SHARP].startswith("Proceed to trust mapping")
    assert GATE_HINTS[ModelState.TRUST_MODELLED].startswith("Proceed to assumptions")
    assert (GATE_HINTS[ModelState.TRUST_ASSUMPTIONS_WRITTEN]
            .startswith("Proceed to vulnerability citation"))
    assert (GATE_HINTS[ModelState.VULNERABILITIES_WRITTEN]
            .startswith("Proceed to failure-mode deduction"))


def test_a_pass_that_never_completes_reports_a_degraded_unit(tmp_path):
    """No fabricated result: a scripted run that stops after the sharpening
    gate yields a degraded outcome carrying the persisted state, and the
    partial model stays for the run driver to decide."""
    store = ThreatModelStore(root_dir=tmp_path)
    turns = _ScriptedTurns(states=[ModelState.UNIT_TECHNICAL_SHARP])

    outcome = asyncio.run(arun_modeller_pass(
        PROJECT, RUN, UNIT, _tools(store), turn_fn=turns))

    assert outcome.status == "degraded"
    assert outcome.state == ModelState.UNIT_TECHNICAL_SHARP.value
    assert "did not reach COMPLETED" in outcome.reason
    assert store.read_model(PROJECT, UNIT) is not None


def test_a_crossing_gate_write_hints_and_the_state_jumps_forward(tmp_path):
    """The pass never gates a transition: a turn that jumps straight to
    COMPLETED is accepted, the skipped states are recorded in the trail, and the
    outcome completes."""
    store = ThreatModelStore(root_dir=tmp_path)
    payloads = _payloads()
    jumps = {ModelState.COMPLETED: payloads[ModelState.COMPLETED]}

    class _Jump(_ScriptedTurns):
        def __call__(self, turn):
            self.turn_inputs.append(turn)
            if turn.state is ModelState.COMPLETED:
                # the forward-jumping turn also writes the sections it skipped
                for state in list(ModelState)[:-1]:
                    self.store_tool(turn).invoke({
                        "cmd": "write", "state": state.value,
                        "sections": payloads[state],
                    })
                self.responses.append(self.store_tool(turn).invoke({
                    "cmd": "write", "state": "COMPLETED",
                    "sections": jumps[ModelState.COMPLETED],
                }))
            return None

    outcome = asyncio.run(arun_modeller_pass(
        PROJECT, RUN, UNIT, _tools(store), turn_fn=_Jump()))

    assert outcome.status == "completed"
    assert [write.state for write in outcome.gate_writes] == [
        state.value for state in ModelState
    ]


def test_the_gate_hint_table_covers_every_gate_but_the_last(tmp_path):
    """The hint table is fixed by S1 9.3: one entry per gate write, none for
    COMPLETED."""
    assert set(GATE_HINTS) == set(ModelState) - {ModelState.COMPLETED}
    assert all(GATE_HINTS.values())


def test_the_suite_pair_binds_and_degrades_the_class_mapping():
    """The `skill_list` / `skill_load` pair is bound before the role is enabled
    (the ticket's contract), and a suite that has not landed degrades fail-open
    with a RECORDED gap instead of an invented class."""
    surface = build_modeller_tool_surface(
        PROJECT, UNIT, _tools(None), )

    assert {"skill_list", "skill_load"} <= set(surface)
    assert {"skill_list", "skill_load"} <= set(TOOL_SURFACE)
    listing = surface["skill_list"].invoke({})
    load = surface["skill_load"].invoke({"name": "idor"})
    assert listing["skills"] == [] and listing["suite_gap"] is True
    assert load["error"] == "suite_unavailable" and load["suite_gap"] is True
    seam = suite_seam_from_tools(list(surface.values()))
    assert seam is not None and seam.gaps


def test_the_suite_pair_lists_the_frontmatter_and_loads_a_class_body():
    """Against the assumed suite contract: the directory names are the classes,
    the listing carries each class's frontmatter description, and the load
    returns the class procedure."""
    bodies = {
        "idor": "---\nname: idor\ndescription: object-level authorisation failures\n---\nbody-x",
        "xss": "---\nname: xss\ndescription: rendered-content injection\n---\nbody-y",
    }
    tools = build_vulnerability_suite_tools(
        classes=("idor", "xss"), read_fn=lambda name: bodies[name])
    surface = {tool.name: tool for tool in tools}

    listing = surface["skill_list"].invoke({})
    load = surface["skill_load"].invoke({"name": "idor"})

    assert [entry["name"] for entry in listing["skills"]] == ["idor", "xss"]
    assert listing["skills"][0]["description"] == "object-level authorisation failures"
    assert load == {"ok": True, "name": "idor", "body": bodies["idor"],
                    "suite_gap": False}


def test_notes_are_keyed_by_the_bound_unit_and_refuse_phase_summary(tmp_path):
    """The episodic note key is `<unit_name>:<note_name>` and the hunter-only
    `phase_summary` kind is refused with a coded rejection (S1 5.2)."""
    store = ThreatModelStore(root_dir=tmp_path)
    surface = build_modeller_tool_surface(PROJECT, UNIT, _tools(store))

    written = surface["notes"].invoke({
        "cmd": "write", "option": "append", "note_name": "grounding",
        "kind": "freeform", "body": "chose the query-id path", "evidence": "GET /catalogue"})
    refused = surface["notes"].invoke({
        "cmd": "write", "option": "append", "note_name": "grounding",
        "kind": "phase_summary", "body": "a hunter-only exit note"})
    read = surface["notes"].invoke({"cmd": "read", "key": "grounding"})

    assert written["ok"] is True
    assert written["key"] == "Service-catalogue-and-discovery:grounding"
    assert refused["ok"] is False and refused["error"] == "notes_write_rejected"
    assert refused["fields"] == ["kind"]
    assert [note["kind"] for note in read["notes"]] == ["freeform"]


def test_an_invalid_completed_model_is_archived_and_reported_degraded(tmp_path):
    """The completion validation call (S1 6.6): a COMPLETED write whose model
    fails the loose checker is non-blocking for the write, and the pass archives
    the model and reports the unit degraded - no loop is dispatched."""
    store = ThreatModelStore(root_dir=tmp_path)
    payloads = {
        ModelState.COMPLETED: {
            "failure_modes": [],
            "loops": [{
                "fault_ref": "fault-not-in-the-model",
                "vulnerability_ref": "v-missing",
                "failure_mode_refs": [],
                "canonical_class": "IDOR",
                "likelihood": "none",
                "likelihood_rationale": "no feasible failure mode",
                "risk_factors": {
                    "attack_vector": "network", "attack_requirements": "none",
                    "privileges_required": "none", "complexity": "low"},
                "confidence": "ASSUMED",
                "evidences": [_evidence()],
            }],
        },
    }
    turns = _ScriptedTurns(payloads=payloads)

    outcome = asyncio.run(arun_modeller_pass(
        PROJECT, RUN, UNIT, _tools(store), turn_fn=turns))

    assert outcome.status == "degraded"
    assert outcome.archived is True
    assert "completion check" in outcome.reason
    assert store.read_model(PROJECT, UNIT) is None
    assert store.read_completed_units(PROJECT) == []
    assert store.read_abandoned_units(PROJECT) == [UNIT]


def test_the_pass_aborts_after_a_run_of_no_decision_turns():
    """A sustained dead seam is typed and operator-visible (the
    consecutive-degradation breaker), so the runtime pauses the run instead of
    grinding on without a model."""
    from polymerhus.attack.hunting.threat_modeller import (
        ThreatModellerDegradedError,
    )

    class _Dead:
        def __call__(self, turn):
            return None

    with pytest.raises(ThreatModellerDegradedError) as excinfo:
        asyncio.run(arun_modeller_pass(
            PROJECT, RUN, UNIT, _tools(None), turn_fn=_Dead()))

    assert excinfo.value.provider_cause is False
    assert excinfo.value.streak == excinfo.value.threshold


def test_a_retargeted_unit_cell_lets_one_surface_follow_the_run(tmp_path):
    """The per-run actor captures its tool surface ONCE; the retargetable unit
    cell is what lets the same tools write unit after unit (the stable-seam
    pattern the planner pass established, #294) - so a run-scoped actor never
    strands its captured tools on the first unit."""
    from polymerhus.attack.hunting.threat_modeller import ModellerUnit

    store = ThreatModelStore(root_dir=tmp_path)
    cell = ModellerUnit()
    tools = ModellerTools(threat_store=store, project_id=PROJECT, run_id=RUN,
                          unit_cell=cell)
    surface = build_modeller_tool_surface(PROJECT, "", tools)
    payload = _payloads()[ModelState.UNIT_TECHNICAL_SHARP]

    for unit_id in ("Service:first", "Service:second"):
        cell.retarget(project_id=PROJECT, run_id=RUN, unit_id=unit_id)
        surface["hunts_store"].invoke({
            "cmd": "write", "state": "UNIT_TECHNICAL_SHARP", "sections": payload})

    for unit_id in ("Service:first", "Service:second"):
        assert store.read_model(PROJECT, unit_id)["state"] == "UNIT_TECHNICAL_SHARP"
        assert store.read_model(PROJECT, unit_id)["unit_id"] == unit_id


def test_the_modeller_tool_surface_is_exactly_the_bound_tools(tmp_path):
    """The surface is exactly the modeller's (S1 5): the store, the notes, the
    HTTP-history read pair, exec, and the suite pair - and NOT `graph_view`,
    `kb_query`, the fault-KB aid, or `replay`."""
    store = ThreatModelStore(root_dir=tmp_path)
    surface = build_modeller_tool_surface(PROJECT, UNIT, _tools(store))

    assert set(surface) == set(TOOL_SURFACE)
    assert {"graph_view", "kb_query", "query_lightrag", "replay",
            "mint_hunt_config"} & set(surface) == set()


def test_the_store_tool_rejects_a_write_without_a_state(tmp_path):
    """A write missing its derivation input is a coded teaching rejection, never
    a raise and never a silent degenerate write."""
    store = ThreatModelStore(root_dir=tmp_path)
    surface = build_modeller_tool_surface(PROJECT, UNIT, _tools(store))

    rejection = surface["hunts_store"].invoke({"cmd": "write", "sections": {}})

    assert rejection["error"] == "hunts_store_write_rejected"
    assert "state" in rejection["fields"]
    assert store.read_model(PROJECT, UNIT) is None


def test_the_store_tool_rejects_a_write_for_a_foreign_section(tmp_path):
    """The gate's section set is the contract: a section outside the state's
    set is refused (S2 5.4) with the coded rejection."""
    store = ThreatModelStore(root_dir=tmp_path)
    surface = build_modeller_tool_surface(PROJECT, UNIT, _tools(store))

    rejection = surface["hunts_store"].invoke({
        "cmd": "write", "state": "TRUST_MODELLED",
        "sections": {"technical_sharpening": {}},
    })

    assert rejection["error"] == "hunts_store_write_rejected"
    assert "trust_model" in rejection["detail"]


def test_a_read_returns_the_bound_unit_and_a_section_projection(tmp_path):
    """A read with no `unit_id` reads the bound unit; a `section` returns only
    that section."""
    store = ThreatModelStore(root_dir=tmp_path)
    store.write_sections(PROJECT, UNIT, ModelState.UNIT_TECHNICAL_SHARP,
                         _payloads()[ModelState.UNIT_TECHNICAL_SHARP], run_id=RUN)
    surface = build_modeller_tool_surface(PROJECT, UNIT, _tools(store))

    full = surface["hunts_store"].invoke({"cmd": "read"})
    section = surface["hunts_store"].invoke({
        "cmd": "read", "section": "technical_sharpening"})

    assert full["unit_id"] == UNIT
    assert full["state"] == ModelState.UNIT_TECHNICAL_SHARP.value
    assert set(section["section"]) == {"interface_agreements", "control_flows",
                                       "data_flows"}
    assert full["risk_profile"] is None
    assert yaml.safe_load(
        next(tmp_path.glob(f"*/hunting/threat_modeller/produced/*/{UNIT.replace(':', '-')}.yaml"))
        .read_text(encoding="utf-8")
    )["unit_id"] == UNIT
