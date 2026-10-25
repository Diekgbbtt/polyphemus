"""Unit tier: the inbox-surfer mover deduction + the ADR Q13 session scheme
(tracker #172, ADR #169 Q3/Q11/Q13, spec #169 "The inbox surfer semantics").

The CORE of the wiring ticket: the mover deduction is a PURE function -
given (the produced set, the session registry state, the dispatch feedback
for this tick) it returns (to dispatch, to move produced->consumed, to retry).
Unit-tested IN MEMORY (CODING_STANDARD s3/s6/s10): no I/O, no clock, no driver;
equal inputs -> equal outputs. Pins the at-least-once protocol:

- a produced item never dispatched -> in to_dispatch;
- an item whose dispatch was admitted and confirmed -> in to_move (the
  produced->consumed move IS the at-least-once marker);
- a refused dispatch (gate full, module paused, run draining) -> in to_retry,
  REMAINING in produced - never dropped, never moved;
- an item whose session id is already live in the registry is considered
  dispatched (the double-dispatch defense at the deduction level) and the
  marker is completed by the move - the R3 crash window closes without extra
  markers;
- an empty produced set -> all-empty outputs.

Also pins the session-id builders exactly as ADR Q13 spells them:
modeller `hunting:<run_id>:threat-modeller` (T10 removed the planner-era
`orchestrator` segment; there is no alias), hunter
`hunting:<run_id>:hunt:<dispatch_id>`, pod
`hunting:<run_id>:pod:<dispatch_id>:<spec_id>`.
"""
import pytest

from polymerhus.attack.hunting.mover import (
    DeliveryPlan,
    DispatchFeedback,
    ProducedItem,
    TestSpecItem,
    ThreatLoopItem,
    d4_spec_body,
    deduce_delivery,
    hunter_session_id,
    pod_session_id,
    sequence_dispatch,
    threat_loop_item,
)


def _item(message_id="m-1", session_id="s-1"):
    """One base produced item for the pure deduction tests."""
    return ProducedItem(message_id=message_id, session_id=session_id)


UNIT = "Service:catalogue-and-discovery"
UNIT_NAME = "Service-catalogue-and-discovery"
RUN = "run-1"
PROJECT = "proj-1"


def _loop_record(*, unit_id=UNIT, loop_id="loop-1", likelihood="high",
                 run_id=RUN, **overrides) -> dict:
    """One loop file record exactly as the store writes it (S2 8.1)."""
    unit_name = unit_id.replace(":", "-")
    record = {
        "loop_id": loop_id,
        "unit_id": unit_id,
        "unit_kind": "service",
        "run_id": run_id,
        "dispatch_id": f"{unit_name}__{loop_id}",
        "likelihood": likelihood,
        "loop": {
            "id": loop_id,
            "fault_ref": "fault-1",
            "vulnerability_ref": "v-1",
            "failure_mode_refs": ["fm-1"],
            "canonical_class": "IDOR",
            "web_vulnerability_class": "idor",
            "likelihood": likelihood,
            "likelihood_rationale": "the item id is caller-supplied",
            "confidence": "INFERRED",
            "evidences": [{"kind": "request", "ref": "GET /catalogue?id=2"}],
        },
        "created_at": "2026-10-19T00:00:00Z",
    }
    record.update(overrides)
    return record


def _loop_item(*, record=None, loop_id="loop-1", likelihood="high",
               run_id=RUN, unit_id=UNIT, unit_name=UNIT_NAME) -> "ThreatLoopItem | None":
    return threat_loop_item(
        project_id=PROJECT, unit_id=unit_id, unit_name=unit_name, loop_id=loop_id,
        record=_loop_record(unit_id=unit_id, loop_id=loop_id,
                            likelihood=likelihood, run_id=run_id)
        if record is None else record,
        run_id=run_id,
    )


# --- the loop dispatch record and the validity predicate (T4, #377) -----------

def test_a_produced_loop_file_becomes_one_dispatch_item():
    """S2 8.1/8.4: ONE loop file dispatches ONE hunter. The item's message id IS
    the loop file's dispatch id and its session id is the per-loop hunter id
    (S3 8.9) - the loop record travels with the item for the payload."""
    item = _loop_item()

    assert item is not None
    assert item.message_id == f"{UNIT_NAME}__loop-1"
    assert item.session_id == f"hunting:{RUN}:hunt:{UNIT_NAME}__loop-1"
    assert item.unit_id == UNIT
    assert item.unit_name == UNIT_NAME
    assert item.loop_id == "loop-1"
    assert item.likelihood == "high"
    assert item.record["loop"]["id"] == "loop-1"


