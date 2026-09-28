"""The eval-wide work-item gate (D14/N12).

Pre-eval dependencies are eval-wide, not per-target attributes. Before the
orchestrator starts any target it refuses while a required item is incomplete,
naming every offending item so the operator knows exactly what to finish.
"""
from __future__ import annotations

from typing import Iterable

from orchestrator.setup import WorkItem


class WorkItemGateError(RuntimeError):
    """A required eval-wide work item is not complete."""


def incomplete_required(items: Iterable[WorkItem]) -> list[str]:
    """Names of the required items whose status is not `complete`, in order."""
    return [item.name for item in items if item.required and item.status != "complete"]


def require_complete(items: Iterable[WorkItem]) -> None:
    """Raise `WorkItemGateError` naming every incomplete required item."""
    missing = incomplete_required(items)
    if missing:
        raise WorkItemGateError(
            "eval work items incomplete: " + ", ".join(missing)
        )
