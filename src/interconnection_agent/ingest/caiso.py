"""Hand-rolled reader for CAISO's public queue workbook — all three sheets.

CAISO publishes its queue as an Excel workbook with three tabs — the active queue, the
completed (energized) projects, and the withdrawn ones — each putting headers on row 4 and
data from row 5, with the operator's own free-text station strings and a queue position
that serves as the natural key. This module reads all three and lands each project in the
canonical ``projects`` table, keyed on ``(source, native_id)`` so a re-run upserts in place
rather than duplicating (golden eval cases store these ids). Holding the outcomes and not
just the pending snapshot is what makes Time-to-Energization and Withdrawal computable.

The three sheets share a layout but differ at the edges, and those differences are the
point of this reader:

  * the active sheet's status is ``ACTIVE``, completed is ``COMPLETED``, withdrawn is
    ``WITHDRAWN`` — each mapped to a canonical token through the reviewed
    :data:`~interconnection_agent.ingest.status.STATUS_MAP`, kept as explicit configuration
    a reviewer can read without this module;
  * completed rows carry an ``Actual On-line Date`` (real energization) that active and
    withdrawn rows do not; withdrawn rows carry a ``Withdrawn Date``; the withdrawn sheet
    has no ``PTO Study Region`` column at all. Missing columns resolve to NULL, not error.

Each row's up-to-three ``Fuel``/``MW`` triples become ``project_resources`` child rows so a
hybrid (solar + storage) is stored as child rows rather than crammed into repeated columns.
Fuel — not the finer prime-mover ``Type`` — is the child key, because LBNL's national file
is fuel-grained and the two sources must stay comparable for the cross-source check. MW is
summed per fuel within a project, since the child key is ``(source, native_id, type)`` and
a row can list the same fuel twice (e.g. two battery blocks).

Each row's station string is resolved to a canonical POI through the reviewed alias table
(ticket 5) by exact match — never fuzzy. A row whose string has no reviewed entry lands
with ``normalized_poi`` NULL and ``poi_unmapped`` true, and is counted (with its MW) in the
per-sheet report rather than guessed. The alias table was reviewed against the active queue
to clear the <2%-of-active-MW bar; the completed and withdrawn sheets name many stations it
never saw, so their unmapped shares are expected to be high and are reported, not judged.

The column mapping is expressed against each sheet's own header text, not bare column
indices, so a reviewer can see which CAISO field feeds which canonical column.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import openpyxl
import psycopg

from interconnection_agent.ingest import _cells
from interconnection_agent.ingest.report import DroppedRow, IngestReport, SheetReport
from interconnection_agent.ingest.status import canonical_status
from interconnection_agent.poi import AliasTable, load_alias_table

# The active sheet's name — the one the alias table was reviewed against, so its POI
# coverage is the figure the <2% stopping criterion is judged on (also imported by the
# LBNL cross-check test).
ACTIVE_SHEET = "Grid GenerationQueue"

# Headers sit on row 4, data begins on row 5 (CAISO's fixed layout, on every sheet).
HEADER_ROW = 4
FIRST_DATA_ROW = 5

# Canonical column <- CAISO header (whitespace-normalized). Kept as data so the mapping
# reads as a table a reviewer can check against the spreadsheet, not as buried lookups.
QUEUE_POSITION = "Queue Position"
QUEUE_DATE = "Queue Date"
APPLICATION_STATUS = "Application Status"
COUNTY = "County"
STATE = "State"
UTILITY = "Utility"
PTO_STUDY_REGION = "PTO Study Region"  # active + completed only; absent on withdrawn
STATION = "Station or Transmission Line"
NET_MW_TO_GRID = "Net MWs to Grid"
PROPOSED_ONLINE_DATE = "Proposed On-line Date (as filed with IR)"
ACTUAL_ONLINE_DATE = "Actual On-line Date"  # completed sheet: real energization date
WITHDRAWN_DATE = "Withdrawn Date"  # withdrawn sheet: the date the request left the queue

# The up-to-three fuel/MW triples, by header. Type is read too (below) but not stored:
# the canonical resource key is fuel, for cross-source comparability with LBNL.
FUEL_HEADERS = ("Fuel-1", "Fuel-2", "Fuel-3")
MW_HEADERS = ("MW-1", "MW-2", "MW-3")


@dataclass(frozen=True)
class SheetSpec:
    """One CAISO sheet and the two date columns that distinguish it from the others."""

    name: str
    actual_online_header: str | None  # -> actual_online_date (completed sheet only)
    withdrawn_date_header: str | None  # -> withdrawn_date (withdrawn sheet only)


# The workbook's three tabs, in read order. The shared columns are read the same way on
# each; only the two per-sheet date columns and the absent study-region column differ.
SHEETS: tuple[SheetSpec, ...] = (
    SheetSpec(ACTIVE_SHEET, actual_online_header=None, withdrawn_date_header=None),
    SheetSpec(
        "Completed Generation Projects",
        actual_online_header=ACTUAL_ONLINE_DATE,
        withdrawn_date_header=None,
    ),
    SheetSpec(
        "Withdrawn Generation Projects",
        actual_online_header=None,
        withdrawn_date_header=WITHDRAWN_DATE,
    ),
)


def _native_id(queue_position: object) -> str:
    """Build the natural-key id from the queue position (e.g. 22 -> ``CAISO-0022``).

    Pure-integer positions are zero-padded to four digits for stable, sortable ids;
    positions carrying a revision suffix (``643R``) are kept as the operator wrote them.
    """
    if isinstance(queue_position, bool):  # bool is an int subclass; never a queue id
        raise TypeError("queue position cannot be a boolean")
    if isinstance(queue_position, int):
        return f"CAISO-{queue_position:04d}"
    if isinstance(queue_position, float) and queue_position.is_integer():
        return f"CAISO-{int(queue_position):04d}"
    return f"CAISO-{str(queue_position).strip()}"


def _mw(value: object) -> float:
    """A Net-MW quantity for coverage sums; a blank or non-numeric cell contributes zero."""
    return _cells.mw_or_none(value) or 0.0


_UPSERT = """
    INSERT INTO projects (
        source, native_id, status, q_date, proposed_online_date, actual_online_date,
        withdrawn_date, county, state, iso, study_region, raw_poi, normalized_poi,
        poi_unmapped, utility
    ) VALUES (
        'caiso_raw', %(native_id)s, %(status)s, %(q_date)s, %(proposed_online_date)s,
        %(actual_online_date)s, %(withdrawn_date)s, %(county)s, %(state)s, 'CAISO',
        %(study_region)s, %(raw_poi)s, %(normalized_poi)s, %(poi_unmapped)s, %(utility)s
    )
    ON CONFLICT (source, native_id) DO UPDATE SET
        status               = EXCLUDED.status,
        q_date               = EXCLUDED.q_date,
        proposed_online_date = EXCLUDED.proposed_online_date,
        actual_online_date   = EXCLUDED.actual_online_date,
        withdrawn_date       = EXCLUDED.withdrawn_date,
        county               = EXCLUDED.county,
        state                = EXCLUDED.state,
        study_region         = EXCLUDED.study_region,
        raw_poi              = EXCLUDED.raw_poi,
        normalized_poi       = EXCLUDED.normalized_poi,
        poi_unmapped         = EXCLUDED.poi_unmapped,
        utility              = EXCLUDED.utility
