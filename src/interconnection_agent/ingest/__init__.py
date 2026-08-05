"""Ingest: hand-rolled ETL from the frozen source workbooks into the canonical schema.

The public surface is the CAISO active-sheet reader and the report it returns. Later
tickets add the completed/withdrawn sheets and the LBNL reader behind this same boundary.
"""

from __future__ import annotations

from interconnection_agent.ingest.caiso import run_caiso_ingest
from interconnection_agent.ingest.report import DroppedRow, IngestReport

__all__ = ["DroppedRow", "IngestReport", "run_caiso_ingest"]
