"""The county query the CLI is built on, proven against the real ingested queue.

Acceptance: a CLI command lists active projects for a county, reading through
``caiso_projects``. The load-bearing behavior is that selection — it must read the
per-source view (so an LBNL row in the same county never leaks in) and return only
active projects. The pure formatting layer is a unit test (``src/.../tests/test_cli``).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from interconnection_agent.cli import list_active_projects
from interconnection_agent.ingest import run_caiso_ingest

Conn = psycopg.Connection[tuple[object, ...]]

WORKBOOK = Path(__file__).resolve().parents[2] / "data" / "publicqueuereport.xlsx"


@pytest.fixture
def seeded(conn: Conn) -> Iterator[Conn]:
    run_caiso_ingest(WORKBOOK, conn)
    yield conn


def test_lists_active_projects_for_a_county(seeded: Conn) -> None:
    projects = list_active_projects(seeded, "SOLANO")
    ids = {p.native_id for p in projects}
    assert "CAISO-0022" in ids  # MONTEZUMA (HIGH WINDS III) sits in Solano county
    assert all(p.county == "SOLANO" for p in projects)


def test_county_match_is_case_insensitive(seeded: Conn) -> None:
    # The workbook stores counties upper-cased; an analyst should not have to know that.
    assert list_active_projects(seeded, "Solano") == list_active_projects(seeded, "SOLANO")


def test_reads_through_the_view_so_an_lbnl_row_in_the_county_is_excluded(
    seeded: Conn,
) -> None:
    # An LBNL project in Solano must not appear in a CAISO county listing — the view's
    # baked-in source filter is what guarantees it, not a WHERE the query remembered.
    seeded.execute(
        "INSERT INTO projects (source, native_id, status, county, iso) "
        "VALUES ('lbnl', 'LBNL-SOLANO-1', 'Active', 'SOLANO', 'CAISO')"
    )
    ids = {p.native_id for p in list_active_projects(seeded, "SOLANO")}
    assert "LBNL-SOLANO-1" not in ids


def test_empty_county_returns_no_rows(seeded: Conn) -> None:
    assert list_active_projects(seeded, "NOWHERE") == []