"""

_UPSERT_RESOURCE = """
    INSERT INTO project_resources (source, native_id, type, mw)
    VALUES ('caiso_raw', %(native_id)s, %(type)s, %(mw)s)
    ON CONFLICT (source, native_id, type) DO UPDATE SET mw = EXCLUDED.mw
"""


def run_caiso_ingest(
    workbook_path: Path, conn: psycopg.Connection[tuple[object, ...]]
) -> IngestReport:
    """Ingest CAISO's active, completed, and withdrawn sheets into the canonical schema.

    Returns an :class:`IngestReport` with a per-sheet breakdown. Idempotent on the natural
    key: re-running upserts every project and resource row in place, so counts and field
    values are unchanged on a second pass. Does not commit — the caller owns the transaction
    boundary, matching :func:`interconnection_agent.migrate.apply_migrations`.
    """
    alias_table = load_alias_table()
    workbook = openpyxl.load_workbook(workbook_path, read_only=True, data_only=True)
    try:
        return IngestReport(
            sheets=tuple(_ingest_sheet(workbook, spec, alias_table, conn) for spec in SHEETS)
        )
    finally:
        workbook.close()


def _ingest_sheet(
    workbook: openpyxl.Workbook,
    spec: SheetSpec,
    alias_table: AliasTable,
    conn: psycopg.Connection[tuple[object, ...]],
) -> SheetReport:
    """Ingest one CAISO sheet into ``projects`` (+ ``project_resources``); return its report."""
    sheet = workbook[spec.name]
    columns = _cells.header_index(sheet, HEADER_ROW)

    def cell(row: tuple[object, ...], header: str) -> object:
        """Read a cell by header; a column absent from this sheet reads as NULL."""
        index = columns.get(header)
        if index is None or index >= len(row):
            return None
        return row[index]

    def fuels(row: tuple[object, ...]) -> tuple[dict[str, float], int]:
        by_fuel: dict[str, float] = {}
        skipped = 0
        for fuel_header, mw_header in zip(FUEL_HEADERS, MW_HEADERS, strict=True):
            fuel = _cells.clean(cell(row, fuel_header))
            mw = _cells.mw_or_none(cell(row, mw_header))
            if fuel is None and mw is None:
                continue  # an empty triple is not a resource
            if fuel is None:
                skipped += 1  # MW with no fuel label: no child key, so reported not stored
                continue
            by_fuel[fuel] = by_fuel.get(fuel, 0.0) + (mw or 0.0)
        return by_fuel, skipped

    rows_read = 0
    rows_written = 0
    resources_written = 0
    resources_skipped = 0
    unmapped_rows = 0
    mw_written = 0.0
    unmapped_mw = 0.0
    dropped: list[DroppedRow] = []

    for offset, row in enumerate(sheet.iter_rows(min_row=FIRST_DATA_ROW, values_only=True)):
        row_number = FIRST_DATA_ROW + offset
        if all(value is None for value in row):
            continue  # trailing blank rows are not records, not drops
        rows_read += 1

        queue_position = cell(row, QUEUE_POSITION)
        if queue_position is None or _cells.clean(queue_position) is None:
            # Footer notes and the disclaimer live in the data range but carry no queue
            # position; without the natural key they are not projects.
            dropped.append(DroppedRow(spec.name, row_number, "no queue position"))
            continue

        raw_status = _cells.clean(cell(row, APPLICATION_STATUS))
        status = canonical_status(raw_status) if raw_status else None
        if status is None:
            dropped.append(
                DroppedRow(
                    spec.name,
                    row_number,
                    f"unrecognized status: {raw_status!r}",
                    category="unrecognized status",
                )
            )
            continue

        native_id = _native_id(queue_position)
        raw_poi = _cells.verbatim(cell(row, STATION))
        normalized_poi = alias_table.resolve(raw_poi)
        poi_unmapped = normalized_poi is None
        mw = _mw(cell(row, NET_MW_TO_GRID))

        conn.execute(
            _UPSERT,
            {
                "native_id": native_id,
                "status": status,
                "q_date": _cells.as_date(cell(row, QUEUE_DATE)),
                "proposed_online_date": _cells.as_date(cell(row, PROPOSED_ONLINE_DATE)),
                "actual_online_date": (
                    _cells.as_date(cell(row, spec.actual_online_header))
                    if spec.actual_online_header
                    else None
                ),
                "withdrawn_date": (
                    _cells.as_date(cell(row, spec.withdrawn_date_header))
                    if spec.withdrawn_date_header
                    else None
                ),
                "county": _cells.clean(cell(row, COUNTY)),
                "state": _cells.clean(cell(row, STATE)),
                "study_region": _cells.clean(cell(row, PTO_STUDY_REGION)),
                "raw_poi": raw_poi,
                "normalized_poi": normalized_poi,
                "poi_unmapped": poi_unmapped,
                "utility": _cells.clean(cell(row, UTILITY)),
            },
        )
        rows_written += 1
        mw_written += mw
        if poi_unmapped:
            unmapped_rows += 1
            unmapped_mw += mw

        by_fuel, skipped = fuels(row)
        resources_skipped += skipped
        for fuel, fuel_mw in by_fuel.items():
            conn.execute(
                _UPSERT_RESOURCE,
                {"native_id": native_id, "type": fuel, "mw": fuel_mw},
            )
            resources_written += 1

    return SheetReport(
        sheet=spec.name,
        rows_read=rows_read,
        rows_written=rows_written,
        resources_written=resources_written,
        resources_skipped=resources_skipped,
        dropped=tuple(dropped),
        unmapped_rows=unmapped_rows,
        mw_written=mw_written,
        unmapped_mw=unmapped_mw,
    )
