"""Unit tier: the tool-output offload half (#95 slice B).

The tool-body policy (ADR D8): a body under ~700 approximate tokens stays FULL in
context; a body at or over the cut line is replaced by a HEADER (tool-call id, tool
name, the command outline verbatim-bounded, the status marker, bounded head and tail
excerpts, and the body ref into the module's OWN store) and its full body offloads to
an injectable ToolOutputStore. Retrieval is exact-ref and byte-identical; an unknown
ref degrades to None, never a raise. No size field. The built-in in-process backing
serves hermetic tests - no live model, no live gateway, no database.
"""
from __future__ import annotations

from langchain_core.messages import ToolMessage

from polymerhus.app.llm import tool_output as T

SENTINEL_BODY = "line-A\n" + ("middle-" * 10000) + "\nline-Z"

UNDER_CUT_BODY = "short output under the cut line"


def test_under_cut_body_stays_full():
    """A body under ~700 tokens stays FULL in context: the message is unchanged and
    nothing is written to the store."""
    store = T.InMemoryToolOutputStore()
    msg = ToolMessage(content=UNDER_CUT_BODY, tool_call_id="t1")
    out = T.offload_tool_message(store, "thr", msg, name="terminal", args="ls")
    assert out is msg
    assert store.put_count() == 0


def test_over_cut_body_offloads_and_headers():
    """A body over the cut line becomes a header in the window and its FULL body is
    in the module's store, byte-identical."""
    store = T.InMemoryToolOutputStore()
    msg = ToolMessage(content=SENTINEL_BODY, tool_call_id="t1")
    out = T.offload_tool_message(store, "thr", msg, name="terminal", args="cat /var/log/app.log",
                                 status="exit=0")
    assert isinstance(out, ToolMessage)
    assert out.tool_call_id == "t1"
    header = out.content
    assert "terminal" in header and "cat /var/log/app.log" in header and "exit=0" in header
    assert "t1" in header
    ref = T.header_ref_from_text(header)
    assert ref is not None
    assert store.get_body("thr", ref) == SENTINEL_BODY


def test_header_carries_bounded_head_and_tail_excerpts():
    """The header carries bounded HEAD and TAIL excerpts (the terminal body's opening
    and ending are its informative parts; the outline alone does not characterise it)."""
    store = T.InMemoryToolOutputStore()
    body = "HEAD-MARKER-0123456789" + ("y" * 4000) + "TAIL-MARKER-9876543210"
    msg = ToolMessage(content=body, tool_call_id="t1")
    out = T.offload_tool_message(store, "thr", msg, name="terminal", args="cmd")
    header = out.content
    assert "HEAD-MARKER-0123456789" in header
    assert "TAIL-MARKER-9876543210" in header
    assert "y" * 1000 not in header  # the middle is elided, not dumped (excerpts are bounded)


def test_retrieval_is_byte_identical_and_unknown_ref_degrades():
    """Retrieval returns the byte-identical body; an unknown ref degrades to None,
    never a raise."""
    store = T.InMemoryToolOutputStore()
    msg = ToolMessage(content=SENTINEL_BODY, tool_call_id="t1")
    out = T.offload_tool_message(store, "thr", msg, name="terminal", args="cmd")
    ref = T.header_ref_from_text(out.content)
    assert T.retrieve_tool_body(store, "thr", ref) == SENTINEL_BODY
    assert T.retrieve_tool_body(store, "thr", "no-such-ref") is None


def test_offload_is_idempotent_one_body_stored():
    """Offloading the same (thread, tool-call) twice yields the SAME ref and exactly
    ONE stored body - a re-offload (the re-filtering of a retrieved body) overwrites,
    never duplicates."""
    store = T.InMemoryToolOutputStore()
    msg = ToolMessage(content=SENTINEL_BODY, tool_call_id="t1")
    out1 = T.offload_tool_message(store, "thr", msg, name="terminal", args="cmd")
    ref1 = T.header_ref_from_text(out1.content)
    out2 = T.offload_tool_message(store, "thr", msg, name="terminal", args="cmd")
    ref2 = T.header_ref_from_text(out2.content)
    assert ref1 == ref2
    assert store.put_count() == 1
    assert store.body_count() == 1


def test_status_derivation_is_fail_open():
    """The status marker derives from the body when not supplied (a heuristic over the
    raw terminal output) and is omitted when nothing signals an exit code."""
    store = T.InMemoryToolOutputStore()
    body = "...\nProcess finished with exit code 0\n" + ("m" * 4000)
    out = T.offload_tool_message(
        store, "thr", ToolMessage(content=body, tool_call_id="t1"), name="terminal", args="cmd")
    assert "exit code 0" in out.content
    out2 = T.offload_tool_message(
        store, "thr", ToolMessage(content="n" * 4000, tool_call_id="t2"),
        name="terminal", args="cmd")
    assert "status=" not in out2.content
