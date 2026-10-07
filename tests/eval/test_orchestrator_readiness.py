"""Bounded, non-blocking readiness: the HTTP probe and the compose-health check."""
from __future__ import annotations

import json

from orchestrator.commands import Command
from orchestrator.readiness import (
    READY_UNREACHABLE,
    ReadinessPlan,
    compose_healthy,
    compose_probe,
    http_probe,
    parse_compose_health,
    plan_compose_health,
    plan_front_http,
    plan_service_port,
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
        probes=(compose_probe("c.yml", "proj"),), retries=5, interval_s=0
    )
    assert plan.kind == "compose"
    assert wait_readiness(runner, plan, sleep=lambda _s: None)
    assert len(runner.calls) == 3


def test_wait_readiness_http_keeps_polling_through_a_front_502(fake_result):
    """#325: the target front answers 502 while the app binds its port. An HTTP
    readiness plan must never accept that 5xx, and must accept the first
    non-5xx answer once the app serves."""
    runner = _runner([fake_result(stdout="502"), fake_result(stdout="200")])
    plan = ReadinessPlan(
        probes=(http_probe(plan_front_http("t-abc.target")),), retries=5, interval_s=0
    )
    assert plan.kind == "http"
    assert wait_readiness(runner, plan, sleep=lambda _s: None)
    assert len(runner.calls) == 2


def test_wait_readiness_composite_requires_the_front_answer_and_the_stack(
    fake_result,
):
    """#325 finding 5: the composite plan asserts BOTH the front answer and the
    compose health, so a no-healthcheck app's boot window is closed without
    dropping the support-service assertion."""
    healthy = fake_result(stdout=json.dumps([{"Service": "app", "State": "running"}]))
    # Attempt 1: front 502, so the poll short-circuits before compose (1 call).
    # Attempt 2: front 200 and compose healthy (2 calls).
    runner = _runner([fake_result(stdout="502"), fake_result(stdout="200"), healthy])
    plan = ReadinessPlan(
        probes=(
            http_probe(plan_front_http("t-abc.target")),
            compose_probe("c.yml", "proj"),
        ),
        retries=5,
        interval_s=0,
    )
    assert plan.kind == "composite"
    assert [c.description for c in plan.commands] == [
        "probe front t-abc.target",
        "compose health proj",
    ]

    assert wait_readiness(runner, plan, sleep=lambda _s: None)
    assert len(runner.calls) == 3


def test_wait_readiness_composite_rejects_a_ready_front_over_an_unhealthy_stack(
    fake_result,
):
    """A composite plan is not satisfied by the front answer alone: the stack's
    declared health must hold too."""
    runner = _runner(
        [
            fake_result(stdout="200"),
            fake_result(stdout=json.dumps([{"Service": "db", "Health": "starting"}])),
        ]
        * 2
    )
    plan = ReadinessPlan(
        probes=(
            http_probe(plan_front_http("t-abc.target")),
            compose_probe("c.yml", "proj"),
        ),
        retries=2,
        interval_s=0,
    )
    assert not wait_readiness(runner, plan, sleep=lambda _s: None)


def test_plan_front_http_probes_the_loopback_with_the_host_header():
    """The synthetic Host is not resolvable from the eval host, so the front is
    reached on the loopback with an explicit Host header - the same bare-domain
    path recon uses."""
    argv = plan_front_http("t-abc.target").argv
    assert "Host: t-abc.target" in argv
    assert "http://127.0.0.1/" in argv


def test_plan_service_port_resolves_the_published_port_then_probes_it():
    """#323: an application service is published on an ephemeral host port; the
    probe resolves it from the running container and reads its own answer, so a
    backend reachable only behind the front root is still asserted."""
    command = plan_service_port("web_jetlinks", "jetlinks", 8848)
    argv = " ".join(command.argv)
    assert "docker compose -p web_jetlinks port jetlinks 8848" in argv
    assert "127.0.0.1:" in argv
    assert "%{http_code}" in argv
    assert command.description == "probe app port jetlinks"


def test_plan_service_port_pins_the_compose_file_against_the_caller_cwd():
    """A compose file in the caller's cwd must not shadow the target's own
    services; the probe pins the resolved compose like the compose poll."""
    command = plan_service_port(
        "web_jetlinks", "jetlinks", 8848, compose_file="/bank/jetlinks.yml"
    )
    assert "-f /bank/jetlinks.yml" in " ".join(command.argv)


def test_wait_readiness_rejects_a_ready_front_while_a_backend_boots(fake_result):
    """#323: the front `/` answers 200 (served by `ui`) while the `jetlinks`
    backend answers 000 because its JVM is still booting. A composite plan must
    not read ready until every application service answers."""
    plan = ReadinessPlan(
        probes=(
            http_probe(plan_front_http("t-abc.target")),
            http_probe(plan_service_port("web_t", "jetlinks", 8848)),
            compose_probe("c.yml", "proj"),
        ),
        retries=5,
        interval_s=0,
    )
    runner = _runner(
        [
            fake_result(stdout="200"),
            fake_result(stdout="000"),
            fake_result(stdout="200"),
            fake_result(stdout="404"),
            fake_result(stdout=json.dumps([{"Service": "jetlinks", "State": "running"}])),
        ]
    )
    assert wait_readiness(runner, plan, sleep=lambda _s: None)
    assert [c.description for c in runner.calls] == [
        "probe front t-abc.target",
        "probe app port jetlinks",
        "probe front t-abc.target",
        "probe app port jetlinks",
        "compose health proj",
    ]


def test_wait_readiness_compose_times_out(fake_result):
    starting = fake_result(stdout=json.dumps([{"Health": "starting"}]))
    runner = _runner([starting] * 2)
    plan = ReadinessPlan(
        probes=(compose_probe("c.yml", "proj"),), retries=2, interval_s=0
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
