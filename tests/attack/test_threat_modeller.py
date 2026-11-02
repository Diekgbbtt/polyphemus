"""Unit tier: the threat modeller pass, gates, tools, and tracker (T2, #375).

The harness contract of S1 5-6 and 9.3: the seven gate writes, the monotonic
model state, the next-state hint injected in the tool response, the exact tool
surface (no `graph_view`, no `kb_query`, no fault-KB aid, no `replay`), the
coded write rejection, the notes binding with the hunter-only kind refused, the
completion validation call and the invalid-model archive, and the
web-vulnerability suite binding with its fail-open gap.

The schema-5 assessment contract (T4, #407): `assess_impact` is the sole
writer of an assessment row, the first call advances `IMPACT_ASSESSED`, its
contract rejects a field it does not take (an authored score included), and
the `hunts_store` surface refuses an `impact_assessment` section.

Every test drives the REAL `ThreatModelStore` on a temporary project root and
the REAL tool surface, through a scripted turn seam - the pass reads the states
passively from the gate writes, so a fake turn that calls the bound tool is the
whole contract.
"""
from __future__ import annotations

import asyncio
import json

import pytest
import yaml

from polymerhus.attack.hunting.threat_model import ModelState
from polymerhus.attack.hunting.threat_model_store import ThreatModelStore
from polymerhus.app.memory.tool_contract import NoteWrite, NotesRead

