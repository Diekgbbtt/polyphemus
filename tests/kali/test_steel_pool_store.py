"""Unit tier: the browser-session store for the Steel pool.

The store is the durable session entity. It is independent of the Steel API
containers and the CLI. These tests use a temporary directory only.
"""
from __future__ import annotations

import json
import stat

import pytest

import kali.steel_pool.store as store_module
from kali.steel_pool.store import (
    BrowserSessionRecord,
    CorruptSessionRecord,
    InvalidSessionName,
    SessionStore,
)


def _record(name: str = "polymerhus-hunt-abc", **overrides) -> BrowserSessionRecord:
    values = {
        "name": name,
        "account": "alice",
        "cookies": [
            {"name": "sid", "value": "super-secret", "domain": "app.test", "path": "/"},
        ],
        "local_storage": {"https://app.test": {"token": "secret-token"}},
        "session_storage": {"https://app.test": {"tab": "secret-tab"}},
        "indexed_db": {"app": {"notes": {"key": "secret-index"}}},
        "created_at": "2026-11-05T10:00:00+00:00",
        "updated_at": "2026-11-05T10:00:00+00:00",
    }
    values.update(overrides)
    return BrowserSessionRecord(**values)


def test_save_and_load_round_trip(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    saved = store.save(_record())
    loaded = store.load(saved.name)

    assert loaded == saved
    assert loaded.cookies[0]["value"] == "super-secret"
    assert loaded.local_storage["https://app.test"]["token"] == "secret-token"
    assert loaded.session_storage["https://app.test"]["tab"] == "secret-tab"
    assert loaded.indexed_db["app"]["notes"]["key"] == "secret-index"
    assert loaded.account == "alice"


def test_save_updates_updated_at_and_preserves_created_at(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    saved = store.save(_record())
    loaded = store.load(saved.name)

    assert loaded.created_at == "2026-11-05T10:00:00+00:00"
    assert loaded.updated_at != "2026-11-05T10:00:00+00:00"


def test_missing_record_returns_none(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    assert store.load("absent") is None


def test_corrupt_json_raises(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    path = store.path_for("broken")
    path.write_text("{", encoding="utf-8")

    with pytest.raises(CorruptSessionRecord):
        store.load("broken")


def test_non_object_json_raises(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    path = store.path_for("broken")
    path.write_text("[1, 2]", encoding="utf-8")

    with pytest.raises(CorruptSessionRecord):
        store.load("broken")


def test_wrong_record_name_raises(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    path = store.path_for("expected")
    path.write_text(json.dumps(_record("other").to_dict()), encoding="utf-8")

    with pytest.raises(CorruptSessionRecord):
        store.load("expected")


@pytest.mark.parametrize(
    "name",
    ["", "../escape", "a/b", "-starts-with-dash", "space name", "dot.name", "café", "a" * 129],
)
def test_invalid_names_are_rejected(tmp_path, name):
    store = SessionStore(tmp_path / "sessions")

    with pytest.raises(InvalidSessionName):
        store.path_for(name)
    with pytest.raises(InvalidSessionName):
        store.load(name)
    with pytest.raises(InvalidSessionName):
        store.save(_record(name))


@pytest.mark.parametrize("name", ["a", "a-b_C9", "0start", "a" * 128])
def test_cli_valid_names_are_accepted(tmp_path, name):
    store = SessionStore(tmp_path / "sessions")
    saved = store.save(_record(name))
    assert store.load(name) == saved


def test_store_and_file_modes(tmp_path):
    root = tmp_path / "sessions"
    store = SessionStore(root)
    saved = store.save(_record())
    path = store.path_for(saved.name)

    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_atomic_write_preserves_previous_record_on_failure(tmp_path, monkeypatch):
    store = SessionStore(tmp_path / "sessions")
    first = store.save(_record(account="alice"))

    def fail_replace(*args, **kwargs):
        raise OSError("replace failed")

    monkeypatch.setattr(store_module.os, "replace", fail_replace)

    with pytest.raises(OSError):
        store.save(_record(account="bob"))

    loaded = store.load(first.name)
    assert loaded == first
    assert not [path for path in store.root.iterdir() if path.name.endswith(".tmp")]


def test_repr_does_not_reveal_session_secrets(tmp_path):
    record = _record()
    text = repr(record)

    assert "super-secret" not in text
    assert "secret-token" not in text
    assert "secret-tab" not in text
    assert "secret-index" not in text
    assert "polymerhus-hunt-abc" in text


def test_to_session_context_keeps_only_restorable_fields():
    context = _record().to_session_context()

    assert set(context) == {"cookies", "localStorage"}
    assert context["cookies"][0]["value"] == "super-secret"
    assert context["localStorage"]["https://app.test"]["token"] == "secret-token"
    assert "sessionStorage" not in context
    assert "indexedDB" not in context


def test_from_context_accepts_api_aliases():
    record = BrowserSessionRecord.from_context(
        "polymerhus-hunt-abc",
        {
            "cookies": [{"name": "sid", "value": "v"}],
            "localStorage": {"https://app.test": {"k": "v"}},
            "sessionStorage": {"https://app.test": {"s": "v"}},
            "indexedDB": {"db": {"store": {}}},
        },
        account="alice",
    )

    assert record.cookies == [{"name": "sid", "value": "v"}]
    assert record.local_storage == {"https://app.test": {"k": "v"}}
    assert record.session_storage == {"https://app.test": {"s": "v"}}
    assert record.indexed_db == {"db": {"store": {}}}
    assert record.account == "alice"


def test_from_context_accepts_sdk_aliases():
    record = BrowserSessionRecord.from_context(
        "polymerhus-hunt-abc",
        {
            "cookies": [],
            "local_storage": {"https://app.test": {"k": "v"}},
            "session_storage": {"https://app.test": {"s": "v"}},
            "indexed_db": {"db": {}},
        },
    )

    assert record.local_storage == {"https://app.test": {"k": "v"}}
    assert record.session_storage == {"https://app.test": {"s": "v"}}
    assert record.indexed_db == {"db": {}}


def test_from_context_defaults_missing_fields():
    record = BrowserSessionRecord.from_context("polymerhus-hunt-abc", {})

    assert record.cookies == []
    assert record.local_storage == {}
    assert record.session_storage == {}
    assert record.indexed_db == {}


def test_delete_removes_the_record(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    saved = store.save(_record())

    assert store.delete(saved.name) is True
    assert store.load(saved.name) is None
    assert store.delete(saved.name) is False
