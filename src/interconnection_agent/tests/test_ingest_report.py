"""Unit tests for the report's derived accounting — pure, no database.

The per-run counts are populated by the ETL and asserted end-to-end in the integration
suite; here we pin the derived arithmetic in isolation: a sheet's unmapped MW share (with
its divide-by-zero guard) and the aggregate roll-up across sheets.
"""

from __future__ import annotations

from interconnection_agent.ingest import DroppedRow, IngestReport, SheetReport


def test_unmapped_share_is_unmapped_over_written_mw() -> None:
    sheet = SheetReport(
        sheet="s", rows_read=10, rows_written=10, unmapped_rows=1, mw_written=1000.0,
        unmapped_mw=15.0,
    )
    assert sheet.unmapped_mw_share == 0.015


def test_unmapped_share_is_zero_when_no_mw_was_ingested() -> None:
    # An empty run must not raise ZeroDivisionError; zero MW means zero share.
    sheet = SheetReport(sheet="s", rows_read=0, rows_written=0)
    assert sheet.unmapped_mw_share == 0.0


def test_aggregate_counts_roll_up_the_per_sheet_reports() -> None:
    report = IngestReport(
        sheets=(
            SheetReport(
                sheet="a", rows_read=5, rows_written=4, resources_written=6,
                resources_skipped=2, dropped=(DroppedRow("a", 9, "no queue position"),),
            ),
            SheetReport(
                sheet="b", rows_read=3, rows_written=3, resources_written=2,
            ),
        )
    )
    assert report.rows_read == 8
    assert report.rows_written == 7
    assert report.resources_written == 8
    assert report.resources_skipped == 2
    assert report.rows_dropped == 1
    assert report.for_sheet("b").rows_written == 3


def test_for_sheet_raises_for_an_uningested_sheet() -> None:
    report = IngestReport(sheets=(SheetReport(sheet="a", rows_read=0, rows_written=0),))
    try:
        report.for_sheet("missing")
    except KeyError:
        return
    raise AssertionError("expected KeyError for an uningested sheet")
