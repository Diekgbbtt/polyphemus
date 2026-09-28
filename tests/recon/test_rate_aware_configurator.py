"""Unit tier: the stateful rate-aware recon Configurator."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from polymerhus.app.rate_limit.store import RateLimitPostureStore
from polymerhus.app.llm import session as session_module
from polymerhus.recon.control import configurator as C
from polymerhus.recon.control.jobs import JOBS


def _offers(phase=3):
    return C.offer_phase_inputs(
        phase,
        "t.com",
        {
            "httpx": [
                {
                    "input_asset": {
                        "name": "app.t.com",
                        "url": "https://app.t.com",
                    },
                    "extra": {
                        "auth_context": {
                            "Authorization": "Bearer SECRET-TOKEN",
                            "Cookie": "sid=SECRET-COOKIE",
                        },
                    },
                },
                {"input_asset": {"name": "api.t.com"}},
            ],
            "steel_crawl": [
                {"input_asset": {"url": "https://app.t.com"}},
            ],
        },
        jobs=JOBS,
    )


def test_contracts_are_closed_and_empty_pods_is_valid():
    proposal = C.ReconPodProposal(
        job_name="httpx",
        input_id="httpx:0",
        command="httpx -u https://app.t.com",
        rationale="bounded probe",
    )
    assert proposal.command

    decision = C.ConfiguratorDecision(
        phase=3,
        target_key="t.com",
        posture_status="known_target",
        pods=[],
        rationale="no useful safe work",
    )
    assert decision.pods == []

    with pytest.raises(ValidationError):
        C.ReconPodProposal(
            job_name="httpx",
            input_id="httpx:0",
            command="httpx",
            rationale="x",
            rate_per_s=1.0,
        )
    with pytest.raises(ValidationError):
        C.ConfiguratorDecision(
            phase=3,
            target_key="t.com",
            posture_status="known_target",
            pods=[],
            rationale="x",
            materialized_phases=["httpx"],
        )
    with pytest.raises(ValidationError):
        C.ConfiguratorDecision(
            phase=3,
            target_key="t.com",
            posture_status="probably-safe",
            pods=[],
            rationale="x",
        )


def test_agentic_proposal_may_carry_no_shell_command():
    proposal = C.ReconPodProposal(
        job_name="steel_crawl",
        input_id="steel_crawl:0",
        command=None,
        rationale="the crawl pod owns its tool loop",
    )
    assert proposal.command is None


def test_offer_phase_inputs_is_stable_unique_and_secret_free():
    first = _offers()
    second = _offers()

    assert isinstance(first, C.PhaseOffers)
    assert first.phase == 3
    assert first.target_key == "t.com"
    assert [offer.input_id for offer in first.offers] == [
        "httpx:0",
        "httpx:1",
        "steel_crawl:0",
    ]
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert len({offer.input_id for offer in first.offers}) == len(first.offers)

    httpx = first.offers[0]
    assert httpx.job_name == "httpx"
    assert httpx.tool == "httpx"
    assert httpx.command_template == JOBS["httpx"].command_template
    assert httpx.consumes == JOBS["httpx"].consumes
    assert httpx.produces == JOBS["httpx"].produces
    assert httpx.configurator_mode == "deterministic"
    assert httpx.use_auth is True
    assert "app.t.com" in httpx.input_preview

    steel = first.offers[-1]
    assert steel.configurator_mode == "agent"

    blob = repr(first.model_dump(mode="json"))
    assert "SECRET-TOKEN" not in blob
    assert "SECRET-COOKIE" not in blob
    assert "auth_context" not in blob
    assert "Authorization" not in blob
    assert "Cookie" not in blob


def test_configure_phase_binds_the_exact_tools_schema_and_session(
    monkeypatch, tmp_path
):
    seen: list[tuple] = []
    checkpointer = object()
    posture_store = RateLimitPostureStore(root=tmp_path)

    def fake_stateful_turn(role_id, thread, messages, **kwargs):
        seen.append((role_id, thread, messages, kwargs))
        return C.ConfiguratorDecision(
            phase=3,
            target_key="t.com",
            posture_status="known_target",
            pods=[],
            rationale="test",
        )

    monkeypatch.setattr(session_module, "stateful_turn", fake_stateful_turn)
    decision = C.configure_phase(
        "p1",
        "run1",
        3,
        "t.com",
        _offers(),
        checkpointer=checkpointer,
        model_factory=lambda role_id: object(),
        posture_store=posture_store,
    )

    assert isinstance(decision, C.ConfiguratorDecision)
    role_id, thread, messages, kwargs = seen[0]
    assert role_id == "configurator"
    assert thread.thread_id == "run:run1:configurator"
    assert messages
    assert kwargs["checkpointer"] is checkpointer
    assert kwargs["schema"] is C.ConfiguratorDecision
    assert [tool.name for tool in kwargs["tools"]] == [
        "load_skill",
        "rate_limit_posture",
    ]
    posture_tool = kwargs["tools"][1]
    assert posture_tool.project_id == "p1"
    assert posture_tool.store is posture_store
    assert kwargs["context"]["skills"] == ["rate-aware-recon-configuration"]
    assert len(kwargs["middleware"]) >= 2
    prompt = kwargs["system_prompt"].lower()
    assert "rate_limit_posture" in prompt
    assert "pods=[]" in prompt
    assert "unreadable" in prompt
    assert "aggregate" in prompt
    assert "rationale" in prompt
    assert "1 request per second" not in prompt
    assert "2.0" not in prompt


def test_two_phases_share_the_run_session_and_other_runs_are_isolated(monkeypatch):
    threads: list[str] = []
    roles: list[str] = []
    expected_phases = [2, 5, 2]

    def fake_stateful_turn(role_id, thread, messages, **kwargs):
        roles.append(role_id)
        threads.append(thread.thread_id)
        return C.ConfiguratorDecision(
            phase=expected_phases.pop(0),
            target_key="t.com",
            posture_status="known_target",
            pods=[],
            rationale="test",
        )

    monkeypatch.setattr(session_module, "stateful_turn", fake_stateful_turn)
    C.configure_phase(
        "p1", "run1", 2, "t.com", _offers(2), checkpointer=object()
    )
    C.configure_phase(
        "p1", "run1", 5, "t.com", _offers(5), checkpointer=object()
    )
    C.configure_phase(
        "p1", "run2", 2, "t.com", _offers(2), checkpointer=object()
    )

    assert roles == ["configurator", "configurator", "configurator"]
    assert threads[0] == threads[1] == "run:run1:configurator"
    assert threads[2] == "run:run2:configurator"
    assert threads[0] != threads[2]
