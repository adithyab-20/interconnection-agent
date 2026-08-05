"""Hand-rolled reader for CAISO's public queue workbook — the active sheet.

CAISO publishes its queue as an Excel workbook whose active sheet puts headers on row 4
and data from row 5, with the operator's own free-text station strings and a queue
position that serves as the natural key. This module reads that sheet and lands each
project in the canonical ``projects`` table, keyed on ``(source, native_id)`` so a re-run
upserts in place rather than duplicating (golden eval cases store these ids).

Scope, deliberately narrow (ticket 4, the walking skeleton):
  * active sheet only — completed and withdrawn come later (ticket 6);
  * parent ``projects`` rows only — the multi-fuel ``project_resources`` child rows are
    ticket 6, so nothing is written to that table here;
  * ``normalized_poi`` is left NULL and ``poi_unmapped`` true — the reviewed alias table
    is ticket 5, and a guessed normalization is worse than an honest "unmapped".

The column mapping is expressed against the sheet's own header text, not bare column
indices, so a reviewer can see which CAISO field feeds which canonical column.
"""

from __future__ import annotations

import datetime
from pathlib import Path

import openpyxl
import psycopg
from openpyxl.worksheet.worksheet import Worksheet

from interconnection_agent.ingest.report import DroppedRow, IngestReport

# The workbook's three tabs; only the first is in scope for this ticket.
ACTIVE_SHEET = "Grid GenerationQueue"

# Headers sit on row 4, data begins on row 5 (CAISO's fixed layout).
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
PTO_STUDY_REGION = "PTO Study Region"
STATION = "Station or Transmission Line"
PROPOSED_ONLINE_DATE = "Proposed On-line Date (as filed with IR)"

# CAISO's status vocabulary -> the canonical set. The active sheet only ever says ACTIVE;
# the full mapping across every sheet's vocabulary is ticket 6's explicit configuration.
STATUS_MAP = {"ACTIVE": "Active"}


def _normalize_header(value: object) -> str:
    """Collapse a header cell's internal newlines/whitespace to a single-spaced string."""
    return " ".join(str(value).split()) if value is not None else ""


def _header_index(sheet: Worksheet) -> dict[str, int]:
    """Map each normalized header on the header row to its 0-based position in the row."""
    header_cells = next(sheet.iter_rows(min_row=HEADER_ROW, max_row=HEADER_ROW, values_only=True))
    return {_normalize_header(v): i for i, v in enumerate(header_cells) if v is not None}


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


def _as_date(value: object) -> datetime.date | None:
    """Coerce a workbook cell to a date; times of day are dropped, blanks stay NULL."""
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    return None


def _clean(value: object) -> str | None:
    """Trim a text cell, treating an all-whitespace or empty cell as NULL."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _verbatim(value: object) -> str | None:
    """Return a text cell exactly as the operator wrote it — no trimming.

    ``raw_poi`` is a provenance field: it must reproduce the original cell so a
    reader can always see the operator's string. Only a truly empty cell is NULL.
    """
    return str(value) if value is not None else None


_UPSERT = """
    INSERT INTO projects (
        source, native_id, status, q_date, proposed_online_date,
        county, state, iso, study_region, raw_poi, normalized_poi, poi_unmapped, utility
    ) VALUES (
        'caiso_raw', %(native_id)s, %(status)s, %(q_date)s, %(proposed_online_date)s,
        %(county)s, %(state)s, 'CAISO', %(study_region)s, %(raw_poi)s, NULL, true, %(utility)s
    )
    ON CONFLICT (source, native_id) DO UPDATE SET
        status               = EXCLUDED.status,
        q_date               = EXCLUDED.q_date,
        proposed_online_date = EXCLUDED.proposed_online_date,
        county               = EXCLUDED.county,
        state                = EXCLUDED.state,
        study_region         = EXCLUDED.study_region,
        raw_poi              = EXCLUDED.raw_poi,
        normalized_poi       = EXCLUDED.normalized_poi,
        poi_unmapped         = EXCLUDED.poi_unmapped,
        utility              = EXCLUDED.utility
"""


def run_caiso_ingest(
    workbook_path: Path, conn: psycopg.Connection[tuple[object, ...]]
) -> IngestReport:
    """Ingest CAISO's active sheet into ``projects``; return what happened.

    Idempotent on the natural key: re-running upserts every row in place, so counts and
    field values are unchanged on a second pass. Does not commit — the caller owns the
    transaction boundary, matching :func:`interconnection_agent.migrate.apply_migrations`.
    """
    workbook = openpyxl.load_workbook(workbook_path, read_only=True, data_only=True)
    try:
        sheet = workbook[ACTIVE_SHEET]
        columns = _header_index(sheet)

        def cell(row: tuple[object, ...], header: str) -> object:
            index = columns[header]
            return row[index] if index < len(row) else None

        rows_read = 0
        rows_written = 0
        dropped: list[DroppedRow] = []

        for offset, row in enumerate(sheet.iter_rows(min_row=FIRST_DATA_ROW, values_only=True)):
            row_number = FIRST_DATA_ROW + offset
            if all(value is None for value in row):
                continue  # trailing blank rows are not records, not drops
            rows_read += 1

            queue_position = cell(row, QUEUE_POSITION)
            if queue_position is None or _clean(queue_position) is None:
                # Footer notes and the disclaimer live in the data range but carry no
                # queue position; without the natural key they are not projects.
                dropped.append(DroppedRow(ACTIVE_SHEET, row_number, "no queue position"))
                continue

            raw_status = _clean(cell(row, APPLICATION_STATUS))
            status = STATUS_MAP.get(raw_status.upper()) if raw_status else None
            if status is None:
                dropped.append(
                    DroppedRow(ACTIVE_SHEET, row_number, f"unrecognized status: {raw_status!r}")
                )
                continue

            conn.execute(
                _UPSERT,
                {
                    "native_id": _native_id(queue_position),
                    "status": status,
                    "q_date": _as_date(cell(row, QUEUE_DATE)),
                    "proposed_online_date": _as_date(cell(row, PROPOSED_ONLINE_DATE)),
                    "county": _clean(cell(row, COUNTY)),
                    "state": _clean(cell(row, STATE)),
                    "study_region": _clean(cell(row, PTO_STUDY_REGION)),
                    "raw_poi": _verbatim(cell(row, STATION)),
                    "utility": _clean(cell(row, UTILITY)),
                },
            )
            rows_written += 1

        return IngestReport(rows_read=rows_read, rows_written=rows_written, dropped=tuple(dropped))
    finally:
        workbook.close()
