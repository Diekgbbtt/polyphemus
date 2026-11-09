"""Unit tier: the browser-session store for the Steel pool.

The store is the durable session entity. It is independent of the Steel API
containers and the CLI. These tests use a temporary directory only.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
import json
import os
from pathlib import Path
import stat

import pytest

import kali.steel_pool.store as store_module
from kali.steel_pool.store import (
    BrowserSessionRecord,
    CorruptSessionRecord,
    InvalidSessionName,
    SessionStore,
    SessionStoreError,
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


@pytest.fixture
def store(tmp_path) -> SessionStore:
    return SessionStore(tmp_path / "sessions")


def test_save_and_load_round_trip(store):
    saved = store.save(_record())
    loaded = store.load(saved.name)

    assert loaded == saved
    assert loaded.cookies[0]["value"] == "super-secret"
    assert loaded.local_storage["https://app.test"]["token"] == "secret-token"
    assert loaded.session_storage["https://app.test"]["tab"] == "secret-tab"
    assert loaded.indexed_db["app"]["notes"]["key"] == "secret-index"
    assert loaded.account == "alice"


def test_session_record_round_trips_the_session_model(store):
    record = _record(
        role="member",
        root_url="http://app.test/index/user/index.html",
        auth_probe="http://app.test/index/user/index.html",
    )
    saved = store.save(record)
    loaded = store.load(saved.name)

    assert loaded.role == "member"
    assert loaded.root_url == "http://app.test/index/user/index.html"
    assert loaded.auth_probe == "http://app.test/index/user/index.html"
    assert loaded.to_dict()["role"] == "member"
    assert BrowserSessionRecord.from_dict(loaded.to_dict()) == loaded


def test_session_model_fields_are_optional():
    record = _record()

    assert record.role is None
    assert record.root_url is None
    assert record.auth_probe is None


def test_save_updates_updated_at_and_preserves_created_at(store):
    saved = store.save(_record())
    loaded = store.load(saved.name)

    assert loaded.created_at == "2026-11-05T10:00:00+00:00"
    assert loaded.updated_at != "2026-11-05T10:00:00+00:00"


def test_created_at_is_stable_across_repeated_saves(store, monkeypatch):
    monkeypatch.setattr(
        store_module, "_now", lambda: "2026-11-05T10:00:00+00:00"
    )
    first = store.save(_record())

    monkeypatch.setattr(
        store_module, "_now", lambda: "2026-11-05T10:05:00+00:00"
    )
    second = store.save(store.load(first.name))
    third = store.save(store.load(second.name))

    assert second.created_at == "2026-11-05T10:00:00+00:00"
    assert second.updated_at == "2026-11-05T10:05:00+00:00"
    assert third.created_at == second.created_at
    assert third.updated_at == second.updated_at


def test_save_does_not_mutate_the_argument(store):
    record = _record()
    before = record.updated_at

    saved = store.save(record)

    assert record.updated_at == before
    assert saved is not record


def test_missing_record_returns_none(store):
    assert store.load("absent") is None


def test_corrupt_json_raises(store):
    path = store.path_for("broken")
    path.write_text("{", encoding="utf-8")

    with pytest.raises(CorruptSessionRecord):
        store.load("broken")


def test_non_object_json_raises(store):
    path = store.path_for("broken")
    path.write_text("[1, 2]", encoding="utf-8")

    with pytest.raises(CorruptSessionRecord):
        store.load("broken")


def test_wrong_record_name_raises(store):
    path = store.path_for("expected")
    path.write_text(json.dumps(_record("other").to_dict()), encoding="utf-8")

    with pytest.raises(CorruptSessionRecord):
        store.load("expected")


def test_invalid_stored_name_raises_corrupt(store):
    path = store.path_for("expected")
    path.write_text(json.dumps({"name": "../escape"}), encoding="utf-8")

    with pytest.raises(CorruptSessionRecord):
        store.load("expected")


def test_non_utf8_record_raises_corrupt(store):
    path = store.path_for("broken")
    path.write_bytes(b'{"name": "broken", "account": "caf\xe9"}')

    with pytest.raises(CorruptSessionRecord):
        store.load("broken")


def test_read_error_is_wrapped(store, monkeypatch):
    store.save(_record())

    def fail_open(*args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(store_module.os, "open", fail_open)

    with pytest.raises(SessionStoreError):
        store.load("polymerhus-hunt-abc")


def test_symlinked_record_is_not_followed(store, tmp_path):
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(_record("linked").to_dict()), encoding="utf-8")
    store.path_for("linked").symlink_to(outside)

    with pytest.raises(CorruptSessionRecord):
        store.load("linked")


def test_open_no_follow_rejects_a_symlink_that_bypasses_the_precheck(
    store, tmp_path, monkeypatch
):
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(_record("linked").to_dict()), encoding="utf-8")
    store.path_for("linked").symlink_to(outside)
    monkeypatch.setattr(store_module.Path, "is_symlink", lambda self: False)

    with pytest.raises(CorruptSessionRecord) as caught:
        store.load("linked")

    assert "symlink" in str(caught.value)


@pytest.mark.parametrize(
    "name",
    [
        "",
        "../escape",
        "a/b",
        "-starts-with-dash",
        "space name",
        "dot.name",
        "café",
        "a" * 129,
    ],
)
def test_invalid_names_are_rejected(store, name):
    with pytest.raises(InvalidSessionName):
        store.path_for(name)
    with pytest.raises(InvalidSessionName):
        store.load(name)
    with pytest.raises(InvalidSessionName):
        _record(name)
    with pytest.raises(InvalidSessionName):
        store.delete(name)


@pytest.mark.parametrize("name", [None, 1, ["name"]])
def test_non_string_names_are_rejected(store, name):
    with pytest.raises(InvalidSessionName):
        store.path_for(name)
    with pytest.raises(InvalidSessionName):
        store.delete(name)


@pytest.mark.parametrize("name", ["a", "a-b_C9", "0start", "a" * 128])
def test_store_valid_names_are_accepted(store, name):
    saved = store.save(_record(name))
    assert store.load(name) == saved


def test_store_and_file_modes(store):
    saved = store.save(_record())
    path = store.path_for(saved.name)

    assert stat.S_IMODE(store.root.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_existing_owner_only_root_is_accepted(tmp_path):
    root = tmp_path / "sessions"
    root.mkdir(mode=0o700)

    assert SessionStore(root).root == root


def test_existing_root_is_not_chmodded(tmp_path, monkeypatch):
    root = tmp_path / "sessions"
    root.mkdir(mode=0o700)

    def fail(*args, **kwargs):
        raise AssertionError("an existing root must not be chmodded")

    monkeypatch.setattr(store_module.os, "chmod", fail)

    assert SessionStore(root).root == root


def test_existing_group_readable_root_fails_loud(tmp_path):
    root = tmp_path / "sessions"
    root.mkdir()
    os.chmod(root, 0o750)

    with pytest.raises(SessionStoreError):
        SessionStore(root)


def test_root_that_is_a_file_fails_loud(tmp_path):
    root = tmp_path / "sessions"
    root.write_text("not a directory", encoding="utf-8")

    with pytest.raises(SessionStoreError):
        SessionStore(root)


def test_symlinked_root_fails_loud(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "sessions"
    link.symlink_to(target, target_is_directory=True)

    with pytest.raises(SessionStoreError):
        SessionStore(link)


def test_from_env_reads_the_store_root(tmp_path):
    store = SessionStore.from_env(
        {"STEEL_SESSION_STORE": str(tmp_path / "sessions")}
    )

    assert store.root == tmp_path / "sessions"
    assert store.root.is_dir()


@pytest.mark.parametrize("value", [None, "", "   "])
def test_from_env_requires_a_root(value):
    env = {} if value is None else {"STEEL_SESSION_STORE": value}

    with pytest.raises(SessionStoreError):
        SessionStore.from_env(env)


def test_atomic_write_preserves_previous_record_on_failure(store, monkeypatch):
    first = store.save(_record(account="alice"))

    def fail_replace(*args, **kwargs):
        raise OSError("replace failed")

    monkeypatch.setattr(store_module.os, "replace", fail_replace)

    with pytest.raises(SessionStoreError):
        store.save(_record(account="bob"))

    loaded = store.load(first.name)
    assert loaded == first
    assert not [path for path in store.root.iterdir() if path.name.endswith(".tmp")]


def test_fsync_failure_preserves_previous_record(store, monkeypatch):
    first = store.save(_record(account="alice"))

    def fail_fsync(descriptor):
        raise OSError("fsync failed")

    monkeypatch.setattr(store_module.os, "fsync", fail_fsync)

    with pytest.raises(SessionStoreError):
        store.save(_record(account="bob"))

    assert store.load(first.name) == first
    assert not [path for path in store.root.iterdir() if path.name.endswith(".tmp")]


def test_fchmod_failure_preserves_previous_record(store, monkeypatch):
    first = store.save(_record(account="alice"))

    def fail_fchmod(descriptor, mode):
        raise PermissionError("fchmod failed")

    monkeypatch.setattr(store_module.os, "fchmod", fail_fchmod)

    with pytest.raises(SessionStoreError):
        store.save(_record(account="bob"))

    assert store.load(first.name) == first
    assert not [path for path in store.root.iterdir() if path.name.endswith(".tmp")]


def test_save_does_not_chmod_after_replace(store, monkeypatch):
    def fail_chmod(path, mode):
        raise PermissionError("chmod failed")

    monkeypatch.setattr(store_module.os, "chmod", fail_chmod)

    saved = store.save(_record())

    assert store.load(saved.name) == saved


def test_parent_directory_is_fsynced_after_replace(store, monkeypatch):
    opened = []
    real_open = store_module.os.open

    def spy(path, flags, *args, **kwargs):
        opened.append(Path(path))
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(store_module.os, "open", spy)
    store.save(_record())

    assert store.root in opened


def test_fdopen_failure_preserves_previous_record(store, monkeypatch):
    first = store.save(_record(account="alice"))

    with monkeypatch.context() as patch:
        patch.setattr(
            store_module.os,
            "fdopen",
            lambda *args, **kwargs: (_ for _ in ()).throw(OSError("fdopen failed")),
        )
        with pytest.raises(SessionStoreError):
            store.save(_record(account="bob"))

    assert store.load(first.name) == first
    assert not [path for path in store.root.iterdir() if path.name.endswith(".tmp")]


def test_json_failure_leaves_previous_record(store, monkeypatch):
    first = store.save(_record(account="alice"))
    real_dumps = store_module.json.dumps

    def selective_dumps(*args, **kwargs):
        if kwargs.get("sort_keys"):
            raise TypeError("boom")
        return real_dumps(*args, **kwargs)

    monkeypatch.setattr(store_module.json, "dumps", selective_dumps)

    with pytest.raises(CorruptSessionRecord):
        store.save(_record(account="bob"))

    assert store.load(first.name) == first
    assert not [path for path in store.root.iterdir() if path.name.endswith(".tmp")]


def test_temp_file_is_created_in_the_store_root(store, monkeypatch):
    seen = {}
    real_mkstemp = store_module.tempfile.mkstemp

    def spy(*args, **kwargs):
        seen.update(kwargs)
        return real_mkstemp(*args, **kwargs)

    monkeypatch.setattr(store_module.tempfile, "mkstemp", spy)
    store.save(_record())

    assert seen["dir"] == store.root


def test_delete_removes_the_record(store):
    saved = store.save(_record())

    assert store.delete(saved.name) is True
    assert store.load(saved.name) is None
    assert store.delete(saved.name) is False


def test_delete_error_is_wrapped(store, monkeypatch):
    saved = store.save(_record())

    def fail_unlink(self, *args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(store_module.Path, "unlink", fail_unlink)

    with pytest.raises(SessionStoreError):
        store.delete(saved.name)


def test_save_rejects_a_non_record(store):
    with pytest.raises(TypeError):
        store.save({"name": "polymerhus-hunt-abc"})


def test_repr_does_not_reveal_session_secrets():
    text = repr(_record())

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


def test_to_session_context_returns_copies():
    record = _record()
    context = record.to_session_context()
    context["cookies"][0]["value"] = "mutated"
    context["localStorage"]["https://app.test"]["token"] = "mutated"

    assert record.cookies[0]["value"] == "super-secret"
    assert record.local_storage["https://app.test"]["token"] == "secret-token"


def test_to_dict_returns_copies():
    record = _record()
    data = record.to_dict()
    data["cookies"][0]["value"] = "mutated"
    data["localStorage"]["https://app.test"]["token"] = "mutated"

    assert record.cookies[0]["value"] == "super-secret"
    assert record.local_storage["https://app.test"]["token"] == "secret-token"


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


def test_from_context_rejects_a_falsy_created_at():
    with pytest.raises(CorruptSessionRecord):
        BrowserSessionRecord.from_context(
            "polymerhus-hunt-abc", {}, created_at=""
        )


def test_from_dict_defaults_a_missing_created_at():
    record = BrowserSessionRecord.from_dict({"name": "polymerhus-hunt-abc"})

    assert record.created_at == record.updated_at


@pytest.mark.parametrize("value", ["", 0, False])
def test_from_dict_rejects_a_falsy_created_at(value):
    with pytest.raises(CorruptSessionRecord):
        BrowserSessionRecord.from_dict(
            {"name": "polymerhus-hunt-abc", "createdAt": value}
        )


def test_from_context_does_not_alias_the_caller():
    context = {
        "cookies": [{"name": "sid", "value": "v"}],
        "localStorage": {"https://app.test": {"k": "v"}},
    }
    record = BrowserSessionRecord.from_context("polymerhus-hunt-abc", context)
    context["cookies"][0]["value"] = "mutated"
    context["localStorage"]["https://app.test"]["k"] = "mutated"

    assert record.cookies[0]["value"] == "v"
    assert record.local_storage["https://app.test"]["k"] == "v"


def test_from_context_rejects_a_non_mapping():
    with pytest.raises(CorruptSessionRecord):
        BrowserSessionRecord.from_context("polymerhus-hunt-abc", [])


def test_from_context_rejects_bad_cookies():
    with pytest.raises(CorruptSessionRecord):
        BrowserSessionRecord.from_context(
            "polymerhus-hunt-abc", {"cookies": {"sid": "v"}}
        )
    with pytest.raises(CorruptSessionRecord):
        BrowserSessionRecord.from_context(
            "polymerhus-hunt-abc", {"cookies": [["sid", "v"]]}
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("cookies", {"sid": "v"}),
        ("cookies", [["sid", "v"]]),
        ("local_storage", ["origin"]),
        ("session_storage", "origin"),
        ("indexed_db", 5),
        ("account", 5),
        ("created_at", 5),
        ("created_at", "not-a-date"),
        ("created_at", "2026-11-05T10:00:00"),
        ("updated_at", 5),
    ],
)
def test_record_rejects_bad_field_shapes(field, value):
    with pytest.raises(CorruptSessionRecord):
        _record(**{field: value})


def test_record_rejects_non_json_values():
    with pytest.raises(CorruptSessionRecord):
        _record(indexed_db={"db": {"store": {object(): "value"}}})


def test_record_rejects_a_lone_surrogate():
    with pytest.raises(CorruptSessionRecord):
        _record(cookies=[{"name": "sid", "value": "\ud800"}])


def test_record_rejects_excessive_nesting():
    value: dict = {}
    cursor = value
    for _ in range(20000):
        child: dict = {}
        cursor["n"] = child
        cursor = child

    with pytest.raises(CorruptSessionRecord):
        _record(indexed_db=value)


def test_record_rejects_non_string_keys():
    with pytest.raises(CorruptSessionRecord):
        _record(local_storage={"https://app.test": {1: "value"}})


def test_record_rejects_circular_values():
    loop: dict = {}
    loop["self"] = loop

    with pytest.raises(CorruptSessionRecord):
        _record(indexed_db={"db": loop})


def test_record_allows_shared_references():
    shared = {"k": "v"}
    record = _record(local_storage={"https://a.test": shared, "https://b.test": shared})

    assert record.local_storage["https://a.test"] == {"k": "v"}
    assert record.local_storage["https://b.test"] == {"k": "v"}


def test_record_is_immutable():
    record = _record()

    with pytest.raises(FrozenInstanceError):
        record.account = "bob"


def test_unicode_content_round_trips(store):
    record = _record(
        cookies=[{"name": "sid", "value": "café", "domain": "täst.test"}],
        local_storage={"https://täst.test": {"ключ": "значение"}},
    )
    saved = store.save(record)
    loaded = store.load(saved.name)

    assert loaded.cookies[0]["value"] == "café"
    assert loaded.local_storage["https://täst.test"]["ключ"] == "значение"


def test_concurrent_saves_converge(store):
    name = "polymerhus-hunt-abc"

    def writer(index: int) -> None:
        store.save(_record(name, account=f"writer-{index}"))

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(writer, range(100)))

    loaded = store.load(name)
    assert loaded is not None
    assert loaded.name == name
    assert not [path for path in store.root.iterdir() if path.name.endswith(".tmp")]


def test_fchmod_failure_leaks_no_descriptor(store, monkeypatch):
    fd_root = "/proc/self/fd" if os.path.isdir("/proc/self/fd") else "/dev/fd"
    if not os.path.isdir(fd_root):
        pytest.skip("no file-descriptor directory on this platform")
    before = len(os.listdir(fd_root))

    def fail_fchmod(descriptor, mode):
        raise PermissionError("fchmod failed")

    monkeypatch.setattr(store_module.os, "fchmod", fail_fchmod)
    for _ in range(5):
        with pytest.raises(SessionStoreError):
            store.save(_record())

    assert len(os.listdir(fd_root)) == before
