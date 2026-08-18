"""LBNL ingest, proven against the real national workbook and Postgres.

Seam 1 (LBNL half) from the vertical slice: ``run_lbnl_ingest(workbook, conn) -> IngestReport``
against the frozen ``LBNL_Ix_Queue_Data_File_thru2025.xlsx``, seeded through the actual ETL —
never a mocked DB. The point of this reader is national breadth and an independent check on
the CAISO ETL, so the tests pin the counts, the ADR-0001 location split (West/Southeast are
never stored as an ISO), the all-NULL ``study_region``, non-ISO handling, and idempotency on
the natural key.

The LBNL workbook is a 15 MB, ~38k-row file and is not committed to the repo; these tests are
skipped when it is absent so a clean checkout's suite still runs.
"""

from __future__ import annotations

import datetime
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from interconnection_agent.ingest import IngestReport, run_lbnl_ingest
from interconnection_agent.ingest.lbnl import COMPLETE_QUEUE_SHEET

Conn = psycopg.Connection[tuple[object, ...]]

WORKBOOK = Path(__file__).resolve().parents[2] / "data" / "LBNL_Ix_Queue_Data_File_thru2025.xlsx"

pytestmark = pytest.mark.skipif(
    not WORKBOOK.exists(), reason="LBNL workbook not present (large, uncommitted data file)"
)

# Counts read straight off the frozen file (report through 2025). The sheet holds 38,201
# data rows; 135 of them collide on LBNL's (q_id, entity) natural key despite the codebook's
# uniqueness claim, so first-seen wins and 135 are dropped-with-reason.
DATA_ROWS = 38201
DUPLICATE_ROWS = 135
PROJECTS_WRITTEN = DATA_ROWS - DUPLICATE_ROWS  # 38066

# Non-ISO catch-alls (West + Southeast) after de-duplication; the rest are the seven ISOs.
NON_ISO_PROJECTS = 12400
ISO_PROJECTS = PROJECTS_WRITTEN - NON_ISO_PROJECTS  # 25666


@pytest.fixture(scope="module")
def report(conn_module: Conn) -> IngestReport:
    """Ingest the real LBNL workbook once for the module, into a rolled-back connection.

    Module-scoped because a 38k-row ingest is expensive; the connection is rolled back after
    the module so nothing persists. Reads run inside the same transaction.
    """
    return run_lbnl_ingest(WORKBOOK, conn_module)


@pytest.fixture(scope="module")
def conn_module() -> Iterator[psycopg.Connection[tuple[object, ...]]]:
    """A module-scoped connection whose work is rolled back after all LBNL tests run."""
    from interconnection_agent.db import connect

    c = connect()
    c.autocommit = False
    try:
        yield c
    finally:
        c.rollback()
        c.close()


def test_writes_every_project_from_the_complete_queue_sheet(report: IngestReport) -> None:
    assert report.rows_read == DATA_ROWS
    assert report.rows_written == PROJECTS_WRITTEN


def test_stores_the_written_rows_in_the_lbnl_view(report: IngestReport, conn_module: Conn) -> None:
    stored = conn_module.execute("SELECT count(*) FROM lbnl_projects").fetchone()
    assert stored is not None and stored[0] == PROJECTS_WRITTEN


def test_every_row_is_tagged_source_lbnl(report: IngestReport, conn_module: Conn) -> None:
    # The lbnl_projects view bakes in WHERE source = 'lbnl'; its count equalling the base
    # table's count for these rows proves every row landed under the right source tag.
    base = conn_module.execute("SELECT count(*) FROM projects WHERE source = 'lbnl'").fetchone()
    assert base is not None and base[0] == PROJECTS_WRITTEN


def test_the_duplicate_natural_keys_are_dropped_with_reason(report: IngestReport) -> None:
    assert report.rows_dropped == DUPLICATE_ROWS
    assert report.rows_read == report.rows_written + report.rows_dropped
    assert all("duplicate natural key" in d.reason for d in report.dropped)


@pytest.mark.usefixtures("report")
def test_study_region_is_null_for_every_lbnl_row(conn_module: Conn) -> None:
    # LBNL has no sub-ISO grain (ADR-0001); study_region must be NULL on all of it.
    populated = conn_module.execute(
        "SELECT count(*) FROM lbnl_projects WHERE study_region IS NOT NULL"
    ).fetchone()
    assert populated is not None and populated[0] == 0


