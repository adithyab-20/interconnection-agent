"""Ingest: hand-rolled ETL from the frozen source workbooks into the canonical schema.

The public surface is the CAISO reader (active, completed, and withdrawn sheets) and the
per-sheet report it returns. A later ticket adds the LBNL reader behind this same boundary.
"""

from __future__ import annotations

from interconnection_agent.ingest.caiso import run_caiso_ingest
from interconnection_agent.ingest.report import DroppedRow, IngestReport, SheetReport

__all__ = ["DroppedRow", "IngestReport", "SheetReport", "run_caiso_ingest"]
