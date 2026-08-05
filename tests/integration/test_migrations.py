"""Migrations bring the schema up from an empty database and are safe to re-run.

Acceptance: "Migrations run from empty against the Compose database." This test
drops every object the migrations create, runs them against the resulting empty
database, and asserts the schema is present — then proves a second run is a no-op.
"""

import psycopg

from interconnection_agent.db import connect
from interconnection_agent.migrate import apply_migrations


def _drop_everything(conn: psycopg.Connection[tuple[object, ...]]) -> None:
    conn.execute("DROP VIEW IF EXISTS caiso_projects, lbnl_projects CASCADE")
    conn.execute("DROP TABLE IF EXISTS project_resources CASCADE")
    conn.execute("DROP TABLE IF EXISTS projects CASCADE")
    conn.execute("DROP TABLE IF EXISTS schema_migrations CASCADE")
    conn.execute("DROP TYPE IF EXISTS source CASCADE")
    conn.commit()


def _scalar(conn: psycopg.Connection[tuple[object, ...]], sql: str, *params: object) -> object:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return row[0]


def _object_exists(conn: psycopg.Connection[tuple[object, ...]], name: str) -> bool:
    return _scalar(conn, "SELECT to_regclass(%s) IS NOT NULL", name) is True


def test_migrations_build_the_schema_from_empty() -> None:
    with connect() as conn:
        _drop_everything(conn)
        assert not _object_exists(conn, "projects")  # genuinely empty first

        apply_migrations(conn)
        conn.commit()

        for name in ("projects", "project_resources", "caiso_projects", "lbnl_projects"):
            assert _object_exists(conn, name), f"{name} missing after migration"


def test_applying_migrations_twice_is_idempotent() -> None:
    with connect() as conn:
        apply_migrations(conn)
        conn.commit()
        before = _scalar(conn, "SELECT count(*) FROM schema_migrations")

        # A second run must apply nothing and must not error on already-present objects.
        apply_migrations(conn)
        conn.commit()
        after = _scalar(conn, "SELECT count(*) FROM schema_migrations")

        assert after == before
