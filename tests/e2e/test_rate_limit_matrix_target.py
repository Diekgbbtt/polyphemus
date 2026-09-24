"""Task 8 (#238 follow-up): the deterministic multi-posture target fixture.

The fixture is the whole "target" the live matrix measures, so its behaviour must
be arithmetic and its inspection API must be generation-guarded and secret-safe.
These tests drive ONE in-process instance per posture - no Compose, no network
namespaces.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from tests.e2e.rate_limit_matrix_target import (
    POSTURES,
    Posture,
    build_server,
    posture_from_env,
)


class Fixture:
    def __init__(self, posture: Posture, secrets: tuple[str, ...] = ()):
        self.server = build_server(posture, host="127.0.0.1", port=0, secrets=secrets)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def _call(self, method: str, path: str, *, headers: dict | None = None):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", method=method, headers=headers or {}
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read() or b"{}"), dict(
                    response.headers
                )
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read() or b"{}"), dict(error.headers)

    def get(self, path: str, **kw):
        return self._call("GET", path, **kw)

    def post(self, path: str, **kw):
        return self._call("POST", path, **kw)

    def reset(self) -> str:
        _status, payload, _headers = self.post("/reset")
        return payload["generation"]

    def counters(self, generation: str):
        return self.get(f"/counters?generation={generation}")


@pytest.fixture
def fixture_factory():
    created: list[Fixture] = []

    def make(posture_name: str, *, secrets: tuple[str, ...] = ()) -> Fixture:
        instance = Fixture(POSTURES[posture_name], secrets=secrets)
        created.append(instance)
        return instance

    yield make
    for instance in created:
        instance.close()


def test_every_documented_posture_exists_and_the_env_selects_one():
    assert set(POSTURES) == {
        "no_limiter", "high_limit", "low_limit", "false_bypass", "burst_inconclusive",
    }
    assert posture_from_env({"RATE_FIXTURE_POSTURE": "low_limit"}).name == "low_limit"
    assert posture_from_env({}).name == "no_limiter"
    with pytest.raises(ValueError, match="RATE_FIXTURE_POSTURE"):
        posture_from_env({"RATE_FIXTURE_POSTURE": "turbo"})


def test_health_reports_the_posture_and_reset_mints_a_new_generation(fixture_factory):
    fixture = fixture_factory("low_limit")
    status, payload, _ = fixture.get("/health")
    assert status == 200 and payload == {"ok": True, "posture": "low_limit"}

    first = fixture.reset()
    second = fixture.reset()
    assert first != second, "a reset must mint a fresh generation"


def test_counters_require_the_current_generation(fixture_factory):
    fixture = fixture_factory("no_limiter")
    generation = fixture.reset()

    status, payload, _ = fixture.get("/counters")
    assert status == 409 and payload["error"] == "generation_required"

    status, payload, _ = fixture.get("/counters?generation=deadbeef")
    assert status == 409 and payload["error"] == "stale_generation"

    status, payload, _ = fixture.counters(generation)
    assert status == 200 and payload["generation"] == generation


def test_reset_isolates_counters_between_scenarios(fixture_factory):
    fixture = fixture_factory("no_limiter")
    generation = fixture.reset()
    fixture.get("/canonical")
    _status, payload, _ = fixture.counters(generation)
    assert payload["requests"] == 1

    fresh = fixture.reset()
    _status, payload, _ = fixture.counters(fresh)
    assert payload["requests"] == 0 and payload["routes"] == {}
    assert payload["events"] == []


# --- posture behaviour -------------------------------------------------------


def test_no_limiter_never_refuses(fixture_factory):
    fixture = fixture_factory("no_limiter")
    generation = fixture.reset()
    statuses = [fixture.get("/canonical")[0] for _ in range(6)]
    assert statuses == [200] * 6
    _status, payload, _ = fixture.counters(generation)
    assert payload["statuses"] == {"200": 6}


def test_low_limit_refuses_a_sustained_burst_with_the_documented_headers(fixture_factory):
    fixture = fixture_factory("low_limit")
    generation = fixture.reset()
    fixture.get("/canonical")  # takes the single permit
    status, payload, headers = fixture.get("/canonical")
    assert status == 429 and payload == {"error": "rate limited"}
    assert headers["Retry-After"] == "1"
    assert headers["X-RateLimit-Remaining"] == "0"
    _status, counters, _ = fixture.counters(generation)
    assert counters["statuses"] == {"200": 1, "429": 1}


def test_high_limit_serves_a_one_rps_step(fixture_factory):
    fixture = fixture_factory("high_limit")
    fixture.reset()
    for _ in range(3):
        assert fixture.get("/canonical")[0] == 200
        time.sleep(0.06)


def test_low_limit_normalizes_the_route_so_a_variant_does_not_bypass(fixture_factory):
    fixture = fixture_factory("low_limit")
    fixture.reset()
    assert fixture.get("/canonical")[0] == 200
    # `/canonical/` is the SAME resource and the SAME bucket: no bypass.
    assert fixture.get("/canonical/")[0] == 429


def test_false_bypass_accepts_a_variant_once_and_never_reproduces_it(fixture_factory):
    fixture = fixture_factory("false_bypass")
    fixture.reset()
    fixture.get("/canonical")  # drain the canonical bucket
    first = fixture.get("/canonical/")[0]
    repeat = fixture.get("/canonical/")[0]
    assert first == 200, "the bypass shape needs a first, unreproduced acceptance"
    assert repeat == 429, "the independent repetition must fail (unconfirmed shape)"


def test_burst_inconclusive_alternates_so_no_transition_can_be_bracketed(fixture_factory):
    fixture = fixture_factory("burst_inconclusive")
    fixture.reset()
    statuses = [fixture.get("/canonical")[0] for _ in range(6)]
    assert statuses == [200, 429, 200, 429, 200, 429]


# --- inspection API ----------------------------------------------------------


def test_events_are_ordered_and_carry_monotonic_timestamps_and_in_flight(fixture_factory):
    fixture = fixture_factory("no_limiter")
    generation = fixture.reset()
    fixture.get("/canonical")
    fixture.get("/other")

    status, payload, _ = fixture.get(f"/events?generation={generation}")
    assert status == 200
    events = payload["events"]
    assert [event["seq"] for event in events] == [1, 2]
    assert [event["route"] for event in events] == ["/canonical", "/other"]
    assert events[0]["monotonic_s"] <= events[1]["monotonic_s"]
    _status, counters, _ = fixture.counters(generation)
    assert counters["max_in_flight"] >= 1
    assert set(counters["events"][0]) == {
        "seq", "monotonic_s", "route", "status", "in_flight", "peak_in_flight",
    }


def test_sensitive_headers_are_redacted_and_secret_values_scrubbed(fixture_factory):
    fixture = fixture_factory("no_limiter", secrets=("s3cr3t-value",))
    generation = fixture.reset()
    fixture.get(
        "/canonical",
        headers={
            "Authorization": "Bearer s3cr3t-value",
            "Cookie": "sid=s3cr3t-value",
            "Proxy-Authorization": "Basic abc",
            "X-Trace": "value-s3cr3t-value",
        },
    )
    _status, payload, _ = fixture.counters(generation)
    assert payload["headers"]["authorization"] == "<redacted>"
    assert payload["headers"]["cookie"] == "<redacted>"
    assert payload["headers"]["proxy-authorization"] == "<redacted>"
    assert payload["headers"]["x-trace"] == "value-<redacted>"
    assert "s3cr3t-value" not in json.dumps(payload)


def test_max_in_flight_is_tracked_under_concurrency(fixture_factory):
    fixture = fixture_factory("no_limiter")
    generation = fixture.reset()

    results: list[int] = []
    guard = threading.Lock()

    def hit() -> None:
        status = fixture.get("/slow")[0]
        with guard:
            results.append(status)

    threads = [threading.Thread(target=hit) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    _status, payload, _ = fixture.counters(generation)
    # The fixture must ACCOUNT for every request and never let the counter go
    # negative; whether the client actually overlaps is not the fixture's promise
    # (the live matrix measures real overlap with delayed routes).
    assert sorted(results) == [200, 200, 200, 200]
    assert payload["requests"] == 4
    assert payload["statuses"] == {"200": 4}
    assert payload["max_in_flight"] >= 1
    assert payload["current_in_flight"] == 0
