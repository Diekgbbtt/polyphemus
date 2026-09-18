"""#241: server-stamped account facts - validity (`status`) and recency (`updated_at`).

Unit tier, CODING_STANDARD sections 3/6/10: pure validation/selection plus the
AuthStore seam over explicit-root temp stores; no live infra, no env var.
Every literal below comes from #223 D223-14/D223-18 and the ticket, not from
the implementation - the tests pin the contract, the modules honour it.
"""
import pytest

from polymerhus.app.auth import (
    AuthInvalidError,
    AuthStore,
    select_account,
    validate_account,
)
from polymerhus.app.auth.tool import build_auth_store_tool

PROJECT = "proj-auth-facts-1"


def _credentials(name="u"):
    return {"username": name, "password": "p",
            "login_url": "https://target.example/login"}


# --- validation: the validity fact accepts its two values, absent allowed ----

def test_status_absent_is_valid():
    assert validate_account({"origin": "agent"}) == {"origin": "agent"}


def test_status_accepts_valid_and_not_valid():
    for value in ("valid", "not_valid"):
        assert validate_account({"origin": "agent", "status": value}) == {
            "origin": "agent", "status": value}


def test_status_refuses_anything_else_with_a_coded_refusal():
    for bad in ("pending", "VALID", "unknown", "", None, 0, ["valid"], {"v": 1}):
        with pytest.raises(AuthInvalidError) as exc:
            validate_account({"origin": "agent", "status": bad})
        assert exc.value.field == "account.status"
        assert "account.status" in str(exc.value)


def test_updated_at_accepts_the_server_stamp_shape():
    record = {"origin": "agent", "updated_at": "2026-09-18T00:00:00+00:00"}
    assert validate_account(record) == record


def test_updated_at_refuses_a_non_string():
    for bad in (1726617600, None, ["2026-09-18"], {"at": "x"}):
        with pytest.raises(AuthInvalidError) as exc:
            validate_account({"origin": "agent", "updated_at": bad})
        assert exc.value.field == "account.updated_at"


# --- stamping: every agent write carries a server-side recency fact ----------

def test_agent_write_stamps_updated_at_server_side(tmp_path):
    store = AuthStore(tmp_path)
    store.write(PROJECT, "accounts.alice.notes", "agent-minted note")
    record = store.read(PROJECT, "accounts.alice")
    assert isinstance(record["updated_at"], str) and record["updated_at"]
    assert record["notes"] == "agent-minted note"
    assert record["origin"] == "agent"


def test_operator_seed_stamps_updated_at_server_side(tmp_path):
    store = AuthStore(tmp_path)
    store.replace_operator_state(
        PROJECT, accounts={"ops": {"credentials": _credentials("o")}})
    record = store.read(PROJECT, "accounts.ops")
    assert isinstance(record["updated_at"], str) and record["updated_at"]
    assert record["origin"] == "operator"


def test_every_write_refreshes_recency(tmp_path, monkeypatch):
    import polymerhus.app.auth.store as store_mod

    stamps = iter(["2026-09-18T00:00:01+00:00", "2026-09-18T00:00:02+00:00"])
    monkeypatch.setattr(store_mod, "_utcnow_iso", lambda: next(stamps))
    store = AuthStore(tmp_path)
    store.write(PROJECT, "accounts.alice.notes", "first")
    first = store.read(PROJECT, "accounts.alice.updated_at")
    store.write(PROJECT, "accounts.alice.notes", "second")
    second = store.read(PROJECT, "accounts.alice.updated_at")
    assert (first, second) == (
        "2026-09-18T00:00:01+00:00", "2026-09-18T00:00:02+00:00")


# --- forgery: a client-supplied recency value is never trusted ---------------

def test_forged_updated_at_on_create_is_ignored_never_trusted(tmp_path):
    store = AuthStore(tmp_path)
    store.write(PROJECT, "accounts.bob",
                {"credentials": _credentials("bob"),
                 "updated_at": "1999-01-01T00:00:00+00:00"})
    stored = store.read(PROJECT, "accounts.bob.updated_at")
    assert stored != "1999-01-01T00:00:00+00:00"
    assert isinstance(stored, str) and stored


def test_forged_updated_at_on_deep_write_is_ignored_never_trusted(tmp_path):
    store = AuthStore(tmp_path)
    store.write(PROJECT, "accounts.alice.notes", "agent-minted note")
    store.write(PROJECT, "accounts.alice.updated_at", "1999-01-01T00:00:00+00:00")
    stored = store.read(PROJECT, "accounts.alice.updated_at")
    assert stored != "1999-01-01T00:00:00+00:00"
    assert isinstance(stored, str) and stored


def test_forged_updated_at_on_seed_is_ignored_never_trusted(tmp_path):
    store = AuthStore(tmp_path)
    store.replace_operator_state(
        PROJECT, accounts={"ops": {"notes": "seeded",
                                   "updated_at": "1999-01-01T00:00:00+00:00"}})
    stored = store.read(PROJECT, "accounts.ops.updated_at")
    assert stored != "1999-01-01T00:00:00+00:00"
    assert isinstance(stored, str) and stored


# --- round-trip: reads expose both facts on seeded and agent-written accounts -

