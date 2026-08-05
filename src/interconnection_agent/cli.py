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
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import psycopg

from interconnection_agent.db import connect
from interconnection_agent.ingest import run_caiso_ingest

Conn = psycopg.Connection[tuple[object, ...]]

# The shape of one row the county query returns, in the column order selected below.
# The named-tuple positions line up with ActiveProject's fields, so a row maps to one
# with ActiveProject(*row) once cast from the connection's untyped tuple[object, ...].
ProjectRow = tuple[
    str,
    str | None,
    str | None,
    str | None,
    str | None,
    datetime.date | None,
    datetime.date | None,
]


@dataclass(frozen=True)
class ActiveProject:
    """One active project as the county listing presents it (a view row, flattened)."""

    native_id: str
    county: str | None
    study_region: str | None
    raw_poi: str | None
    utility: str | None
    q_date: datetime.date | None
    proposed_online_date: datetime.date | None


def list_active_projects(conn: Conn, county: str) -> list[ActiveProject]:
    """Return the active CAISO projects in ``county`` (case-insensitive), ordered by id.

    Reads the per-source view so only CAISO rows are considered. All narrowing happens in
    SQL — the caller never post-filters a broader result set.
    """
    rows = conn.execute(
        "SELECT native_id, county, study_region, raw_poi, utility, q_date, "
        "       proposed_online_date "
        "FROM caiso_projects "
        "WHERE status = 'Active' AND upper(county) = upper(%s) "
        "ORDER BY native_id",
        (county,),
    ).fetchall()
    return [ActiveProject(*cast(ProjectRow, r)) for r in rows]


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
