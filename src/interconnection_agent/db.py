"""Database access for the interconnection agent.

A single place that knows how to reach Postgres, so tests, ETL, and the API all
resolve the same DSN. The default points at the Docker Compose service defined in
``docker-compose.yml`` (see ``.env.example``); override it with ``DATABASE_URL``.
"""

from __future__ import annotations

import os

import psycopg

# Kept in sync with docker-compose.yml and .env.example. A contributor who runs
# `docker compose up` then `pytest` needs no configuration for this to resolve.
DEFAULT_DATABASE_URL = "postgresql://postgres@localhost:5433/interconnection"


def database_url() -> str:
    """Return the Postgres DSN, preferring ``DATABASE_URL`` over the local default."""
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def connect() -> psycopg.Connection[tuple[object, ...]]:
    """Open a new connection to the configured Postgres database."""
    return psycopg.connect(database_url())
