"""T2 (#228): the per-project auth bucket store - persistence behind one seam.

Unit tier, CODING_STANDARD sections 3/5/6/10: tests cross only the public
AuthStore seam with explicit-root temp stores (no live infra); every literal
below comes from the #220 spec shapes and the ticket rules, not from the
implementation - the tests pin the contract, the module honours it.
"""
import pytest
import yaml

from polymerhus.app.auth.records import AuthInvalidError
from polymerhus.app.auth.store import (
    AuthStore,
    DuplicateAuthError,
    OperatorImmutableError,
    StoreUnavailableError,
)
from polymerhus.app.data_root import DATA_ROOT

PROJECT = "proj-auth-1"


# --- roots: app-owned default, explicit root for tests, no I/O on import -----

def test_default_root_is_the_app_owned_data_root():
    assert DATA_ROOT.name == "data"
    assert str(DATA_ROOT).endswith("data")
    assert AuthStore()._root == DATA_ROOT
    assert AuthStore()._bucket_dir(PROJECT) == DATA_ROOT / PROJECT / "auth"


def test_explicit_root_points_at_a_temp_dir(tmp_path):
    assert AuthStore(tmp_path)._root == tmp_path


# --- lazy bucket: created at the first write, exactly the two spec files -----

def test_read_of_an_unseeded_project_is_a_valid_empty_and_creates_nothing(tmp_path):
    store = AuthStore(tmp_path)
    assert store.read(PROJECT) == {"overview": {}, "accounts": {}}
    assert not (tmp_path / PROJECT).exists()


def test_first_write_creates_exactly_the_two_spec_files(tmp_path):
    store = AuthStore(tmp_path)
    store.write(PROJECT, "overview.notes", "operator ground truth", origin="operator")
    bucket = tmp_path / PROJECT / "auth"
    assert sorted(p.name for p in bucket.iterdir()) == ["credentials.yaml", "overview.yaml"]


# --- reads: full state, dotted projections, missing paths are valid empty -----

def test_write_account_field_stamps_the_agent_origin_server_side(tmp_path):
    store = AuthStore(tmp_path)
    store.write(PROJECT, "accounts.alice.notes", "agent-minted note")
    assert store.read(PROJECT, "accounts.alice") == {
        "origin": "agent", "notes": "agent-minted note"}


def test_read_full_state_after_seeded_writes(tmp_path):
    store = AuthStore(tmp_path)
    store.write(PROJECT, "overview.notes", "operator ground truth", origin="operator")
    store.write(PROJECT, "accounts.alice.notes", "agent-minted note")
    assert store.read(PROJECT) == {
        "overview": {"notes": "operator ground truth"},
        "accounts": {"alice": {"origin": "agent", "notes": "agent-minted note"}},
    }


def test_read_dotted_paths_project_the_field(tmp_path):
    store = AuthStore(tmp_path)
    store.write(PROJECT, "overview.notes", "operator ground truth", origin="operator")
    store.write(PROJECT, "accounts.alice.notes", "agent-minted note")
    assert store.read(PROJECT, "overview") == {"notes": "operator ground truth"}
    assert store.read(PROJECT, "overview.notes") == "operator ground truth"
    assert store.read(PROJECT, "accounts.alice") == {"origin": "agent", "notes": "agent-minted note"}


def test_read_nested_token_path_projects_the_token_entry(tmp_path):
    store = AuthStore(tmp_path)
    store.write(PROJECT, "accounts.alice.tokens.session",
                {"value": "abc123", "location": "cookie"})
    assert store.read(PROJECT, "accounts.alice.tokens.session") == {
        "value": "abc123", "location": "cookie"}
    assert store.read(PROJECT, "accounts.alice.tokens") == {
        "session": {"value": "abc123", "location": "cookie"}}


def test_read_missing_paths_are_valid_empty_never_an_error(tmp_path):
    store = AuthStore(tmp_path)
    store.write(PROJECT, "overview.notes", "operator ground truth", origin="operator")
    assert store.read(PROJECT, "accounts.bob") == {}
    assert store.read(PROJECT, "accounts.alice.tokens.session") == {}
    assert store.read(PROJECT, "overview.nope") == {}
    assert store.read(PROJECT, "bogus") == {}


def test_read_returns_copies_never_store_handles(tmp_path):
    store = AuthStore(tmp_path)
    store.write(PROJECT, "overview.notes", "operator ground truth", origin="operator")
    state = store.read(PROJECT)
    state["overview"]["notes"] = "mutated"
    assert store.read(PROJECT, "overview.notes") == "operator ground truth"


# --- writes: CREATE at the account root, merge below it, null removes --------

def _credentials(name="ops-admin") -> dict:
    return {"username": name, "password": "s3cret",
            "login_url": "https://target.example/login"}


def test_create_account_root_upserts_the_whole_record_stamped_agent(tmp_path):
    store = AuthStore(tmp_path)
    store.write(PROJECT, "accounts.bob", {"credentials": _credentials("bob")})
    assert store.read(PROJECT, "accounts.bob") == {
        "origin": "agent", "credentials": _credentials("bob")}


