"""Unit tier: T1 (#177) - the pod `note` tool (D84-20/27/32/36).

`PodNoteTool(BaseTool)` with `args_schema=NoteToolSpec` (`extra="forbid"` -
D84-22: a wrong parameter FAILS as a rejected tool call before `_run`), a
write/read operation discriminator, coded contract rejections
(`NOTES_ARGS_REJECTED` / `NOTES_EMPTY_BODY` / `NOTES_BAD_KIND` /
`NOTES_NO_STORE`), and fail-open on a None store (O10). Reads return the note
body prompt-verbatim and un-truncated (D84-19.2). T1: the tool rides the
per-project deterministic-key store - the write's `variant_ref` is the integer
`order` (D84-36), notes keyed `<spec_id>:<order>:<note_name>`, and the read
surface gains the typed attribute filters (`order`, `kind`, `classification`,
`symptom_status`). The wiring proof binds the tool into a real `create_agent`
ReAct loop on a FAKE chat model - no live LLM.
"""
from __future__ import annotations

import asyncio

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from polymerhus.app.llm.session import arun_session_turn
from polymerhus.attack.hunting.pod.note_tool import (
    NOTES_ARGS_REJECTED,
    NOTES_BAD_KIND,
    NOTES_EMPTY_BODY,
    NOTES_NO_STORE,
    NOTE_KINDS_DECLARED,
    PodNoteTool,
)
from polymerhus.attack.hunting.pod.pod_memory import PodMemoryStore, note_key

SPEC = {
    "target_identity": "service:web:soupmarket",
    "verification_symptoms": ["HTTP 200 with a non-empty body on GET /"],
    "payload_vector_space": {"method": "GET", "path": "/"},
}

SPEC_ID = "sqli_blind"  # the #164 `<fault>_<strategy>` memory key


@pytest.fixture
def store(tmp_path):
    return PodMemoryStore(tmp_path)


@pytest.fixture
def spec_id():
    return SPEC_ID


def _tool(*, store, spec_id):
    return PodNoteTool(store=store, spec_id=spec_id)


# --- direct invocation: write / read round-trip -------------------------------

def test_tool_write_persists_a_note_and_reads_it_back_verbatim(store, spec_id):
    tool = _tool(store=store, spec_id=spec_id)
    out = tool.invoke({"operation": "write", "order": 0, "note_name": "experiment",
                       "kind": "experiment_summary",
                       "body": "space exhausted; no new primitive",
                       "classification": "symptom-absent", "symptom_status": "clean",
                       "kb_primitives_used": ["status-diff"],
                       "exhaustion_evidence": "terminal KB query returned the same set"})
    assert note_key(spec_id, 0, "experiment") in out
    # D84-35: the experiment_summary sinks into the variant's log slice as its
    # terminal record - NOT into notes.yaml (kb_insight/freeform only). The
    # summary's value IS the note body string (operator, 2026-08-24).
    from polymerhus.attack.hunting.pod.pod_memory import read_variant_summary
    assert read_variant_summary(store, spec_id, 0) == "space exhausted; no new primitive"
    assert store.read_notes(spec_id) == []

    read = tool.invoke({"operation": "read", "kind": "experiment_summary", "order": 0})
    assert "space exhausted; no new primitive" in read


def test_tool_read_returns_the_body_prompt_verbatim_and_untruncated(store, spec_id):
    # D84-19.2: a consolidation note must return full-body, never body-sliced.
    long_body = "symptom absent on " + "; ".join(f"probe-{i:03d}" for i in range(450))
    assert len(long_body) > 1200
    tool = _tool(store=store, spec_id=spec_id)
    tool.invoke({"operation": "write", "order": 0, "note_name": "experiment",
                 "kind": "experiment_summary", "body": long_body})
    read = tool.invoke({"operation": "read", "kind": "experiment_summary", "order": 0})
    assert "symptom absent on " in read
    assert "probe-449" in read
    assert read.count("probe-") == 450


def test_tool_read_zero_matches_is_a_graceful_empty_result(store, spec_id):
    out = _tool(store=store, spec_id=spec_id).invoke(
        {"operation": "read", "order": 9})
    assert "no notes matched" in out.lower()


# --- the typed attribute read filters (D84-36) --------------------------------

def test_tool_read_kind_and_classification_filters(store, spec_id):
    tool = _tool(store=store, spec_id=spec_id)
    tool.invoke({"operation": "write", "order": 0, "note_name": "a",
                 "kind": "kb_insight", "body": "payload family X"})
    tool.invoke({"operation": "write", "order": 1, "note_name": "b",
                 "kind": "freeform", "body": "consolidation",
                 "classification": "symptom-absent"})
    # The kb_insight/freeform notes accumulate in notes.yaml (D84-35); the kind
    # filter ranges them. An experiment_summary read ranges the log slice.
    kind_hits = tool.invoke({"operation": "read", "kind": "kb_insight"})
    assert "payload family X" in kind_hits
    assert "consolidation" not in kind_hits
    class_hits = tool.invoke({"operation": "read", "classification": "symptom-absent"})
    assert "consolidation" in class_hits


