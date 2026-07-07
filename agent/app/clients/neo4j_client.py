from neo4j import GraphDatabase
from agent.app.config import config
from db.neo4j.init_schema import init_schema

_driver = GraphDatabase.driver(config.NEO4J_URI, auth=(config.NEO4J_USER, config.NEO4J_PASSWORD))

def check() -> bool:
    _driver.verify_connectivity()
    return True

def ensure_schema() -> None:
    with _driver.session() as s:
        init_schema(s)

def merge(cypher: str, params: dict) -> None:
    """Parameterized MERGE helper (the only Layer-0 write path)."""
    with _driver.session() as s:
        s.run(cypher, **params)


def read(cypher: str, params: dict) -> list[dict]:
    """Read-only query helper; returns a list of plain dict rows."""
    with _driver.session() as s:
        return [dict(r) for r in s.run(cypher, **params)]
