from neo4j import GraphDatabase
from agent.app.config import config
from db.neo4j.init_schema import init_schema
from db.neo4j.l1_schema import init_l1_schema

_driver = GraphDatabase.driver(config.NEO4J_URI, auth=(config.NEO4J_USER, config.NEO4J_PASSWORD))

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
    dispatch through: the L0 curator (agent/recon/curator.py) and the L1 curator
    (agent/recon/analysis/l1_curator.py). Sole-writer discipline is enforced at
    the module/builder level (only those two build the respective Cypher), not
    here."""
    with _driver.session() as s:
        s.run(cypher, **params)


def read(cypher: str, params: dict) -> list[dict]:
    """Read-only query helper; returns a list of plain dict rows."""
    with _driver.session() as s:
        return [dict(r) for r in s.run(cypher, **params)]
