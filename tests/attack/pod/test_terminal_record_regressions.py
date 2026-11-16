"""Regression tests for the pod terminal-record failure modes.

The terminal record has one deterministic owner per fact:

1. the Runner's `experiment_summary` is bound to the current variant from the
   harness log; the model cannot supply an order;
2. a domain terminal without a summary gets one focused Runner recovery turn;
   a hard teardown never fabricates one;
3. the pod-owned `<spec_id>/<run_id>.yaml` is the only terminal export record;
   the retired durable pod-export note is not written.
"""
from __future__ import annotations

import asyncio

from polymerhus.attack.hunting.pod import arun_pod
from polymerhus.attack.hunting.pod.agents import (
    runner_react_tools,
    symbolic_runner_step_fn,
)
from polymerhus.attack.hunting.pod.pod_memory import (
    PodMemoryStore,
    read_variant_summary,
)
from polymerhus.attack.hunting.surfer import run_pod_session
from polymerhus.recon.domain.types import ExecResult

SPEC_ID = "idor__status-unpublished__query-param-detail__article"
RUN_ID = "run-1"
PROJECT = "proj-1"
HUNT_KEY = "Unit__threat-1"

SPEC = {
    "target_identity": {"url": "http://target/", "unit_id": "unit-1"},
    "verification_symptoms": ["HTTP 200 with a marker"],
    "assumptions": ["network egress allowed"],
    "rationale": "the probe reaches the target",
}

_ABSENT = "not found\n__POD_HTTP_STATUS__:404\n__POD_HTTP_TIME__:0.02"


def _notes_tool(tools):
    return next(tool for tool in tools if tool.name == "notes")


def _exec(stdout: str = _ABSENT):
    def fake(command, timeout_s):
        return ExecResult(stdout=stdout, stderr="", returncode=0, duration_ms=1)
    return fake


def _terminal_triager(spec, observation, log, facts):
    return {
        "classification": "noise",
        "action": "terminate",
        "verdict": "unsuccessful",
        "terminal_reason": "space-exhausted",
        "clean": True,
        "note": "the stretch is exhausted",
    }


def test_summary_write_rejects_a_model_supplied_order_and_uses_the_bound_order(
    tmp_path,
):
    """The harness owns the order. A stale/one-based model argument is a coded
    rejection, and the valid write lands on the bound current variant."""
    store = PodMemoryStore(tmp_path)
    tools = runner_react_tools(
        exec_fn=lambda *args, **kwargs: None,
        memory_store=store,
        spec_id=SPEC_ID,
        log=None,
        variant_ref="v0",
    )
    note = _notes_tool(tools)

    rejected = note.invoke({
        "command": "write",
        "order": 1,
        "note_name": "experiment",
        "kind": "experiment_summary",
        "body": "the v0 consolidation",
    })
    assert "notes_args_rejected" in rejected
    assert read_variant_summary(store, SPEC_ID, 0) == ""
    assert store.read_experiment_log(SPEC_ID, 1) == {}

    accepted = note.invoke({
        "command": "write",
        "note_name": "experiment",
        "kind": "experiment_summary",
        "body": "the v0 consolidation",
    })
    assert f"{SPEC_ID}:0:experiment_summary" in accepted
    assert read_variant_summary(store, SPEC_ID, 0) == "the v0 consolidation"
    assert store.read_experiment_log(SPEC_ID, 1) == {}


def test_domain_terminal_repairs_a_missing_summary_on_the_bound_order(tmp_path):
    """A domain terminal without a P3 summary gets one recovery turn. The turn
    writes through the harness-bound order, so the terminal slice is complete."""
    store = PodMemoryStore(tmp_path)
    repairs: list[int] = []

    def repair(spec, messages, tool_calls):
        repairs.append(tool_calls)
        store.write_variant_summary(
            SPEC_ID, 0, "recovered consolidation from the current trail")

    envelope = asyncio.run(arun_pod(
        SPEC,
        exec_fn=_exec(),
        runner_step_fn=symbolic_runner_step_fn,
        triager_fn=_terminal_triager,
        trace_fn=lambda _run_id: [],
        memory_store=store,
        spec_id=SPEC_ID,
        summary_repair_fn=repair,
    ))

    assert envelope["verdict"] == "unsuccessful"
    assert repairs == [1]
    assert read_variant_summary(store, SPEC_ID, 0) == (
        "recovered consolidation from the current trail")
    assert store.read_experiment_log(SPEC_ID, 1) == {}


