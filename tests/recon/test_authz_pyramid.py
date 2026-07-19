"""FR-AUTHZSKILL unit tier — the authorization-pyramid anatomy skill: the
inverse-pyramid per-role probe, and the STRUCTURAL AUTHORIZED_BY {role} /
AUTHENTICATED_BY {realm} typed edges it writes from per-role outcomes.

Each test names the assertion it encodes (docs/design/L1-MVP-plan.md FR-AUTHZSKILL ledger).
"""
from agent.recon.analysis import anatomy
from agent.recon.analysis.anatomy import plan_authz_probes, classify_authz, commit_anatomy


_AUTH_CTX = {
    "roles": {
        "guest": {},
        "shopper": {"realm": "credential", "cookies": [{"name": "sid", "value": "S"}]},
        "admin": {"realm": "credential", "Authorization": "Bearer ADMIN"},
    },
}


# --- AST-AUTHZ-01: one interface-B probe per role, each with that role's creds ---

def test_plan_probes_one_per_role_with_selected_creds():
    probes = plan_authz_probes("https://shop/api/Orders/7", ["guest", "shopper", "admin"],
                               _AUTH_CTX, service_slug="orders", requester_id="req-1")
    assert len(probes) == 3
    for p in probes:
        assert p.origin == "anatomy_skill" and p.skill_id == "authorization_pyramid"
        assert p.scope.service_id == "orders" and p.scope.targets == ["https://shop/api/Orders/7"]
        assert p.requester_id == "req-1" and p.scope.note  # self-describing
    by_role = {p.scope.note.split("role '")[1].rstrip("'"): p for p in probes}
    # each probe carries THAT role's SELECTED credentials
    assert by_role["admin"].scope.auth_context == {"realm": "credential", "Authorization": "Bearer ADMIN"}
    assert by_role["shopper"].scope.auth_context == {"realm": "credential", "cookies": [{"name": "sid", "value": "S"}]}
    assert by_role["guest"].scope.auth_context is None  # guest has no creds (empty -> None)


# --- AST-AUTHZ-02: authorised roles -> typed AUTHORIZED_BY {role} edges ---

def test_authorized_roles_become_typed_role_edges():
    res = classify_authz("delete-order", {"guest": False, "shopper": False, "admin": True},
                         service_slug="orders")
    authz_edges = [e for e in res.system_edges if e.rel == "AUTHORIZED_BY"]
    assert len(authz_edges) == 1  # only the authorised role
    e = authz_edges[0]
    assert e.role == "admin"  # the role rides an edge PROP (typed), not prose
    assert e.system_kind == "AuthorizationSystem" and e.service_slug == "orders"
    # denied roles get NO edge
    assert {e.role for e in authz_edges} == {"admin"}


def test_multiple_authorized_roles_each_get_an_edge():
    res = classify_authz("view-order", {"shopper": True, "admin": True, "guest": False},
                         service_slug="orders")
    roles = sorted(e.role for e in res.system_edges if e.rel == "AUTHORIZED_BY")
    assert roles == ["admin", "shopper"]


# --- AST-AUTHZ-03: realms -> AUTHENTICATED_BY {realm} edges (mechanism separate) ---

def test_realms_become_authenticated_by_edges():
    res = classify_authz("refund", {"support": True, "admin": True},
                         service_slug="support-desk",
                         role_realms={"support": "credential", "admin": "idp"})
    authn = [e for e in res.system_edges if e.rel == "AUTHENTICATED_BY"]
    assert {e.realm for e in authn} == {"credential", "idp"}  # one per distinct realm
    assert all(e.system_kind == "AuthenticationMechanism" for e in authn)  # mechanism = System
    # policy (role) and mechanism (realm) are on SEPARATE edges/systems (L1D-5)
    authz = [e for e in res.system_edges if e.rel == "AUTHORIZED_BY"]
    assert all(e.system_kind == "AuthorizationSystem" for e in authz)


# --- AST-AUTHZ-04: authz_model classification + evidence ---

def test_authz_model_classification_and_evidence():
    # some allowed, some denied -> role-restricted
    r1 = classify_authz("pay", {"guest": False, "shopper": True}, service_slug="checkout")
    c = r1.classifications[0]
    assert c.slot == "authz_model" and c.value == "role-restricted"
    assert c.confidence in ("High", "Medium", "Low") and "authorized=" in c.evidence
    # evidence Observation records the authorised vs denied set verbatim
    assert r1.observations and r1.observations[0].macro_kind == "authorization_pyramid"
    assert "shopper" in r1.observations[0].evidence

    # every probed role allowed -> unrestricted; none -> locked
    assert classify_authz("x", {"guest": True, "shopper": True}, service_slug="s").classifications[0].value == "unrestricted"
    assert classify_authz("x", {"guest": False, "admin": False}, service_slug="s").classifications[0].value == "locked"


# --- AST-AUTHZ-05: commit writes the edges via l1_curator sole-writer, fail-open ---

def test_commit_writes_system_edges_fail_open():
    res = classify_authz("delete", {"admin": True, "shopper": False}, service_slug="orders",
                         role_realms={"admin": "credential"})
    captured = {}

    def fake_edge_fn(system_edges, project_id):
        captured["edges"] = system_edges
        captured["project_id"] = project_id
        return {"system_edges": len(system_edges)}

    written = commit_anatomy(res, "proj-1", "orders",
                             curate_fn=lambda s, sys, p: (len(s), len(sys)),
                             observe_fn=lambda o, p: (0, len(o)),
                             edge_fn=fake_edge_fn)
    # AUTHORIZED_BY(admin) + AUTHENTICATED_BY(credential) written via the sole-writer
    rels = sorted(e.rel for e in captured["edges"])
    assert rels == ["AUTHENTICATED_BY", "AUTHORIZED_BY"]
    assert written["system_edges"] == 2

    # a write error degrades per-leg (fail-open), never raises
    def boom(system_edges, project_id):
        raise RuntimeError("neo4j down")

    written2 = commit_anatomy(res, "proj-1", "orders",
                              curate_fn=lambda s, sys, p: (len(s), len(sys)),
                              observe_fn=lambda o, p: (0, len(o)),
                              edge_fn=boom)
    assert written2["system_edges"] == 0  # degraded, no crash
    assert written2["classifications"] == 1  # other legs still ran


# --- AST-AUTHZ-06: the SKILL.md encodes the inverse-pyramid discipline ---

def test_authz_skill_encodes_inverse_pyramid():
    from agent.recon import skills
    skills.clear_cache()
    text = skills.skill_for("analysis/anatomy/authorization-pyramid")
    assert not text.startswith("---")  # frontmatter stripped
    low = text.lower()
    assert "inverse" in low and "pyramid" in low  # the probe discipline
    assert "different roles" in low or "per role" in low
    assert "AUTHORIZED_BY" in text and "AUTHENTICATED_BY" in text  # typed edges
    assert "auth_context" in low  # carries creds per role
    assert "structural" in low or "not prose" in low or "typed" in low
    skills.clear_cache()
