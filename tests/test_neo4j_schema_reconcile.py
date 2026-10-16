"""Unit tier for the `init_schema` identity-key reconcile (db/neo4j/init_schema.py).

The live tier (`tests/test_neo4j_schema.py`) applies the schema against real
Neo4j. This tier pins the reconcile decision with a recording session:

  * a live constraint whose key set drifted from the declaration is dropped
    BEFORE the re-apply (the arm J trial regression: the Header identity moved
    to `{name, endpoint, baseurl}` while the live `header_unique` still required
    `(name, value, baseurl, project_id)`, so 1337 Header merges were rejected on
    2026-10-16 and each delta was dropped from the graph and the feed);
  * a matching or absent constraint is left alone;
  * undeclared live constraints (another component's labels) are never touched;
  * every declared statement is understood by the parse, and the Header keys
    stay aligned with the read-side identity (`l0_stream.L0_IDENTITY_KEYS`).
"""
from db.neo4j.init_schema import declared_constraint_keys, init_schema
from db.neo4j.schema import CONSTRAINTS


class RecordingSession:
    """A session stub that records the DDL statements it is asked to run."""

    def __init__(self, live_rows):
        self._live_rows = live_rows
        self.statements: list[str] = []

    def run(self, stmt, **kwargs):
        self.statements.append(stmt)
        if stmt.startswith("SHOW CONSTRAINTS"):
            return list(self._live_rows)
        return []


def _row(name, properties):
    return {"name": name, "properties": properties}


def _drops(session):
    return [s for s in session.statements if s.startswith("DROP CONSTRAINT")]


def test_stale_key_set_is_dropped_before_reapply():
    session = RecordingSession(
        [_row("header_unique", ["name", "value", "baseurl", "project_id"])]
    )
    init_schema(session)
    assert _drops(session) == ["DROP CONSTRAINT `header_unique`"]
    apply_index = next(
        i
        for i, stmt in enumerate(session.statements)
        if "CREATE CONSTRAINT header_unique" in stmt
    )
    assert session.statements.index(_drops(session)[0]) < apply_index


def test_matching_key_set_is_left_alone():
    session = RecordingSession(
        [_row("header_unique", ["name", "endpoint", "baseurl", "project_id"])]
    )
    init_schema(session)
    assert _drops(session) == []


def test_fresh_database_never_drops():
    session = RecordingSession([])
    init_schema(session)
    assert _drops(session) == []
    assert any("CREATE CONSTRAINT header_unique" in s for s in session.statements)


def test_undeclared_live_constraints_are_untouched():
    # A constraint owned by another component (not in CONSTRAINTS) must never
    # be dropped by this reconcile.
    session = RecordingSession([_row("lightrag_entity_unique", ["id"])])
    init_schema(session)
    assert _drops(session) == []


def test_every_declared_constraint_is_parsed():
    # A statement the regex cannot read would silently lose its drift
    # protection; the parse must understand the whole declaration.
    assert len(declared_constraint_keys()) == len(CONSTRAINTS)


def test_header_keys_match_read_side_identity():
    from polymerhus.analysis.l0_stream import L0_IDENTITY_KEYS

    assert declared_constraint_keys()["header_unique"] == (
        set(L0_IDENTITY_KEYS["Header"]) | {"project_id"}
    )
