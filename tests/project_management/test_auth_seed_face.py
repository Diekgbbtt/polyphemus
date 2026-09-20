"""#230 (T4): the operator seed face over the auth store - use-case + endpoint seams.

Use-case tests fake the pg gateway (monkeypatched `project_exists`, the
`test_rest_api.py` posture) and the store seam (a recording FakeStore passed
as `store=`); endpoint tests run real HTTP against a real `AuthStore` rooted
at `tmp_path` (the T2 explicit-root seam), so the seed-then-read round trip,
the wholesale-replace semantics, and the agent-preservation guarantee are all
exercised on disk without any live database.
"""
import copy

import pytest
from fastapi.testclient import TestClient

from polymerhus.app.auth.records import AuthInvalidError
from polymerhus.app.auth.store import AuthStore
from polymerhus.app.clients import pg
from polymerhus.app.main import app
from polymerhus.project_management import repository
from polymerhus.project_management.repository import (
    ProjectNotFound,
    read_project_auth,
    seed_project_auth,
)

client = TestClient(app)

OVERVIEW = {
    "login_endpoint": "https://app.example.com/login",
    "mechanism": "password",
    "notes": "operator ground truth",
}

OPERATOR_ACCOUNT = {
    "credentials": {
        "username": "op@example.com",
        "password": "pw",
        "login_url": "https://app.example.com/login",
    }
}

AGENT_ACCOUNT = {
    "credentials": {
        "username": "agent-minted",
        "password": "pw",
        "login_url": "https://app.example.com/login",
    }
}


class FakeStore:
    """Recording stand-in for `AuthStore`: captures seed/read calls and replays
    a canned state. `seed_error` fails the next seed like the T1 seam would."""

    def __init__(self):
        self.seeds = []
        self.reads = []
        self.state = {"overview": {}, "accounts": {}}
        self.seed_error = None

    def replace_operator_state(self, project_id, *, overview=None, accounts=None):
        if self.seed_error is not None:
            raise self.seed_error
        self.seeds.append((project_id, overview, accounts))

    def read(self, project_id, path=""):
        self.reads.append((project_id, path))
        return copy.deepcopy(self.state)


def _live_pg(monkeypatch):
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)


def _tmp_store(monkeypatch, tmp_path):
    """Point the repository's lazily-resolved production store at `tmp_path`,
    so endpoint tests exercise the real store on disk."""
    monkeypatch.setattr(
        repository, "_default_auth_store", lambda: AuthStore(root_dir=tmp_path)
    )
    return AuthStore(root_dir=tmp_path)


# --- use-case seam: seed -------------------------------------------------------


def test_seed_delegates_present_sections_to_store(monkeypatch):
    _live_pg(monkeypatch)
    fake = FakeStore()

    assert seed_project_auth("p1", overview=OVERVIEW, accounts={"op": OPERATOR_ACCOUNT},
                             store=fake) is None
    assert fake.seeds == [("p1", OVERVIEW, {"op": OPERATOR_ACCOUNT})]


def test_seed_absent_sections_pass_none_through(monkeypatch):
    _live_pg(monkeypatch)
    fake = FakeStore()

    seed_project_auth("p1", overview=OVERVIEW, store=fake)
    assert fake.seeds == [("p1", OVERVIEW, None)]


def test_seed_unknown_project_raises_before_touching_store(monkeypatch):
    monkeypatch.setattr(pg, "project_exists", lambda pid: False)
    fake = FakeStore()

    with pytest.raises(ProjectNotFound):
        seed_project_auth("nope", overview=OVERVIEW, store=fake)
    assert fake.seeds == []


def test_seed_shape_violation_propagates_naming_the_field(monkeypatch):
    _live_pg(monkeypatch)
    fake = FakeStore()
    fake.seed_error = AuthInvalidError("overview.bogus", "is not a known overview field")

    with pytest.raises(ValueError, match="overview.bogus"):
        seed_project_auth("p1", overview={"bogus": 1}, store=fake)
    assert fake.seeds == []


# --- use-case seam: read -------------------------------------------------------


def test_read_returns_full_state(monkeypatch):
    _live_pg(monkeypatch)
    fake = FakeStore()
    fake.state = {"overview": OVERVIEW, "accounts": {"op": OPERATOR_ACCOUNT}}

    assert read_project_auth("p1", store=fake) == fake.state
    assert fake.reads == [("p1", "")]


def test_read_unknown_project_raises(monkeypatch):
    monkeypatch.setattr(pg, "project_exists", lambda pid: False)

    with pytest.raises(ProjectNotFound):
        read_project_auth("nope", store=FakeStore())


