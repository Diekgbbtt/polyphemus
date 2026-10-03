"""E2E: token tracking from the ephemeral stateful agent to the eval budget probe.

Two halves, one process:

1. The LLM-client half: an ephemeral agent is instantiated through the SAME
   ubiquitous stateful-agent pattern the canonical agents use (`stateful_turn`
   and `run_session_agent`), with a deterministic fake model that reports a
   fixed `usage_metadata`. The per-agent token aggregation is then read over
   real HTTP from the app usage endpoint (`GET /projects/{id}/usage`).
2. The eval half: while an ephemeral agent consumes tokens, the eval harness's
   own probing mechanics (`Trial._check_spend`) poll the same usage endpoint
   through the real `HttpApiRunner` seam and stop the run on overflow.

Both share one process, so the process-wide usage ledger the agent writes is
the one the HTTP server reads.
"""
from __future__ import annotations

import asyncio
import socket
import sys
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from fastapi import FastAPI
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

from eval.orchestrator.api import HttpApiRunner, usage  # noqa: E402
from eval.orchestrator.trial import Trial, TrialConfig  # noqa: E402
from polymerhus.app.llm.usage import usage_ledger  # noqa: E402
from polymerhus.project_management.api import router as app_router  # noqa: E402
from tests.test_llm_usage import _UsageFakeChatModel  # noqa: E402

PROJECT = "e2e-project"
_PER_CALL = 18


class _FakeRuntime:
    """The stop verb's runtime stub: records the run it was asked to cancel."""

    def __init__(self) -> None:
        self.cancelled: list[tuple[str, str]] = []

    def cancel_run(self, module: str, run_id: str) -> None:
        self.cancelled.append((module, run_id))


@pytest.fixture(autouse=True)
def _clean_ledger():
    usage_ledger().reset()
    yield
    usage_ledger().reset()


@pytest.fixture
def server(monkeypatch):
    import polymerhus.app.runtime as runtime_mod

    fake = _FakeRuntime()
    monkeypatch.setattr(runtime_mod, "get_active_runtime", lambda: fake)

    app = FastAPI()
    app.include_router(app_router)

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    uvicorn_server = uvicorn.Server(config)
    thread = threading.Thread(target=uvicorn_server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if uvicorn_server.started:
            break
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}", fake
    finally:
        uvicorn_server.should_exit = True
        thread.join(timeout=5)


def _ephemeral_turn(role_id: str, thread_id: str, project_id: str) -> None:
    """One turn of an ephemeral stateful agent, exactly as a canonical agent runs."""
    from polymerhus.app.llm.session import stateful_turn

    stateful_turn(
        role_id,
        thread_id,
        [HumanMessage(content="go")],
        checkpointer=InMemorySaver(),
        model_factory=lambda _role: _UsageFakeChatModel(),
        observe=False,
        usage_scope=project_id,
    )


def _run_ephemeral_actor(role_id: str, thread_id: str, project_id: str, turns: int) -> None:
    """An ephemeral async actor, the `run_session_agent` pattern canonical actors use."""
    from polymerhus.app.llm.actor import run_session_agent

    async def _go() -> None:
        await run_session_agent(
            role_id,
            thread_id,
            [HumanMessage(content="go")],
            checkpointer=InMemorySaver(),
            model_factory=lambda _role: _UsageFakeChatModel(),
            observe=False,
            usage_scope=project_id,
            max_turns=turns,
        )

    asyncio.run(_go())


def test_client_tracking_aggregates_per_agent_over_real_http(server):
    base_url, _ = server
    for _ in range(2):
        _ephemeral_turn("assigner", "t-assigner", PROJECT)
        _ephemeral_turn("triager", "t-triager", PROJECT)

    snapshot = HttpApiRunner(base_url)(usage(PROJECT))

    assert snapshot["total_tokens"] == 4 * _PER_CALL
    assert snapshot["calls"] == 4
    assert snapshot["by_agent"]["assigner"]["total_tokens"] == 2 * _PER_CALL
    assert snapshot["by_agent"]["triager"]["total_tokens"] == 2 * _PER_CALL


def test_client_tracking_counts_the_actor_path(server):
    base_url, _ = server
    _run_ephemeral_actor("orchestrator", "t-actor", PROJECT, turns=1)

    snapshot = HttpApiRunner(base_url)(usage(PROJECT))
    assert snapshot["calls"] == 1
    assert snapshot["by_agent"]["orchestrator"]["total_tokens"] == _PER_CALL


def test_unscoped_agent_tokens_never_leak_into_the_project(server):
    base_url, _ = server
    _ephemeral_turn("assigner", "t-scoped", PROJECT)
    _ephemeral_turn("assigner", "t-unscoped", None)

    snapshot = HttpApiRunner(base_url)(usage(PROJECT))
    assert snapshot["total_tokens"] == _PER_CALL
    assert snapshot["calls"] == 1


def test_eval_probe_stops_the_run_on_token_overflow_concurrently(server):
    base_url, fake = server
    budget = 5 * _PER_CALL
    stop = threading.Event()

    def consume() -> None:
        turn = 0
        while not stop.is_set() and turn < 40:
            _ephemeral_turn("hunter", f"t-hunter-{turn}", PROJECT)
            turn += 1

    consumer = threading.Thread(target=consume, daemon=True)
    consumer.start()

    trial = Trial(
        TrialConfig(instance_id="i", target_id="t", token_budget=budget),
        api_runner=HttpApiRunner(base_url),
        clock=time.monotonic,
        sleep=lambda _s: None,
    )

    spend = None
    deadline = time.monotonic() + 30
    while spend is None and time.monotonic() < deadline:
        spend = trial._check_spend(PROJECT, "recon", "r0")
        if spend is None:
            time.sleep(0.05)

    stop.set()
    consumer.join(timeout=5)

    assert spend is not None, "the token budget never tripped"
    assert spend.spent >= budget
    assert spend.spent == trial._spend.spent
    assert spend.by_agent and "hunter" in spend.by_agent
    assert fake.cancelled == [("recon", "r0")]


def test_eval_probe_does_not_stop_below_budget(server):
    base_url, fake = server
    _ephemeral_turn("hunter", "t-hunter", PROJECT)

    trial = Trial(
        TrialConfig(instance_id="i", target_id="t", token_budget=100 * _PER_CALL),
        api_runner=HttpApiRunner(base_url),
        clock=time.monotonic,
        sleep=lambda _s: None,
    )
    assert trial._check_spend(PROJECT, "recon", "r0") is None
    assert fake.cancelled == []