def test_tool_read_order_filter_returns_only_that_variant(store, spec_id):
    tool = _tool(store=store, spec_id=spec_id)
    tool.invoke({"operation": "write", "order": 0, "note_name": "n",
                 "kind": "freeform", "body": "first variant"})
    tool.invoke({"operation": "write", "order": 1, "note_name": "n",
                 "kind": "freeform", "body": "second variant"})
    hit = tool.invoke({"operation": "read", "order": 1})
    assert "second variant" in hit
    assert "first variant" not in hit


def test_tool_read_symptom_status_filter(store, spec_id):
    """D84-36: `symptom_status` is a first-class typed attribute read filter on
    the `note` tool, passed through to `read_notes` (the store owns the match).
    Notes accumulate in notes.yaml (D84-35); the filter ranges them."""
    tool = _tool(store=store, spec_id=spec_id)
    tool.invoke({"operation": "write", "order": 0, "note_name": "a",
                 "kind": "kb_insight", "body": "payload family X",
                 "symptom_status": "clean"})
    tool.invoke({"operation": "write", "order": 1, "note_name": "b",
                 "kind": "freeform", "body": "partial",
                 "symptom_status": "blocked"})
    clean_hits = tool.invoke({"operation": "read", "symptom_status": "clean"})
    assert "payload family X" in clean_hits
    assert "partial" not in clean_hits
    blocked_hits = tool.invoke({"operation": "read", "symptom_status": "blocked"})
    assert "partial" in blocked_hits
    assert "payload family X" not in blocked_hits
    # Combines with the order filter.
    both = tool.invoke({"operation": "read", "symptom_status": "clean", "order": 0})
    assert "payload family X" in both
    assert "partial" not in both


# --- T4: the raw experiment-log slice read by order (D84-27) ------------------
# The key-list renders the experiment-log identifier <spec_id>/<order>; the note
# tool's read must let the agent address that raw D6 slice body by order - not
# only the consolidated experiment_summary.

def test_tool_read_returns_the_raw_experiment_log_slice_by_order(store, spec_id):
    store.write_experiment_log(spec_id, 0, {
        "order": 0, "variant_ref": "v0",
        "raw_observations": [{"status": 404, "body": "not found"}],
        "kb_observations": [{"query": "sqli", "response": "primitive-set"}],
        "interpretations": [{"classification": "symptom-absent", "note": "absent"}],
        "executed": ["sig-1"],
    })
    out = _tool(store=store, spec_id=spec_id).invoke(
        {"operation": "read", "kind": "experiment_log", "order": 0})
    assert f"{spec_id}/0" in out            # the deterministic identifier
    assert "sig-1" in out                   # the full D6 slice body
    assert "not found" in out
    assert "primitive-set" in out
    assert "symptom-absent" in out


def test_tool_read_experiment_log_zero_matches_is_graceful(store, spec_id):
    out = _tool(store=store, spec_id=spec_id).invoke(
        {"operation": "read", "kind": "experiment_log", "order": 9})
    assert "no experiment log" in out.lower()


def test_tool_read_experiment_log_needs_the_order(store, spec_id):
    out = _tool(store=store, spec_id=spec_id).invoke(
        {"operation": "read", "kind": "experiment_log"})
    assert out.startswith(NOTES_ARGS_REJECTED)


# --- extra="forbid": a wrong parameter is rejected before _run -----------------

def test_unknown_parameter_is_rejected_by_the_args_schema(store, spec_id):
    tool = _tool(store=store, spec_id=spec_id)
    with pytest.raises(ValueError):
        tool.invoke({"operation": "write", "order": 0, "note_name": "n",
                     "kind": "freeform", "body": "x", "bogus_param": 1})


def test_unknown_parameter_never_reaches_run(store, spec_id):
    """D84-22: the tool's own contract is the validator - an extra parameter is
    REJECTED as a tool-call request, and `_run` provably never executes."""
    calls = []

    class SpyTool(PodNoteTool):
        def _run(self, **kwargs):
            calls.append(kwargs)
            return super()._run(**kwargs)

    tool = SpyTool(store=store, spec_id=spec_id)
    with pytest.raises(ValueError):
        tool.invoke({"operation": "read", "order": 0, "nonsense": 2})
    assert calls == []


# --- the coded contract rejections --------------------------------------------

