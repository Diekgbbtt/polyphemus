"""The white-jotter-001 ground-truth service fixture.

Source of truth:
`/Users/diekgbbtt/.local/share/polymerhus/vuln-groundtruth/white-jotter/white-jotter-001/`
(`l1-profile.md`, `l0-surface.yaml`, `symptoms.md`) and
`/Users/diekgbbtt/WebExploitBench/white-jotter/challenge.json`.

The sample is the weak/default-credentials chain on `Service:account-sign-in`:
`POST /api/login` with `admin`/`123` returns `code:200`; a wrong password
returns `code:400`. The local `http-e2e-target` serves that surface
(`tests/e2e/http_e2e_target.py`), and this module seeds the matching real L1
graph so the modeller's projection, the intake order, and the hunter's loop
range over the ground-truth unit rather than a synthetic stand-in.

The service contract and the edge/data vocabulary are copied from the ground
truth profile; only the base URL is the local target (`WHITE_JOTTER_TARGET_BASE`,
default `http://172.28.0.20`, the `http-e2e-target` container on the shared
network).
"""
from __future__ import annotations

import os

TARGET_BASE = os.environ.get("WHITE_JOTTER_TARGET_BASE", "http://172.28.0.20")
SERVICE_SLUG = "account-sign-in"
SERVICE_CONTRACT = (
    "Authenticate a username and password against the user store; issue a "
    "Shiro subject session and a rememberMe cookie"
)
BUSINESS_FUNCTION = (
    "Account sign-in: verify the caller's credentials and start their session"
)

SYSTEMS = (
    ("AuthenticationMechanism", "__singleton__",
     "Apache Shiro authenticates a username and password against the user store "
     "with salted password hashing"),
    ("RESTApi", "account-sign-in::rest",
     "The JSON {code, message, result} response paradigm over the sign-in routes"),
    ("WebPresentation", "account-sign-in::login-shell",
     "The SPA sign-in page cluster that issues the login XHR"),
)

EDGES = (
    ("AuthenticationMechanism", "__singleton__", "AUTHENTICATED_BY"),
    ("RESTApi", "account-sign-in::rest", "EXPOSED_VIA"),
    ("WebPresentation", "account-sign-in::login-shell", "EXPOSED_VIA"),
)

DATA_ITEMS = (
    ("user_credential", "credential", "high", ["password", "username"],
     "The caller-supplied username and password verified against the seeded user table"),
    ("authenticated_session", "session", "high", ["principal", "remember_me"],
     "The Shiro subject identity kept in the servlet session and persisted through the rememberMe cookie"),
)

DATA_FLOWS = (
    ("user_credential", "CONSUMES"),
    ("authenticated_session", "PRODUCES"),
)

ENDPOINTS = (
    ("POST", "/api/login"),
    ("GET", "/api/authentication"),
    ("GET", "/api/logout"),
    ("GET", "/api/admin/user"),
)


def load_white_jotter_l1(project_id: str, session, *, baseurl: str | None = None) -> dict:
    """MERGE the white-jotter-001 L1 under ``project_id`` (idempotent).

    Writes the real `L1Service`, the three `L1System`s, the typed
    `AUTHENTICATED_BY`/`EXPOSED_VIA` edges, the two `L1DataItem`s and their
    `CONSUMES`/`PRODUCES` flows, and the four L0 `Endpoint`s aggregated by the
    service. Returns the exact seeded counts.
    """
    base = (baseurl or TARGET_BASE).rstrip("/")
    session.run(
        "MERGE (s:L1TestableUnit:L1Service {business_function_slug: $slug, "
        "project_id: $p}) "
        "SET s.exposure = 'public', s.service_contract = $contract, "
        "s.business_function = $business_function, s.api_paradigm = 'rest', "
        "s.auth_methods = ['password']",
        slug=SERVICE_SLUG, p=project_id, contract=SERVICE_CONTRACT,
        business_function=BUSINESS_FUNCTION,
    )
    for kind, discriminator, description in SYSTEMS:
        session.run(
            "MERGE (sy:L1TestableUnit:L1System {kind: $kind, "
            "discriminator: $disc, project_id: $p}) "
            "SET sy.exposure = 'public', sy.description = $description",
            kind=kind, disc=discriminator, p=project_id, description=description,
        )
    for kind, discriminator, rel in EDGES:
        session.run(
            "MATCH (s:L1Service {business_function_slug: $slug, project_id: $p}) "
            "MATCH (sy:L1System {kind: $kind, discriminator: $disc, project_id: $p}) "
            f"MERGE (s)-[:{rel}]->(sy)",
            slug=SERVICE_SLUG, kind=kind, disc=discriminator, p=project_id,
        )
    for item_key, item_type, sensitivity, fields, notes in DATA_ITEMS:
        session.run(
            "MERGE (d:L1DataItem {item_key: $key, project_id: $p}) "
            "SET d.type = $type, d.sensitivity = $sensitivity, "
            "d.fields = $fields, d.notes = $notes",
            key=item_key, p=project_id, type=item_type,
            sensitivity=sensitivity, fields=fields, notes=notes,
        )
    for item_key, rel in DATA_FLOWS:
        session.run(
            "MATCH (s:L1Service {business_function_slug: $slug, project_id: $p}) "
            "MATCH (d:L1DataItem {item_key: $key, project_id: $p}) "
            f"MERGE (s)-[:{rel}]->(d)",
            slug=SERVICE_SLUG, key=item_key, p=project_id,
        )
    for method, path in ENDPOINTS:
        session.run(
            "MERGE (e:Endpoint {path: $path, method: $method, baseurl: $base, "
            "project_id: $p})",
            path=path, method=method, base=base, p=project_id,
        )
        session.run(
            "MATCH (s:L1Service {business_function_slug: $slug, project_id: $p}) "
            "MATCH (e:Endpoint {path: $path, method: $method, baseurl: $base, "
            "project_id: $p}) "
            "MERGE (s)-[:AGGREGATES {status: 'committed'}]->(e)",
            slug=SERVICE_SLUG, path=path, method=method, base=base, p=project_id,
        )
    return {
        "service": SERVICE_SLUG,
        "systems": len(SYSTEMS),
        "edges": len(EDGES),
        "data_items": len(DATA_ITEMS),
        "data_flows": len(DATA_FLOWS),
        "endpoints": len(ENDPOINTS),
        "baseurl": base,
    }