def test_production_runner_repair_turn_writes_the_missing_summary(tmp_path):
    """The default production repair seam re-enters the SAME `pod_runner`
    session with only the notes tool bound; the summary lands on the bound
    order. This is the structural guarantee for a domain terminal that skipped
    P3."""
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, ChatResult

    class Fake(BaseChatModel):
        replies: list = []
        idx: dict = {}

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            i = self.idx.get("i", 0)
            self.idx["i"] = i + 1
            return ChatResult(generations=[ChatGeneration(
                message=self.replies[min(i, len(self.replies) - 1)])])

        @property
        def _llm_type(self):
            return "fake"

        def bind_tools(self, tools, **kwargs):
            return self

    replies = [
        AIMessage(content="", tool_calls=[{
            "name": "exec", "args": {"command": "curl -k -sS https://target/"},
            "id": "c1"}]),
        AIMessage(content="stretch concluded without the P3 note"),
        AIMessage(content="", tool_calls=[{
            "name": "notes", "args": {
                "command": "write", "note_name": "experiment",
                "kind": "experiment_summary",
                "body": "recovered from the current trail"},
            "id": "c2"}]),
        AIMessage(content="summary written"),
    ]
    store = PodMemoryStore(tmp_path)
    fake = Fake(replies=list(replies), idx={})

    envelope = asyncio.run(arun_pod(
        SPEC,
        exec_fn=_exec(),
        triager_fn=_terminal_triager,
        trace_fn=lambda _run_id: [],
        memory_store=store,
        spec_id=SPEC_ID,
        model_factory=lambda _role: fake,
    ))

    assert envelope["verdict"] == "unsuccessful"
    assert read_variant_summary(store, SPEC_ID, 0) == (
        "recovered from the current trail")
    assert store.read_experiment_log(SPEC_ID, 1) == {}


def test_hard_teardown_does_not_fabricate_a_summary(tmp_path):
    """A hard teardown may destroy the live Runner context. The finalizer keeps
    the honest absence instead of inventing a consolidation."""
    store = PodMemoryStore(tmp_path)
    store.write_experiment_log(SPEC_ID, 0, {
        "order": 0,
        "variant_ref": "v0",
        "raw_observations": [{"probe_ref": "sig-0", "variant_ref": "v0",
                              "status": 404, "body": "not found"}],
        "kb_observations": [],
        "interpretations": [],
        "executed": ["sig-0"],
    })
    async def _pod_builder(*args, **kwargs):
        # Simulate a graph that was cancelled by the session watchdog.
        await asyncio.sleep(30)

    async def _run():
        return await run_pod_session(
            spec=SPEC,
            project_id=PROJECT,
            run_id=RUN_ID,
            hunt_key=HUNT_KEY,
            spec_id=SPEC_ID,
            inbox=None,
            gate=None,
            pod_builder=_pod_builder,
            pod_store=store,
            session_timeout_s=0.01,
        )

    # The timeout path finalizes from the durable trail; the repair seam is not
    # reachable because the graph task is gone.
    envelope = asyncio.run(_run())
    assert envelope["evidence"]["terminal_reason"] == "pod-watchdog-timeout"
    assert read_variant_summary(store, SPEC_ID, 0) == ""
    assert store.read_experiment_log(SPEC_ID, 0)["raw_observations"][0][
        "probe_ref"] == "sig-0"


def test_experiment_log_updates_cannot_lose_each_others_fields(tmp_path):
    """The capture middleware and the summary write both read-modify-write the
    same slice. The store lock makes the two updates one critical section, so a
    slow writer cannot restore a stale copy over a newer field."""
    import threading
    import time

    store = PodMemoryStore(tmp_path)
    entered = threading.Event()
    release = threading.Event()

    def _summary(current):
        entered.set()
        release.wait(timeout=5)
        current["experiment_summary"] = "the summary"
        return current

    def _observation(current):
        current["raw_observations"] = [{"probe_ref": "sig-1"}]
        return current

    first = threading.Thread(
        target=store.update_experiment_log, args=(SPEC_ID, 0, _summary))
    first.start()
    assert entered.wait(timeout=5)
    second = threading.Thread(
        target=store.update_experiment_log, args=(SPEC_ID, 0, _observation))
    second.start()
    time.sleep(0.05)
    release.set()
    first.join(timeout=5)
    second.join(timeout=5)

    slice = store.read_experiment_log(SPEC_ID, 0)
    assert slice["experiment_summary"] == "the summary"
    assert slice["raw_observations"] == [{"probe_ref": "sig-1"}]


def test_run_pod_session_writes_no_durable_pod_export_note(tmp_path):
    """The canonical export is the pod's own file; the retired durable note is
    not written even when a live parent inbox exists."""
    store = PodMemoryStore(tmp_path / "pod")
    calls: list[str] = []

    async def _pod_builder(spec, **kwargs):
        calls.append(kwargs["spec_id"])
        return {"verdict": "successful",
                "evidence": {"terminal_reason": "symptom-confirmed",
                             "iterations": 1, "clean": True,
                             "variant_specs": [], "raw_observations": [],
                             "interpretations": [], "init_validation": []}}

    async def _run():
        return await run_pod_session(
            spec=SPEC,
            project_id=PROJECT,
            run_id=RUN_ID,
            hunt_key=HUNT_KEY,
            spec_id=SPEC_ID,
            inbox=None,
            gate=None,
            pod_builder=_pod_builder,
            pod_store=store,
        )

    envelope = asyncio.run(_run())
    assert calls == [SPEC_ID]
    assert envelope["verdict"] == "successful"
    assert store.read_pod_export(SPEC_ID, RUN_ID)["verdict"] == "successful"
    assert list(tmp_path.rglob("pod-export")) == []