from polymerhus.attack.hunting.threat_modeller import (
    GATE_HINTS,
    TOOL_SURFACE,
    UnitOutcome,
    arun_modeller_pass,
)
from polymerhus.attack.hunting.threat_modeller_tools import (
    ModellerNotesHandle,
    ModellerTools,
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


# The shared worked example and the scripted turn seam live in
# `tests/hunting_fixtures.py`: the runtime wiring tests (T2b) drive the SAME
# seven-gate payloads, so the fixture has one home.
from tests.hunting_fixtures import (  # noqa: E402
    ITEM_RISK,
    ITEM_VECTOR,
    ScriptedModellerTurns as _ScriptedTurns,
    _evidence,
    write_gate,
)
from tests.hunting_fixtures import (  # noqa: E402
    modeller_gate_payloads as _payloads,
)


def _tools(store, **kwargs) -> ModellerTools:
    return ModellerTools(threat_store=store, project_id=PROJECT, run_id=RUN,
                         **kwargs)


def _write_to_prior_art(store) -> None:
    """Drive the real store to `PRIOR_ART`: the state the assessment write
    accepts, with the one vulnerability the worked example assesses."""
    payloads = _payloads()
    for state in (ModelState.UNIT_TECHNICAL_SHARP,
                  ModelState.VULNERABILITIES_WRITTEN,
                  ModelState.PRIOR_ART):
        store.write_sections(PROJECT, UNIT, state, payloads[state], run_id=RUN)


def test_a_scripted_pass_writes_all_seven_gates_to_the_real_store(tmp_path):
    """A scripted modeller turn writes all seven gates; the persisted model is
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
    assert model["prior_art"]["queries"]
    assert model["trust_model"]["trust_agreements"]
    assert model["assumptions"]
    assert model["vulnerabilities"]
    assert model["impact_assessment"]
    assert model["impact_assessment"][0]["capability"]
    # the profile sums the DERIVED row score the threat mirrors
    assert model["risk_profile"]["total"] == ITEM_RISK
    assert model["validation"]["valid"] is True
    # the threat file landed for the non-`none` threat
    assert [threat["threat_id"] for threat in store.read_threat_files(PROJECT, UNIT)] == ["threat-1"]


def test_the_pass_carries_the_project_scope_on_every_turn(tmp_path):
    """#438: the run reads the project scope once at its start; the pass stamps
    that one value on EVERY turn it asks - the seven gates and the
    well-formedness pass - so the assumptions phase is bound wherever it runs."""
    store = ThreatModelStore(root_dir=tmp_path)
    turns = _ScriptedTurns()
    tools = _tools(store)
    tools.threat_model_scope = (
        "The target is assumed to have a WAF in blocking mode.")

    asyncio.run(arun_modeller_pass(PROJECT, RUN, UNIT, tools, turn_fn=turns))

    assert any(turn.phase == "WELLFORMEDNESS" for turn in turns.turn_inputs)
    assert {turn.threat_model_scope for turn in turns.turn_inputs} == {
        "The target is assumed to have a WAF in blocking mode."}


def test_the_pass_defaults_the_project_scope_to_empty(tmp_path):
    """#438: a run whose project set no scope carries the empty string - the
    turn then appends no scope section."""
    store = ThreatModelStore(root_dir=tmp_path)
    turns = _ScriptedTurns()

    asyncio.run(arun_modeller_pass(PROJECT, RUN, UNIT, _tools(store), turn_fn=turns))

    assert {turn.threat_model_scope for turn in turns.turn_inputs} == {""}


def test_the_pass_prompts_each_state_in_order_with_its_gate_instruction(tmp_path):
    """The pass asks for the seven states in workflow order; each turn carries
    that state's gate section names and instruction (the prompt-level cadence).
    The well-formedness turn sits between the vulnerabilities and the impact
    writes, and its exit is the IMPACT_ASSESSED gate."""
    store = ThreatModelStore(root_dir=tmp_path)
    turns = _ScriptedTurns()

    asyncio.run(arun_modeller_pass(PROJECT, RUN, UNIT, _tools(store), turn_fn=turns))

    assert [turn.state for turn in turns.turn_inputs] == [
        ModelState.UNIT_TECHNICAL_SHARP,
        ModelState.TRUST_MODELLED,
        ModelState.TRUST_ASSUMPTIONS_WRITTEN,
        ModelState.VULNERABILITIES_WRITTEN,
        ModelState.VULNERABILITIES_WRITTEN,
        ModelState.PRIOR_ART,
        ModelState.IMPACT_ASSESSED,
        ModelState.COMPLETED,
    ]
    assert turns.turn_inputs[4].phase == "WELLFORMEDNESS"
    assert turns.turn_inputs[4].instruction.startswith(
        "Run the well-formedness phase")
    first = turns.turn_inputs[0]
    assert first.unit_id == UNIT
    assert set(first.sections) == {"technical_sharpening"}
    assert "interface agreements" in first.instruction.lower()
    assert set(turns.turn_inputs[5].sections) == {"prior_art"}
    assert set(turns.turn_inputs[7].sections) == {"threats"}


def test_the_prior_art_gate_is_tracked_between_sharpening_and_trust(tmp_path):
    """S2 section 5: `PRIOR_ART` is a tracked gate whose section is
    `prior_art`; the passive tracker observes it after the technical
    sharpening and before the trust model, never gating the write."""
    from polymerhus.attack.hunting.threat_model import GATE_SECTIONS

    store = ThreatModelStore(root_dir=tmp_path)
    turns = _ScriptedTurns()

    outcome = asyncio.run(arun_modeller_pass(
        PROJECT, RUN, UNIT, _tools(store), turn_fn=turns))

    assert GATE_SECTIONS[ModelState.PRIOR_ART] == ("prior_art",)
    states = [write.state for write in outcome.gate_writes]
    assert states.index(ModelState.PRIOR_ART) == (
        states.index(ModelState.VULNERABILITIES_WRITTEN) + 1)
    prior = outcome.gate_writes[states.index(ModelState.PRIOR_ART)]
    assert prior.sections == ("prior_art",)
    assert store.read_model(PROJECT, UNIT)["prior_art"]["queries"]


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
    last: `hunts_store` for its gates, `assess_impact` for the tool-only
    `IMPACT_ASSESSED` transition, whose hint is the completion pointer. The
    COMPLETED write carries no hint, and no response ever carries a score."""
    store = ThreatModelStore(root_dir=tmp_path)
    turns = _ScriptedTurns()

    asyncio.run(arun_modeller_pass(PROJECT, RUN, UNIT, _tools(store), turn_fn=turns))

    # the responses are in gate order: five `hunts_store` writes below COMPLETED,
    # the assessment write, then the COMPLETED write with no hint
    hints = [response.get("hint") for response in turns.responses]
    assert hints == [GATE_HINTS[state] for state in list(ModelState)[:-1]] + [None]
    assert "state" not in turns.responses[5]
    assert "score" not in turns.responses[5]
    assert "vector" not in turns.responses[5]
    assert "factors" not in turns.responses[5]
    assert GATE_HINTS[ModelState.UNIT_TECHNICAL_SHARP].startswith("Proceed to trust mapping")
    assert GATE_HINTS[ModelState.PRIOR_ART].startswith("Proceed to the impact assessment")
    assert GATE_HINTS[ModelState.TRUST_MODELLED].startswith("Proceed to assumptions")
    assert (GATE_HINTS[ModelState.TRUST_ASSUMPTIONS_WRITTEN]
            .startswith("Proceed to vulnerability citation"))
    assert (GATE_HINTS[ModelState.VULNERABILITIES_WRITTEN]
            .startswith("Proceed to the well-formedness phase"))
    assert (GATE_HINTS[ModelState.IMPACT_ASSESSED]
            .startswith("Proceed to completion"))
    # the assessment hint names the tool; the completion hint names the derived
    # risk, the coverage, and the chains to verify
    assert "`assess_impact`" in GATE_HINTS[ModelState.PRIOR_ART]
    assert "derived" in GATE_HINTS[ModelState.IMPACT_ASSESSED].lower()
    assert "never author a score" in GATE_HINTS[ModelState.IMPACT_ASSESSED].lower()
    assert "enabling chains" in GATE_HINTS[ModelState.IMPACT_ASSESSED]


def test_a_pass_that_never_completes_reports_a_degraded_unit(tmp_path):
    """No fabricated result: a scripted run that stops after the sharpening
    gate yields a degraded outcome carrying the persisted state, and its PARTIAL
    model is archived to `abandoned/` (S1 7.7) - never left in `produced/`,
    where the in-flight exclusion would skip the unit for the rest of the
    producing run's life."""
    store = ThreatModelStore(root_dir=tmp_path)
    turns = _ScriptedTurns(states=[ModelState.UNIT_TECHNICAL_SHARP])

    outcome = asyncio.run(arun_modeller_pass(
        PROJECT, RUN, UNIT, _tools(store), turn_fn=turns))

    assert outcome.status == "degraded"
    assert outcome.state == ModelState.UNIT_TECHNICAL_SHARP.value
    assert "did not reach COMPLETED" in outcome.reason
    assert outcome.archived is True
    assert store.read_model(PROJECT, UNIT) is None
    assert store.read_abandoned_units(PROJECT) == [UNIT]


def test_a_lower_gate_write_re_enters_the_wellformedness_turn(tmp_path):
    """The well-formedness phase is a threat: the first turn writes a lower gate
    (a local patch), the pass asks the phase again, and the second turn writes
    the exit note and the IMPACT_ASSESSED gate (the COMPLETED turn follows).
    The harness records the lower-gate re-entry."""
    store = ThreatModelStore(root_dir=tmp_path)

    class _Reentering(_ScriptedTurns):
        def __call__(self, turn):
            self.turn_inputs.append(turn)
            if turn.phase == "WELLFORMEDNESS":
                attempts = [t for t in self.turn_inputs
                            if t.phase == "WELLFORMEDNESS"]
                if len(attempts) == 1:
                    self.store_tool(turn).invoke({
                        "cmd": "write",
                        "state": ModelState.TRUST_ASSUMPTIONS_WRITTEN.value,
                        "sections": _payloads()[
                            ModelState.TRUST_ASSUMPTIONS_WRITTEN]})
                    return None
                notes = next(tool for tool in turn.tools if tool.name == "notes")
                notes.invoke({
                    "cmd": "write", "option": "append",
                    "note_name": "wellformedness", "kind": "wellformedness",
                    "body": "every threat checked after the local patch",
                })
                return None
            self.write_gate(turn, turn.state)
            return None

    turns = _Reentering()
    outcome = asyncio.run(arun_modeller_pass(
        PROJECT, RUN, UNIT, _tools(store), turn_fn=turns))

    assert outcome.status == "completed"
    wellformedness_turns = [
        turn for turn in turns.turn_inputs if turn.phase == "WELLFORMEDNESS"]
    assert len(wellformedness_turns) == 2
    assert any(entry.kind == "lower_gate" for entry in outcome.trail)


def test_a_degraded_units_retry_re_authors_every_gate_from_scratch(tmp_path):
    """S1 7.7 retry policy: the archived partial leaves no persisted state, so a
    retry asks for the first gate again and models the unit to COMPLETED."""
    store = ThreatModelStore(root_dir=tmp_path)
    first = _ScriptedTurns(states=[ModelState.UNIT_TECHNICAL_SHARP])
    asyncio.run(arun_modeller_pass(
        PROJECT, RUN, UNIT, _tools(store), turn_fn=first))

    retry = _ScriptedTurns()
    outcome = asyncio.run(arun_modeller_pass(
        PROJECT, RUN, UNIT, _tools(store), turn_fn=retry))

    assert outcome.status == "completed"
    assert [turn.state for turn in retry.turn_inputs] == [
        ModelState.UNIT_TECHNICAL_SHARP,
        ModelState.TRUST_MODELLED,
        ModelState.TRUST_ASSUMPTIONS_WRITTEN,
        ModelState.VULNERABILITIES_WRITTEN,
        ModelState.VULNERABILITIES_WRITTEN,
        ModelState.PRIOR_ART,
        ModelState.IMPACT_ASSESSED,
        ModelState.COMPLETED,
    ]
    assert retry.turn_inputs[4].phase == "WELLFORMEDNESS"
    assert store.read_model(PROJECT, UNIT)["state"] == ModelState.COMPLETED.value
    assert store.read_abandoned_units(PROJECT) == [UNIT]



def test_a_crossing_gate_write_hints_and_the_state_jumps_forward(tmp_path):
    """The pass never gates a transition: one turn writes every gate in order
    (the last write crosses into COMPLETED from a cold start), the pass reads
    the state passively, and never re-asks a state it already observed."""
    store = ThreatModelStore(root_dir=tmp_path)
    payloads = _payloads()

    class _Jump(_ScriptedTurns):
        def __call__(self, turn):
            self.turn_inputs.append(turn)
            if turn.state is ModelState.UNIT_TECHNICAL_SHARP:
                # one turn writes every gate below COMPLETED and then COMPLETED
                # itself: the pass reads one forward jump and never re-asks
                for state in list(ModelState)[:-1]:
                    self.write_gate(turn, state)
                self.responses.append(self.store_tool(turn).invoke({
                    "cmd": "write", "state": "COMPLETED",
                    "sections": payloads[ModelState.COMPLETED],
                }))
            return None

    turns = _Jump()
    outcome = asyncio.run(arun_modeller_pass(
        PROJECT, RUN, UNIT, _tools(store), turn_fn=turns))

    assert outcome.status == "completed"
    assert [write.state for write in outcome.gate_writes] == [
        state.value for state in ModelState
    ]
    assert [turn.state for turn in turns.turn_inputs] == [
        ModelState.UNIT_TECHNICAL_SHARP,
    ]


def test_a_silent_ladder_then_a_forward_jump_is_accepted(tmp_path):
    """The pass tolerates six silent turns and still accepts the cold forward
    jump on the seventh. This pins the default abort bound at 7: the six states
    below COMPLETED are silent on a cold jump."""
    store = ThreatModelStore(root_dir=tmp_path)
    payloads = _payloads()

    class _ColdJump(_ScriptedTurns):
        def __call__(self, turn):
            self.turn_inputs.append(turn)
            if len(self.turn_inputs) < 7:
                return None
            for state in list(ModelState)[:-1]:
                self.write_gate(turn, state)
            self.responses.append(self.store_tool(turn).invoke({
                "cmd": "write", "state": "COMPLETED",
                "sections": payloads[ModelState.COMPLETED],
            }))
            return None

    turns = _ColdJump()
    outcome = asyncio.run(arun_modeller_pass(
        PROJECT, RUN, UNIT, _tools(store), turn_fn=turns))

    assert outcome.status == "completed"
    assert len(turns.turn_inputs) == 7
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
    filtered = surface["skill_list"].invoke({"filter": "idor"})
    assert listing["error"] == "skill_filter_required"
    assert listing["skills"] == []
    assert filtered["skills"] == [] and filtered["suite_gap"] is True
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

    listing = surface["skill_list"].invoke({"filter": "idor|xss"})
    load = surface["skill_load"].invoke({"name": "idor"})

    assert [entry["name"] for entry in listing["skills"]] == ["idor", "xss"]
    assert listing["skills"][0]["description"] == "object-level authorisation failures"
    assert load == {"ok": True, "name": "idor", "body": bodies["idor"],
                    "suite_gap": False}


def test_the_suite_listing_cascades_a_parent_to_its_leaves():
    """A parent regex returns the class parent plus every leaf of that class,
    even when a leaf name does not repeat the parent name (`bfla-*`)."""
    bodies = {
        "broken-function-level-authorization":
            "---\ndescription: bfla\n---\nbody",
        "bfla-alternate-path": "---\ndescription: alternate\n---\nbody",
        "bfla-client-identity-trust": "---\ndescription: client\n---\nbody",
        "idor": "---\ndescription: idor\n---\nbody",
    }
    parents = {
        "broken-function-level-authorization":
            "broken-function-level-authorization",
        "bfla-alternate-path": "broken-function-level-authorization",
        "bfla-client-identity-trust": "broken-function-level-authorization",
        "idor": "idor",
    }
    tools = build_vulnerability_suite_tools(
        classes=tuple(bodies), read_fn=bodies.__getitem__, parents=parents)
    surface = {tool.name: tool for tool in tools}

    listing = surface["skill_list"].invoke(
        {"filter": "broken-function-level-authorization"})

    assert [entry["name"] for entry in listing["skills"]] == [
        "broken-function-level-authorization",
        "bfla-alternate-path",
        "bfla-client-identity-trust",
    ]
    assert listing["skills"][0]["kind"] == "parent"
    assert listing["skills"][1]["parent"] == (
        "broken-function-level-authorization")
    assert listing["filter"] == "broken-function-level-authorization"


def test_the_suite_listing_returns_the_parent_for_a_leaf_match():
    """A leaf regex returns the leaf and its class parent; the match is
    case-insensitive."""
    bodies = {
        "information-disclosure": "---\ndescription: disclosure\n---\nbody",
        "information-disclosure-excessive-data-exposure":
            "---\ndescription: excessive\n---\nbody",
    }
    parents = {
        "information-disclosure": "information-disclosure",
        "information-disclosure-excessive-data-exposure":
            "information-disclosure",
    }
    surface = {
        tool.name: tool
        for tool in build_vulnerability_suite_tools(
            classes=tuple(bodies), read_fn=bodies.__getitem__, parents=parents)
    }

    listing = surface["skill_list"].invoke(
        {"filter": "INFORMATION-DISCLOSURE-EXCESSIVE-DATA-EXPOSURE"})

    assert [entry["name"] for entry in listing["skills"]] == [
        "information-disclosure",
        "information-disclosure-excessive-data-exposure",
    ]
    assert listing["skills"][1]["kind"] == "leaf"


def test_the_suite_listing_requires_a_filter_and_accepts_a_no_match():
    """A missing filter is a coded error with no listing; a no-match regex is
    an empty listing, not an error."""
    bodies = {"idor": "---\ndescription: idor\n---\nbody"}
    surface = {
        tool.name: tool
        for tool in build_vulnerability_suite_tools(
            classes=tuple(bodies), read_fn=bodies.__getitem__)
    }

    missing = surface["skill_list"].invoke({})
    no_match = surface["skill_list"].invoke({"filter": "no-such-class"})

    assert missing["error"] == "skill_filter_required"
    assert missing["skills"] == []
    assert no_match["skills"] == []
    assert no_match["filter"] == "no-such-class"
    assert "error" not in no_match


def test_the_suite_listing_rejects_an_invalid_regex_without_raising():
    bodies = {"idor": "---\ndescription: idor\n---\nbody"}
    surface = {
        tool.name: tool
        for tool in build_vulnerability_suite_tools(
            classes=tuple(bodies), read_fn=bodies.__getitem__)
    }

    invalid = surface["skill_list"].invoke({"filter": "["})

    assert invalid["error"] == "skill_filter_invalid"
    assert invalid["skills"] == []
    assert invalid["filter"] == "["


def test_the_suite_listing_caps_a_broad_cascade_and_reports_omitted():
    bodies = {"cap-parent": "---\ndescription: parent\n---\nbody"}
    parents = {"cap-parent": "cap-parent"}
    for index in range(25):
        leaf = f"cap-leaf-{index:02d}"
        bodies[leaf] = f"---\ndescription: {leaf}\n---\nbody"
        parents[leaf] = "cap-parent"
    surface = {
        tool.name: tool
        for tool in build_vulnerability_suite_tools(
            classes=tuple(bodies), read_fn=bodies.__getitem__, parents=parents)
    }

    listing = surface["skill_list"].invoke({"filter": "cap-parent"})

    assert len(listing["skills"]) == 20
    assert listing["omitted"] == 6
    assert listing["skills"][0]["name"] == "cap-parent"


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
    the model and reports the unit degraded - no threat is dispatched."""
    store = ThreatModelStore(root_dir=tmp_path)
    payloads = {
        ModelState.COMPLETED: {
            "threats": [{
                "fault_ref": "fault-not-in-the-model",
                "vulnerability_ref": "v-missing",
                "canonical_class": "IDOR",
                "impact_ref": "ia-missing",
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


def test_a_run_scoped_actor_capture_completes_every_unit_of_the_run(tmp_path):
    """The per-run actor captures its tool surface ONCE. A run-scoped tracker
    (shared through `ModellerTools`) is what keeps a second unit's gate writes
    observed - otherwise the captured tool holds a pre-pass seam, the second
    unit's writes land unobserved, and the breaker aborts a unit whose COMPLETED
    write already succeeded."""
    from polymerhus.attack.hunting.threat_modeller import ModellerUnit, PassiveGateTracker

    store = ThreatModelStore(root_dir=tmp_path)
    tools = ModellerTools(threat_store=store, project_id=PROJECT, run_id=RUN,
                          tracker=PassiveGateTracker(), unit_cell=ModellerUnit())
    captured: dict = {}

    def captured_surface():
        # the actor's `_ensure_started`: built once, on the first turn, and
        # reused for every later unit of the same run
        if "surface" not in captured:
            captured["surface"] = build_modeller_tool_surface(
                PROJECT, tools.unit_cell.unit_id, tools)
        return captured["surface"]

    class _ActorShaped:
        def __init__(self):
            self.turns = []

        def __call__(self, turn):
            self.turns.append(turn)
            if turn.phase == "WELLFORMEDNESS":
                captured_surface()["notes"].invoke({
                    "cmd": "write", "option": "append",
                    "note_name": "wellformedness", "kind": "wellformedness",
                    "body": "every threat checked",
                })
                return None
            write_gate(captured_surface(), turn.state)
            return None

    for unit_id in ("Service:first", "Service:second"):
        turns = _ActorShaped()
        outcome = asyncio.run(arun_modeller_pass(
            PROJECT, RUN, unit_id, tools, turn_fn=turns))

        assert outcome.status == "completed"
        assert outcome.state == ModelState.COMPLETED.value
        # the outcome carries THIS unit's writes, not the run's whole history
        assert [write.state for write in outcome.gate_writes] == list(ModelState)
        assert len(turns.turns) == len(ModelState) + 1

    assert tools.tracker.state is ModelState.COMPLETED
    for unit_id in ("Service:first", "Service:second"):
        persisted = store.read_model(PROJECT, unit_id)
        assert persisted["state"] == ModelState.COMPLETED.value
        assert persisted["validation"]["valid"] is True


def test_a_pass_seeded_from_a_completed_model_re_authors_nothing(tmp_path):
    """A resume (or a replayed unit) seeds the tracker from the persisted model:
    the states at or behind it are never re-asked, so a lower-gate write can
    never overwrite a COMPLETED model's sections."""
    store = ThreatModelStore(root_dir=tmp_path)
    first = _ScriptedTurns()
    asyncio.run(arun_modeller_pass(PROJECT, RUN, UNIT, _tools(store),
                                   turn_fn=first))

    class _Replay(_ScriptedTurns):
        def __call__(self, turn):
            self.turn_inputs.append(turn)
            # a resume that would regress the sharpening section
            self.store_tool(turn).invoke({
                "cmd": "write", "state": "UNIT_TECHNICAL_SHARP",
                "sections": {
                    "technical_sharpening": {
                        "interface_agreements": [{
                            "id": "ia-1", "statement": "re-authored",
                            "confidence": "ASSUMED", "evidences": [_evidence()],
                        }],
                        "control_flows": [],
                        "data_flows": [],
                    }}})
            return None

    replay = _Replay()
    outcome = asyncio.run(arun_modeller_pass(PROJECT, RUN, UNIT, _tools(store),
                                             turn_fn=replay))

    assert replay.turn_inputs == []          # seeded COMPLETED: nothing re-asked
    assert outcome.status == "completed"
    assert outcome.state == ModelState.COMPLETED.value
    assert [write.state for write in outcome.gate_writes] == []
    model = store.read_model(PROJECT, UNIT)
    assert model["state"] == ModelState.COMPLETED.value
    assert (model["technical_sharpening"]["interface_agreements"][0]["statement"]
            == "The catalogue endpoint reads the item id from the query.")


def test_a_prewrapped_store_shares_its_own_tracker(tmp_path):
    """A caller may hand a tracking store WITHOUT the `tracker` field. The pass
    then adopts that store's own tracker: creating a second one would observe
    nothing (the captured tool writes through the wrapper) and abort at the
    fifth state while the model is already COMPLETED and valid."""
    from polymerhus.attack.hunting.threat_modeller import (
        PassiveGateTracker,
        TrackingThreatModelStore,
    )

    store = ThreatModelStore(root_dir=tmp_path)
    tracker = PassiveGateTracker()
    wrapped = TrackingThreatModelStore(store, tracker)
    tools = ModellerTools(threat_store=wrapped, project_id=PROJECT, run_id=RUN)

    outcome = asyncio.run(arun_modeller_pass(PROJECT, RUN, UNIT, tools,
                                             turn_fn=_ScriptedTurns()))

    assert outcome.status == "completed"
    assert tools.threat_store is wrapped          # never double-wrapped
    assert tools.tracker is tracker               # the wrapper's own tracker
    assert [write.state for write in tracker.writes] == list(ModelState)
    assert [write.state for write in outcome.gate_writes] == list(ModelState)


def test_the_notes_read_filters_by_key(tmp_path):
    """The key filter is live: a read with a note name returns that note only,
    where a read with no key returns the unit's notes."""
    store = ThreatModelStore(root_dir=tmp_path)
    surface = build_modeller_tool_surface(PROJECT, UNIT, _tools(store))
    for name, kind in (("grounding", "freeform"),
                       ("boundary-check", "implicit_test_primitive")):
        surface["notes"].invoke({
            "cmd": "write", "option": "append", "note_name": name,
            "kind": kind, "body": f"note for {name}"})

    filtered = surface["notes"].invoke({"cmd": "read", "key": "grounding"})
    unfiltered = surface["notes"].invoke({"cmd": "read"})

    assert [note["note_name"] for note in filtered["notes"]] == ["grounding"]
    assert filtered["key"] == "Service-catalogue-and-discovery:grounding"
    assert {note["note_name"] for note in unfiltered["notes"]} == {
        "grounding", "boundary-check"}


def test_a_notes_read_with_no_bound_unit_is_a_coded_rejection():
    """The sibling store tool returns a coded rejection for an unbound
    identity; the notes handle must not raise where it does."""
    handle = ModellerNotesHandle(store=None, project_id=PROJECT, unit_id="")
    read = handle.read(NotesRead(key="grounding"))
    write = handle.write(NoteWrite(action="append", note_name="grounding",
                                   body="x"))

    assert read["error"] in ("invalid_args", "threat model store unavailable")
    assert read["notes"] == []
    assert write["ok"] is False


def test_a_write_carrying_a_unit_id_is_rejected(tmp_path):
    """The unit identity is bound: a write that tries to address another unit
    is a coded rejection, never a silently ignored field."""
    store = ThreatModelStore(root_dir=tmp_path)
    surface = build_modeller_tool_surface(PROJECT, UNIT, _tools(store))

    rejection = surface["hunts_store"].invoke({
        "cmd": "write", "state": "UNIT_TECHNICAL_SHARP",
        "sections": _payloads()[ModelState.UNIT_TECHNICAL_SHARP],
        "unit_id": "Service:another-unit",
    })

    assert rejection["error"] == "hunts_store_write_rejected"
    assert rejection["fields"] == ["unit_id"]
    assert store.read_model(PROJECT, "Service:another-unit") is None
    assert store.read_model(PROJECT, UNIT) is None


def test_the_read_response_carries_the_written_section_names(tmp_path):
    """The read lists the sections the model actually holds, not a static
    catalogue of the schema's section names."""
    store = ThreatModelStore(root_dir=tmp_path)
    store.write_sections(PROJECT, UNIT, ModelState.UNIT_TECHNICAL_SHARP,
                         _payloads()[ModelState.UNIT_TECHNICAL_SHARP], run_id=RUN)
    store.write_sections(PROJECT, UNIT, ModelState.TRUST_MODELLED,
                         _payloads()[ModelState.TRUST_MODELLED], run_id=RUN)
    surface = build_modeller_tool_surface(PROJECT, UNIT, _tools(store))

    read = surface["hunts_store"].invoke({"cmd": "read"})

    assert read["sections"] == ["technical_sharpening", "trust_model"]


def test_a_consumed_identity_write_does_not_advance_the_tracker(tmp_path):
    """The move-aware no-op write (S2 4.5): a write for an identity that lives
    in consumed/ re-creates nothing, so the tracker must not claim a gate write
    that never landed."""
    from polymerhus.attack.hunting.threat_modeller import(
        PassiveGateTracker,
        TrackingThreatModelStore,
    )

    store = ThreatModelStore(root_dir=tmp_path)
    asyncio.run(arun_modeller_pass(PROJECT, RUN, UNIT, _tools(store),
                                   turn_fn=_ScriptedTurns()))
    for threat in store.read_threat_files(PROJECT, UNIT):
        store.consume_threat(PROJECT, UNIT, threat["threat_id"])
    assert store.consume_model_if_done(PROJECT, UNIT) is True
    assert store.read_model(PROJECT, UNIT)["state"] == ModelState.COMPLETED.value

    tracker = PassiveGateTracker()
    wrapped = TrackingThreatModelStore(store, tracker)
    surface = build_modeller_tool_surface(
        PROJECT, UNIT,
        ModellerTools(threat_store=wrapped, project_id=PROJECT, run_id=RUN))
    response = surface["hunts_store"].invoke({
        "cmd": "write", "state": "TRUST_MODELLED",
        "sections": _payloads()[ModelState.TRUST_MODELLED]})

    assert response["ok"] is True
    assert tracker.writes == []
    assert tracker.state is None
    from polymerhus.attack.hunting.threat_model_store import sanitise_unit_name
    produced = (tmp_path / PROJECT / "hunting" / "threat_modeller" / "produced"
                / sanitise_unit_name(UNIT))
    assert not produced.exists()


def test_the_suite_gap_reaches_the_unit_outcome(tmp_path):
    """A degraded class mapping must leave the seam: the pass carries the
    recorded suite gaps into the unit outcome so the run can report it."""
    store = ThreatModelStore(root_dir=tmp_path)

    class _ProbingSuite(_ScriptedTurns):
        def __call__(self, turn):
            self.turn_inputs.append(turn)
            if turn.phase == "WELLFORMEDNESS":
                notes = next(tool for tool in turn.tools if tool.name == "notes")
                notes.invoke({
                    "cmd": "write", "option": "append",
                    "note_name": "wellformedness", "kind": "wellformedness",
                    "body": "every threat checked",
                })
                return None
            suite_load = next(tool for tool in turn.tools
                              if tool.name == "skill_load")
            self.responses.append(suite_load.invoke({"name": "idor"}))
            self.write_gate(turn, turn.state)
            return None

    turns = _ProbingSuite()
    outcome = asyncio.run(arun_modeller_pass(
        PROJECT, RUN, UNIT, _tools(store), turn_fn=turns))

    assert outcome.status == "completed"
    assert outcome.suite_gaps
    assert any("suite_unavailable" in gap for gap in outcome.suite_gaps)


def test_injected_suite_tools_still_report_their_gaps(tmp_path):
    """The injected-pair lane exposes the same seam: a caller that supplies its
    own `skill_list` / `skill_load` pair must not lose the gap record."""
    from polymerhus.attack.hunting.threat_modeller_tools import (
        VulnerabilitySuiteSeam,
    )

    store = ThreatModelStore(root_dir=tmp_path)
    seam = VulnerabilitySuiteSeam()
    tools = _tools(store, suite_tools=build_vulnerability_suite_tools(suite=seam))

    class _ProbingSuite(_ScriptedTurns):
        def __call__(self, turn):
            self.turn_inputs.append(turn)
            if turn.phase == "WELLFORMEDNESS":
                notes = next(tool for tool in turn.tools if tool.name == "notes")
                notes.invoke({
                    "cmd": "write", "option": "append",
                    "note_name": "wellformedness", "kind": "wellformedness",
                    "body": "every threat checked",
                })
                return None
            suite_load = next(tool for tool in turn.tools
                              if tool.name == "skill_load")
            suite_load.invoke({"name": "idor"})
            self.write_gate(turn, turn.state)
            return None

    outcome = asyncio.run(arun_modeller_pass(PROJECT, RUN, UNIT, tools,
                                             turn_fn=_ProbingSuite()))

    assert tools.suite is seam
    assert outcome.status == "completed"
    assert any("suite_unavailable" in gap for gap in outcome.suite_gaps)


def test_the_turn_carries_the_projection_and_the_surface_overview(tmp_path):
    """S1 4.6 / 5.6: the modeller is fed the unit projection and the L1
    application-surface overview, and a source that cannot be reached degrades
    with a RECORDED gap instead of silence."""
    store = ThreatModelStore(root_dir=tmp_path)
    tools = _tools(
        store,
        projection={"unit_id": UNIT, "data_items": {"reads": ["item"]}},
        surface_overview={"core_features": ["catalogue"],
                          "user_journeys": ["browse -> add -> publish"]},
    )
    turns = _ScriptedTurns()
    asyncio.run(arun_modeller_pass(PROJECT, RUN, UNIT, tools, turn_fn=turns))

    first = turns.turn_inputs[0]
    assert first.projection["unit_id"] == UNIT
    assert first.surface_overview["core_features"] == ["catalogue"]
    assert first.context_gaps == ()

    absent = _ScriptedTurns()
    # a unit with no model yet: the seeded tracker must not skip the states
    asyncio.run(arun_modeller_pass(PROJECT, RUN, "Service:second-unit",
                                   _tools(store), turn_fn=absent))
    gaps = absent.turn_inputs[0].context_gaps
    assert len(gaps) == 2
    assert any("projection unavailable" in gap for gap in gaps)
    assert any("surface overview unavailable" in gap for gap in gaps)


def test_a_context_provider_supplies_the_grounding_per_unit(tmp_path):
    """A live provider is the seam the run driver wires: it is called per unit
    and a raising read degrades to the recorded gaps."""
    store = ThreatModelStore(root_dir=tmp_path)
    seen: list[str] = []

    def provider(unit_id: str) -> dict:
        seen.append(unit_id)
        return {"projection": {"unit_id": unit_id}, "surface_overview": {"a": 1}}

    turns = _ScriptedTurns()
    outcome = asyncio.run(arun_modeller_pass(
        PROJECT, RUN, UNIT,
        _tools(store, context_provider=provider), turn_fn=turns))

    assert seen == [UNIT]
    assert turns.turn_inputs[0].projection == {"unit_id": UNIT}
    assert outcome.context_gaps == []

    def broken(unit_id: str) -> dict:
        raise RuntimeError("graph unavailable")

    broken_turns = _ScriptedTurns()
    asyncio.run(arun_modeller_pass(
        PROJECT, RUN, "Service:third-unit",
        _tools(store, context_provider=broken), turn_fn=broken_turns))
    assert broken_turns.turn_inputs[0].context_gaps


def test_the_actor_registry_is_keyed_by_run_id_under_a_factory():
    """Both lanes key the registry by run id, so the reap seam and the
    degrade-cause lookup address the same actor the pass built."""
    from polymerhus.attack.hunting import threat_modeller as tm

    stops: list[str] = []

    class _FakeActor:
        def __init__(self, run_id: str):
            self.run_id = run_id
            self.tools = None
            self.project_id = None

        async def turn(self, turn_input):
            return None

        async def stop(self):
            stops.append(self.run_id)

        def last_degrade_cause(self):
            return None

    tm._MODELLER_ACTORS.clear()
    with pytest.raises(tm.ThreatModellerDegradedError):
        asyncio.run(arun_modeller_pass(
            PROJECT, RUN, UNIT, _tools(None), actor_factory=_FakeActor))

    assert set(tm._MODELLER_ACTORS) == {RUN}

    asyncio.run(tm._reap_modeller(RUN))

    assert stops == [RUN]
    assert tm._MODELLER_ACTORS == {}


def test_the_modeller_tool_surface_is_exactly_the_bound_tools(tmp_path):
    """The surface is exactly the modeller's (S1 5): the store, the assessment
    write, the notes, the HTTP-history read pair, exec, and the suite pair -
    and NOT `graph_view`, `kb_query`, the fault-KB aid, or `replay`."""
    store = ThreatModelStore(root_dir=tmp_path)
    surface = build_modeller_tool_surface(PROJECT, UNIT, _tools(store))

    assert set(surface) == set(TOOL_SURFACE)
    assert "assess_impact" in surface
    assert {"graph_view", "kb_query", "query_lightrag", "replay",
            "mint_hunt_config"} & set(surface) == set()


# --- the `assess_impact` tool (schema-5 spec 4, ticket #407) -----------------

def test_the_assess_impact_tool_writes_the_row_and_advances_the_state(tmp_path):
    """The tool is the row's sole writer. The typed args carry the two prose
    blocks and the eight factors; the persistence derives the score and the
    vector; the first call advances `IMPACT_ASSESSED`; and the response is the
    success envelope plus the next-state hint - no score, no vector, no factor
    echo."""
    store = ThreatModelStore(root_dir=tmp_path)
    surface = build_modeller_tool_surface(PROJECT, UNIT, _tools(store))
    _write_to_prior_art(store)
    assert store.read_model(PROJECT, UNIT)["state"] == "PRIOR_ART"

    response = surface["assess_impact"].invoke(
        dict(_payloads()[ModelState.IMPACT_ASSESSED]))

    # the envelope is success plus the next-state cadence hint: no score, no
    # vector, no factor echo
    assert response["ok"] is True
    assert set(response) == {"ok", "hint"}
    model = store.read_model(PROJECT, UNIT)
    assert model["state"] == ModelState.IMPACT_ASSESSED.value
    row = model["impact_assessment"][0]
    assert row["id"] == "ia-1"
    assert row["impact_description"] and row["exploitability_description"]
    assert row["capability"] and row["capability_id"]
    # the score and the vector are the derived CVSS 4.0 values for the factors
    assert row["risk"] == ITEM_RISK
    assert row["risk_vector"] == ITEM_VECTOR
    # the read still reports the section the tool wrote, so the model can read
    # its rows back (the rows are the scored claim, not a gate section)
    assert "impact_assessment" in surface["hunts_store"].invoke(
        {"cmd": "read"})["sections"]


def test_the_assess_impact_tool_rejects_a_field_it_does_not_take(tmp_path):
    """An authored score is not a field of the contract: the args schema refuses
    it with a coded rejection naming the field, so the model can never bias the
    score it must not see."""
    store = ThreatModelStore(root_dir=tmp_path)
    surface = build_modeller_tool_surface(PROJECT, UNIT, _tools(store))
    _write_to_prior_art(store)

    rejection = surface["assess_impact"].invoke({
        **_payloads()[ModelState.IMPACT_ASSESSED], "risk": 9.9})

    assert rejection["ok"] is False
    assert rejection["error"] == "assess_impact_args_rejected"
    assert rejection["fields"] == ["risk"]
    assert store.read_model(PROJECT, UNIT)["impact_assessment"] == []


def test_the_assess_impact_tool_returns_the_store_rejection_with_its_field(
        tmp_path):
    """The store owns the referential check; its coded rejection is re-surfaced
    with the field to fix and the known values, never a raise and never a
    silent write."""
    store = ThreatModelStore(root_dir=tmp_path)
    surface = build_modeller_tool_surface(PROJECT, UNIT, _tools(store))
    _write_to_prior_art(store)

    rejection = surface["assess_impact"].invoke({
        **_payloads()[ModelState.IMPACT_ASSESSED],
        "vulnerability_ref": "v-missing",
    })

    assert rejection["ok"] is False
    assert rejection["error"] == "assess_impact_rejected"
    assert rejection["fields"] == ["vulnerability_ref"]
    assert "v-1" in rejection["detail"]
    assert store.read_model(PROJECT, UNIT)["state"] == "PRIOR_ART"
    assert store.read_model(PROJECT, UNIT)["impact_assessment"] == []


def test_the_assess_impact_factor_descriptions_come_from_the_single_source():
    """The factor semantics and the examples are defined ONCE, in the risk
    module; the tool's `factors` schema renders the same entries, so the tool
    contract and the prompt cannot drift."""
    from polymerhus.attack.hunting.risk_score import FACTOR_DESCRIPTIONS
    from polymerhus.attack.hunting.threat_modeller_tools import (
        AssessImpactArgs,
    )

    properties = AssessImpactArgs.model_json_schema()["$defs"]["RiskMetrics"][
        "properties"]
    missing = [
        f"{field}.{value}: {text}"
        for field, values in FACTOR_DESCRIPTIONS.items()
        for value, text in values.items()
        if text not in properties[field]["description"]
    ]

    assert missing == []


def test_the_assess_impact_rejection_reaches_the_harness_as_a_tool_message(
        tmp_path):
    """The graph's ToolNode invokes a tool with a ToolCall dict and requires a
    ToolMessage back; a rejected field must not raise out of the graph."""
    store = ThreatModelStore(root_dir=tmp_path)
    surface = build_modeller_tool_surface(PROJECT, UNIT, _tools(store))
    _write_to_prior_art(store)

    message = surface["assess_impact"].invoke({
        "name": "assess_impact", "type": "tool_call", "id": "call-1",
        "args": {**_payloads()[ModelState.IMPACT_ASSESSED], "risk": 1.0},
    })

    assert message.tool_call_id == "call-1"
    assert json.loads(message.content)["fields"] == ["risk"]


def test_a_rejected_assessment_does_not_advance_the_tracked_state(tmp_path):
    """The tracking store observes the assessment write only once it landed: a
    refused row raises before the observation, so the pass never reads a gate
    the store never wrote, and a success does advance it."""
    from polymerhus.attack.hunting.threat_modeller import (
        PassiveGateTracker,
        TrackingThreatModelStore,
    )

    store = ThreatModelStore(root_dir=tmp_path)
    tracker = PassiveGateTracker()
    wrapped = TrackingThreatModelStore(store, tracker)
    _write_to_prior_art(store)
    tool = build_modeller_tool_surface(
        PROJECT, UNIT,
        ModellerTools(threat_store=wrapped, project_id=PROJECT, run_id=RUN),
    )["assess_impact"]

    rejected = tool.invoke({
        **_payloads()[ModelState.IMPACT_ASSESSED],
        "vulnerability_ref": "v-missing",
    })
    assert rejected["ok"] is False
    assert tracker.writes == [] and tracker.state is None

    accepted = tool.invoke(dict(_payloads()[ModelState.IMPACT_ASSESSED]))
    assert accepted["ok"] is True
    assert tracker.state is ModelState.IMPACT_ASSESSED
    assert [write.state for write in tracker.writes] == [
        ModelState.IMPACT_ASSESSED]


def test_the_hunts_store_surface_rejects_the_impact_assessment_section(tmp_path):
    """The assessment rows have ONE writer (schema-5 spec 4): `hunts_store` no
    longer takes the section, so the model cannot bypass the tool's contract."""
    store = ThreatModelStore(root_dir=tmp_path)
    surface = build_modeller_tool_surface(PROJECT, UNIT, _tools(store))

    rejection = surface["hunts_store"].invoke({
        "cmd": "write", "state": "IMPACT_ASSESSED",
        "sections": {"impact_assessment": [
            _payloads()[ModelState.IMPACT_ASSESSED]]},
    })

    assert rejection["ok"] is False
    assert rejection["error"] == "hunts_store_args_rejected"
    assert rejection["fields"] == ["sections.impact_assessment"]
    assert store.read_model(PROJECT, UNIT) is None



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