def test_create_ignores_a_forged_origin_inside_the_value(tmp_path):
    store = AuthStore(tmp_path)
    store.write(PROJECT, "accounts.bob",
                {"origin": "operator", "credentials": _credentials("bob")})
    assert store.read(PROJECT, "accounts.bob.origin") == "agent"


def test_create_of_a_known_name_fails_duplicate_leaving_the_record(tmp_path):
    store = AuthStore(tmp_path)
    store.write(PROJECT, "accounts.bob", {"credentials": _credentials("bob")},
                origin="operator")
    with pytest.raises(DuplicateAuthError):
        store.write(PROJECT, "accounts.bob", {"notes": "forked"})
    assert store.read(PROJECT, "accounts.bob") == {
        "origin": "operator", "credentials": _credentials("bob")}


def test_write_merges_leaving_sibling_fields_untouched(tmp_path):
    store = AuthStore(tmp_path)
    store.write(PROJECT, "accounts.alice.notes", "agent-minted note")
    store.write(PROJECT, "accounts.alice.tokens.session",
                {"value": "abc123", "location": "cookie"})
    assert store.read(PROJECT, "accounts.alice") == {
        "origin": "agent",
        "notes": "agent-minted note",
        "tokens": {"session": {"value": "abc123", "location": "cookie"}},
    }


def test_null_removes_an_optional_field_keeping_the_record_valid(tmp_path):
    store = AuthStore(tmp_path)
    store.write(PROJECT, "accounts.alice.notes", "agent-minted note")
    store.write(PROJECT, "accounts.alice.notes", None)
    assert store.read(PROJECT, "accounts.alice") == {"origin": "agent"}
    assert store.read(PROJECT, "accounts.alice.notes") == {}


def test_shape_violation_refuses_naming_the_field_leaving_state(tmp_path):
    store = AuthStore(tmp_path)
    store.write(PROJECT, "accounts.alice.notes", "agent-minted note")
    with pytest.raises(AuthInvalidError) as exc:
        store.write(PROJECT, "accounts.alice.tokens.session",
                    {"value": "abc123", "location": "side-channel"})
    assert "account.tokens.session.location" in str(exc.value)
    assert store.read(PROJECT, "accounts.alice") == {
        "origin": "agent", "notes": "agent-minted note"}


def test_agent_write_into_an_operator_account_is_refused_immutable(tmp_path):
    store = AuthStore(tmp_path)
    store.write(PROJECT, "accounts.bob", {"credentials": _credentials("bob")},
                origin="operator")
    with pytest.raises(OperatorImmutableError):
        store.write(PROJECT, "accounts.bob.notes", "agent graffito")
    assert store.read(PROJECT, "accounts.bob") == {
        "origin": "operator", "credentials": _credentials("bob")}


def test_agent_write_to_the_operator_overview_is_refused_immutable(tmp_path):
    store = AuthStore(tmp_path)
    with pytest.raises(OperatorImmutableError):
        store.write(PROJECT, "overview.notes", "agent graffito")
    assert store.read(PROJECT) == {"overview": {}, "accounts": {}}


def test_operator_write_to_the_overview_merges(tmp_path):
    store = AuthStore(tmp_path)
    store.write(PROJECT, "overview.notes", "operator ground truth", origin="operator")
    store.write(PROJECT, "overview.mechanism", "password-login", origin="operator")
    assert store.read(PROJECT, "overview") == {
        "notes": "operator ground truth", "mechanism": "password-login"}


def test_write_with_an_empty_path_or_bad_origin_is_refused(tmp_path):
    store = AuthStore(tmp_path)
    with pytest.raises(AuthInvalidError):
        store.write(PROJECT, "", "x")
    with pytest.raises(AuthInvalidError):
        store.write(PROJECT, "overview.notes", "x", origin="human")


def test_write_refuses_store_unavailable_on_a_corrupt_bucket_file(tmp_path):
    store = AuthStore(tmp_path)
    store.write(PROJECT, "overview.notes", "operator ground truth", origin="operator")
    bucket = tmp_path / PROJECT / "auth"
    (bucket / "overview.yaml").write_text("[[[not yaml\n", encoding="utf-8")
    # Reads degrade fail-open to a valid empty, never a raise ...
    assert store.read(PROJECT, "overview.notes") == {}
    # ... while a write over unreadable state refuses loudly, never corrupting.
    with pytest.raises(StoreUnavailableError):
        store.write(PROJECT, "overview.mechanism", "password-login", origin="operator")
    assert (bucket / "overview.yaml").read_text(encoding="utf-8") == "[[[not yaml\n"


# --- operator seed: wholesale replace of the operator-owned state -------------