def test_a_loop_file_from_another_run_is_refused():
    """S2 8.3: the sequencing is run-scoped - another run's loop file is left
    untouched, never dispatched by this run."""
    assert _loop_item(record=_loop_record(run_id="another-run")) is None
    assert _loop_item(record=_loop_record(), run_id="another-run") is None


@pytest.mark.parametrize("broken", [
    pytest.param("not-a-mapping", id="record-not-a-mapping"),
    pytest.param({**_loop_record(), "likelihood": "urgent"}, id="bad-likelihood"),
    pytest.param({**_loop_record(), "likelihood": "none"}, id="none-has-no-file"),
    pytest.param({**_loop_record(), "dispatch_id": ""}, id="missing-dispatch-id"),
    pytest.param({**_loop_record(), "dispatch_id": f"{UNIT_NAME}__loop-2"},
                 id="dispatch-id-disagrees-with-the-file"),
    pytest.param({**_loop_record(), "unit_id": ""}, id="missing-unit-id"),
    pytest.param({**_loop_record(), "unit_kind": "unknown"}, id="bad-unit-kind"),
    pytest.param({**_loop_record(), "loop": None}, id="missing-loop-record"),
    pytest.param({**_loop_record(), "loop": {"id": "loop-1"}},
                 id="loop-record-without-its-refs"),
])
def test_a_malformed_loop_file_is_refused(broken):
    """S2 8.4 (T4 AC): a malformed loop is refused - it is never dispatched and
    never counted as dispatchable work, so it cannot wedge the quiesce."""
    assert _loop_item(record=broken) is None


def test_the_file_stem_must_be_the_loop_id_of_the_form():
    """The store owns the `loop-<rank>` id (S2 10.2); a file whose stem is not
    one (or disagrees with the record) is refused."""
    assert _loop_item(loop_id="loop-2", record=_loop_record()) is None
    assert _loop_item(
        loop_id="not-a-loop", record=_loop_record(loop_id="not-a-loop")) is None
    assert _loop_item(
        loop_id="loop-1",
        record=_loop_record(loop_id="loop-2",
                            dispatch_id=f"{UNIT_NAME}__loop-2")) is None


# --- the dispatch sequencing filter (S2 8.3, S1 7.6) --------------------------

def test_higher_tier_loops_dispatch_and_low_loops_pause_behind_them():
    high = _loop_item()
    low = _loop_item(
        loop_id="loop-2",
        record=_loop_record(loop_id="loop-2", dispatch_id=f"{UNIT_NAME}__loop-2",
                            likelihood="low"),
    )

    assert sequence_dispatch([low]) == (low,)
    assert sequence_dispatch([high, low]) == (high,)
    assert sequence_dispatch([low, high]) == (high,)


def test_a_low_loop_pauses_while_a_higher_tier_session_is_live():
    low = _loop_item(record=_loop_record(likelihood="low"))

    assert sequence_dispatch([low], live_likelihoods={"d-1": "medium"}) == ()
    assert sequence_dispatch([low], live_likelihoods={"d-1": "low"}) == (low,)
    assert sequence_dispatch([low], live_likelihoods=()) == (low,)
    assert sequence_dispatch([low], live_likelihoods={"d-1": "none"}) == (low,)


def test_the_low_pause_is_per_tick_and_cross_unit():
    """S2 8.3/S1 7.6: a low loop is released on the tick where no higher loop
    file is produced (cross-unit: another unit's produced high loop holds it)."""
    low = _loop_item(record=_loop_record(likelihood="low"))
    other_high = threat_loop_item(
        project_id=PROJECT,
        unit_id="Service:other", unit_name="Service-other", loop_id="loop-1",
        record=_loop_record(
            unit_id="Service:other", dispatch_id="Service-other__loop-1"),
        run_id=RUN,
    )

    assert sequence_dispatch([low, other_high]) == (other_high,)
    assert sequence_dispatch([low]) == (low,)


def test_sequence_dispatch_leaves_the_spec_family_alone():
    """The pod path stays (S3 8.7): the sequencing ranks LOOPS; a produced spec
    is not held by a higher-ranked loop file."""
    spec = TestSpecItem(message_id="k/f.yaml", session_id="s", hunt_key="k",
                        spec_file="f.yaml")
    assert sequence_dispatch([spec]) == (spec,)


# --- empty and never-dispatched ------------------------------------------------

def test_empty_produced_set_yields_all_empty_outputs():
    plan = deduce_delivery([], live_session_ids={"s-1"}, feedback={"ghost": DispatchFeedback.REFUSED})
    assert plan == DeliveryPlan()
    assert plan.to_dispatch == ()
    assert plan.to_move == ()
    assert plan.to_retry == ()


