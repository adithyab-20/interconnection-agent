"""The report every ingest run returns, so fidelity is measured rather than assumed.

An ETL that silently drops rows is indistinguishable from one that read them all. The
report makes the difference observable: how many rows were read, how many written, and —
for each row that did not make it — why. Later tickets extend this (unmapped-POI MW in
ticket 5, per-sheet counts in ticket 6); the shape stays additive.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DroppedRow:
    """One source row the ETL refused, with the reason a reviewer can act on."""

    sheet: str
    row_number: int  # 1-based row in the worksheet, so it points at a real cell
    reason: str


@dataclass(frozen=True)
class IngestReport:
    """The outcome of an ingest run: what was read, written, and dropped-with-reason."""

    rows_read: int
    rows_written: int
    dropped: tuple[DroppedRow, ...] = ()

    @property
    def rows_dropped(self) -> int:
        return len(self.dropped)
