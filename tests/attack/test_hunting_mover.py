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
orchestrator `hunting:<run_id>:orchestrator`, hunter
`hunting:<run_id>:hunt:<config_id>`, pod
`hunting:<run_id>:pod:<config_id>:<spec_id>`.
"""
import pytest

from polymerhus.attack.hunting.mover import (
    DeliveryPlan,
    DispatchFeedback,
    HuntConfigItem,
    ProducedItem,
    TestSpecItem,
    deduce_delivery,
    hunter_session_id,
    orchestrator_session_id,
    pod_session_id,
)


def _item(message_id="m-1", session_id="s-1"):
    """One base produced item for the pure deduction tests."""
    return ProducedItem(message_id=message_id, session_id=session_id)


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


def test_family_items_mix_in_one_deduction():
    cfg = HuntConfigItem(
        message_id="Service:a::CWE-639::IDOR",
        session_id="hunting:run-1:hunt:Service:a_CWE-639_IDOR",
        config_key="Service:a::CWE-639::IDOR",
    )
    spec = TestSpecItem(
        message_id="Service:a_CWE-639_IDOR/sqli_blind",
        session_id="hunting:run-1:pod:Service:a_CWE-639_IDOR:sqli_blind",
        fault_key="Service:a_CWE-639_IDOR",
        spec_file="sqli_blind",
    )
    plan = deduce_delivery([cfg, spec], feedback={
        cfg.message_id: DispatchFeedback.ADMITTED,
        spec.message_id: DispatchFeedback.REFUSED,
    })
    assert plan.to_move == (cfg,)
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

def test_orchestrator_session_id_is_the_adr_shape():
    assert orchestrator_session_id("r-9") == "hunting:r-9:orchestrator"


def test_hunter_session_id_is_the_adr_shape():
    assert hunter_session_id("r-9", "Service:a_CWE-639_IDOR") == \
        "hunting:r-9:hunt:Service:a_CWE-639_IDOR"


def test_pod_session_id_embeds_config_and_spec():
    assert pod_session_id("r-9", "Service:a_CWE-639_IDOR", "sqli_blind") == \
        "hunting:r-9:pod:Service:a_CWE-639_IDOR:sqli_blind"


def test_session_ids_reject_empty_segments():
    with pytest.raises(ValueError):
        orchestrator_session_id("")
    with pytest.raises(ValueError):
        hunter_session_id("", "cfg-1")
    with pytest.raises(ValueError):
        hunter_session_id("r-1", "")
    with pytest.raises(ValueError):
        pod_session_id("r-1", "", "spec-1")
    with pytest.raises(ValueError):
        pod_session_id("r-1", "cfg-1", "")