def test_read_unseeded_empty_state_is_valid(monkeypatch):
    _live_pg(monkeypatch)

    assert read_project_auth("p1", store=FakeStore()) == {"overview": {}, "accounts": {}}


# --- endpoint seam -------------------------------------------------------------


def test_put_seed_unknown_project_404(monkeypatch):
    monkeypatch.setattr(pg, "project_exists", lambda pid: False)

    resp = client.put("/projects/nope/auth", json={"overview": OVERVIEW})

    assert resp.status_code == 404


def test_put_seed_then_get_round_trip(monkeypatch, tmp_path):
    _live_pg(monkeypatch)
    _tmp_store(monkeypatch, tmp_path)

    put = client.put("/projects/p1/auth",
                     json={"overview": OVERVIEW, "accounts": {"op": OPERATOR_ACCOUNT}})
    assert put.status_code == 200
    assert put.json() == {"ok": True}

    got = client.get("/projects/p1/auth")
    assert got.status_code == 200
    body = got.json()
    assert body["overview"] == OVERVIEW
    # seeded accounts are stamped operator server-side
    assert body["accounts"]["op"]["origin"] == "operator"
    assert body["accounts"]["op"]["credentials"]["username"] == "op@example.com"


def test_put_reseed_replaces_wholesale_absent_sections_untouched(monkeypatch, tmp_path):
    _live_pg(monkeypatch)
    _tmp_store(monkeypatch, tmp_path)
    client.put("/projects/p1/auth",
               json={"overview": OVERVIEW, "accounts": {"op": OPERATOR_ACCOUNT}})

    # accounts-only reseed: the operator set is replaced wholesale (no 409),
    # the absent overview section is untouched
    reseed = client.put("/projects/p1/auth", json={"accounts": {"op2": OPERATOR_ACCOUNT}})
    assert reseed.status_code == 200
    assert reseed.json() == {"ok": True}
    body = client.get("/projects/p1/auth").json()
    assert set(body["accounts"]) == {"op2"}
    assert body["overview"] == OVERVIEW

    # overview-only reseed: accounts untouched
    client.put("/projects/p1/auth", json={"overview": {**OVERVIEW, "notes": "v2"}})
    body = client.get("/projects/p1/auth").json()
    assert set(body["accounts"]) == {"op2"}
    assert body["overview"]["notes"] == "v2"


def test_put_reseed_never_touches_agent_accounts(monkeypatch, tmp_path):
    _live_pg(monkeypatch)
    store = _tmp_store(monkeypatch, tmp_path)
    client.put("/projects/p1/auth", json={"accounts": {"op": OPERATOR_ACCOUNT}})
    store.write("p1", "accounts.agentbot", AGENT_ACCOUNT, origin="agent")

    # reseed replaces the operator account's values AND tries to collide with
    # the live agent name: the agent record must survive exactly as minted
    # (the T2 warn-drop ruling), the operator entry is dropped
    reseed = client.put("/projects/p1/auth", json={"accounts": {
        "op": {"credentials": {**OPERATOR_ACCOUNT["credentials"], "password": "new"}},
        "agentbot": OPERATOR_ACCOUNT,
    }})
    assert reseed.status_code == 200
    body = client.get("/projects/p1/auth").json()
    assert body["accounts"]["op"]["credentials"]["password"] == "new"
    assert body["accounts"]["agentbot"]["origin"] == "agent"
    assert body["accounts"]["agentbot"]["credentials"]["username"] == "agent-minted"


def test_put_shape_violation_400_envelope_names_field(monkeypatch, tmp_path):
    _live_pg(monkeypatch)
    _tmp_store(monkeypatch, tmp_path)

    resp = client.put("/projects/p1/auth", json={"overview": {"bogus": 1}})

    assert resp.status_code == 400
    body = resp.json()
    assert body["ok"] is False
    assert body["error"] == "auth_invalid"
    assert "overview.bogus" in body["detail"]


