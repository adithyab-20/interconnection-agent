"""Command-line access to the ingested queue — the walking skeleton's front door.

Two subcommands:

  * ``ingest <workbook>`` — load CAISO's three sheets into the canonical schema and print
    the resulting per-sheet :class:`~interconnection_agent.ingest.report.IngestReport`;
  * ``projects --county <county>`` — list the active projects in a county;
  * ``projects --poi <name>`` — list the projects at a normalized (reviewed) POI.

Both listings read through the ``caiso_projects`` view, never the base table, so a project
that also appears in LBNL's national file cannot leak into a CAISO listing — the
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
    normalized_poi: str | None
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


def list_projects_at_poi(conn: Conn, poi: str) -> list[ActiveProject]:
    """Return the CAISO projects at a normalized POI (case-insensitive), ordered by id.

    Matches on ``normalized_poi``, the reviewed canonical name — so the reviewed aliases
    for one substation are grouped and the operator's raw spellings collapse into a single
    POI. Reads the per-source view; all narrowing happens in SQL. Rows left unmapped
    (``normalized_poi`` NULL) never match, so an unresolved string cannot masquerade as a
    POI hit.
    """
    with conn.cursor(row_factory=class_row(ActiveProject)) as cur:
        return cur.execute(
            f"SELECT {_PROJECT_COLUMNS} "
            "FROM caiso_projects "
            "WHERE upper(normalized_poi) = upper(%s) "
            "ORDER BY native_id",
            (poi,),
        ).fetchall()


def _date(value: datetime.date | None) -> str:
    return value.isoformat() if value is not None else "-"


def format_projects(projects: list[ActiveProject], scope: str) -> str:
    """Render a project listing as plain lines: a header, then one line per project.

    ``scope`` is the prepositional phrase naming what was queried — ``"in county
    'SOLANO'"`` or ``"at POI 'Birds Landing 230 kV'"`` — so the same renderer serves both
    listings and an empty result reads as an explicit "no matching evidence".
    """
    if not projects:
        return f"No CAISO projects {scope}."

    header = f"{len(projects)} CAISO project(s) {scope}:"
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
        f"Ingested CAISO: {report.rows_written} projects and "
        f"{report.resources_written} resources written, {report.rows_dropped} dropped, "
        f"{report.resources_skipped} resources skipped, {report.rows_read} read."
    )
    for sheet in report.sheets:
        print(
            f"  {sheet.sheet}: {sheet.rows_written} written, "
            f"{sheet.resources_written} resources ({sheet.resources_skipped} skipped), "
            f"{sheet.rows_dropped} dropped; POI {sheet.unmapped_rows} unmapped "
            f"({sheet.unmapped_mw:.0f} of {sheet.mw_written:.0f} MW, "
            f"{sheet.unmapped_mw_share:.2%})."
        )
    for dropped in report.dropped:
        print(f"  dropped {dropped.sheet} row {dropped.row_number}: {dropped.reason}")
    return 0


def _cmd_projects(args: argparse.Namespace) -> int:
    with connect() as conn:
        if args.poi is not None:
            projects = list_projects_at_poi(conn, args.poi)
            scope = f"at POI {args.poi!r}"
        else:
            projects = list_active_projects(conn, args.county)
            scope = f"in county {args.county!r}"
    print(format_projects(projects, scope=scope))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="interconnection-agent")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="load CAISO's three sheets into the schema")
    ingest.add_argument("workbook", help="path to publicqueuereport.xlsx")
    ingest.set_defaults(func=_cmd_ingest)

    projects = sub.add_parser("projects", help="list CAISO projects by county or normalized POI")
    scope = projects.add_mutually_exclusive_group(required=True)
    scope.add_argument("--county", help="county name (case-insensitive)")
    scope.add_argument("--poi", help="normalized POI name (case-insensitive)")
    projects.set_defaults(func=_cmd_projects)

    args = parser.parse_args(argv)
    func: object = args.func
    assert callable(func)
    return int(func(args))


if __name__ == "__main__":
    raise SystemExit(main())