def test_empty_body_is_a_coded_rejection(store, spec_id):
    out = _tool(store=store, spec_id=spec_id).invoke(
        {"operation": "write", "order": 0, "note_name": "n",
         "kind": "freeform", "body": "   "})
    assert out.startswith(NOTES_EMPTY_BODY)


def test_bad_kind_is_a_coded_rejection(store, spec_id):
    out = _tool(store=store, spec_id=spec_id).invoke(
        {"operation": "write", "order": 0, "note_name": "n",
         "kind": "hypothesis_refusal", "body": "x"})
    assert out.startswith(NOTES_BAD_KIND)
    assert store.read_notes(spec_id) == []          # nothing persisted
    assert NOTE_KINDS_DECLARED == ["experiment_summary", "kb_insight", "freeform"]


def test_no_store_is_a_coded_rejection_for_writes(spec_id):
    out = PodNoteTool(store=None, spec_id=spec_id).invoke(
        {"operation": "write", "order": 0, "note_name": "n",
         "kind": "freeform", "body": "x"})
    assert out.startswith(NOTES_NO_STORE)


# --- fail-open on a None store (O10) ------------------------------------------

def test_no_store_reads_fail_open_never_raise(spec_id):
    out = PodNoteTool(store=None, spec_id=spec_id).invoke(
        {"operation": "read", "order": 0})
    assert "no pod memory" in out.lower()


def test_no_store_create_agent_loop_still_concludes(spec_id):
    """A note tool bound with a None store inside a real create_agent loop does
    not break the lane - the write is a coded rejection the loop's model sees."""
    from langchain_core.language_models import BaseChatModel
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langchain_core.messages import HumanMessage

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

    factory = lambda role: Fake(replies=[  # noqa: E731
        AIMessage(content="", tool_calls=[{"name": "note", "id": "c1", "args": {
            "operation": "write", "order": 0, "note_name": "n",
            "kind": "freeform", "body": "x"}}]),
        AIMessage(content="concluded"),
    ])

    async def _drive():
        return await arun_session_turn(
            "pod_runner", "t", [HumanMessage(content="go")],
            checkpointer=InMemorySaver(), tools=[PodNoteTool(store=None, spec_id=spec_id)],
            model_factory=factory, observe=False)

    turn = asyncio.run(_drive())
    assert turn.content == "concluded"               # the loop survived the rejected write
    assert any("NOTES_NO_STORE" in m.content for m in turn.messages)


# --- the wiring proof in a real create_agent ReAct loop -----------------------

def test_create_agent_loop_write_wrong_param_and_read(store, spec_id):
    """D84-22 + D84-36 end-to-end on a FAKE model: a valid write persists
    through the ReAct loop, a wrong parameter becomes the rejected
    `Error invoking tool 'note' ... Extra inputs are not permitted` ToolMessage
    the loop sees, and a valid read returns the note verbatim."""
    from langchain_core.language_models import BaseChatModel
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langchain_core.messages import HumanMessage

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

    factory = lambda role: Fake(replies=[  # noqa: E731
        AIMessage(content="", tool_calls=[{"name": "note", "id": "c1", "args": {
            "operation": "write", "order": 0, "note_name": "experiment",
            "kind": "experiment_summary", "body": "the summary", "bogus": 1}}]),
        AIMessage(content="", tool_calls=[{"name": "note", "id": "c2", "args": {
            "operation": "write", "order": 0, "note_name": "experiment",
            "kind": "experiment_summary", "body": "the summary"}}]),
        AIMessage(content="", tool_calls=[{"name": "note", "id": "c3", "args": {
            "operation": "read", "order": 0}}]),
        AIMessage(content="done"),
    ])

    async def _drive():
        return await arun_session_turn(
            "pod_runner", "t",
            [HumanMessage(content="write the summary then read it back")],
            checkpointer=InMemorySaver(), tools=[_tool(store=store, spec_id=spec_id)],
            model_factory=factory, observe=False)

    turn = asyncio.run(_drive())
    assert turn.content == "done"
    texts = " ".join(str(getattr(m, "content", "")) for m in turn.messages)
    assert "Error invoking tool 'note'" in texts          # the wrong-param rejection
    assert "Extra inputs are not permitted" in texts       # coded by the args schema
    assert "the summary" in texts                          # the read returned the body
    from polymerhus.attack.hunting.pod.pod_memory import read_variant_summary
    assert read_variant_summary(store, spec_id, 0) == "the summary"  # ONE terminal record
    assert store.read_notes(spec_id) == []                 # NOT in notes.yaml


def test_notes_args_rejected_code_is_declared():
    assert NOTES_ARGS_REJECTED.startswith("NOTES_ARGS_REJECTED")
