"""The tool-output offload half of the context-window manager (#95 slice B).

The tool-body policy (ADR `docs/design/context-compaction-95-decisions.md` D8):

- A body under ~700 approximate tokens stays FULL in context.
- A body at or over the cut line is replaced by a HEADER - the tool-call id, the
  tool name, the OUTLINE (the command/args, verbatim, bounded), the STATUS marker
  the tool result records (for the raw terminal tool, the exit code), bounded HEAD
  and TAIL excerpts of the body (required: the outline alone does not characterise
  a terminal body, whose informative parts are its opening and ending), and the
  body REF into the module's own store - and its full body offloads.
- No size field.
- Retrieval is exact-ref (`get_body`) and byte-identical; an unknown ref degrades
  to None, never a raise.
- Offloading is idempotent: the same (thread, tool-call) yields the same ref and
  one stored body, so re-offloading a retrieved body overwrites, never duplicates
  (the re-filtering a later compact pass performs).

The store is a `ToolOutputStore` Protocol - each module backs it with ITS OWN store
(e.g. the test-executor pod's experiment log); `InMemoryToolOutputStore` is the
built-in in-process backing for hermetic tests. mem0 is deliberately NOT here:
semantic retrieval belongs to the unified memory work item, not this ticket.

Importing this module performs no I/O and requires no env var (CODING_STANDARD
section 6).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from langchain_core.messages import ToolMessage

# D8: the approximate token cut line - a body under this stays full in context.
TOOL_BODY_CUT_TOKENS = 700
# The bounded head/tail excerpt size (chars), each side.
HEAD_TAIL_EXCERPT_CHARS = 600
# The chars-per-token approximation used to cut bodies ("~700 tokens" - approximate
# by the ADR's own wording; consistent with count_tokens_approximately's 4.0 default).
_CHARS_PER_TOKEN = 4.0


class ToolOutputStore(Protocol):
    """The module-owned backing for offloaded tool bodies (D8). A module supplies its
    own; the contract is exact-ref: put returns a ref, get returns the body."""

    def put_body(self, thread_id: str, tool_call_id: str, body: str) -> str: ...

    def get_body(self, thread_id: str, ref: str) -> str | None: ...


class InMemoryToolOutputStore:
    """The built-in in-process backing (hermetic tests, or a module with no durable
    store). The ref is the tool-call id - deterministic, so re-putting is idempotent."""

    def __init__(self) -> None:
        self._bodies: dict[str, dict[str, str]] = {}

    def put_body(self, thread_id: str, tool_call_id: str, body: str) -> str:
        self._bodies.setdefault(thread_id, {})[tool_call_id] = body
        return tool_call_id

    def get_body(self, thread_id: str, ref: str) -> str | None:
        return self._bodies.get(thread_id, {}).get(ref)

    def put_count(self) -> int:
        return sum(len(b) for b in self._bodies.values())

    def body_count(self) -> int:
        return sum(len(b) for b in self._bodies.values())


def _approx_body_tokens(body: str) -> int:
    """The approximate token count of a tool body (chars/4 - the ADR's '~700 tokens'
    approximate cut, matching count_tokens_approximately's default chars-per-token)."""
    return int(len(body) / _CHARS_PER_TOKEN)


def is_over_cut(body: str) -> bool:
    """Whether a tool body crosses the cut line and must be offloaded (D8)."""
    return _approx_body_tokens(body) >= TOOL_BODY_CUT_TOKENS


@dataclass(frozen=True)
class ToolOutputHeader:
    """The precise header a tool body is replaced by in the window (D8).

    No size field (operator ruling). `outline` is the command/args verbatim
    (bounded); `status` is the outcome marker (the exit code for the raw terminal
    tool), `head`/`tail` the bounded excerpts, `body_ref` the module-store ref."""

    tool_call_id: str
    name: str
    outline: str
    status: str | None
    head: str
    tail: str
    body_ref: str

    def to_text(self) -> str:
        line = f"[offloaded tool output] tool={self.name} command={self.outline}"
        if self.status:
            line += f" status={self.status}"
        line += f" ref={self.body_ref}"
        return f"{line}\n--head--\n{self.head}\n--tail--\n{self.tail}"


_REF_RE = re.compile(r"\bref=(\S+)")


def header_ref_from_text(header: str) -> str | None:
    """Extract the store ref from a header's text (the retrieval path's lookup key)."""
    match = _REF_RE.search(header)
    return match.group(1) if match else None


def _derive_status(body: str) -> str | None:
    """A best-effort status marker from the raw terminal output: the exit code when
    the body signals one, else None (fail-open - the header simply omits it)."""
    for pattern in (r"exit\s+code\s+(\d+)", r"exit\s+status\s+(\d+)", r"\bexit\s+(\d+)"):
        match = re.search(pattern, body, flags=re.IGNORECASE)
        if match:
            return f"exit={match.group(1)}"
    return None


def offload_tool_message(
    store: ToolOutputStore,
    thread_id: str,
    message: ToolMessage,
    *,
    name: str,
    args: str,
    status: str | None = None,
) -> ToolMessage:
    """Apply the layered cutting rule to one tool result (D8).

    Under the cut line the message is returned UNCHANGED (full in context, no store
    write). At or over it, the body offloads to the module's store and the message is
    replaced by its header (same tool-call id, other attributes preserved). The
    `name`/`args` outline and optional `status` come from the paired tool call; the
    status derives heuristically from the body when not supplied."""
    body = message.content if isinstance(message.content, str) else str(message.content)
    if not is_over_cut(body):
        return message
    body_ref = store.put_body(thread_id, message.tool_call_id, body)
    header = ToolOutputHeader(
        tool_call_id=message.tool_call_id,
        name=name,
        outline=args[:HEAD_TAIL_EXCERPT_CHARS],
        status=status or _derive_status(body),
        head=body[:HEAD_TAIL_EXCERPT_CHARS],
        tail=body[-HEAD_TAIL_EXCERPT_CHARS:],
        body_ref=body_ref,
    )
    return message.model_copy(update={"content": header.to_text()})


def retrieve_tool_body(store: ToolOutputStore, thread_id: str, ref: str) -> str | None:
    """Exact-ref retrieval: the byte-identical full body for a header ref, or None
    (an unknown ref degrades, never raises)."""
    try:
        return store.get_body(thread_id, ref)
    except Exception:  # noqa: BLE001 - a failing module store degrades, never raises
        return None
