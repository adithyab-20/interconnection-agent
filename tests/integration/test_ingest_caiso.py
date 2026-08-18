"""CAISO ingest across all three sheets, proven against the real workbook and Postgres.

Seam 1 from the vertical slice: ``run_caiso_ingest(workbook, conn) -> IngestReport``
against the frozen ``publicqueuereport.xlsx``, seeded through the actual ETL — never a
mocked DB and never a fixture spreadsheet, because the point of this work is that the
operator's real active/completed/withdrawn queues land in the canonical schema, with
hybrid projects as child resource rows and outcome dates that make Time-to-Energization
and Withdrawal computable.
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

ACTIVE_SHEET = "Grid GenerationQueue"
COMPLETED_SHEET = "Completed Generation Projects"
WITHDRAWN_SHEET = "Withdrawn Generation Projects"

# Real project counts per sheet, plus the trailing legend/disclaimer rows that sit inside
# the data range but carry no queue position. These are asserted, not approximated — a
# shifted count means the reader started on the wrong row or swallowed a project.
ACTIVE_PROJECTS = 270
COMPLETED_PROJECTS = 249
WITHDRAWN_PROJECTS = 1759
TOTAL_PROJECTS = ACTIVE_PROJECTS + COMPLETED_PROJECTS + WITHDRAWN_PROJECTS


@pytest.fixture
def report(conn: Conn) -> IngestReport:
    """Ingest the real workbook into the rolled-back ``conn``, once per test.

    Shares the session's rollback ``conn`` fixture (function-scoped, so a test that asks
    for both gets this same connection): the rows are visible for the test's duration and
    vanish afterwards, so the suite needs no truncate step.
    """
    return run_caiso_ingest(WORKBOOK, conn)


def test_ingest_writes_every_project_from_all_three_sheets(
    report: IngestReport, conn: Conn
) -> None:
    assert report.rows_written == TOTAL_PROJECTS
    stored = conn.execute("SELECT count(*) FROM caiso_projects").fetchone()
    assert stored is not None and stored[0] == TOTAL_PROJECTS


def test_report_carries_per_sheet_counts(report: IngestReport) -> None:
    # Each sheet's counts stand on their own so a shift in one is not hidden by the total.
    assert report.for_sheet(ACTIVE_SHEET).rows_written == ACTIVE_PROJECTS
    assert report.for_sheet(COMPLETED_SHEET).rows_written == COMPLETED_PROJECTS
    assert report.for_sheet(WITHDRAWN_SHEET).rows_written == WITHDRAWN_PROJECTS
    # The trailing legend/disclaimer rows have no queue position and are dropped-with-reason.
    assert report.for_sheet(ACTIVE_SHEET).rows_dropped == 5
    assert report.for_sheet(COMPLETED_SHEET).rows_dropped == 1
    assert report.for_sheet(WITHDRAWN_SHEET).rows_dropped == 1
    assert {d.reason for d in report.dropped} == {"no queue position"}
    for sheet in report.sheets:
        assert sheet.rows_read == sheet.rows_written + sheet.rows_dropped


@pytest.mark.usefixtures("report")
def test_status_vocabulary_is_mapped_to_the_canonical_set(conn: Conn) -> None:
    # Each sheet's single CAISO status maps to one canonical token; COMPLETED is the
    # documented rename to Operational (ADR-0002's resolved-rate vocabulary).
    statuses = {
        row[0]: row[1]
        for row in conn.execute(
            "SELECT status, count(*) FROM caiso_projects GROUP BY status"
        ).fetchall()
    }
    assert statuses == {
        "Active": ACTIVE_PROJECTS,
        "Operational": COMPLETED_PROJECTS,
        "Withdrawn": WITHDRAWN_PROJECTS,
    }


@pytest.mark.usefixtures("report")
def test_ingest_maps_a_known_active_project_into_the_canonical_schema(conn: Conn) -> None:
    # MONTEZUMA (HIGH WINDS III), queue position 22 — the first active data row. Its cells
    # are read straight off the sheet, so this pins the column mapping end to end.
    row = conn.execute(
        "SELECT source, status, iso, study_region, county, state, utility, raw_poi, "
        "       normalized_poi, poi_unmapped, q_date, proposed_online_date, "
        "       actual_online_date, withdrawn_date "
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
        "Birds Landing 230 kV",  # normalized through the reviewed alias table (ticket 5)
        False,  # resolved, so not flagged unmapped
        datetime.date(2003, 11, 18),
        datetime.date(2005, 6, 30),
        None,  # active rows never carry an actual on-line date
        None,  # nor a withdrawn date
    )


@pytest.mark.usefixtures("report")
def test_a_hybrid_project_produces_its_expected_child_resource_rows(conn: Conn) -> None:
    # MONTEZUMA is a wind + storage hybrid: two fuel/MW triples, so two child rows keyed on
    # fuel (the LBNL-comparable taxonomy), each carrying its own MW.
    rows = conn.execute(
        "SELECT type, mw FROM project_resources "
        "WHERE source = 'caiso_raw' AND native_id = 'CAISO-0022' ORDER BY type"
    ).fetchall()
    assert rows == [("Battery", 38.0), ("Wind Turbine", 38.0)]


@pytest.mark.usefixtures("report")
def test_repeated_fuels_in_one_project_aggregate_into_a_single_child_row(conn: Conn) -> None:
    # CAISO-0096 lists Wind Turbine + Battery + Battery. The child key is (source, id, type),
    # so the two battery triples must fold into one Battery row with their MW summed rather
    # than collide on the primary key.
    rows = {
        row[0]: row[1]
        for row in conn.execute(
            "SELECT type, count(*) FROM project_resources "
            "WHERE source = 'caiso_raw' AND native_id = 'CAISO-0096' GROUP BY type"
        ).fetchall()
    }
    assert rows == {"Wind Turbine": 1, "Battery": 1}


@pytest.mark.usefixtures("report")
def test_a_completed_project_carries_both_a_queue_date_and_an_actual_online_date(
    conn: Conn,
) -> None:
    # OTAY MESA GENERATING PROJECT, queue position 1A — a completed row. It must carry the
    # queue date (vintage axis) and the actual on-line date (energization) that make
    # Time-to-Energization computable, and no withdrawn date.
    row = conn.execute(
        "SELECT status, q_date, actual_online_date, withdrawn_date "
        "FROM caiso_projects WHERE native_id = 'CAISO-1A'"
    ).fetchone()
    assert row == (
        "Operational",
        datetime.date(1999, 11, 1),
        datetime.date(2009, 10, 2),
        None,
    )


@pytest.mark.usefixtures("report")
def test_a_withdrawn_project_carries_a_withdrawn_date(conn: Conn) -> None:
    # TESLA POWER PLANT, queue position 6 — a withdrawn row. The withdrawn date is the
    # per-sheet column completed rows do not have; the sheet's reason column is, per the
    # frozen schema (which has no reason column), deliberately not persisted.
    row = conn.execute(
        "SELECT status, withdrawn_date, actual_online_date "
        "FROM caiso_projects WHERE native_id = 'CAISO-0006'"
    ).fetchone()
    assert row == ("Withdrawn", datetime.date(2011, 6, 16), None)


def test_child_resource_rows_are_written_for_every_sheet(report: IngestReport, conn: Conn) -> None:
    # Every sheet's fuel/MW triples land as child rows. The five completed triples that
    # carry MW but no fuel label have no child key and are reported skipped, not dropped.
    assert report.for_sheet(ACTIVE_SHEET).resources_written == 427
    assert report.for_sheet(COMPLETED_SHEET).resources_written == 289
    assert report.for_sheet(COMPLETED_SHEET).resources_skipped == 5
    assert report.for_sheet(WITHDRAWN_SHEET).resources_written == 2063
    stored = conn.execute("SELECT count(*) FROM project_resources").fetchone()
    assert stored is not None and stored[0] == report.resources_written


@pytest.mark.usefixtures("report")
def test_ingest_flags_a_conceptual_poi_as_unmapped(conn: Conn) -> None:
    # CAISO-0096's station is "Tehachapi Conceptual Substation #1" — a POI that does not
    # physically exist, so the reviewer left it out of the alias table. It must be flagged,
    # never guessed: an energized-history saturation figure needs a real substation.
    row = conn.execute(
        "SELECT raw_poi, normalized_poi, poi_unmapped "
        "FROM caiso_projects WHERE native_id = 'CAISO-0096'"
    ).fetchone()
    assert row == ("Tehachapi Conceptual Substation #1", None, True)


def test_active_sheet_poi_coverage_clears_the_stopping_bar(report: IngestReport) -> None:
    # Coverage is a measured number, not an assumption. The <2% bar is defined on the active
    # queue alone — the alias table was reviewed against it — so it is asserted per sheet.
    active = report.for_sheet(ACTIVE_SHEET)
    assert active.unmapped_rows == 2
    assert active.mw_written == pytest.approx(76287.3, abs=0.1)
    assert active.unmapped_mw == pytest.approx(1100.0, abs=0.1)
    assert 0.0 < active.unmapped_mw_share < 0.02


def test_reingest_is_idempotent_on_the_natural_key(report: IngestReport, conn: Conn) -> None:
    # Re-running against the same workbook upserts every project and resource in place: the
    # row counts are unchanged and a known project keeps its field values — no duplicate.
    before = conn.execute(
        "SELECT status, raw_poi FROM caiso_projects WHERE native_id = 'CAISO-0022'"
    ).fetchone()

    second = run_caiso_ingest(WORKBOOK, conn)

    assert second.rows_written == report.rows_written
    assert second.resources_written == report.resources_written
    projects = conn.execute("SELECT count(*) FROM caiso_projects").fetchone()
    assert projects is not None and projects[0] == TOTAL_PROJECTS
    resources = conn.execute("SELECT count(*) FROM project_resources").fetchone()
    assert resources is not None and resources[0] == report.resources_written
    after = conn.execute(
        "SELECT status, raw_poi FROM caiso_projects WHERE native_id = 'CAISO-0022'"
    ).fetchone()
    assert after == before
