"""The report every ingest run returns, so fidelity is measured rather than assumed.

An ETL that silently drops rows is indistinguishable from one that read them all. The
report makes the difference observable: for each of CAISO's three sheets, how many rows
were read, written, and — for each row that did not make it — why. The counts are kept
per sheet (ticket #6) because the sheets differ in size and vocabulary, and because the
POI-coverage stopping criterion is defined on the *active* queue alone: the completed and
withdrawn sheets carry stations the active-queue alias table was never reviewed against,
so their unmapped shares are expected to be high and are not judged against the <2% bar.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DroppedRow:
    """One source row the ETL refused, with the reason a reviewer can act on.

    ``reason`` is the human-facing detail (it names the offending value); ``category`` is the
    machine-facing bucket a summary groups on, so a caller counts drops by kind without
    parsing the reason string. ``category`` defaults to ``reason`` for the callers that carry
    no distinct detail.
    """

    sheet: str
    row_number: int  # 1-based row in the worksheet, so it points at a real cell
    reason: str
    category: str = ""

    def __post_init__(self) -> None:
        if not self.category:
            object.__setattr__(self, "category", self.reason)


@dataclass(frozen=True)
class SheetReport:
    """The outcome of ingesting one CAISO sheet: read, written, dropped, and POI coverage.

    ``resources_written`` counts the ``project_resources`` child rows landed from this
    sheet's fuel/MW triples (aggregated per fuel within a project). ``resources_skipped``
    counts triples that carried an MW quantity but no fuel label, which cannot become a
    child row — the schema keys resources on their type — and so are reported rather than
    dropped silently.

    POI coverage is measured here too: ``unmapped_rows`` counts written rows whose station
    string had no reviewed alias, and ``unmapped_mw`` / ``mw_written`` express that as a
    share of the sheet's Net-MW — the figure the active sheet's <2% stopping criterion is
    judged against.
    """

    sheet: str
    rows_read: int
    rows_written: int
    resources_written: int = 0
    resources_skipped: int = 0
    dropped: tuple[DroppedRow, ...] = ()
    unmapped_rows: int = 0
    mw_written: float = 0.0
    unmapped_mw: float = 0.0

    @property
    def rows_dropped(self) -> int:
        return len(self.dropped)

    @property
    def unmapped_mw_share(self) -> float:
        """Unmapped MW as a fraction of the sheet's written MW; 0.0 when none was ingested."""
        return self.unmapped_mw / self.mw_written if self.mw_written else 0.0


@dataclass(frozen=True)
class IngestReport:
    """An ingest run across CAISO's sheets: one :class:`SheetReport` per sheet.

    The aggregate counts are derived from the per-sheet reports so the two can never drift.
    """

    sheets: tuple[SheetReport, ...] = field(default_factory=tuple)

    def for_sheet(self, sheet: str) -> SheetReport:
        """Return the sub-report for ``sheet``; raise ``KeyError`` if it was not ingested."""
        for report in self.sheets:
            if report.sheet == sheet:
                return report
        raise KeyError(sheet)

    @property
    def rows_read(self) -> int:
        return sum(s.rows_read for s in self.sheets)

    @property
    def rows_written(self) -> int:
        return sum(s.rows_written for s in self.sheets)

    @property
    def resources_written(self) -> int:
        return sum(s.resources_written for s in self.sheets)

    @property
    def resources_skipped(self) -> int:
        return sum(s.resources_skipped for s in self.sheets)

    @property
    def dropped(self) -> tuple[DroppedRow, ...]:
        return tuple(d for s in self.sheets for d in s.dropped)

    @property
    def rows_dropped(self) -> int:
        return len(self.dropped)
