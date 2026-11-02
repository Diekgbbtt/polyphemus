"""Fake seams for the steel-crawl unit tests.

Each fake is injected exactly where the production collaborator will be, so a
test observes the contract rather than reaching into an implementation.
"""
from __future__ import annotations

from .cdp import CdpCommand, FakeCdpTransport
from .decision import DecisionQuestion, DecisionQueueExhausted, FakeDecisionClient
from .exec_fn import ExecQueueExhausted, FakeExecFn
from .golden import assert_matches_golden
from .jev import (
    MISSING_ANSWER,
    AskCall,
    AskQueueExhausted,
    AsyncAskCall,
    FakeAskClient,
    FakeAsyncTypeSafe,
)

__all__ = [
    "MISSING_ANSWER",
    "AskCall",
    "AskQueueExhausted",
    "AsyncAskCall",
    "CdpCommand",
    "DecisionQuestion",
    "DecisionQueueExhausted",
    "ExecQueueExhausted",
    "FakeAskClient",
    "FakeAsyncTypeSafe",
    "FakeCdpTransport",
    "FakeDecisionClient",
    "FakeExecFn",
    "assert_matches_golden",
]
