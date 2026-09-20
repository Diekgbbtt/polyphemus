"""T3 (#229): the one shared read/write `auth_store` agent tool.

Unit tier, CODING_STANDARD sections 5/6/8/10: tests invoke the REAL tool
object (built by `build_auth_store_tool` over an explicit-root temp store);
every literal below comes from the #220 spec shapes and the ticket rules, not
from the implementation - the tests pin the contract, the module honours it.
Pilot posture throughout: state is seeded via the store seam, round-tripped
via the tool; no production seam binding is touched here.
"""
from polymerhus.app.auth.store import AuthStore
from polymerhus.app.auth.tool import AUTH_STORE_CONTRACT, build_auth_store_tool

PROJECT = "proj-auth-tool-1"


def _seeded_store(tmp_path):
    """Pilot seed via the store seam: operator overview + one agent account."""
    store = AuthStore(tmp_path)
    store.write(PROJECT, "overview.notes", "operator ground truth",
                origin="operator")
    store.write(PROJECT, "accounts.alice.notes", "agent-minted note")
    return store


# --- factory: binds the project once, agents never pass identity -------------

def test_tool_name_is_auth_store(tmp_path):
    assert build_auth_store_tool(PROJECT, AuthStore(tmp_path)).name == "auth_store"


def test_tool_takes_no_project_identity_argument(tmp_path):
    tool = build_auth_store_tool(PROJECT, AuthStore(tmp_path))
    assert "project_id" not in tool.args
    assert set(tool.args) == {"command", "path", "value"}


def test_factory_binds_the_project_id_once(tmp_path):
    store = _seeded_store(tmp_path)
    other = AuthStore(tmp_path)
    other.write("proj-other", "accounts.bob.notes", "sibling secret")
    tool = build_auth_store_tool(PROJECT, store)
    out = tool.invoke({"command": "read", "path": ""})
    assert out["ok"] is True
    assert out["value"]["accounts"]["alice"]["notes"] == "agent-minted note"
    assert "bob" not in out["value"]["accounts"]


def test_default_store_is_the_production_auth_store():
    tool = build_auth_store_tool(PROJECT)
    assert tool.name == "auth_store"
    assert set(tool.args) == {"command", "path", "value"}


def test_factory_defaults_the_project_to_the_control_plane(tmp_path, monkeypatch):
    """Tool-owned scoping: with no explicit project the tool binds the
    deployment's single project (`config.PROJECT_ID`), so no agent harness
    threads identity."""
    from polymerhus.app.config import config

    monkeypatch.setattr(config, "PROJECT_ID", "proj-cfg")
    tool = build_auth_store_tool(store=AuthStore(tmp_path))
    out = tool.invoke(
        {
            "command": "write",
            "path": "accounts.bob",
            "value": {
                "credentials": {
                    "username": "u",
                    "password": "p",
                    "login_url": "https://t/login",
                }
            },
        }
    )
    assert out["ok"] is True
    assert (tmp_path / "proj-cfg" / "auth" / "credentials.yaml").is_file()


# --- contract: model, schema, and rules ride the description ------------------

def test_description_carries_the_full_contract(tmp_path):
    desc = build_auth_store_tool(PROJECT, AuthStore(tmp_path)).description
    assert desc == AUTH_STORE_CONTRACT or AUTH_STORE_CONTRACT in desc


def test_contract_teaches_the_domain_model():
    for marker in ("auth store", "account record", "operator section",
                   "agent section", "technical condition",
                   "browser-profile reference", "concrete snapshot",
                   "operator seed", "procedure label"):
        assert marker in AUTH_STORE_CONTRACT, f"contract missing {marker!r}"


def test_contract_carries_the_account_identity_rule():
    """The account NAME carries the credential identity, so a second name for
    the same identity is a fork, not a second account (the #237 e2e defect:
    sign-up and sign-in forked two accounts sharing one username)."""
    for marker in ("ACCOUNT IDENTITY", "<email>-<minting_context>",
                   "minting context", "never the procedure",
                   "not an identity axis", "roles.*.username", "new ROLE"):
        assert marker in AUTH_STORE_CONTRACT, f"contract missing {marker!r}"


def test_contract_carries_the_overall_schema():
    for marker in ("login_endpoint", "required_headers", "mechanism",
                   "defences", "fingerprinting", "technical_conditions",
                   "credentials", "tokens", "steel", "snapshot",
                   "procedure", "origin", "roles", "default_role"):
        assert marker in AUTH_STORE_CONTRACT, f"contract missing {marker!r}"


