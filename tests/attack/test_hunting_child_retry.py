"""F-026 (B): the per-child transient-failure ledger and the mover's deferral.

A single child provider failure is infrastructure, not a run failure: the failed
item backs off while its siblings stay live. Only quota exhaustion or the third
consecutive transient failure of ONE child is fatal, and only then does the
#331 stop/flush/stamp handler pause the run. These tests pin the pure ledger and
the mover's dispatch deferral; the runtime tests pin the live sibling behaviour.
"""
from polymerhus.attack.hunting.mover import (
    DeliveryPlan,
    ThreatLoopItem,
    deduce_delivery,
)
from polymerhus.attack.hunting.surfer import (
    DEFAULT_CHILD_RETRY_BACKOFF_S,
    MAX_CONSECUTIVE_CHILD_FAILURES,
    RunDispatchState,
)
from polymerhus.app.llm.provider_failure import ProviderUnavailableError


def _throttle(*, retry_after_s=None, quota=False) -> ProviderUnavailableError:
    return ProviderUnavailableError(
        "Go usage limit exceeded", status_code=429,
        retry_after_s=retry_after_s, quota_exhausted=quota,
    )


def _recovered_loop() -> ThreatLoopItem:
    return ThreatLoopItem(
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


# --- the ledger ---------------------------------------------------------------

def test_a_transient_failure_defers_only_that_child_and_never_pauses_the_run():
    state = RunDispatchState()
    error = _throttle(retry_after_s=10.0)

    fatal = state.record_child_failure("hunt-a", error, now=100.0)

    assert fatal is False
    assert state.provider_failure is None
    assert state.deferred_session_ids(now=100.0) == {"hunt-a"}
    assert state.deferred_session_ids(now=109.999) == {"hunt-a"}
    assert state.deferred_session_ids(now=110.0) == frozenset()
    assert state.child_failures["hunt-a"].attempts == 1
    assert state.child_failures["hunt-a"].error is error


def test_a_second_different_child_is_not_fatal_on_its_first_failure():
    state = RunDispatchState()
    assert state.record_child_failure("hunt-a", _throttle(), now=0.0) is False
    assert state.record_child_failure("hunt-b", _throttle(), now=0.0) is False
    assert state.provider_failure is None
    assert state.child_failures["hunt-a"].attempts == 1
    assert state.child_failures["hunt-b"].attempts == 1


def test_three_consecutive_transient_failures_of_one_child_are_fatal():
    state = RunDispatchState()
    error = _throttle()
    for _ in range(MAX_CONSECUTIVE_CHILD_FAILURES - 1):
        assert state.record_child_failure("hunt-a", error, now=0.0) is False
        assert state.provider_failure is None

    assert state.record_child_failure("hunt-a", error, now=0.0) is True
    assert state.provider_failure is error


def test_a_success_resets_the_consecutive_count():
    state = RunDispatchState()
    error = _throttle()
    assert state.record_child_failure("hunt-a", error, now=0.0) is False
    assert state.record_child_failure("hunt-a", error, now=0.0) is False

    state.record_child_success("hunt-a")

    assert "hunt-a" not in state.child_failures
    for _ in range(MAX_CONSECUTIVE_CHILD_FAILURES - 1):
        assert state.record_child_failure("hunt-a", error, now=0.0) is False
    assert state.record_child_failure("hunt-a", error, now=0.0) is True


def test_quota_exhaustion_is_fatal_on_the_first_failure():
    state = RunDispatchState()
    error = _throttle(quota=True)

    assert state.record_child_failure("hunt-a", error, now=0.0) is True
    assert state.provider_failure is error
    assert state.child_failures["hunt-a"].attempts == 1


def test_the_default_backoff_applies_when_the_provider_supplies_none():
    state = RunDispatchState()
    state.record_child_failure("hunt-a", _throttle(), now=0.0)
    assert state.child_failures["hunt-a"].retry_after == (
        DEFAULT_CHILD_RETRY_BACKOFF_S)


# --- the mover's deferral -----------------------------------------------------

def test_a_deferred_item_is_neither_dispatched_nor_moved():
    item = _recovered_loop()
    plan = deduce_delivery(
        [item], deferred_session_ids={item.session_id})
    assert plan == DeliveryPlan(to_dispatch=(), to_move=(), to_retry=())
    # It remains pending work, so the surfer's quiesce predicate cannot pass;
    # the runtime integration tests prove that end to end.


def test_a_live_deferred_item_still_lands_its_admission_move():
    """The crash-window move is about admission, not dispatch: a live item that
    is also backing off must still land the produced->consumed marker (and a
    recovered one is already moved, so no plan at all)."""
    produced = ThreatLoopItem(
        message_id="Service-a__loop-1",
        session_id="hunting:run-1:hunt:Service-a__loop-1",
        unit_id="Service:a",
        unit_name="Service-a",
        loop_id="loop-1",
        dispatch_id="Service-a__loop-1",
        likelihood="high",
        record={},
    )
    plan = deduce_delivery(
        [produced], live_session_ids={produced.session_id},
        deferred_session_ids={produced.session_id})
    assert plan.to_move == (produced,)
    assert plan.to_dispatch == () and plan.to_retry == ()

    recovered = _recovered_loop()
    plan = deduce_delivery(
        [recovered], live_session_ids={recovered.session_id},
        deferred_session_ids={recovered.session_id})
    assert plan == DeliveryPlan(to_dispatch=(), to_move=(), to_retry=())
