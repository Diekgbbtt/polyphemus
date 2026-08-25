from polymerhus.app.clients import pg
from polymerhus.ingestion import migrate_url_schema


def test_main_calls_apply_url_ingestion_migrations_exactly_once(monkeypatch):
    calls = []

    def fake_apply() -> None:
        calls.append(1)

    monkeypatch.setattr(migrate_url_schema.pg, "apply_url_ingestion_migrations", fake_apply)

    migrate_url_schema.main()

    assert calls == [1]


def test_url_ingestion_migration_sql_contains_expected_statements():
    expected = [
        "ALTER TABLE ingestion_sources ADD COLUMN IF NOT EXISTS source_metadata JSONB NOT NULL DEFAULT '{}'",
        "ALTER TABLE ingestion_sources ALTER COLUMN content_hash DROP NOT NULL",
    ]

    assert pg._URL_INGESTION_MIGRATION_SQL == expected


def test_url_ingestion_migration_sql_has_no_destructive_operations():
    destructive_tokens = ("DROP TABLE", "DELETE", "TRUNCATE", "DROP COLUMN", "UPDATE", "INSERT")

    for statement in pg._URL_INGESTION_MIGRATION_SQL:
        upper = statement.upper()
        for token in destructive_tokens:
            assert token not in upper, f"destructive token {token!r} found in migration statement: {statement}"


def test_url_ingestion_migration_is_idempotent_at_sql_level():
    # Each idempotency keyword is present; the same list will be executed again
    # without changing the schema.
    for statement in pg._URL_INGESTION_MIGRATION_SQL:
        assert "IF NOT EXISTS" in statement or "DROP NOT NULL" in statement
