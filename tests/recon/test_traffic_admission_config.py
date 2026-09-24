"""Task 1 (#238 follow-up): the typed job traffic-cost catalogue and the
startup-validated admission configuration.

The admission controller (Tasks 2-4) reads exactly two things from here:
each canonical `JobSpec`'s mandatory `traffic_cost`, and the single typed
`TrafficAdmissionSettings` parsed once at the configuration boundary. This
suite pins the closed vocabulary, the approved classification of every
current job, and the loud rejection of any invalid threshold value.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from polymerhus.recon.control.jobs import JOBS
from polymerhus.recon.domain.traffic_admission import (
    JobTrafficCost,
    TrafficAdmissionSettings,
    TrafficCostClass,
)

# The approved classification of every canonical job (Task 1 Step 4).
EXPECTED_COST_CLASS: dict[str, str] = {
    # request_intensive: pass posture + rate + projected-duration gates.
    "arjun": "request_intensive",
    "ffuf": "request_intensive",
    # bounded_http: target HTTP, tightly bounded, allowed under a conservative
    # policy.
    "httpx": "bounded_http",
    "httpx_services": "bounded_http",
    "httpx_reprofile": "bounded_http",
    "katana": "bounded_http",
    "kiterunner": "bounded_http",
    "jsluice": "bounded_http",
    "graphql-cop": "bounded_http",
    "steel_crawl": "bounded_http",
    # non_target: no HTTP requests to the measured target.
    "subfinder": "non_target",
    "amass": "non_target",
    "whois": "non_target",
    "dnsx": "non_target",
    "puredns": "non_target",
    "subdomain_takeover": "non_target",
    "naabu": "non_target",
    "paramspider": "non_target",
}


def test_every_job_declares_a_typed_cost_class():
    assert set(JOBS) == set(EXPECTED_COST_CLASS)
    assert {
        name: spec.traffic_cost.cost_class for name, spec in JOBS.items()
    } == EXPECTED_COST_CLASS


def test_request_intensive_jobs_are_arjun_and_ffuf():
    intensive = {
        name
        for name, spec in JOBS.items()
        if spec.traffic_cost.cost_class is TrafficCostClass.REQUEST_INTENSIVE
    }
    assert intensive == {"arjun", "ffuf"}


def test_arjun_declares_a_fixed_conservative_estimate():
    cost = JOBS["arjun"].traffic_cost
    assert cost.cost_class is TrafficCostClass.REQUEST_INTENSIVE
    assert cost.estimated_requests_per_input == 260
    assert cost.estimation_basis == "fixed"
    assert cost.cardinality_source is None


def test_ffuf_binds_its_estimate_to_the_pinned_wordlist():
    cost = JOBS["ffuf"].traffic_cost
    assert cost.cost_class is TrafficCostClass.REQUEST_INTENSIVE
    assert cost.estimation_basis == "wordlist_cardinality"
    assert (
        cost.cardinality_source
        == "/usr/share/seclists/Discovery/Web-Content/common.txt"
    )


def test_job_traffic_cost_is_closed_and_frozen():
    cost = JobTrafficCost(
        cost_class=TrafficCostClass.BOUNDED_HTTP,
        estimated_requests_per_input=1,
        estimation_basis="fixed",
    )
    with pytest.raises(ValidationError):
        JobTrafficCost(
            cost_class=TrafficCostClass.BOUNDED_HTTP,
            estimated_requests_per_input=1,
            estimation_basis="fixed",
            surprise=1,  # extra="forbid"
        )
    with pytest.raises(ValidationError):
        cost.cost_class = TrafficCostClass.NON_TARGET  # frozen


def test_traffic_admission_settings_defaults():
    settings = TrafficAdmissionSettings.from_env({})
    assert settings.min_safe_rate_per_s == 2.0
    assert settings.max_projected_duration_s == 300.0


def test_traffic_admission_settings_env_override():
    settings = TrafficAdmissionSettings.from_env(
        {
            "RATE_LIMIT_INTENSIVE_MIN_SAFE_RATE_PER_S": "3.5",
            "RATE_LIMIT_INTENSIVE_MAX_PROJECTED_DURATION_S": "120",
        }
    )
    assert settings.min_safe_rate_per_s == 3.5
    assert settings.max_projected_duration_s == 120.0


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "-inf", "not-a-number"])
def test_invalid_min_rate_fails_startup(value):
    with pytest.raises(ValueError, match="RATE_LIMIT_INTENSIVE_MIN_SAFE_RATE_PER_S"):
        TrafficAdmissionSettings.from_env(
            {"RATE_LIMIT_INTENSIVE_MIN_SAFE_RATE_PER_S": value}
        )


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "-inf", "not-a-number"])
def test_invalid_max_duration_fails_startup(value):
    with pytest.raises(
        ValueError, match="RATE_LIMIT_INTENSIVE_MAX_PROJECTED_DURATION_S"
    ):
        TrafficAdmissionSettings.from_env(
            {"RATE_LIMIT_INTENSIVE_MAX_PROJECTED_DURATION_S": value}
        )
