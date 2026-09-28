"""Pure validation/materialization at the Configurator phase boundary."""
from __future__ import annotations

import pytest

from polymerhus.recon.control import configurator as C
from polymerhus.recon.control.jobs import JOBS


def _prepared():
    return {
        "httpx": [
            {
                "input_asset": {"name": "a.t.com"},
                "asset_context": "",
                "extra": {"project_id": "p1", "auth_account": "alice"},
            },
            {
                "input_asset": {"name": "b.t.com"},
                "asset_context": "",
                "extra": {"project_id": "p1", "auth_account": "alice"},
            },
        ],
        "steel_crawl": [
            {
                "input_asset": {"url": "https://a.t.com"},
                "asset_context": "",
                "extra": {"project_id": "p1"},
            },
        ],
    }


def _offers():
    return C.offer_phase_inputs(3, "t.com", _prepared(), jobs=JOBS)


def _decision(*pods):
    return C.ConfiguratorDecision(
        phase=3,
        target_key="t.com",
        posture_status="known_target",
        pods=list(pods),
        rationale="test",
    )


def _proposal(job_name, input_id, command):
    return C.ReconPodProposal(
        job_name=job_name,
        input_id=input_id,
        command=command,
        rationale="test",
    )


def test_materializes_only_the_selected_subset_and_attaches_command():
    offers = _offers()
    decision = _decision(
        _proposal("httpx", "httpx:1", "httpx -u {target} -rate-limit 2"),
        _proposal("steel_crawl", "steel_crawl:0", None),
    )

    materialized = C.materialize_configurator_decision(decision, offers)

    assert list(materialized) == ["httpx", "steel_crawl"]
    assert materialized["httpx"] == [
        {
            "input_asset": {"name": "b.t.com"},
            "asset_context": "",
            "extra": {"project_id": "p1", "auth_account": "alice"},
            "configured_command": "httpx -u {target} -rate-limit 2",
        }
    ]
    assert materialized["steel_crawl"] == [
        {
            "input_asset": {"url": "https://a.t.com"},
            "asset_context": "",
            "extra": {"project_id": "p1"},
            "configured_command": None,
        }
    ]

    # Materialization copies: the source prepared input is never mutated.
    assert "configured_command" not in offers.source_inputs["httpx:1"]


def test_empty_pods_is_a_valid_empty_phase_plan():
    assert C.materialize_configurator_decision(_decision(), _offers()) == {}


@pytest.mark.parametrize(
    "decision",
    [
        None,
        _decision(
            _proposal("httpx", "httpx:0", "httpx -u {target}"),
            _proposal("httpx", "httpx:0", "httpx -u {target}"),
        ),
        _decision(_proposal("katana", "httpx:0", "katana -u {target}")),
        _decision(_proposal("httpx", "missing:0", "httpx -u {target}")),
        _decision(_proposal("httpx", "httpx:0", "")),
        _decision(_proposal("httpx", "httpx:0", "   ")),
        _decision(_proposal("steel_crawl", "steel_crawl:0", "steel run")),
    ],
)
def test_any_invalid_decision_is_rejected_atomically(decision):
    with pytest.raises(ValueError):
        C.materialize_configurator_decision(decision, _offers())


@pytest.mark.parametrize(
    "phase,target",
    [(2, "t.com"), (3, "other.t.com")],
)
def test_phase_target_mismatch_rejects_the_whole_decision(phase, target):
    decision = _decision(_proposal("httpx", "httpx:0", "httpx -u {target}"))
    decision = decision.model_copy(update={"phase": phase, "target_key": target})

    with pytest.raises(ValueError):
        C.materialize_configurator_decision(decision, _offers())
