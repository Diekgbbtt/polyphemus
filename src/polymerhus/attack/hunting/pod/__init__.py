"""The test-executor pod (#84): the bottom of the hunting agent hierarchy.

The test-EXECUTION side of the Q8 design/execution partition - an actor-critic
cooperative team (Runner + Triager) over a LangGraph looped state machine that
executes a `TestImplementationSpec` (D4) against the live target and returns the
binary verdict with the full experiment log as evidence (D5 + D6), via IA-4.

As of T7 (#157) the Runner and Triager are production `create_agent` ReAct
sessions (D84-16/17/23): the Runner is ONE stateful ReAct turn per stretch with
`tools=[exec, kb_retrieve, note]` (the KB wiring hole closed, D84-16/26) and the
P3 experiment_summary note write as its final tool call (D84-17/19); the Triager
reads that note through a `stateful_turn` (D84-23). The pod owns a persistent
experiment-memory store (`PodMemoryStore`, D84-20/28) with the prompt-memory
pattern (D84-27); the harness middleware owns G1/G4/O7 (D84-22) and the
`tool_exec` graph node is retired from the production lane (D84-29).
"""
from __future__ import annotations

from polymerhus.attack.hunting.pod.graph import build_pod_graph
from polymerhus.attack.hunting.pod.note_tool import PodNoteTool
from polymerhus.attack.hunting.pod.pod import arun_pod
from polymerhus.attack.hunting.pod.pod_memory import (
    POD_NOTE_KINDS,
    PodMemoryStore,
    canonical_spec_id,
    compose_memory_guidance,
)
from polymerhus.attack.hunting.pod.types import (
    PodExport,
    TestImplementationSpec,
)

__all__ = [
    "arun_pod",
    "build_pod_graph",
    "PodExport",
    "TestImplementationSpec",
    "PodMemoryStore",
    "PodNoteTool",
    "POD_NOTE_KINDS",
    "canonical_spec_id",
    "compose_memory_guidance",
]