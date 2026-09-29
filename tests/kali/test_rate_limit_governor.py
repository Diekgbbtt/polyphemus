"""#238 Task 7 - the shared per-target egress governor.

One asynchronous token bucket per `(project_id, target_key)`: every concurrent
namespace lease for the same target consumes the SAME allowance, different
targets and projects stay independent, and a material policy change replaces
the limits without ever granting more traffic than the new policy allows.

Determinism: the monotonic clock and the async waiter are injected, so "wait
for the refill" is an arithmetic assertion, never a sleep. The waiter advances
the fake clock by exactly the amount it was asked to wait.
"""
from __future__ import annotations

import asyncio

import pytest

from kali.http_history.governor import (
    TargetGovernor,
    TrafficContext,
    validate_traffic_policy,
)


class FakeClock:
    def __init__(self, start: float = 1000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeSleeper:
    """Records every wait and advances the fake clock by exactly that amount."""

    def __init__(self, clock: FakeClock):
        self.clock = clock
        self.waits: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)
        self.clock.advance(seconds)


class BlockingSleeper(FakeSleeper):
    """Blocks on its FIRST wait (so the caller can cancel it), then behaves."""

    def __init__(self, clock: FakeClock):
        super().__init__(clock)
        self.gate = asyncio.Event()
        self.blocked = False

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)
        if not self.blocked:
            self.blocked = True
            await self.gate.wait()
        else:
            self.clock.advance(seconds)


def _policy(**overrides) -> dict:
    base = {
        "target_key": "app.example.com",
        "host_patterns": ["app.example.com"],
        "rate_per_s": 2.0,
        "burst": 1,
        "max_concurrency": 1,
        "min_delay_ms": 500.0,
        "source": "measured-transition",
        "version": "traffic-policy/v2",
    }
    base.update(overrides)
    return base


def _governor(clock, sleeper) -> TargetGovernor:
    return TargetGovernor(clock=clock, sleeper=sleeper)


def _acquire(
    governor, policy, *, project="p1", host="app.example.com",
    source_ip="10.0.0.2", release=True,
):
    """Acquire (and by default immediately release) one permit, so these tests
    pin the BUCKET arithmetic independently of the concurrency ceiling - a held
    permit would otherwise block the next acquire by design."""

    async def _run():
        decision = await governor.acquire(
            project,
            traffic_policy=policy,
            context=TrafficContext(source_ip=source_ip, request_host=host),
        )
        if release and decision.permit is not None:
            await governor.release(decision.permit)
        return decision

    return asyncio.run(_run())


def test_burst_tokens_are_consumed_before_any_wait():
    clock, sleeper = FakeClock(), None
    sleeper = FakeSleeper(clock)
    governor = _governor(clock, sleeper)

    decisions = [_acquire(governor, _policy(rate_per_s=1.0, burst=3)) for _ in range(3)]

    assert [d.governed for d in decisions] == [True, True, True]
    assert [d.waited_s for d in decisions] == [0.0, 0.0, 0.0]
    assert sleeper.waits == []


def test_the_next_request_waits_for_the_refill_the_bucket_owes():
    clock, sleeper = FakeClock(), None
    sleeper = FakeSleeper(clock)
    governor = _governor(clock, sleeper)

    first = _acquire(governor, _policy(rate_per_s=2.0, burst=1))
    second = _acquire(governor, _policy(rate_per_s=2.0, burst=1))

    assert first.waited_s == 0.0
    assert second.governed is True
    assert second.waited_s == pytest.approx(0.5)
    assert sleeper.waits == pytest.approx([0.5])


def test_two_concurrent_pods_of_one_project_and_target_share_one_bucket():
    """The Review Focus pin: concurrent namespace leases for one target consume
    ONE bucket, so the offered rate is aggregate, not per-pod."""
    clock = FakeClock()
    sleeper = FakeSleeper(clock)
    governor = _governor(clock, sleeper)
    policy = _policy(rate_per_s=1.0, burst=1, max_concurrency=2)

    async def scenario():
        return await asyncio.gather(
            governor.acquire(
                "p1", traffic_policy=policy,
                context=TrafficContext(source_ip="10.0.0.2", request_host="app.example.com"),
            ),
            governor.acquire(
                "p1", traffic_policy=policy,
                context=TrafficContext(source_ip="10.0.0.3", request_host="app.example.com"),
            ),
        )

    decisions = asyncio.run(scenario())

    assert [d.governed for d in decisions] == [True, True]
    # Exactly one caller paid the refill: two pods cannot both spend the burst.
    assert sleeper.waits == pytest.approx([1.0])


