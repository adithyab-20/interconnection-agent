"""CAISO active-sheet ingest, proven against the real workbook and a real Postgres.

Seam 1 from the vertical slice: ``run_caiso_ingest(workbook, conn) -> IngestReport``
against the frozen ``publicqueuereport.xlsx``, seeded through the actual ETL — never a
mocked DB and never a fixture spreadsheet, because the point of this ticket (the walking
skeleton) is that the operator's real active queue lands in the canonical schema.

Scope is the active sheet only. ``project_resources`` child rows, POI normalization, and
the completed/withdrawn sheets are later tickets; here every row is ``poi_unmapped`` and
carries no resources yet.
"""

from __future__ import annotations

import datetime
from pathlib import Path

import psycopg
import pytest

from interconnection_agent.ingest import IngestReport, run_caiso_ingest

Conn = psycopg.Connection[tuple[object, ...]]

# The frozen snapshot committed to the repo. The counts and the known-project field
# values below are read from this exact file (report run date 07/24/2026).
WORKBOOK = Path(__file__).resolve().parents[2] / "data" / "publicqueuereport.xlsx"

# The active sheet carries 270 real projects plus five trailing legend/disclaimer rows
# with no queue position. These numbers are asserted, not approximated — a shifted count
# means the reader started on the wrong row or swallowed a project.
ACTIVE_PROJECTS = 270


@pytest.fixture
def report(conn: Conn) -> IngestReport:
    """Ingest the real workbook into the rolled-back ``conn``, once per test.

    Shares the session's rollback ``conn`` fixture (function-scoped, so a test that
    asks for both gets this same connection): the 270 rows are visible for the test's
    duration and vanish afterwards, so the suite needs no truncate step.
    """
    return run_caiso_ingest(WORKBOOK, conn)


def test_ingest_writes_every_active_project(report: IngestReport, conn: Conn) -> None:
    assert report.rows_written == ACTIVE_PROJECTS
    stored = conn.execute("SELECT count(*) FROM caiso_projects").fetchone()
    assert stored is not None and stored[0] == ACTIVE_PROJECTS


@pytest.mark.usefixtures("report")
def test_ingest_maps_a_known_project_into_the_canonical_schema(conn: Conn) -> None:
    # MONTEZUMA (HIGH WINDS III), queue position 22 — the first data row. Its cells are
    # read straight off the sheet, so this pins the column mapping end to end.
    row = conn.execute(
        "SELECT source, status, iso, study_region, county, state, utility, raw_poi, "
        "       normalized_poi, poi_unmapped, q_date, proposed_online_date "
        "FROM caiso_projects WHERE native_id = 'CAISO-0022'"
    ).fetchone()
    assert row == (
        "caiso_raw",
        "Active",
        "CAISO",  # constant for every CAISO row
        "Northern",  # PTO Study Region
        "SOLANO",
        "CA",
        "PGAE",
        "Birds Landing 230 kV",  # raw_poi is the operator's string, verbatim
        None,  # no alias table yet (ticket 5)
        True,  # so every row is unmapped for now
        datetime.date(2003, 11, 18),
        datetime.date(2005, 6, 30),
    )


def test_ingest_reports_read_written_and_dropped_with_reason(report: IngestReport) -> None:
    # The five trailing legend/disclaimer rows sit inside the data range but carry no
    # queue position, so they are dropped-with-reason rather than written or ignored.
    assert report.rows_read == report.rows_written + report.rows_dropped
    assert report.rows_dropped == 5
    assert {d.reason for d in report.dropped} == {"no queue position"}


def test_reingest_is_idempotent_on_the_natural_key(report: IngestReport, conn: Conn) -> None:
    # Re-running against the same workbook upserts every row in place: the row count is
    # unchanged and a known project keeps its field values — no duplicate, no drift.
    before = conn.execute(
        "SELECT status, raw_poi FROM caiso_projects WHERE native_id = 'CAISO-0022'"
    ).fetchone()

    second = run_caiso_ingest(WORKBOOK, conn)

    assert second.rows_written == report.rows_written
    total = conn.execute("SELECT count(*) FROM caiso_projects").fetchone()
    assert total is not None and total[0] == ACTIVE_PROJECTS
    after = conn.execute(
        "SELECT status, raw_poi FROM caiso_projects WHERE native_id = 'CAISO-0022'"
    ).fetchone()
    assert after == before