def test_operator_seed_replaces_the_overview_wholesale(tmp_path):
    store = AuthStore(tmp_path)
    store.replace_operator_state(PROJECT, overview={"notes": "v1", "mechanism": "m1"})
    store.replace_operator_state(PROJECT, overview={"notes": "v2"})
    assert store.read(PROJECT, "overview") == {"notes": "v2"}


def test_operator_seed_stamps_accounts_operator_server_side(tmp_path):
    store = AuthStore(tmp_path)
    store.replace_operator_state(
        PROJECT, accounts={"ops": {"origin": "agent", "notes": "seeded"}})
    assert store.read(PROJECT, "accounts.ops") == {
        "origin": "operator", "notes": "seeded"}


def test_reseed_replaces_operator_accounts_but_keeps_agent_ones(tmp_path):
    store = AuthStore(tmp_path)
    store.replace_operator_state(
        PROJECT, accounts={"ops1": {"credentials": _credentials("o1")}})
    store.write(PROJECT, "accounts.agent1", {"notes": "agent-minted"})
    store.replace_operator_state(
        PROJECT, accounts={"ops2": {"credentials": _credentials("o2")}})
    assert store.read(PROJECT, "accounts") == {
        "agent1": {"origin": "agent", "notes": "agent-minted"},
        "ops2": {"origin": "operator", "credentials": _credentials("o2")},
    }


def test_absent_seed_sections_leave_state_untouched(tmp_path):
    store = AuthStore(tmp_path)
    store.replace_operator_state(PROJECT, overview={"notes": "v1"})
    store.write(PROJECT, "accounts.agent1", {"notes": "agent-minted"})
    store.replace_operator_state(
        PROJECT, accounts={"ops": {"credentials": _credentials("o")}})

    assert store.read(PROJECT, "overview") == {"notes": "v1"}
    store.replace_operator_state(PROJECT, overview={"notes": "v2"})
    assert store.read(PROJECT, "accounts.agent1") == {
        "origin": "agent", "notes": "agent-minted"}


def test_seed_name_colliding_with_a_live_agent_record_keeps_the_agent(tmp_path, caplog):
    import logging

    store = AuthStore(tmp_path)
    store.write(PROJECT, "accounts.scout", {"notes": "agent-minted"})
    with caplog.at_level(logging.WARNING, logger="polymerhus.app.auth.store"):
        store.replace_operator_state(
            PROJECT, accounts={"scout": {"notes": "operator ground truth"}})
    assert store.read(PROJECT, "accounts.scout") == {
        "origin": "agent", "notes": "agent-minted"}
    assert "scout" in caplog.text


def test_seed_shape_violation_refuses_naming_the_field(tmp_path):
    store = AuthStore(tmp_path)
    with pytest.raises(AuthInvalidError) as exc:
        store.replace_operator_state(
            PROJECT, accounts={"ops": {"credentials": {"username": "o"}}})
    assert "account.credentials" in str(exc.value)
    with pytest.raises(AuthInvalidError) as exc:
        store.replace_operator_state(PROJECT, overview={"replay_manner": "fast"})
    assert "overview.replay_manner" in str(exc.value)
    assert store.read(PROJECT) == {"overview": {}, "accounts": {}}


# --- concurrency: per-project locks, atomic writes, novelty gate --------------

def _parses(path) -> bool:
    try:
        yaml.safe_load(path.read_text(encoding="utf-8"))
        return True
    except (OSError, yaml.YAMLError):
        return False


def test_concurrent_distinct_field_writes_converge_without_loss(tmp_path):
    import threading

    store = AuthStore(tmp_path)
    errors: list = []

    def write_token(i: int):
        try:
            store.write(PROJECT, f"accounts.shared.tokens.tok{i}",
                        {"value": f"v{i}", "location": "cookie"})
        except Exception as exc:  # noqa: BLE001 - collected, never swallowed
            errors.append(exc)

    threads = [threading.Thread(target=write_token, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    tokens = store.read(PROJECT, "accounts.shared.tokens")
    assert tokens == {f"tok{i}": {"value": f"v{i}", "location": "cookie"}
                      for i in range(8)}
    bucket = tmp_path / PROJECT / "auth"
    assert _parses(bucket / "credentials.yaml")
    assert _parses(bucket / "overview.yaml")


def test_concurrent_create_race_first_writer_wins_no_fork(tmp_path):
    import threading

    store = AuthStore(tmp_path)
    outcomes: list = []

    def create(marker: str):
        try:
            store.write(PROJECT, "accounts.racer", {"notes": marker})
            outcomes.append("created")
        except DuplicateAuthError:
            outcomes.append("duplicate")

    threads = [threading.Thread(target=create, args=(f"w{i}",)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(outcomes) == ["created", "duplicate"]
    record = store.read(PROJECT, "accounts.racer")
    assert record["notes"] in ("w0", "w1") and record["origin"] == "agent"
    assert store.read(PROJECT, "accounts") == {"racer": record}
    bucket = tmp_path / PROJECT / "auth"
    assert _parses(bucket / "credentials.yaml")
    assert _parses(bucket / "overview.yaml")
