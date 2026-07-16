"""Layer-1 schema for polymerhus (service/system model).

Mirrors `db/neo4j/schema.py` (the Layer-0 schema) but for the disjoint `:L1*`
label namespace. L1 lives in the SAME physical neo4j:5-community instance as L0
(community edition cannot host a second named database, `neo4j_client.py` opens
no `database=`), kept independently navigable by a reserved `L1` label prefix so
the L1 business `Service` never collides with the L0 network `:Service`
(`schema.py:12`). Ratified one-way door D1 (see docs/design/L1-MVP-plan.md §1).

Identity keys (ratified one-way door D2):
  * L1Service  -> (project_id, business_function_slug)                 [L1D-12]
  * L1System   -> (project_id, system_kind, discriminator)            [L1D-9]
  * SystemKind -> (id, project_id)  controlled-vocab catalogue         [L1D-6]

Interface agreement A (the `AGGREGATES` cross-layer reference, L1D-25) is a
NATIVE edge `(:L1Service)-[:AGGREGATES {envelope}]->(:L0 node)` to the
co-resident L0 node (operator decision, option A; spec §6), not a reified node,
so it needs no additional node constraint - idempotency comes from MERGE on the
`(Service)-[:AGGREGATES]->(L0)` pattern (community edition has no relationship
key constraints, and the L0 node's own key already makes the target unique).

Every key is a non-null composite `IS UNIQUE`, exactly like the L0 keys, so the
`__singleton__` discriminator sentinel must be a real string (L1R-2). Applied by
`init_l1_schema`, which mirrors `db/neo4j/init_schema.py` (every statement is
`IF NOT EXISTS`, so re-applying is idempotent)."""

L1_CONSTRAINTS = [
    "CREATE CONSTRAINT l1service_unique IF NOT EXISTS FOR (s:L1Service) REQUIRE (s.project_id, s.business_function_slug) IS UNIQUE",
    "CREATE CONSTRAINT l1system_unique IF NOT EXISTS FOR (sy:L1System) REQUIRE (sy.project_id, sy.system_kind, sy.discriminator) IS UNIQUE",
    "CREATE CONSTRAINT systemkind_unique IF NOT EXISTS FOR (k:SystemKind) REQUIRE (k.id, k.project_id) IS UNIQUE",
    # FR-ENRICH: DataItem flexible identity (project_id, item_key) - a semantic
    # key, identity independent of the L0 sites it surfaces at (L1D-13/L1OP-1).
    "CREATE CONSTRAINT l1dataitem_unique IF NOT EXISTS FOR (d:L1DataItem) REQUIRE (d.project_id, d.item_key) IS UNIQUE",
    # FR-ENRICH: DataRelationship controlled-vocabulary catalogue, extensible by
    # rows (L1OP-2), same shape as SystemKind.
    "CREATE CONSTRAINT datarelationshipkind_unique IF NOT EXISTS FOR (k:DataRelationshipKind) REQUIRE (k.id, k.project_id) IS UNIQUE",
]

L1_INDEXES = [
    "CREATE INDEX idx_l1service_tenant IF NOT EXISTS FOR (s:L1Service) ON (s.project_id)",
    "CREATE INDEX idx_l1system_tenant IF NOT EXISTS FOR (sy:L1System) ON (sy.project_id)",
    "CREATE INDEX idx_l1testableunit_tenant IF NOT EXISTS FOR (u:L1TestableUnit) ON (u.project_id)",
    "CREATE INDEX idx_systemkind_tenant IF NOT EXISTS FOR (k:SystemKind) ON (k.project_id)",
    "CREATE INDEX idx_l1dataitem_tenant IF NOT EXISTS FOR (d:L1DataItem) ON (d.project_id)",
    "CREATE INDEX idx_datarelationshipkind_tenant IF NOT EXISTS FOR (k:DataRelationshipKind) ON (k.project_id)",
]


def init_l1_schema(session):
    """Apply all L1 constraints and indexes. Idempotent (every statement is
    IF NOT EXISTS). Mirrors `db/neo4j/init_schema.py:init_schema`."""
    for stmt in L1_CONSTRAINTS + L1_INDEXES:
        session.run(stmt)