def test_status_write_round_trips_on_agent_accounts(tmp_path):
    store = AuthStore(tmp_path)
    store.write(PROJECT, "accounts.alice", {"notes": "fresh"})
    store.write(PROJECT, "accounts.alice.status", "not_valid")
    assert store.read(PROJECT, "accounts.alice.status") == "not_valid"
    store.write(PROJECT, "accounts.alice.status", "valid")
    assert store.read(PROJECT, "accounts.alice.status") == "valid"


def test_status_bad_value_refuses_naming_the_field(tmp_path):
    store = AuthStore(tmp_path)
    store.write(PROJECT, "accounts.alice", {"notes": "fresh"})
    with pytest.raises(AuthInvalidError) as exc:
        store.write(PROJECT, "accounts.alice.status", "pending")
    assert "account.status" in str(exc.value)
    assert store.read(PROJECT, "accounts.alice.status") == {}


def test_status_null_removes_the_fact_keeping_the_record_valid(tmp_path):
    store = AuthStore(tmp_path)
    store.write(PROJECT, "accounts.alice.status", "valid")
    store.write(PROJECT, "accounts.alice.status", None)
    assert store.read(PROJECT, "accounts.alice.status") == {}
    assert store.read(PROJECT, "accounts.alice.origin") == "agent"


def test_reads_expose_both_facts_on_seeded_and_agent_written_accounts(tmp_path):
    store = AuthStore(tmp_path)
    store.replace_operator_state(
        PROJECT, accounts={"ops": {"credentials": _credentials("o"),
                                   "status": "valid"}})
    store.write(PROJECT, "accounts.scout.notes", "agent-minted")
    store.write(PROJECT, "accounts.scout.status", "not_valid")
    seeded = store.read(PROJECT, "accounts.ops")
    assert seeded["status"] == "valid"
    assert isinstance(seeded["updated_at"], str)
    written = store.read(PROJECT, "accounts.scout")
    assert written["status"] == "not_valid"
    assert isinstance(written["updated_at"], str)


# --- selection: most recent first, list position as tie-break ----------------

def test_select_picks_the_most_recently_updated_usable_account():
    accounts = {
        "old": {"origin": "agent", "updated_at": "2026-09-16T00:00:00+00:00"},
        "new": {"origin": "agent", "updated_at": "2026-09-18T00:00:00+00:00"},
        "mid": {"origin": "agent", "updated_at": "2026-09-17T00:00:00+00:00"},
    }
    assert select_account(accounts) == "new"


def test_select_tie_breaks_by_list_position_newest_last():
    stamp = "2026-09-18T00:00:00+00:00"
    accounts = {
        "first": {"origin": "agent", "updated_at": stamp},
        "second": {"origin": "agent", "updated_at": stamp},
    }
    assert select_account(accounts) == "second"


def test_select_skips_not_valid_accounts():
    accounts = {
        "stale-good": {"origin": "agent", "status": "valid",
                       "updated_at": "2026-09-16T00:00:00+00:00"},
        "fresh-bad": {"origin": "agent", "status": "not_valid",
                      "updated_at": "2026-09-18T00:00:00+00:00"},
    }
    assert select_account(accounts) == "stale-good"


def test_select_treats_a_missing_stamp_as_oldest():
    accounts = {
        "unstamped": {"origin": "agent"},
        "stamped": {"origin": "agent", "updated_at": "2026-09-16T00:00:00+00:00"},
    }
    assert select_account(accounts) == "stamped"


def test_select_returns_none_when_no_account_is_usable():
    assert select_account({}) is None
    assert select_account({
        "bad": {"origin": "agent", "status": "not_valid",
                "updated_at": "2026-09-18T00:00:00+00:00"},
    }) is None


# --- tool face: coded envelopes, forgery never trusted ------------------------

def test_tool_write_of_each_validity_value_round_trips(tmp_path):
    tool = build_auth_store_tool(PROJECT, AuthStore(tmp_path))
    for value in ("valid", "not_valid"):
        out = tool.invoke({"command": "write",
                           "path": "accounts.alice.status", "value": value})
        assert out["ok"] is True
        assert tool.invoke({"command": "read",
                            "path": "accounts.alice.status"})["value"] == value


def test_tool_write_of_a_bad_validity_value_is_auth_invalid(tmp_path):
    tool = build_auth_store_tool(PROJECT, AuthStore(tmp_path))
    out = tool.invoke({"command": "write", "path": "accounts.alice.status",
                       "value": "pending"})
    assert out["ok"] is False
    assert out["error"] == "auth_invalid"
    assert "account.status" in out["detail"]


def test_tool_forged_updated_at_is_never_trusted(tmp_path):
    tool = build_auth_store_tool(PROJECT, AuthStore(tmp_path))
    out = tool.invoke({"command": "write", "path": "accounts.alice.updated_at",
                       "value": "1999-01-01T00:00:00+00:00"})
    assert out["ok"] is True
    stored = tool.invoke({"command": "read",
                          "path": "accounts.alice.updated_at"})["value"]
    assert stored != "1999-01-01T00:00:00+00:00"
    assert isinstance(stored, str) and stored
