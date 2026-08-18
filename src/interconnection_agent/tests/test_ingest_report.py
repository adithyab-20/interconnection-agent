"""Unit tests for IngestReport's derived accounting — pure, no database.

The per-run counts are populated by the ETL and asserted end-to-end in the integration
suite; here we pin the derived arithmetic in isolation, including the divide-by-zero guard
for a run that ingested no MW.
"""

from __future__ import annotations

from interconnection_agent.ingest import IngestReport


def test_unmapped_share_is_unmapped_over_active_mw() -> None:
    report = IngestReport(
        rows_read=10, rows_written=10, unmapped_rows=1, active_mw=1000.0, unmapped_mw=15.0
    )
    assert report.unmapped_mw_share == 0.015


def test_unmapped_share_is_zero_when_no_mw_was_ingested() -> None:
    # An empty run must not raise ZeroDivisionError; zero MW means zero share.
    report = IngestReport(rows_read=0, rows_written=0)
    assert report.unmapped_mw_share == 0.0
