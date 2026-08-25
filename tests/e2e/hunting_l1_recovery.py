"""Recover the previous project's L1 abstraction from Langfuse and
re-materialize it into the live neo4j graph (candidates-rewrite e2e).

Caveat B1/B4: prior project data in neo4j/postgres was deleted, so the ONLY
source for the previous project's L1 abstraction is Langfuse. The mechanism
typist emits a ``typist-systems-and-edges`` trace (trace name on the run's
session) whose output carries the recovered Systems + Service->System edges:

    {"systems": [{"kind": "RESTApi", "discriminator": "__singleton__"}, ...],
     "edges":   [{"service_slug": "account", "kind": "RESTApi",
                  "discriminator": "__singleton__", "rel": "EXPOSED_VIA"}, ...]}

This module fetches that trace from Langfuse, maps it onto the L1TestableUnit
schema (L1Service/L1System + EXPOSED_VIA/IDENTIFIED_BY/AUTHENTICATED_BY typed
edges), re-materializes it under a project_id, and returns the recovered model.
It is the L1 *fixture* for the walkthrough tier: giving the recovered project's
id grants the hunting orchestrator a live graph surface that matches the
operator's prior L1, recovered only from Langfuse.
"""
from __future__ import annotations

import os
from typing import Any

PRIOR_TRACE_NAME = "typist-systems-and-edges"


def langfuse_env() -> dict[str, str]:
    """The Langfuse credentials/host from the environment (fail loudly when a
    key is missing so the fixture cannot silently recover nothing)."""
    import os as _os

    host = _os.environ.get("LANGFUSE_HOST") or _os.environ.get("LANGFUSE_BASE_URL")
    pk = _os.environ.get("LANGFUSE_PUBLIC_KEY")
    sk = _os.environ.get("LANGFUSE_SECRET_KEY")
    missing = [k for k, v in (("LANGFUSE_HOST", host), ("LANGFUSE_PUBLIC_KEY", pk),
                              ("LANGFUSE_SECRET_KEY", sk)) if not v]
    if missing:
        raise RuntimeError(
            f"cannot recover previous L1 from Langfuse: missing env {missing} "
        )
    return {"host": host or "", "public_key": pk or "", "secret_key": sk or ""}


def fetch_prior_l1(*, host: str, public_key: str, secret_key: str,
                   limit: int = 1) -> dict[str, Any]:
    """Fetch the latest ``typist-systems-and-edges`` trace output from Langfuse.

    Returns the trace's ``output`` dict (``{systems: [...], edges: [...]}``).
    Raises when no trace carries the name (blocked, not a double-substitute).
    """
    import base64
    import json
    import urllib.request

    token = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
    url = f"{host}/api/public/traces?name={PRIOR_TRACE_NAME}&limit={int(limit)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {token}"})
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
        body = json.loads(resp.read().decode())
    data = body.get("data") or []
    if not data:
        raise RuntimeError(
            f"no prior L1 trace named {PRIOR_TRACE_NAME!r} found in Langfuse "
        )
    trace = data[0]
    output = trace.get("output") or {}
    if not output.get("systems") or not output.get("edges"):
        raise RuntimeError(
            f"prior L1 trace {trace.get('id')} has empty systems/edges output"
        )
    return output


def materialize_prior_l1(project_id: str, prior: dict[str, Any], session) -> dict:
    """Re-materialize the recovered L1 under ``project_id`` (idempotent MERGE).

    * L1Service per distinct ``edge.service_slug`` (spine exposure public -
      matching the prior model's accounting service exposure).
    * L1System per distinct (kind, discriminator).
    * typed Service->System edges by ``rel`` (EXPOSED_VIA / IDENTIFIED_BY /
      AUTHENTICATED_BY, else GENERIC_REL).
    * one L0 Endpoint per service (path ``/api/<slug>``, GET, base
      ``https://<slug>.example``) so the read-only surface is non-empty.

    Returns the recovered counts ``{services, systems, edges, endpoints}``.
    """
    systems = {(s["kind"], s.get("discriminator") or "__singleton__")
               for s in prior["systems"]}
    services = {e["service_slug"] for e in prior["edges"]}
    for slug in services:
        session.run(
            "MERGE (:L1TestableUnit:L1Service {business_function_slug: $slug, "
            "project_id: $p, exposure: 'public'})",
            slug=slug, p=project_id,
        )
    for kind, disc in systems:
        session.run(
            "MERGE (:L1TestableUnit:L1System {kind: $kind, discriminator: $disc, "
            "project_id: $p})",
            kind=kind, disc=disc, p=project_id,
        )
    for edge in prior["edges"]:
        rel = edge.get("rel") or "GENERIC_REL"
        session.run(
            "MATCH (s:L1Service {business_function_slug: $slug, project_id: $p}) "
            "MATCH (sy:L1System {kind: $kind, discriminator: $disc, project_id: $p}) "
            f"MERGE (s)-[:{rel}]->(sy)",
            slug=edge["service_slug"], kind=edge["kind"],
            disc=edge.get("discriminator") or "__singleton__", p=project_id,
        )
    for slug in services:
        session.run(
            "MERGE (:Endpoint {path: $path, method: 'GET', baseurl: $base, "
            "project_id: $p}) "
            "WITH * MATCH (s:L1Service {business_function_slug: $slug, project_id: $p}) "
            "MERGE (s)-[:AGGREGATES {status: 'committed'}]->"
            "(:Endpoint {path: $path, baseurl: $base, project_id: $p})",
            path=f"/api/{slug}", base=f"https://{slug}.example", slug=slug, p=project_id,
        )
    return {
        "services": sorted(services),
        "systems": sorted(f"{k}::{d}" for k, d in systems),
        "edges": len(prior["edges"]),
        "endpoints": len(services),
    }


def recover_prior_l1(project_id: str, session) -> dict[str, Any]:
    """One-shot: fetch prior L1 from Langfuse and materialize it live."""
    env = langfuse_env()
    prior = fetch_prior_l1(**env)
    return materialize_prior_l1(project_id, prior, session)


def recovered_identity(prior: dict[str, Any]) -> str:
    """The operator-facing identity of the recovered L1 abstration."""
    services = sorted({e["service_slug"] for e in prior.get("edges", [])})
    systems = sorted({f"{s['kind']}::{s.get('discriminator')}"
                      for s in prior.get("systems", [])})
    return f"services={services}; systems={systems}"


def is_langfuse_running() -> bool:
    return all(os.environ.get(k) for k in (
        "LANGFUSE_HOST", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"))