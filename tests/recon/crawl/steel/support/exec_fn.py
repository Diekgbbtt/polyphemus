"""A queued stand-in for the session client's `exec_fn` seam.

The production client will pass one command argument list and receive one CLI
JSON envelope back. The fake mirrors that shape, records every command, and
fails loudly when a test asks for an envelope it never queued.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from typing import Any

from tests.recon.crawl.steel.fixtures import CliEnvelope


class ExecQueueExhausted(RuntimeError):
    """The consumer asked for an envelope the fake never queued."""


def _envelope_dict(envelope: CliEnvelope | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(envelope, CliEnvelope):
        return envelope.model_dump(mode="json")
    return dict(envelope)


class FakeExecFn:
    """Callable `exec_fn`: one command in, one queued envelope out."""

    def __init__(self, *envelopes: CliEnvelope | Mapping[str, Any]) -> None:
        self.commands: list[list[str]] = []
        self._queue: deque[dict[str, Any]] = deque(_envelope_dict(e) for e in envelopes)

    def __call__(self, command: Sequence[str]) -> dict[str, Any]:
        recorded = [str(part) for part in command]
        self.commands.append(recorded)
        if not self._queue:
            raise ExecQueueExhausted(f"no queued envelope for command: {recorded}")
        return self._queue.popleft()

    def queue(self, *envelopes: CliEnvelope | Mapping[str, Any]) -> None:
        self._queue.extend(_envelope_dict(envelope) for envelope in envelopes)

    @property
    def last_command(self) -> list[str] | None:
        return self.commands[-1] if self.commands else None
