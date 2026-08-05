"""Shared fixtures for schema integration tests.

These run against the real Docker Compose Postgres (``docker compose up`` first) —
never a mocked DB, because ADR-0001's no-double-counting guarantee is enforced by
the views themselves and mocking would leave it untested exactly where it matters.
"""

from collections.abc import Iterator

import psycopg
import pytest

from interconnection_agent.db import connect
from interconnection_agent.migrate import apply_migrations


@pytest.fixture(scope="session", autouse=True)
def _schema() -> None:
    """Bring the schema up once for the whole session, from whatever state exists."""
    with connect() as conn:
        apply_migrations(conn)
        conn.commit()


@pytest.fixture
def conn() -> Iterator[psycopg.Connection[tuple[object, ...]]]:
    """A connection whose work is rolled back, so seeded rows never persist.

    Each test seeds its own rows and reads them back inside one transaction; the
    rollback keeps tests isolated without truncate machinery between them.
    """
    with connect() as c:
        c.autocommit = False
        try:
            yield c
        finally:
            c.rollback()
