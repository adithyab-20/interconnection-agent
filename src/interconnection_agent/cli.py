"""Command-line access to the ingested queue — the walking skeleton's front door.

Two subcommands:

  * ``ingest <workbook>`` — load CAISO's active sheet into the canonical schema and print
    the resulting :class:`~interconnection_agent.ingest.report.IngestReport`;
  * ``projects --county <county>`` — list the active projects in a county.

The county listing reads through the ``caiso_projects`` view, never the base table, so a
project that also appears in LBNL's national file cannot leak into a CAISO listing — the
no-double-counting guarantee is structural (ADR-0001), not a WHERE clause to remember.
"""

from __future__ import annotations

import argparse
import datetime
from dataclasses import dataclass, fields
from pathlib import Path

import psycopg
from psycopg.rows import class_row

from interconnection_agent.db import connect
from interconnection_agent.ingest import run_caiso_ingest

Conn = psycopg.Connection[tuple[object, ...]]


@dataclass(frozen=True)
class ActiveProject:
    """One active project as the county listing presents it (a view row, flattened).

    This is the single source of truth for the county listing's shape: the SELECT column
    list is derived from these field names and rows are mapped back by name (see
    ``list_active_projects``), so adding a field here extends the query automatically.
    """

    native_id: str
    county: str | None
    study_region: str | None
    raw_poi: str | None
    utility: str | None
    q_date: datetime.date | None
    proposed_online_date: datetime.date | None


# The columns the county query selects, derived from ActiveProject so the two cannot drift.
# Field names match the caiso_projects view's columns; class_row maps rows back by name.
_PROJECT_COLUMNS = ", ".join(f.name for f in fields(ActiveProject))


def list_active_projects(conn: Conn, county: str) -> list[ActiveProject]:
    """Return the active CAISO projects in ``county`` (case-insensitive), ordered by id.

    Reads the per-source view so only CAISO rows are considered. All narrowing happens in
    SQL — the caller never post-filters a broader result set.
    """
    with conn.cursor(row_factory=class_row(ActiveProject)) as cur:
        return cur.execute(
            f"SELECT {_PROJECT_COLUMNS} "
            "FROM caiso_projects "
            "WHERE status = 'Active' AND upper(county) = upper(%s) "
            "ORDER BY native_id",
            (county,),
        ).fetchall()


def _date(value: datetime.date | None) -> str:
    return value.isoformat() if value is not None else "-"


def format_projects(projects: list[ActiveProject], county: str) -> str:
    """Render a county listing as plain lines: a header, then one line per project."""
    if not projects:
        return f"No active CAISO projects in county {county!r}."

    header = f"{len(projects)} active CAISO project(s) in county {county!r}:"
    lines = [
        f"  {p.native_id}  q={_date(p.q_date)}  online~{_date(p.proposed_online_date)}  "
        f"{p.utility or '-'}  {p.study_region or '-'}  {p.raw_poi or '-'}"
        for p in projects
    ]
    return "\n".join([header, *lines])


def _cmd_ingest(args: argparse.Namespace) -> int:
    with connect() as conn:
        report = run_caiso_ingest(Path(args.workbook), conn)
        conn.commit()
    print(
        f"Ingested CAISO active sheet: {report.rows_written} written, "
        f"{report.rows_dropped} dropped, {report.rows_read} read."
    )
    for dropped in report.dropped:
        print(f"  dropped row {dropped.row_number}: {dropped.reason}")
    return 0


def _cmd_projects(args: argparse.Namespace) -> int:
    with connect() as conn:
        projects = list_active_projects(conn, args.county)
    print(format_projects(projects, county=args.county))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="interconnection-agent")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="load CAISO's active sheet into the schema")
    ingest.add_argument("workbook", help="path to publicqueuereport.xlsx")
    ingest.set_defaults(func=_cmd_ingest)

    projects = sub.add_parser("projects", help="list active CAISO projects in a county")
    projects.add_argument("--county", required=True, help="county name (case-insensitive)")
    projects.set_defaults(func=_cmd_projects)

    args = parser.parse_args(argv)
    func: object = args.func
    assert callable(func)
    return int(func(args))


if __name__ == "__main__":
    raise SystemExit(main())
