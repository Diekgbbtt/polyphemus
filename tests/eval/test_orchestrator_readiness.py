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


def test_wait_probe_rejects_500(fake_result):
    """A 500 is a live app that is broken, never a ready target."""
    assert "500" in READY_UNREACHABLE
    runner = _runner([fake_result(stdout="500"), fake_result(stdout="200")])
    assert wait_probe(
        runner, Command(argv=("curl",)), retries=3, interval_s=0, sleep=lambda _s: None
    )
    assert len(runner.calls) == 2


def test_http_ready_rejects_every_5xx():
    from orchestrator.readiness import http_ready

    for code in ("", "000", "500", "501", "502", "503", "504", "599"):
        assert not http_ready(code), code
    for code in ("200", "204", "301", "401", "403"):
        assert http_ready(code), code


def test_parse_compose_health_json_array():
    output = json.dumps(
        [
            {"Service": "db", "Health": "healthy", "State": "running", "ExitCode": 0},
            {"Service": "app", "State": "running", "ExitCode": 0},
        ]
    )
    services = parse_compose_health(output)
    assert [(s.service, s.state, s.health, s.exit_code) for s in services] == [
        ("db", "running", "healthy", 0),
        ("app", "running", "", 0),
    ]
    assert compose_healthy(services)


def test_parse_compose_health_json_lines():
    output = (
        '{"Service": "app", "Health": "starting"}\n'
        '{"Service": "db", "State": "running"}'
    )
    services = parse_compose_health(output)
    assert [(s.service, s.state, s.health) for s in services] == [
        ("app", "", "starting"),
        ("db", "running", ""),
    ]


def test_parse_compose_health_empty():
    assert parse_compose_health("") == ()


def test_plan_compose_health_lists_every_service_with_dash_a():
    argv = plan_compose_health("c.yml", "proj").argv
    assert "-a" in argv
    assert argv[-2:] == ("--format", "json")


def test_compose_healthy_all_ready():
    assert compose_healthy(parse_compose_health(json.dumps([
        {"Service": "db", "Health": "healthy", "State": "running", "ExitCode": 0},
        {"Service": "app", "State": "running", "ExitCode": 0},
    ])))


def test_compose_healthy_accepts_a_clean_one_shot_exit():
    assert compose_healthy(parse_compose_health(json.dumps([
        {"Service": "db", "Health": "healthy", "State": "running", "ExitCode": 0},
        {"Service": "migrate", "State": "exited", "ExitCode": 0},
    ])))


def test_compose_healthy_rejects_starting_unhealthy_and_failed_one_shot():
    assert not compose_healthy(parse_compose_health(json.dumps([
        {"Service": "app", "Health": "starting", "State": "running"},
    ])))
    assert not compose_healthy(parse_compose_health(json.dumps([
        {"Service": "app", "Health": "unhealthy", "State": "running"},
    ])))
    assert not compose_healthy(parse_compose_health(json.dumps([
        {"Service": "migrate", "State": "exited", "ExitCode": 1},
    ])))
    assert not compose_healthy(parse_compose_health(json.dumps([
        {"Service": "app", "State": "created"},
    ])))
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
