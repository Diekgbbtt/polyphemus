"""A replayed stand-in for the capture sidecar's CDP transport.

The sidecar consumes events and sends a small, passive set of commands. The
fake serves both directions from a checked-in stream and keeps every sent
command, so a test can prove the sidecar sent no navigation, input, or DOM
mutation.
"""
from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from tests.recon.crawl.steel.fixtures import CdpEvent, CdpStream

BODY_METHOD = "Network.getResponseBody"


@dataclass(frozen=True)
class CdpCommand:
    """One command the consumer sent over the fake transport."""

    method: str
    params: dict[str, Any] = field(default_factory=dict)


class FakeCdpTransport:
    """Small CDP seam: `send` records, `replay` yields events in order.

    `replay` restarts on every call; it is a fixture, not a socket.
    """

    def __init__(self, stream: CdpStream) -> None:
        self._events: list[CdpEvent] = list(stream.events)
        self._bodies: dict[str, str] = dict(stream.bodies)
        self.sent: list[CdpCommand] = []

    def send(self, method: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        recorded = dict(params or {})
        self.sent.append(CdpCommand(method=method, params=recorded))
        if method == BODY_METHOD:
            request_id = recorded.get("requestId")
            if request_id not in self._bodies:
                raise KeyError(f"no body queued for request {request_id!r}")
            return {"body": self._bodies[request_id], "base64Encoded": False}
        return {}

    def replay(self) -> Iterator[CdpEvent]:
        yield from self._events

    @property
    def sent_methods(self) -> list[str]:
        return [command.method for command in self.sent]
