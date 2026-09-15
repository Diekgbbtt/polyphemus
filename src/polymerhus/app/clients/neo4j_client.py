import logging

from neo4j import GraphDatabase
from polymerhus.app.config import config
from db.neo4j.init_schema import init_schema
from db.neo4j.l1_schema import init_l1_schema

logger = logging.getLogger(__name__)

_driver = GraphDatabase.driver(config.NEO4J_URI, auth=(config.NEO4J_USER, config.NEO4J_PASSWORD))


def close() -> None:
    """Close the persistent driver at process shutdown (#211, TD-7: a stop that
    halts everything). Fail-open and idempotent: a driver already closed (or a
    close that raises) is logged, never raised - teardown must not fail on it."""
    try:
        _driver.close()
    except Exception as exc:  # noqa: BLE001 - fail-open, teardown never raises
        logger.warning("neo4j driver close failed (fail-open): %s", exc)


def check() -> bool:
    _driver.verify_connectivity()
    return True

def ensure_schema() -> None:
    with _driver.session() as s:
        init_schema(s)

def ensure_l1_schema() -> None:
    """Apply the Layer-1 constraints/indexes (db/neo4j/l1_schema.py). Separate
    from ensure_schema so L1 substrate can be provisioned independently of L0."""
    with _driver.session() as s:
        init_l1_schema(s)

def merge(cypher: str, params: dict) -> None:
    """Parameterized MERGE helper. The low-level write seam both sole-writers
    dispatch through: the L0 curator (src/polymerhus/recon/domain/curator.py) and the L1 curator
    (src/polymerhus/analysis/l1_curator.py). Sole-writer discipline is enforced at
    the module/builder level (only those two build the respective Cypher), not
    here."""
    with _driver.session() as s:
        s.run(cypher, **params)


def read(cypher: str, params: dict) -> list[dict]:
    """Read-only query helper; returns a list of plain dict rows."""
    with _driver.session() as s:
        return [dict(r) for r in s.run(cypher, **params)]
