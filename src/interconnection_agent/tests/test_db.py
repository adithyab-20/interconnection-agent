"""Unit tests for :mod:`interconnection_agent.db`.

Live under the component's own ``tests/`` directory. Pure logic only — no database
required; the live-connection behavior is covered by ``tests/integration/``.
"""

import pytest

from interconnection_agent.db import DEFAULT_DATABASE_URL, database_url


def test_database_url_defaults_to_local_compose(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert database_url() == DEFAULT_DATABASE_URL


def test_database_url_prefers_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@db.example:6000/other")
    assert database_url() == "postgresql://user:pw@db.example:6000/other"
