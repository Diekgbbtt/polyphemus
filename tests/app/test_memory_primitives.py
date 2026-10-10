"""Unit tier: the shared memory primitives lifted to `app.memory` (T1).

Pins the lift's two contracts: the bounded-retention primitive has a SINGLE
definition in the shared module (hunting imports it, never re-defines it), and
the notes-tool base / coded-teaching rejection the hunting seams bind IS the
shared module's, re-exported at the historical `attack.hunting.tool_contract`
path. No DB, no LLM, no filesystem.
"""
from __future__ import annotations

from polymerhus.app.memory import bounds as shared_bounds
from polymerhus.app.memory import store as shared_store
from polymerhus.app.memory import tool_contract as shared_contract
from polymerhus.attack.hunting import hunter_memory, hunt_store
from polymerhus.attack.hunting import tool_contract as hunting_contract


def test_retain_bounded_records_has_a_single_definition():
    assert hunt_store.retain_bounded_records is shared_bounds.retain_bounded_records
    assert not hasattr(hunter_memory, "retain_bounded_records")


def test_hunting_stores_build_on_the_shared_bounded_store_base():
    assert issubclass(hunt_store.HuntStore, shared_store.BoundedRecordStore)
    assert issubclass(
        hunter_memory.HunterMemoryStore, shared_store.BoundedRecordStore
    )


def test_hunting_tool_contract_reexports_the_shared_definitions():
    assert hunting_contract.StoreToolBase is shared_contract.StoreToolBase
    assert hunting_contract.build_notes_tool is shared_contract.build_notes_tool
    assert hunting_contract.NotesFieldMap is shared_contract.NotesFieldMap
    assert hunting_contract.NotesStoreHandle is shared_contract.NotesStoreHandle


def test_hunting_seams_bind_the_shared_tool_base():
    from polymerhus.attack.hunting import actors, hunter_tools

    assert actors.StoreToolBase is shared_contract.StoreToolBase
    assert hunter_tools.StoreToolBase is shared_contract.StoreToolBase
    assert hunter_tools.StoreNotesTool is shared_contract.StoreNotesTool
