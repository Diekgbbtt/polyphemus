"""The eval-wide work-item gate (ticket #269, D14/N12).

Pre-eval dependencies live at the `EvalSetup` level and are target-agnostic.
Before any target starts, the orchestrator refuses while a required item is
incomplete and names every offending item, so the operator knows exactly what
to finish.
"""
from __future__ import annotations

import pytest

from orchestrator import setup as setup_mod
from orchestrator import workitems


def test_incomplete_required_items_are_named() -> None:
    items = (
        setup_mod.WorkItem("auth-bootstrap", status="incomplete"),
        setup_mod.WorkItem("l1-surface", status="pending"),
        setup_mod.WorkItem("hunting-artifacts", status="complete"),
    )

    assert workitems.incomplete_required(items) == ["auth-bootstrap", "l1-surface"]


def test_gate_passes_when_all_required_items_are_complete() -> None:
    items = (
        setup_mod.WorkItem("auth-bootstrap", status="complete"),
        setup_mod.WorkItem("l1-surface", status="complete"),
    )

    workitems.require_complete(items)


def test_gate_refuses_and_names_items() -> None:
    items = (
        setup_mod.WorkItem("auth-bootstrap", status="incomplete"),
        setup_mod.WorkItem("l1-surface", status="incomplete"),
    )

    with pytest.raises(workitems.WorkItemGateError) as excinfo:
        workitems.require_complete(items)

    message = str(excinfo.value)
    assert "auth-bootstrap" in message
    assert "l1-surface" in message


def test_non_required_incomplete_item_does_not_gate() -> None:
    items = (
        setup_mod.WorkItem("hunting-artifacts", status="incomplete", required=False),
    )

    workitems.require_complete(items)


def test_gate_on_an_empty_list_passes() -> None:
    workitems.require_complete(())