def test_put_shape_violation_writes_nothing(monkeypatch, tmp_path):
    _live_pg(monkeypatch)
    _tmp_store(monkeypatch, tmp_path)
    client.put("/projects/p1/auth",
               json={"overview": OVERVIEW, "accounts": {"op": OPERATOR_ACCOUNT}})

    # both sections validate BEFORE any write: the bad accounts section must
    # not wipe the good overview that rode the same body
    resp = client.put("/projects/p1/auth", json={
        "overview": {**OVERVIEW, "notes": "should-not-land"},
        "accounts": {"bad": {"credentials": {"username": "x"}}},
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "auth_invalid"
    body = client.get("/projects/p1/auth").json()
    assert body["overview"] == OVERVIEW
    assert set(body["accounts"]) == {"op"}


def test_put_identity_collision_is_a_500_duplicate_identity(monkeypatch, tmp_path):
    """A seed that forks one credential identity is a HARD contract breach
    (D220-11): 500 `duplicate_identity`, nothing lands."""
    _live_pg(monkeypatch)
    _tmp_store(monkeypatch, tmp_path)
    creds = {"username": "u@example.com", "password": "pw",
             "login_url": "https://app.example.com/login"}

    resp = client.put("/projects/p1/auth", json={
        "accounts": {"u-signup": {"credentials": creds, "procedure": "sign-up"},
                     "u-signin": {"credentials": creds, "procedure": "sign-in"}},
    })

    assert resp.status_code == 500
    body = resp.json()
    assert body["ok"] is False
    assert body["error"] == "duplicate_identity"
    assert "u@example.com" in body["detail"]
    assert client.get("/projects/p1/auth").json() == {"overview": {}, "accounts": {}}


def test_put_seed_colliding_with_a_kept_agent_identity_is_a_500(monkeypatch, tmp_path):
    _live_pg(monkeypatch)
    store = _tmp_store(monkeypatch, tmp_path)
    store.write("p1", "accounts.agentbot", {"credentials": {
        "username": "agent@example.com", "password": "pw",
        "login_url": "https://app.example.com/login"}})

    resp = client.put("/projects/p1/auth", json={"accounts": {"op": {"credentials": {
        "username": "agent@example.com", "password": "pw",
        "login_url": "https://app.example.com/login"}}}})

    assert resp.status_code == 500
    assert resp.json()["error"] == "duplicate_identity"
    assert set(client.get("/projects/p1/auth").json()["accounts"]) == {"agentbot"}


def test_put_accounts_not_object_400(monkeypatch, tmp_path):
    _live_pg(monkeypatch)
    _tmp_store(monkeypatch, tmp_path)

    resp = client.put("/projects/p1/auth", json={"accounts": ["not", "an", "object"]})

    assert resp.status_code == 400
    assert resp.json()["error"] == "auth_invalid"
    assert "accounts" in resp.json()["detail"]


def test_get_unknown_project_404(monkeypatch):
    monkeypatch.setattr(pg, "project_exists", lambda pid: False)

    assert client.get("/projects/nope/auth").status_code == 404


def test_get_unseeded_project_returns_empty_state(monkeypatch, tmp_path):
    _live_pg(monkeypatch)
    _tmp_store(monkeypatch, tmp_path)

    resp = client.get("/projects/p1/auth")

    assert resp.status_code == 200
    assert resp.json() == {"overview": {}, "accounts": {}}


# --- #237: the anti-bot + HTTP-client replayability facts round-trip ---


def test_put_seed_round_trips_the_anti_bot_and_replayability_facts(monkeypatch, tmp_path):
    _live_pg(monkeypatch)
    _tmp_store(monkeypatch, tmp_path)
    overview = {
        **OVERVIEW,
        "anti-bot": "akamai_v3",
        "http-client-replayability": False,
    }

    put = client.put("/projects/p1/auth", json={"overview": overview})
    assert put.status_code == 200

    body = client.get("/projects/p1/auth").json()
    assert body["overview"]["anti-bot"] == "akamai_v3"
    assert body["overview"]["http-client-replayability"] is False


def test_put_absent_replayability_reads_back_absent_never_false(monkeypatch, tmp_path):
    _live_pg(monkeypatch)
    _tmp_store(monkeypatch, tmp_path)

    client.put("/projects/p1/auth", json={"overview": {"anti-bot": None}})

    body = client.get("/projects/p1/auth").json()
    assert body["overview"]["anti-bot"] is None
    assert "http-client-replayability" not in body["overview"]


def test_put_bad_replayability_type_400_names_the_field(monkeypatch, tmp_path):
    _live_pg(monkeypatch)
    _tmp_store(monkeypatch, tmp_path)

    resp = client.put(
        "/projects/p1/auth", json={"overview": {"http-client-replayability": "true"}}
    )

    assert resp.status_code == 400
    body = resp.json()
    assert body["ok"] is False
    assert body["error"] == "auth_invalid"
    assert "overview.http-client-replayability" in body["detail"]
