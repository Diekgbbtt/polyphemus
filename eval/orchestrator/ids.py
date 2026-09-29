"""Stable short identifiers the orchestrator derives names from.

One hash function so the compose project (`ph-<short>`), the target container
name, and any other derived handle never drift between the instance, target,
and routing layers.
"""
from __future__ import annotations

import hashlib

SHORT_LENGTH = 8


def short_id(value: str, length: int = SHORT_LENGTH) -> str:
    """A deterministic lowercase hex prefix of `sha1(value)`.

    Deterministic so a rerun of the same setup addresses the same compose
    project and synthetic Host; short so it stays readable in a container name.
    """
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:length]
