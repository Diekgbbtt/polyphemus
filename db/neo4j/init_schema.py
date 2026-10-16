"""Apply the Layer-0 schema to a live Neo4j session.

`schema.py` stays the single source of truth and application is declarative and
idempotent (every statement carries `IF NOT EXISTS`). Identity keys can still
change over time - on 2026-10-16 the Header identity gained `endpoint` - and an
`IF NOT EXISTS` re-apply alone cannot replace a live constraint that carries an
outdated key set: the stale definition keeps rejecting MERGEs built with the
new identity (arm J trial evidence: 1337 Header merges rejected in four
minutes, each delta dropped from the graph and the analysis feed). Application
therefore reconciles first: any DECLARED constraint whose live key set differs
is dropped and recreated with the declared keys. Undeclared live constraints
(other components' labels) are never touched.
"""
import logging
import re

from db.neo4j.schema import CONSTRAINTS, INDEXES

logger = logging.getLogger(__name__)

# The single DDL template every entry in `CONSTRAINTS` uses; the reconcile
# reads the declared identity keys straight out of it so that a changed
# declaration and the applied DDL cannot drift apart.
_CREATE_CONSTRAINT = re.compile(
    r"CREATE CONSTRAINT (?P<name>\S+) IF NOT EXISTS "
    r"FOR \(\w+:(?P<label>\w+)\) REQUIRE \((?P<props>[^)]+)\) IS UNIQUE"
)


def declared_constraint_keys() -> dict[str, set[str]]:
    """Constraint name -> declared identity key set, parsed from CONSTRAINTS."""
    declared: dict[str, set[str]] = {}
    for stmt in CONSTRAINTS:
        match = _CREATE_CONSTRAINT.match(stmt)
        if match is None:  # not a uniqueness constraint; nothing to reconcile
            continue
        props = {
            prop.strip().rsplit(".", 1)[-1]
            for prop in match.group("props").split(",")
        }
        declared[match.group("name")] = props
    return declared


def init_schema(session):
    """Apply all constraints and indexes, reconciling changed identity keys.

    Idempotent: a fresh or already-correct database sees `CREATE ... IF NOT
    EXISTS` no-ops only, because the reconcile drops a constraint solely when
    its live key set differs from the declared one.
    """
    declared = declared_constraint_keys()
    live = {
        row["name"]: set(row["properties"] or [])
        for row in session.run("SHOW CONSTRAINTS YIELD name, properties")
    }
    for name, keys in declared.items():
        if name in live and live[name] != keys:
            logger.info(
                "init_schema: recreating constraint %r - live keys %s != declared %s",
                name,
                sorted(live[name]),
                sorted(keys),
            )
            session.run(f"DROP CONSTRAINT `{name}`")
    for stmt in CONSTRAINTS + INDEXES:
        session.run(stmt)
