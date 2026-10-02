"""Bounded, non-blocking readiness: the HTTP probe and the compose-health check."""
from __future__ import annotations

import json

from orchestrator.commands import Command
from orchestrator.readiness import (
    READY_UNREACHABLE,
    ReadinessPlan,
    compose_healthy,
    parse_compose_health,
    plan_compose_health,
    wait_probe,
    wait_readiness,
)


def test_wait_probe_succeeds_on_first_reachable(fake_result):
    runner = _runner([fake_result(stdout="200")])
    assert wait_probe(runner, Command(argv=("curl",)), retries=3, interval_s=0, sleep=lambda _s: None)
    assert len(runner.calls) == 1


def test_wait_probe_retries_then_fails(fake_result):
    runner = _runner([fake_result(stdout="502")] * 3)
    assert not wait_probe(
        runner, Command(argv=("curl",)), retries=3, interval_s=0, sleep=lambda _s: None
    )
    assert len(runner.calls) == 3


def test_wait_probe_treats_front_codes_as_unreachable(fake_result):
    runner = _runner([fake_result(stdout="000"), fake_result(stdout="200")])
    assert wait_probe(
        runner, Command(argv=("curl",)), retries=3, interval_s=0, sleep=lambda _s: None
    )
    assert "000" in READY_UNREACHABLE


def test_parse_compose_health_json_array():
    output = json.dumps(
        [
            {"Service": "db", "Health": "healthy", "State": "running"},
            {"Service": "app", "State": "running"},
        ]
    )
    assert parse_compose_health(output) == ("healthy", "running")


def test_parse_compose_health_json_lines():
    output = '{"Service": "app", "Health": "starting"}\n{"Service": "db", "State": "running"}'
    assert parse_compose_health(output) == ("starting", "running")


def test_parse_compose_health_empty():
    assert parse_compose_health("") == ()


def test_compose_healthy_all_ready():
    assert compose_healthy(("healthy", "running"))


def test_compose_healthy_rejects_starting_or_unhealthy():
    assert not compose_healthy(("healthy", "starting"))
    assert not compose_healthy(("unhealthy",))
    assert not compose_healthy(())


def test_wait_readiness_compose_polls_until_healthy(fake_result):
    starting = fake_result(stdout=json.dumps([{"Health": "starting"}]))
    healthy = fake_result(stdout=json.dumps([{"Health": "healthy"}]))
    runner = _runner([starting, starting, healthy])
    plan = ReadinessPlan(
        probe=plan_compose_health("c.yml", "proj"), retries=5, interval_s=0, kind="compose"
    )
    assert wait_readiness(runner, plan, sleep=lambda _s: None)
    assert len(runner.calls) == 3


def test_wait_readiness_compose_times_out(fake_result):
    starting = fake_result(stdout=json.dumps([{"Health": "starting"}]))
    runner = _runner([starting] * 2)
    plan = ReadinessPlan(
        probe=plan_compose_health("c.yml", "proj"), retries=2, interval_s=0, kind="compose"
    )
    assert not wait_readiness(runner, plan, sleep=lambda _s: None)


class _Runner:
    def __init__(self, results):
        self._results = list(results)
        self.calls = []

    def __call__(self, command):
        self.calls.append(command)
        if self._results:
            return self._results.pop(0)
        return self._results_default()

    @staticmethod
    def _results_default():
        from tests.eval.conftest import FakeResult

        return FakeResult()


def _runner(results):
    return _Runner(results)