def test_never_dispatched_item_goes_to_dispatch():
    item = _item()
    plan = deduce_delivery([item])
    assert plan.to_dispatch == (item,)
    assert plan.to_move == ()
    assert plan.to_retry == ()


# --- admitted / refused feedback ------------------------------------------------

def test_admitted_feedback_moves_the_item():
    item = _item()
    plan = deduce_delivery([item], feedback={item.message_id: DispatchFeedback.ADMITTED})
    assert plan.to_move == (item,)
    assert plan.to_dispatch == ()
    assert plan.to_retry == ()


def test_refused_feedback_keeps_the_item_in_produced_for_retry():
    item = _item()
    plan = deduce_delivery([item], feedback={item.message_id: DispatchFeedback.REFUSED})
    assert plan.to_retry == (item,)
    assert plan.to_move == ()
    assert plan.to_dispatch == ()


def test_refused_item_redelivers_to_dispatch_on_the_next_tick():
    """At-least-once: a refused item stays produced, and the NEXT tick (no
    carried feedback, still not live) re-attempts it through to_dispatch."""
    item = _item()
    first = deduce_delivery([item], feedback={item.message_id: DispatchFeedback.REFUSED})
    assert first.to_retry == (item,)
    second = deduce_delivery([item])
    assert second.to_dispatch == (item,)
    assert second.to_retry == ()


def test_refused_is_never_moved_or_dispatched_the_same_tick():
    item = _item()
    plan = deduce_delivery([item], feedback={item.message_id: DispatchFeedback.REFUSED})
    assert plan.to_move == () and plan.to_dispatch == ()


# --- the session registry as the double-dispatch defense ------------------------

def test_live_registry_session_is_considered_dispatched_and_moves():
    """A produced item whose session id is already live in the registry is
    considered dispatched (Q12: session id = registry run name): never
    re-dispatched, never refused - and the produced->consumed marker lands
    (this is what closes the R3 crash window without extra markers)."""
    item = _item(session_id="live-1")
    plan = deduce_delivery([item], live_session_ids={"live-1"})
    assert plan.to_move == (item,)
    assert plan.to_dispatch == ()
    assert plan.to_retry == ()


def test_live_registry_defends_double_dispatch_even_against_refused_feedback():
    item = _item(session_id="live-1")
    plan = deduce_delivery(
        [item], live_session_ids={"live-1"},
        feedback={item.message_id: DispatchFeedback.REFUSED},
    )
    assert plan.to_move == (item,)
    assert plan.to_dispatch == ()
    assert plan.to_retry == ()


def test_live_registry_item_is_never_redispatched_when_no_feedback():
    item = _item(session_id="live-1")
    plan = deduce_delivery([item], live_session_ids={"live-1"}, feedback={})
    assert plan.to_dispatch == ()


# --- determinism and the typed contract ------------------------------------------

def test_outputs_preserve_the_produced_order_within_each_action():
    a, b, c, d = (_item(message_id=m, session_id=f"s-{m}") for m in ("a", "b", "c", "d"))
    plan = deduce_delivery(
        [a, b, c, d],
        live_session_ids={"s-d"},
        feedback={a.message_id: DispatchFeedback.ADMITTED,
                  c.message_id: DispatchFeedback.REFUSED},
    )
    assert plan.to_move == (a, d)   # admitted + live, in produced order
    assert plan.to_dispatch == (b,)
    assert plan.to_retry == (c,)


def test_feedback_for_items_outside_the_produced_set_is_ignored():
    item = _item(message_id="m-1")
    plan = deduce_delivery([item], feedback={"ghost": DispatchFeedback.ADMITTED})
    assert plan.to_dispatch == (item,)


def test_unknown_feedback_value_is_rejected():
    item = _item()
    with pytest.raises(ValueError, match="DispatchFeedback"):
        deduce_delivery([item], feedback={item.message_id: "admitted"})


