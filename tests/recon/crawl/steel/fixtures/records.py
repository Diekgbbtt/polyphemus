"""Typed records the fixture pack loads into.

These models are test scaffolding, not production contracts. They pin the
shape of each checked-in fixture so a typo in the pack fails at load time
instead of surfacing as a confusing assertion later.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CliEnvelope(BaseModel):
    """One `steel browser <verb> --json` stdout object.

    `data` stays untyped on purpose: each verb carries its own payload, and
    the fixtures are the only place the crawl tests pin those payloads.
    """

    model_config = ConfigDict(extra="forbid")

    success: bool
    data: Any = None
    error: str | None = None


class DomNode(BaseModel):
    """One element in a DOM snapshot.

    `attributes` carries the raw HTML attributes, because the element map
    classifies on signals such as `hidden`, `role`, and `onclick`.
    """

    model_config = ConfigDict(extra="forbid")

    tag: str
    ref: str | None = None
    role: str | None = None
    name: str | None = None
    text: str | None = None
    attributes: dict[str, str] = Field(default_factory=dict)
    visible: bool = True
    children: list["DomNode"] = Field(default_factory=list)


class DomSnapshot(BaseModel):
    """A checked-in DOM snapshot: the page plus its element tree."""

    model_config = ConfigDict(extra="forbid")

    url: str
    title: str
    nodes: list[DomNode]


class CdpEvent(BaseModel):
    """One raw CDP event: the method name and its params object."""

    model_config = ConfigDict(extra="forbid")

    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class CdpStream(BaseModel):
    """An ordered CDP replay plus the bodies fetched by request id."""

    model_config = ConfigDict(extra="forbid")

    events: list[CdpEvent]
    bodies: dict[str, str] = Field(default_factory=dict)
