"""Apply the SQL migrations that build the canonical schema.

Deliberately tiny: numbered ``.sql`` files in ``migrations/`` applied in filename
order, each recorded in a ``schema_migrations`` table so a re-run applies only what
is new. No ORM and no migration framework — the schema is small, hand-written SQL is
the auditable artifact, and "run from empty" is the only guarantee we need.

Run it as ``python -m interconnection_agent.migrate`` against the configured
``DATABASE_URL``; call :func:`apply_migrations` from tests and ETL.
"""

from __future__ import annotations

from pathlib import Path

import psycopg

from interconnection_agent.db import connect

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _migration_files() -> list[Path]:
    """Migration files in the order they must be applied (lexical == chronological)."""
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def apply_migrations(conn: psycopg.Connection[tuple[object, ...]]) -> list[str]:
    """Apply every not-yet-applied migration; return the versions applied this run.

    Idempotent: already-applied versions are skipped, so a second run is a no-op.
    Does not commit — the caller controls the transaction boundary.
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "    version text PRIMARY KEY,"
        "    applied_at timestamptz NOT NULL DEFAULT now()"
        ")"
    )
    already_applied = {
        row[0] for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
    }

    applied_now: list[str] = []
    for path in _migration_files():
        version = path.stem
        if version in already_applied:
            continue
        conn.execute(path.read_text())
        conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
        applied_now.append(version)
    return applied_now


def main() -> None:
    with connect() as conn:
        applied = apply_migrations(conn)
        conn.commit()
    if applied:
        print("Applied migrations: " + ", ".join(applied))
    else:
        print("Schema already up to date.")


if __name__ == "__main__":
    main()