def test_contract_carries_the_read_write_rules():
    for marker in ("read", "write", "valid empty", "single-field",
                   "operator_immutable", "duplicate_auth", "duplicate_identity",
                   "auth_invalid", "store_unavailable"):
        assert marker in AUTH_STORE_CONTRACT, f"contract missing {marker!r}"


def test_each_parameter_documents_its_role(tmp_path):
    args = build_auth_store_tool(PROJECT, AuthStore(tmp_path)).args
    assert "read" in args["command"]["description"]
    assert "write" in args["command"]["description"]
    assert "full state" in args["path"]["description"]
    assert "accounts.alice" in args["path"]["description"]
    assert "null" in args["value"]["description"].lower()
    assert "single-field" in args["value"]["description"].lower()


# --- reads: full state, narrow paths, missing paths are valid-empty -----------

def test_read_empty_path_returns_the_full_state(tmp_path):
    tool = build_auth_store_tool(PROJECT, _seeded_store(tmp_path))
    assert tool.invoke({"command": "read", "path": ""}) == {
        "ok": True, "command": "read", "path": "",
        "value": {"overview": {"notes": "operator ground truth"},
                  "accounts": {"alice": {"origin": "agent",
                                         "notes": "agent-minted note"}}},
    }


def test_read_narrow_path_projects_the_field(tmp_path):
    tool = build_auth_store_tool(PROJECT, _seeded_store(tmp_path))
    out = tool.invoke({"command": "read", "path": "accounts.alice"})
    assert out == {"ok": True, "command": "read", "path": "accounts.alice",
                   "value": {"origin": "agent", "notes": "agent-minted note"}}


def test_read_scalar_leaf_returns_the_scalar(tmp_path):
    tool = build_auth_store_tool(PROJECT, _seeded_store(tmp_path))
    out = tool.invoke({"command": "read", "path": "overview.notes"})
    assert out == {"ok": True, "command": "read", "path": "overview.notes",
                   "value": "operator ground truth"}


def test_read_missing_path_is_a_valid_empty(tmp_path):
    tool = build_auth_store_tool(PROJECT, _seeded_store(tmp_path))
    out = tool.invoke({"command": "read", "path": "accounts.nobody"})
    assert out == {"ok": True, "command": "read",
                   "path": "accounts.nobody", "value": {}}


def test_read_of_an_unseeded_project_is_a_valid_empty(tmp_path):
    tool = build_auth_store_tool(PROJECT, AuthStore(tmp_path))
    out = tool.invoke({"command": "read", "path": ""})
    assert out == {"ok": True, "command": "read", "path": "",
                   "value": {"overview": {}, "accounts": {}}}


def test_unknown_command_is_an_auth_invalid_envelope(tmp_path):
    tool = build_auth_store_tool(PROJECT, _seeded_store(tmp_path))
    out = tool.invoke({"command": "drop", "path": ""})
    assert out["ok"] is False
    assert out["error"] == "auth_invalid"
    assert "command" in out["detail"]


# --- writes: single-field merges, null deletes, creates, coded refusals ------

def test_write_single_field_merges_and_round_trips(tmp_path):
    tool = build_auth_store_tool(PROJECT, _seeded_store(tmp_path))
    out = tool.invoke({"command": "write", "path": "accounts.alice.tokens.session",
                       "value": {"value": "tok-1", "location": "header"}})
    assert out == {"ok": True, "command": "write",
                   "path": "accounts.alice.tokens.session",
                   "value": {"value": "tok-1", "location": "header"}}
    assert tool.invoke({"command": "read",
                        "path": "accounts.alice.tokens.session"})["value"] == {
        "value": "tok-1", "location": "header"}
    assert tool.invoke({"command": "read",
                        "path": "accounts.alice.notes"})["value"] == "agent-minted note"


def test_write_null_removes_an_optional_field(tmp_path):
    tool = build_auth_store_tool(PROJECT, _seeded_store(tmp_path))
    out = tool.invoke({"command": "write", "path": "accounts.alice.notes",
                       "value": None})
    assert out["ok"] is True
    assert tool.invoke({"command": "read",
                        "path": "accounts.alice.notes"})["value"] == {}


