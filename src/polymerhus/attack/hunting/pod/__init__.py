"""The test-executor pod (#84): the bottom of the hunting agent hierarchy.

The test-EXECUTION side of the Q8 design/execution partition - an actor-critic
cooperative team (Runner + Triager) over a LangGraph looped state machine that
executes a `TestImplementationSpec` (D4) against the live target and returns the
binary verdict with the full experiment log as evidence (D5 + D6), via IA-4.
This build ships the minimal scaffold only (D67-01).
"""
from __future__ import annotations

from polymerhus.attack.hunting.pod.graph import build_pod_graph
from polymerhus.attack.hunting.pod.pod import run_pod
from polymerhus.attack.hunting.pod.types import (
    PodExport,
    TestImplementationSpec,
)

__all__ = ["run_pod", "build_pod_graph", "PodExport", "TestImplementationSpec"]
