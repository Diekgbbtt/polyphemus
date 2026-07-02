from db.neo4j.schema import CONSTRAINTS, INDEXES

def init_schema(session):
    """Apply all constraints and indexes. Idempotent (every statement is IF NOT EXISTS)."""
    for stmt in CONSTRAINTS + INDEXES:
        session.run(stmt)