def test_write_record_mapping_at_a_fresh_name_creates(tmp_path):
    tool = build_auth_store_tool(PROJECT, _seeded_store(tmp_path))
    out = tool.invoke({"command": "write", "path": "accounts.bob",
                       "value": {"notes": "fresh test account",
                                 "procedure": "password-login"}})
    assert out["ok"] is True
    assert tool.invoke({"command": "read",
                        "path": "accounts.bob"})["value"] == {
        "origin": "agent", "notes": "fresh test account",
        "procedure": "password-login"}


def test_write_to_the_overview_refuses_operator_immutable(tmp_path):
    tool = build_auth_store_tool(PROJECT, _seeded_store(tmp_path))
    out = tool.invoke({"command": "write", "path": "overview.notes",
                       "value": "agent overwrite"})
    assert out["ok"] is False
    assert out["error"] == "operator_immutable"
    assert tool.invoke({"command": "read",
                        "path": "overview.notes"})["value"] == "operator ground truth"


def test_write_to_an_operator_stamped_account_refuses(tmp_path):
    store = AuthStore(tmp_path)
    store.replace_operator_state(PROJECT, accounts={"root": {"notes": "seeded"}})
    tool = build_auth_store_tool(PROJECT, store)
    out = tool.invoke({"command": "write", "path": "accounts.root.notes",
                       "value": "agent overwrite"})
    assert out["ok"] is False
    assert out["error"] == "operator_immutable"


def test_create_of_a_known_name_signals_duplicate_auth(tmp_path):
    tool = build_auth_store_tool(PROJECT, _seeded_store(tmp_path))
    out = tool.invoke({"command": "write", "path": "accounts.alice",
                       "value": {"notes": "second record"}})
    assert out["ok"] is False
    assert out["error"] == "duplicate_auth"
    assert "alice" in out["detail"]


def test_create_sharing_a_credential_identity_signals_duplicate_identity(tmp_path):
    """A second account for an existing credential identity refuses with the
    identity envelope (the #237 e2e fork): the repair is a role, not a fork."""
    creds = {"username": "u@example.com", "password": "p",
             "login_url": "https://t/login"}
    store = AuthStore(tmp_path)
    store.write(PROJECT, "accounts.u-signup", {"credentials": creds})
    tool = build_auth_store_tool(PROJECT, store)
    out = tool.invoke({"command": "write", "path": "accounts.u-signin",
                       "value": {"credentials": creds}})
    assert out["ok"] is False
    assert out["error"] == "duplicate_identity"
    assert "u@example.com" in out["detail"]


def test_shape_violation_is_auth_invalid_naming_the_field(tmp_path):
    tool = build_auth_store_tool(PROJECT, _seeded_store(tmp_path))
    out = tool.invoke({"command": "write", "path": "accounts.bob.tokens.bad",
                       "value": {"value": "tok-x", "location": "pocket"}})
    assert out["ok"] is False
    assert out["error"] == "auth_invalid"
    assert "account.tokens.bad.location" in out["detail"]


def test_write_with_an_empty_path_is_auth_invalid(tmp_path):
    tool = build_auth_store_tool(PROJECT, _seeded_store(tmp_path))
    out = tool.invoke({"command": "write", "path": ""})
    assert out["ok"] is False
    assert out["error"] == "auth_invalid"
    assert "path" in out["detail"]


def test_degraded_store_is_store_unavailable(tmp_path):
    store = AuthStore(tmp_path)
    bucket = tmp_path / PROJECT / "auth"
    bucket.mkdir(parents=True)
    (bucket / "credentials.yaml").write_text("{{{not yaml", encoding="utf-8")
    tool = build_auth_store_tool(PROJECT, store)
    out = tool.invoke({"command": "write", "path": "accounts.alice.notes",
                       "value": "lost write"})
    assert out["ok"] is False
    assert out["error"] == "store_unavailable"


def test_envelopes_are_json_serializable(tmp_path):
    import json

    tool = build_auth_store_tool(PROJECT, _seeded_store(tmp_path))
    for call in ({"command": "read", "path": ""},
                 {"command": "read", "path": "accounts.nobody"},
                 {"command": "write", "path": "accounts.alice.notes",
                  "value": "fresh note"},
                 {"command": "write", "path": "overview.notes",
                  "value": "refused"},
                 {"command": "write", "path": "accounts.alice",
                  "value": {"notes": "duplicate"}}):
        json.dumps(tool.invoke(call))
