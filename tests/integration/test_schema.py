"""The canonical schema's structural guarantees, proven against hand-seeded rows.

The load-bearing test is that a project present in *both* sources cannot be
double-counted: analysis reads a per-source view, and each view bakes in its own
source filter (ADR-0001). ``iso`` and ``study_region`` are separate columns and
must never be collapsed.
"""

import datetime

import psycopg
import pytest

Conn = psycopg.Connection[tuple[object, ...]]


def one(cur: psycopg.Cursor[tuple[object, ...]]) -> tuple[object, ...]:
    """Return the single row a query must have produced (fails loudly if none)."""
    row = cur.fetchone()
    assert row is not None
    return row


# Every column a project row carries, per the vertical-slice schema. Kept explicit
# so a dropped column is a failing test, not a silent gap.
PROJECT_COLUMNS = (
    "source",
    "native_id",
    "status",
    "q_date",
    "proposed_online_date",
    "actual_online_date",
    "withdrawn_date",
    "ia_date",
    "county",
    "state",
    "iso",
    "study_region",
    "non_iso_entity",
    "raw_poi",
    "normalized_poi",
    "poi_unmapped",
    "utility",
)


def insert_project(conn: Conn, **overrides: object) -> None:
    """Insert one project row, defaulting every unspecified column to NULL/false."""
    row: dict[str, object] = {col: None for col in PROJECT_COLUMNS}
    row["poi_unmapped"] = False
    row.update(overrides)
    cols = ", ".join(row)
    placeholders = ", ".join(f"%({c})s" for c in row)
    conn.execute(f"INSERT INTO projects ({cols}) VALUES ({placeholders})", row)


def insert_resource(conn: Conn, source: str, native_id: str, type_: str, mw: float) -> None:
    conn.execute(
        "INSERT INTO project_resources (source, native_id, type, mw) VALUES (%s, %s, %s, %s)",
        (source, native_id, type_, mw),
    )


def test_projects_row_carries_every_canonical_column(conn: Conn) -> None:
    insert_project(
        conn,
        source="caiso_raw",
        native_id="CAISO-0001",
        status="Active",
        q_date=datetime.date(2020, 1, 1),
        proposed_online_date=datetime.date(2025, 6, 1),
        actual_online_date=None,
        withdrawn_date=None,
        ia_date=datetime.date(2021, 3, 1),
        county="Monterey",
        state="CA",
        iso="CAISO",
        study_region="Northern",
        non_iso_entity=None,
        raw_poi="Moss Landing 230kV Bus",
        normalized_poi="MOSS LANDING",
        poi_unmapped=False,
        utility="PG&E",
    )
    got = one(
        conn.execute(
            f"SELECT {', '.join(PROJECT_COLUMNS)} FROM projects WHERE native_id = 'CAISO-0001'"
        )
    )
    assert got == (
        "caiso_raw",
        "CAISO-0001",
        "Active",
        datetime.date(2020, 1, 1),
        datetime.date(2025, 6, 1),
        None,
        None,
        datetime.date(2021, 3, 1),
        "Monterey",
        "CA",
        "CAISO",
        "Northern",
        None,
        "Moss Landing 230kV Bus",
        "MOSS LANDING",
        False,
        "PG&E",
    )


def test_source_is_constrained_to_the_closed_enum(conn: Conn) -> None:
    with pytest.raises(psycopg.errors.Error):
        insert_project(conn, source="ercot", native_id="X-1")


def test_iso_and_study_region_are_independent_columns(conn: Conn) -> None:
    # An LBNL non-ISO row: iso NULL, study_region NULL, entity in its own column —
    # the same level-mixing bug must not be rebuilt one tier down (ADR-0001).
    insert_project(
        conn, source="lbnl", native_id="LBNL-77", iso=None, study_region=None, non_iso_entity="West"
    )
    iso, study_region, entity = one(
        conn.execute(
            "SELECT iso, study_region, non_iso_entity FROM projects WHERE native_id = 'LBNL-77'"
        )
    )
    assert (iso, study_region, entity) == (None, None, "West")


