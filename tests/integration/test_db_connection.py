"""Integration tests: the skeleton's proof of life against a real Postgres.

Requires the Docker Compose Postgres to be running (``docker compose up``). This is
the harness every later ticket lands in — if it passes in CI, a contributor knows
``docker compose up`` + ``pytest`` gives them a working database.
"""

from interconnection_agent.db import connect


def test_can_query_postgres() -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1")
        assert cur.fetchone() == (1,)


def test_connects_to_a_real_postgres() -> None:
    # version() only exists on a real server, so this fails loudly against a stub
    # or a wrong DSN rather than passing silently.
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT version()")
        row = cur.fetchone()
        assert row is not None
        assert "PostgreSQL" in str(row[0])
