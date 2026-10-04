"""Safe Trial-resolution context for the unified read API (unified workspace).

The resolved endpoints map one fully-identified Trial - as it appears in the
projected ``/snapshot`` - to the storage context the resolvers need: the
server-side ``project_id`` and ``instance_id`` plus whether the current
instance's fallback sources (Neo4j graph, raw project directory) may be read.

Nothing here performs I/O, trusts a client path, or infers an association from
a shared ``project_id``: a Trial is selected only by its exact
``(target_id, target_run_id, trial_id)`` identity, and every failure is a
coded, path-free ``ResolvedDataError``.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

TRIAL_NOT_FOUND = "trial_not_found"

_PATH_SEPARATORS = ("/", "\\", "\x00")


class ResolvedDataError(RuntimeError):
    """A coded, path-free resolved-data failure. `code` is the HTTP detail."""

    def __init__(self, code: str, status_code: int) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class TrialContext:
    """The storage context one resolved request needs; never a client path."""

    target_id: str
    target_run_id: str
    trial_id: str
    project_id: str | None
    instance_id: str | None
    fallback_eligible: bool


def resolve_trial_context(
    snapshot: Mapping[str, object],
    target_id: str,
    target_run_id: str,
    trial_id: str,
    *,
    configured_instance_id: str | None,
) -> TrialContext:
    """Resolve one exact Trial identity to its storage context.

    Unknown or unsafe identities raise ``trial_not_found``/404. A missing or
    unsafe ``project_id``/``instance_id`` is unavailable metadata, not an
    error: the Trial still renders, but its fallback sections stay unavailable.
    """
    if not all(_is_safe_segment(part) for part in (target_id, target_run_id, trial_id)):
        raise ResolvedDataError(TRIAL_NOT_FOUND, 404)

    record = _find_record(snapshot, target_id, target_run_id, trial_id)
    if record is None:
        raise ResolvedDataError(TRIAL_NOT_FOUND, 404)

    project_id = _safe_optional_id(record.get("project_id"))
    instance_id = _safe_optional_id(record.get("instance_id"))
    fallback_eligible = (
        project_id is not None
        and instance_id is not None
        and configured_instance_id is not None
        and instance_id == configured_instance_id
    )
    return TrialContext(
        target_id=target_id,
        target_run_id=target_run_id,
        trial_id=trial_id,
        project_id=project_id,
        instance_id=instance_id,
        fallback_eligible=fallback_eligible,
    )


def _find_record(
    snapshot: Mapping[str, object],
    target_id: str,
    target_run_id: str,
    trial_id: str,
) -> Mapping[str, Any] | None:
    if not isinstance(snapshot, Mapping):
        return None
    trials = snapshot.get("trials")
    if not isinstance(trials, list):
        return None
    for record in trials:
        if not isinstance(record, Mapping):
            continue
        if (
            record.get("target_id") == target_id
            and record.get("target_run_id") == target_run_id
            and record.get("trial_id") == trial_id
        ):
            return record
    return None


def _safe_optional_id(value: object) -> str | None:
    """One safe identifier, or None for missing/unsafe values."""
    return value if _is_safe_segment(value) else None


def _is_safe_segment(segment: object) -> bool:
    """One path-safe segment: no separators, no `.`/`..`, no control chars."""
    if not isinstance(segment, str) or not segment or segment in (".", ".."):
        return False
    if any(char in segment for char in _PATH_SEPARATORS):
        return False
    return not any(ord(char) < 32 or ord(char) == 127 for char in segment)


def is_safe_identifier(value: object) -> bool:
    """True when `value` is one path-safe segment (a project id or a dir name)."""
    return _is_safe_segment(value)


__all__ = [
    "ResolvedDataError",
    "TRIAL_NOT_FOUND",
    "TrialContext",
    "is_safe_identifier",
    "resolve_trial_context",
]