def test_different_targets_and_projects_keep_independent_buckets():
    clock = FakeClock()
    sleeper = FakeSleeper(clock)
    governor = _governor(clock, sleeper)
    policy = _policy(rate_per_s=1.0, burst=1)

    # p1/app.example.com: the first call spends the burst, the second pays.
    _acquire(governor, policy, project="p1", host="app.example.com")
    assert _acquire(governor, policy, project="p1").waited_s == pytest.approx(1.0)

    # Two DIFFERENT buckets start full, so neither waits for the other.
    other_policy = _policy(target_key="other.example.com", host_patterns=["other.example.com"])
    assert _acquire(governor, other_policy, host="other.example.com").waited_s == 0.0
    assert _acquire(governor, policy, project="p2", host="app.example.com").waited_s == 0.0
    assert sleeper.waits == pytest.approx([1.0])


def test_a_material_policy_change_uses_the_new_rate_immediately():
    clock = FakeClock()
    sleeper = FakeSleeper(clock)
    governor = _governor(clock, sleeper)

    _acquire(governor, _policy(rate_per_s=1.0, burst=1))
    relaxed = _acquire(governor, _policy(rate_per_s=10.0, burst=1))

    # The bucket now refills at the NEW rate: 1/10 s, not 1/1 s.
    assert relaxed.waited_s == pytest.approx(0.1)
    assert sleeper.waits == pytest.approx([0.1])

    # ... and a stricter replacement slows the next wait down again.
    _acquire(governor, _policy(rate_per_s=2.0, burst=1))
    assert sleeper.waits[-1] == pytest.approx(0.5)


def test_a_narrower_burst_replacement_never_gifts_the_old_allowance():
    clock = FakeClock()
    sleeper = FakeSleeper(clock)
    governor = _governor(clock, sleeper)

    _acquire(governor, _policy(rate_per_s=1.0, burst=4))  # 3 tokens left over
    narrow = _policy(rate_per_s=1.0, burst=1)

    first = _acquire(governor, narrow)  # the new burst of 1, immediately
    second = _acquire(governor, narrow)  # ... and nothing more

    assert first.waited_s == 0.0
    assert second.waited_s == pytest.approx(1.0)
    assert sleeper.waits == pytest.approx([1.0])


def test_a_foreign_host_is_not_governed_by_this_targets_policy():
    clock = FakeClock()
    sleeper = FakeSleeper(clock)
    governor = _governor(clock, sleeper)
    policy = _policy(rate_per_s=1.0, burst=1)

    _acquire(governor, policy, host="app.example.com")
    foreign = _acquire(governor, policy, host="unrelated.example.net")

    assert foreign.governed is False
    assert sleeper.waits == []


def test_host_patterns_match_exactly_and_by_wildcard():
    clock = FakeClock()
    sleeper = FakeSleeper(clock)
    governor = _governor(clock, sleeper)
    policy = _policy(
        target_key="example.com", host_patterns=["example.com", "*.example.com"],
        rate_per_s=1.0, burst=1,
    )

    assert _acquire(governor, policy, host="example.com").governed is True
    assert _acquire(governor, policy, host="api.example.com").governed is True
    assert _acquire(governor, policy, host="example.com.evil.net").governed is False
    assert _acquire(governor, policy, host="example.net").governed is False


def test_an_empty_host_pattern_list_governs_whatever_this_project_sends():
    clock = FakeClock()
    sleeper = FakeSleeper(clock)
    governor = _governor(clock, sleeper)
    assert _acquire(governor, _policy(host_patterns=[]), host=None).governed is True


def test_an_unvalidated_policy_is_never_enforced():
    clock = FakeClock()
    sleeper = FakeSleeper(clock)
    governor = _governor(clock, sleeper)

    assert validate_traffic_policy(_policy()) is not None
    for broken in (
        None,
        {},
        _policy(version="traffic-policy/v1"),
        _policy(target_key=""),
        _policy(rate_per_s=0),
        _policy(burst=0),
        "not-a-policy",
    ):
        assert validate_traffic_policy(broken) is None
        assert _acquire(governor, broken).governed is False
    assert sleeper.waits == []


