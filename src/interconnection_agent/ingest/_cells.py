"""Workbook-cell coercions shared by the CAISO and LBNL readers.

Both readers face the same raw-cell problems — a header row whose text carries stray
newlines, date cells that arrive as datetimes, text cells that are blank-but-not-None, MW
cells that might be a string or a stray boolean. The coercions are identical across sources,
so they live here once rather than being copied per reader; in particular the load-bearing
"a boolean is never a quantity" guard in :func:`mw_or_none` has a single home. The
source-specific decisions (which header feeds which column, how a natural key is built, how a
missing MW is aggregated) stay in each reader, where they belong.
"""

from __future__ import annotations

import datetime

from openpyxl.worksheet.worksheet import Worksheet


def normalize_header(value: object) -> str:
    """Collapse a header cell's internal newlines/whitespace to a single-spaced string."""
    return " ".join(str(value).split()) if value is not None else ""


def header_index(sheet: Worksheet, header_row: int) -> dict[str, int]:
    """Map each normalized header on ``header_row`` to its 0-based position in that row."""
    header_cells = next(sheet.iter_rows(min_row=header_row, max_row=header_row, values_only=True))
    return {normalize_header(v): i for i, v in enumerate(header_cells) if v is not None}


def as_date(value: object) -> datetime.date | None:
    """Coerce a workbook cell to a date; times of day are dropped, blanks stay NULL."""
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    return None


def clean(value: object) -> str | None:
    """Trim a text cell, treating an all-whitespace or empty cell as NULL."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def verbatim(value: object) -> str | None:
    """Return a text cell exactly as the operator wrote it — no trimming.

    Used for provenance fields such as ``raw_poi``, which must reproduce the original cell so
    a reader can always see the source string. Only a truly empty cell is NULL.
    """
    return str(value) if value is not None else None


def mw_or_none(value: object) -> float | None:
    """Coerce an MW cell to a float, or ``None`` when it is blank or non-numeric.

    A boolean is never a quantity (``bool`` is an ``int`` subclass), so it too reads as
    ``None``.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if value is not None:
        try:
            return float(str(value).strip())
        except ValueError:
            return None
    return None
