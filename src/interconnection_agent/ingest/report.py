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
    """The outcome of an ingest run: what was read, written, and dropped-with-reason.

    POI coverage is measured here too, so an unmapped row is a reported number rather than
    a silent exclusion: ``unmapped_rows`` counts written rows whose station string had no
    reviewed alias, and ``unmapped_mw`` / ``active_mw`` express that as a share of
    active-queue MW — the figure the <2% stopping criterion is judged against.
    """

    rows_read: int
    rows_written: int
    dropped: tuple[DroppedRow, ...] = ()
    unmapped_rows: int = 0
    active_mw: float = 0.0
    unmapped_mw: float = 0.0

    @property
    def rows_dropped(self) -> int:
        return len(self.dropped)

    @property
    def unmapped_mw_share(self) -> float:
        """Unmapped MW as a fraction of active-queue MW; 0.0 when no MW was ingested."""
        return self.unmapped_mw / self.active_mw if self.active_mw else 0.0