def test_a_cancelled_waiter_does_not_wedge_the_bucket():
    """The lock is released BEFORE the sleep: a cancelled waiter must not leave
    the per-target bucket unusable for the pods that follow it."""
    clock = FakeClock()
    sleeper = BlockingSleeper(clock)
    governor = _governor(clock, sleeper)
    policy = _policy(rate_per_s=1.0, burst=1, max_concurrency=2)

    async def scenario():
        await governor.acquire(
            "p1", traffic_policy=policy,
            context=TrafficContext(source_ip="10.0.0.2", request_host="app.example.com"),
        )
        cancelled = asyncio.create_task(
            governor.acquire(
                "p1", traffic_policy=policy,
                context=TrafficContext(source_ip="10.0.0.3", request_host="app.example.com"),
            )
        )
        for _ in range(1000):
            if sleeper.waits:
                break
            await asyncio.sleep(0)
        cancelled.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled
        return await governor.acquire(
            "p1", traffic_policy=policy,
            context=TrafficContext(source_ip="10.0.0.4", request_host="app.example.com"),
        )

    followup = asyncio.run(scenario())

    assert followup.governed is True
    # The cancelled waiter consumed no token and advanced no clock: the next
    # caller owes exactly the same refill.
    assert followup.waited_s == pytest.approx(1.0)
    assert sleeper.waits == pytest.approx([1.0, 1.0])


def test_status_reports_the_governed_buckets():
    clock = FakeClock()
    sleeper = FakeSleeper(clock)
    governor = _governor(clock, sleeper)
    _acquire(governor, _policy())
    _acquire(governor, _policy(target_key="other.example.com",
                               host_patterns=["other.example.com"]),
             host="other.example.com")
    status = governor.status()
    assert status["buckets"] == 2
    assert sorted(status["keys"]) == ["p1/app.example.com", "p1/other.example.com"]


# --- #238 follow-up (Task 6): concurrency permits -----------------------------


def _ctx(source_ip="10.0.0.2", host="app.example.com"):
    return TrafficContext(source_ip=source_ip, request_host=host)


def test_concurrency_ceiling_blocks_the_next_flow_until_release():
    clock, sleeper = FakeClock(), None
    sleeper = FakeSleeper(clock)
    governor = _governor(clock, sleeper)
    policy = _policy(rate_per_s=1000.0, burst=10, max_concurrency=1)

    async def scenario():
        first = await governor.acquire("p1", traffic_policy=policy, context=_ctx())
        second = asyncio.create_task(
            governor.acquire("p1", traffic_policy=policy, context=_ctx("10.0.0.3"))
        )
        await asyncio.sleep(0.05)
        blocked = not second.done()
        await governor.release(first.permit)
        allowed = (await asyncio.wait_for(second, timeout=2.0)).governed
        return blocked, allowed

    blocked, allowed = asyncio.run(scenario())
    assert blocked, "the second flow was admitted past the concurrency ceiling"
    assert allowed
    assert governor.status()["peak_inflight"] == 1


def test_a_different_source_ip_cannot_partition_the_shared_capacity():
    """The Review Focus adversarial pin: source IP is lookup transport only."""
    clock = FakeClock()
    sleeper = FakeSleeper(clock)
    governor = _governor(clock, sleeper)
    policy = _policy(rate_per_s=1000.0, burst=10, max_concurrency=1)

    async def scenario():
        first = await governor.acquire("p1", traffic_policy=policy, context=_ctx("10.0.0.2"))
        second = asyncio.create_task(
            governor.acquire("p1", traffic_policy=policy, context=_ctx("10.0.0.9"))
        )
        await asyncio.sleep(0.05)
        blocked = not second.done()
        await governor.release(first.permit)
        await asyncio.wait_for(second, timeout=2.0)
        return blocked

    assert asyncio.run(scenario())
    assert governor.status()["duplicate_releases"] == 0


def test_different_projects_keep_independent_concurrency():
    clock = FakeClock()
    sleeper = FakeSleeper(clock)
    governor = _governor(clock, sleeper)
    policy = _policy(rate_per_s=1000.0, burst=10, max_concurrency=1)

    async def scenario():
        await governor.acquire("p1", traffic_policy=policy, context=_ctx())
        second = await asyncio.wait_for(
            governor.acquire("p2", traffic_policy=policy, context=_ctx()),
            timeout=1.0,
        )
        return second.governed

    assert asyncio.run(scenario()) is True


