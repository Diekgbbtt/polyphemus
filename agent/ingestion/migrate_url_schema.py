"""Executable entry point for applying URL ingestion schema migrations."""

from agent.app.clients import pg


def main() -> None:
    pg.apply_url_ingestion_migrations()
    print("URL ingestion schema migration applied successfully.")


if __name__ == "__main__":
    main()
