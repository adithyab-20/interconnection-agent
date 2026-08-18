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

from interconnection_agent.cli import list_active_projects, list_projects_at_poi
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


def test_lists_projects_at_a_normalized_poi(seeded: Conn) -> None:
    # Three active projects sit at Birds Landing 230 kV; querying the normalized POI must
    # return them, and every returned row must carry that normalized POI.
    projects = list_projects_at_poi(seeded, "Birds Landing 230 kV")
    assert "CAISO-0022" in {p.native_id for p in projects}
    assert all(p.normalized_poi == "Birds Landing 230 kV" for p in projects)


def test_poi_listing_groups_the_reviewed_aliases(seeded: Conn) -> None:
    # Eldorado 230 kV is written three ways in the workbook ("Eldorado Substation 230kV",
    # "SCE owned Eldorado Bus 230kV", "SCE portion of Eldorado Substation 230 kV"). The
    # alias table groups them, so one POI query returns rows with differing raw strings.
    projects = list_projects_at_poi(seeded, "Eldorado Substation 230 kV")
    assert len({p.raw_poi for p in projects}) > 1


def test_poi_match_is_case_insensitive(seeded: Conn) -> None:
    assert list_projects_at_poi(seeded, "birds landing 230 kV") == list_projects_at_poi(
        seeded, "Birds Landing 230 kV"
    )


def test_empty_poi_returns_no_rows(seeded: Conn) -> None:
    assert list_projects_at_poi(seeded, "Nonexistent Substation 999 kV") == []