def test_a_duplicate_release_is_counted_and_never_over_admits():
    clock = FakeClock()
    sleeper = FakeSleeper(clock)
    governor = _governor(clock, sleeper)
    policy = _policy(rate_per_s=1000.0, burst=10, max_concurrency=1)

    async def scenario():
        first = await governor.acquire("p1", traffic_policy=policy, context=_ctx())
        await governor.release(first.permit)
        await governor.release(first.permit)  # doubled response/error hook
        return await governor.acquire("p1", traffic_policy=policy, context=_ctx())

    decision = asyncio.run(scenario())
    assert decision.governed
    assert governor.status()["duplicate_releases"] == 1
    assert governor.status()["inflight"] == 1


def test_an_admitted_decision_carries_a_permit_and_an_unarmed_one_does_not():
    clock = FakeClock()
    sleeper = FakeSleeper(clock)
    governor = _governor(clock, sleeper)
    admitted = _acquire(governor, _policy())
    ungoverned = _acquire(governor, _policy(), host="elsewhere.example.net")
    assert admitted.governed is True
    assert ungoverned.governed is False and ungoverned.permit is None


def test_the_supported_policy_versions_are_advertised():
    status = TargetGovernor(clock=FakeClock(), sleeper=FakeSleeper(FakeClock())).status()
    assert "traffic-policy/v2" in status["supported_policy_versions"]


# --- the adversarial regression gate (#238 Task 11) -------------------------------
#
# One test per deliberate one-line regression (plan Task 11 Step 4). Each is
# named exactly as the gate table names it, so "does the suite kill this
# mutation?" is answerable by `pytest -k <name>`. The recon-armed LIVE twins of
# the timing rows were retired with the deterministic-admission gate (#238 LLM
# Configurator): the governor is no longer armed by the recon path, so its
# contract is certified here and by the direct-MCP mapping tier
# (`tests/e2e/test_rate_limit_mapping_e2e.py`).


def test_same_project_different_source_ips_share_live_bucket():
    """Kills: "add `source_ip` to the governor bucket key".

    Two namespaces of ONE project asking for ONE target are paced by ONE token
    bucket. A key that included the source address would let each namespace
    spend the whole allowance, so the second call would return immediately.
    """
    clock = FakeClock()
    sleeper = FakeSleeper(clock)
    governor = _governor(clock, sleeper)
    policy = _policy(rate_per_s=1.0, burst=1, max_concurrency=8)

    first = _acquire(governor, policy, source_ip="10.0.0.2")
    second = _acquire(governor, policy, source_ip="10.0.0.9")

    assert first.governed is True and second.governed is True
    assert sleeper.waits, (
        "the second source address spent the SAME bucket and had to wait; a "
        "key partitioned by source_ip would have admitted it for free")
    assert sum(sleeper.waits) == pytest.approx(1.0, abs=1e-6)
    assert governor.status()["keys"] == ["p1/app.example.com"]


def test_live_target_never_exceeds_policy_concurrency():
    """Kills: "ignore `max_concurrency`".

    The target's peak in-flight is the observable the live twin reads; here the
    held permits stand in for it. Three concurrent flows under
    `max_concurrency=2` admit exactly two and hold the third.
    """
    clock = FakeClock()
    sleeper = FakeSleeper(clock)
    governor = _governor(clock, sleeper)
    policy = _policy(rate_per_s=1000.0, burst=10, max_concurrency=2)

    async def scenario():
        held = [
            await governor.acquire("p1", traffic_policy=policy, context=_ctx())
            for _ in range(2)
        ]
        blocked = asyncio.create_task(
            governor.acquire("p1", traffic_policy=policy, context=_ctx()))
        await asyncio.sleep(0.05)
        peak = governor.status()["inflight"]
        still_blocked = not blocked.done()
        await governor.release(held[0].permit)
        third = await asyncio.wait_for(blocked, timeout=2.0)
        return len(held), peak, still_blocked, third

    held, peak, still_blocked, third = asyncio.run(scenario())
    assert held == 2
    assert peak == 2, "the peak in-flight exceeded the enforced concurrency"
    assert still_blocked, "a third concurrent flow was over-admitted"
    assert third.governed is True