def test_a_recovered_loop_dispatches_but_its_move_is_already_satisfied():
    """F-022: a consumed loop recovered from consumed/ has already landed its
    produced->consumed move. It is dispatched when idle (at-least-once), but an
    admitted or live recovered loop NEVER lands in `to_move` again."""
    loop = ThreatLoopItem(
        message_id="Service-a__loop-1",
        session_id="hunting:run-1:hunt:Service-a__loop-1",
        unit_id="Service:a",
        unit_name="Service-a",
        loop_id="loop-1",
        dispatch_id="Service-a__loop-1",
        likelihood="high",
        record={},
        recovered=True,
    )
    assert deduce_delivery([loop]).to_dispatch == (loop,)
    admitted = deduce_delivery(
        [loop], feedback={loop.message_id: DispatchFeedback.ADMITTED})
    assert admitted == DeliveryPlan(
        to_dispatch=(), to_move=(), to_retry=())
    live = deduce_delivery([loop], live_session_ids={loop.session_id})
    assert live == DeliveryPlan(to_dispatch=(), to_move=(), to_retry=())
    refused = deduce_delivery(
        [loop], feedback={loop.message_id: DispatchFeedback.REFUSED})
    assert refused.to_retry == (loop,)


def test_the_one_loop_predicate_carries_the_recovered_flag():
    record = _loop_record()
    item = threat_loop_item(
        project_id=PROJECT, unit_id=UNIT, unit_name=UNIT_NAME,
        loop_id="loop-1", record=record, run_id=RUN, recovered=True)
    assert item is not None and item.recovered is True
    produced = threat_loop_item(
        project_id=PROJECT, unit_id=UNIT, unit_name=UNIT_NAME,
        loop_id="loop-1", record=record, run_id=RUN)
    assert produced is not None and produced.recovered is False


def test_family_items_mix_in_one_deduction():
    loop = ThreatLoopItem(
        message_id="Service-a__loop-1",
        session_id="hunting:run-1:hunt:Service-a__loop-1",
        unit_id="Service:a",
        unit_name="Service-a",
        loop_id="loop-1",
        dispatch_id="Service-a__loop-1",
        likelihood="high",
        record={},
    )
    spec = TestSpecItem(
        message_id="Service-a__loop-1/sqli_blind",
        session_id="hunting:run-1:pod:Service-a__loop-1:sqli_blind",
        hunt_key="Service-a__loop-1",
        spec_file="sqli__blind__boolean",
    )
    plan = deduce_delivery([loop, spec], feedback={
        loop.message_id: DispatchFeedback.ADMITTED,
        spec.message_id: DispatchFeedback.REFUSED,
    })
    assert plan.to_move == (loop,)
    assert plan.to_retry == (spec,)
    assert plan.to_dispatch == ()


def test_equal_inputs_are_deterministic_across_calls():
    produced = [_item("a", "s-a"), _item("b", "s-b")]
    feedback = {"a": DispatchFeedback.ADMITTED, "b": DispatchFeedback.REFUSED}
    first = deduce_delivery(produced, set(), feedback)
    second = deduce_delivery(produced, set(), feedback)
    assert first == second == DeliveryPlan(
        to_dispatch=(),
        to_move=(_item("a", "s-a"),),
        to_retry=(_item("b", "s-b"),),
    )


# --- the ADR Q13 session-id scheme ----------------------------------------------

def test_hunter_session_id_is_the_adr_shape():
    assert hunter_session_id("r-9", "Service-a__loop-1") == \
        "hunting:r-9:hunt:Service-a__loop-1"


def test_pod_session_id_embeds_config_and_spec():
    assert pod_session_id("r-9", "Service:a_CWE-639_IDOR", "sqli__blind__boolean") == \
        "hunting:r-9:pod:Service:a_CWE-639_IDOR:sqli__blind__boolean"


def test_session_ids_reject_empty_segments():
    with pytest.raises(ValueError):
        hunter_session_id("", "cfg-1")
    with pytest.raises(ValueError):
        hunter_session_id("r-1", "")
    with pytest.raises(ValueError):
        pod_session_id("r-1", "", "spec-1")
    with pytest.raises(ValueError):
        pod_session_id("r-1", "cfg-1", "")

def test_d4_spec_body_drops_only_the_store_metadata():
    """S5 8.4: the pod's INIT gate sees the D4, never the hunter store's
    bookkeeping; a retired field is NOT projected away, so the gate stays the
    authority on the retired names."""
    body = {
        "status": "ratified",
        "discriminators": [
            {"axis": "fault", "value": "sqli"},
            {"axis": "technique", "value": "blind"},
        ],
        "target_identity": {"url": "http://target.example/"},
        "verification_symptoms": ["reflects the marker"],
        "assumptions": [],
        "rationale": "r",
        "parent_spec_ref": None,
        "provenance": {"loop_id": "loop-1"},
    }
    projected = d4_spec_body(body)
    assert projected == {
        key: value for key, value in body.items()
        if key not in ("status",)
    }
    assert "testing_pattern" in d4_spec_body({**body, "testing_pattern": "x"})
    assert d4_spec_body(None) == {}