def test_hybrid_project_stores_resources_as_child_rows(conn: Conn) -> None:
    insert_project(conn, source="caiso_raw", native_id="CAISO-HYB")
    insert_resource(conn, "caiso_raw", "CAISO-HYB", "Solar", 100.0)
    insert_resource(conn, "caiso_raw", "CAISO-HYB", "Storage", 50.0)
    rows = conn.execute(
        "SELECT type, mw FROM project_resources "
        "WHERE source = 'caiso_raw' AND native_id = 'CAISO-HYB' ORDER BY type"
    ).fetchall()
    assert rows == [("Solar", 100.0), ("Storage", 50.0)]


def test_resource_requires_an_existing_parent_project(conn: Conn) -> None:
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        insert_resource(conn, "caiso_raw", "does-not-exist", "Solar", 10.0)


def test_row_id_is_a_natural_key_that_survives_reingest(conn: Conn) -> None:
    # No surrogate auto-increment: the row is addressed by (source, native_id), and
    # re-ingesting the same request updates in place rather than minting a new id —
    # eval cases store these ids and must still resolve after a re-run.
    insert_project(conn, source="caiso_raw", native_id="CAISO-0123", status="Active")
    conn.execute(
        "INSERT INTO projects (source, native_id, status) VALUES ('caiso_raw', 'CAISO-0123', %s) "
        "ON CONFLICT (source, native_id) DO UPDATE SET status = EXCLUDED.status",
        ("Withdrawn",),
    )
    rows = conn.execute(
        "SELECT status FROM projects WHERE source = 'caiso_raw' AND native_id = 'CAISO-0123'"
    ).fetchall()
    assert rows == [("Withdrawn",)]


def test_projects_has_no_surrogate_id_column(conn: Conn) -> None:
    cols = {
        r[0]
        for r in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'projects'"
        ).fetchall()
    }
    assert "id" not in cols


def test_caiso_view_returns_only_caiso_rows(conn: Conn) -> None:
    insert_project(conn, source="caiso_raw", native_id="C-1")
    insert_project(conn, source="lbnl", native_id="L-1")
    sources = {r[0] for r in conn.execute("SELECT DISTINCT source FROM caiso_projects").fetchall()}
    assert sources == {"caiso_raw"}


def test_lbnl_view_returns_only_lbnl_rows(conn: Conn) -> None:
    insert_project(conn, source="caiso_raw", native_id="C-2")
    insert_project(conn, source="lbnl", native_id="L-2")
    sources = {r[0] for r in conn.execute("SELECT DISTINCT source FROM lbnl_projects").fetchall()}
    assert sources == {"lbnl"}


def test_project_present_in_both_sources_is_not_double_counted(conn: Conn) -> None:
    # The same interconnection request is listed by CAISO's own workbook and by
    # LBNL's national file. A query that forgot `WHERE source = ...` would see it
    # twice; each view returns it exactly once, so a cross-source count is
    # physically impossible without deliberately reading the base table.
    shared = "MOSS-LANDING-EXPANSION"
    insert_project(conn, source="caiso_raw", native_id=shared, iso="CAISO")
    insert_project(conn, source="lbnl", native_id=shared, iso="CAISO")

    base = one(conn.execute("SELECT count(*) FROM projects WHERE native_id = %s", (shared,)))[0]
    in_caiso = one(
        conn.execute("SELECT count(*) FROM caiso_projects WHERE native_id = %s", (shared,))
    )[0]
    in_lbnl = one(
        conn.execute("SELECT count(*) FROM lbnl_projects WHERE native_id = %s", (shared,))
    )[0]

    assert base == 2  # both copies live in the base table
    assert in_caiso == 1  # but each view sees only its own source's copy
    assert in_lbnl == 1