@pytest.mark.usefixtures("report")
def test_iso_rows_and_non_iso_rows_partition_the_data(conn_module: Conn) -> None:
    # Every row is either an ISO row (iso set, non_iso_entity NULL) or a non-ISO catch-all
    # (iso NULL, non_iso_entity set) — never both, never neither.
    iso_rows = conn_module.execute(
        "SELECT count(*) FROM lbnl_projects WHERE iso IS NOT NULL AND non_iso_entity IS NULL"
    ).fetchone()
    non_iso_rows = conn_module.execute(
        "SELECT count(*) FROM lbnl_projects WHERE iso IS NULL AND non_iso_entity IS NOT NULL"
    ).fetchone()
    both_or_neither = conn_module.execute(
        "SELECT count(*) FROM lbnl_projects WHERE (iso IS NULL) = (non_iso_entity IS NULL)"
    ).fetchone()
    assert iso_rows is not None and iso_rows[0] == ISO_PROJECTS
    assert non_iso_rows is not None and non_iso_rows[0] == NON_ISO_PROJECTS
    assert both_or_neither is not None and both_or_neither[0] == 0


@pytest.mark.usefixtures("report")
def test_west_and_southeast_are_the_only_non_iso_entities(conn_module: Conn) -> None:
    # ADR-0001: the catch-alls are the sole source of non-ISO rows; no ISO name leaks into
    # non_iso_entity and "West"/"Southeast" never appear in the iso column.
    leaked = conn_module.execute(
        "SELECT count(*) FROM lbnl_projects WHERE iso IN ('West', 'Southeast')"
    ).fetchone()
    assert leaked is not None and leaked[0] == 0


@pytest.mark.usefixtures("report")
def test_maps_a_known_iso_project_into_the_canonical_schema(conn_module: Conn) -> None:
    # AVENAL ENERGY PROJECT — LBNL q_id 10 under entity CAISO, the first CAISO row. Its cells
    # are read straight off the sheet, pinning the column mapping end to end.
    row = conn_module.execute(
        "SELECT source, status, iso, study_region, non_iso_entity, county, state, utility, "
        "       raw_poi, normalized_poi, poi_unmapped, q_date, ia_date "
        "FROM lbnl_projects WHERE native_id = 'CAISO / 10'"
    ).fetchone()
    assert row == (
        "lbnl",
        "Withdrawn",
        "CAISO",  # region CAISO -> iso
        None,  # no sub-ISO grain
        None,  # an ISO row, so no non_iso_entity
        "Kings",
        "CA",
        "PGAE",
        "Gates Substation (Arco - Gates 230 kV line)",  # raw_poi, verbatim
        None,  # LBNL's own normalization is not the reviewed CAISO alias table
        False,  # no alias resolution attempted, so not flagged unmapped
        datetime.date(2001, 5, 2),
        None,
    )


@pytest.mark.usefixtures("report")
def test_maps_a_known_non_iso_project_with_iso_null(conn_module: Conn) -> None:
    # A West (non-ISO) row: entity APS, q_id "not assigned". iso is NULL and non_iso_entity
    # carries the balancing-area name from the entity field — never stored as an ISO.
    row = conn_module.execute(
        "SELECT status, iso, non_iso_entity, study_region, county, state "
        "FROM lbnl_projects WHERE native_id = 'APS / not assigned'"
    ).fetchone()
    assert row == ("Withdrawn", None, "APS", None, "Coconino", "AZ")


@pytest.mark.usefixtures("report")
def test_a_hybrid_project_produces_one_child_row_per_type(conn_module: Conn) -> None:
    # APS q_id Q173 is Solar+Gas: two type/MW pairs -> two child rows keyed on fuel. Solar
    # carries its 620 MW; Gas has no MW in the file (imputed capacity is excluded), so its
    # child row stores NULL rather than a fabricated zero.
    rows = conn_module.execute(
        "SELECT type, mw FROM project_resources "
        "WHERE source = 'lbnl' AND native_id = 'APS / Q173' ORDER BY type"
    ).fetchall()
    assert rows == [("Gas", None), ("Solar", 620.0)]


def test_reingest_is_idempotent_on_the_natural_key(report: IngestReport, conn_module: Conn) -> None:
    # Re-running upserts every project and resource in place: counts unchanged, a known
    # project keeps its field values, no duplicate row appears.
    before = conn_module.execute(
        "SELECT status, raw_poi, iso FROM lbnl_projects WHERE native_id = 'CAISO / 10'"
    ).fetchone()

    second = run_lbnl_ingest(WORKBOOK, conn_module)

    assert second.rows_written == report.rows_written
    assert second.resources_written == report.resources_written
    projects = conn_module.execute("SELECT count(*) FROM lbnl_projects").fetchone()
    assert projects is not None and projects[0] == PROJECTS_WRITTEN
    after = conn_module.execute(
        "SELECT status, raw_poi, iso FROM lbnl_projects WHERE native_id = 'CAISO / 10'"
    ).fetchone()
    assert after == before


def test_report_names_the_complete_queue_sheet(report: IngestReport) -> None:
    assert len(report.sheets) == 1
    assert report.for_sheet(COMPLETE_QUEUE_SHEET).rows_written == PROJECTS_WRITTEN
