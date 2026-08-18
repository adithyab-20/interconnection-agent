"""Hand-rolled reader for LBNL's national "Queued Up" workbook — the breadth layer.

LBNL (Berkeley Lab) publishes a pre-normalized national interconnection dataset covering
all seven ISOs plus two non-ISO catch-alls. This module reads its one row-per-request sheet
— ``03. Complete Queue Data``, headers on row 2, data from row 3 — and lands every project
in the same canonical ``projects`` table CAISO lands in, tagged ``source = lbnl``. It exists
for two reasons: national breadth CAISO's own workbook cannot give, and an *independent
check* on the hand-rolled CAISO ETL. Both sources carry CAISO's projects, so a figure
derived from CAISO-raw can be recomputed from LBNL's CAISO rows and the two compared — the
cross-validation that lives in the integration suite. Because both carry CAISO, they are
never aggregated together; ADR-0001's per-source views keep that structural.

Three decisions, each kept as reviewer-readable configuration below rather than buried in
the loop:

  * **Region → location (ADR-0001).** LBNL's ``region`` field is mixed: the seven ISO names
    plus "West" and "Southeast", which are *not* ISOs but balancing-area catch-alls. ISO
    rows populate ``iso``; West/Southeast rows get ``iso = NULL`` and the balancing-area name
    from the ``entity`` field in ``non_iso_entity``. They must never be stored as an ISO. A
    region that is neither is dropped-with-reason, not guessed.
  * **``study_region`` is NULL for every LBNL row.** LBNL has no sub-ISO grain; only CAISO's
    own workbook does. Storing anything here would invent a level the data does not have.
  * **Status vocabulary.** LBNL's five documented statuses map to canonical tokens through
    :data:`LBNL_STATUS_MAP`. active/withdrawn/operational reuse the exact tokens CAISO lands,
    so the resolved-rate SQL (``withdrawn / (withdrawn + operational)``) is literally the same
    query on either source; suspended/unknown are LBNL-only states with their own tokens. A
    status absent from the table is dropped-with-reason.

The natural key is LBNL's own identifier. Per the codebook, ``q_id`` is unique only when
combined with ``entity``, so ``native_id`` encodes exactly that pair (``"CAISO / 10"``).
Ingest is idempotent on it: a re-run upserts every row in place. The source data holds a
small number of rows that collide on ``(q_id, entity)`` despite the codebook's claim of
uniqueness; first-seen wins and the rest are reported as dropped duplicates rather than
silently overwriting a just-written row.

Each row's up-to-three ``type``/``mw`` pairs become ``project_resources`` child rows, keyed
on fuel like CAISO's — the two sources share the fuel taxonomy so a cross-source comparison
lines up. A pair's MW is stored NULL when LBNL leaves it blank (the codebook excludes imputed
storage capacity), never coerced to zero, so an unknown capacity is not read as none.

LBNL's ``poi_name`` is already normalized nationally, but by *LBNL's* rules, not the reviewed
CAISO alias table. It is preserved verbatim in ``raw_poi`` as provenance; ``normalized_poi``
stays NULL and ``poi_unmapped`` stays false, because no alias resolution is attempted here —
this reader makes no POI-coverage claim, and the coverage report is a CAISO-only concept.
"""

from __future__ import annotations

from pathlib import Path

import openpyxl
import psycopg

from interconnection_agent.ingest import _cells
from interconnection_agent.ingest.report import DroppedRow, IngestReport, SheetReport

# The one row-per-request sheet. Headers sit on row 2, data begins on row 3 (the sheet's
# fixed layout — row 1 is a "RETURN TO CONTENTS" banner).
COMPLETE_QUEUE_SHEET = "03. Complete Queue Data"
HEADER_ROW = 2
FIRST_DATA_ROW = 3

# Canonical column <- LBNL header. Kept as data so the mapping reads as a table a reviewer
# can check against the codebook, not as bare column indices.
Q_ID = "q_id"
Q_STATUS = "q_status"
Q_DATE = "q_date"
PROP_DATE = "prop_date"
ON_DATE = "on_date"
WD_DATE = "wd_date"
IA_DATE = "ia_date"
COUNTY = "county"
STATE = "state"
POI_NAME = "poi_name"
REGION = "region"
UTILITY = "utility"
ENTITY = "entity"

# The up-to-three resource type/MW pairs, by header.
TYPE_HEADERS = ("type_1", "type_2", "type_3")
MW_HEADERS = ("mw_1", "mw_2", "mw_3")

# LBNL q_status (lower-cased) -> canonical projects.status token. The three shared with
# CAISO reuse CAISO's exact tokens so the cross-source resolved-rate query is uniform;
# suspended/unknown are LBNL-only states. A status absent here is reviewed before it lands.
LBNL_STATUS_MAP: dict[str, str] = {
    "active": "Active",
    "withdrawn": "Withdrawn",
    "operational": "Operational",
    "suspended": "Suspended",
    "unknown": "Unknown",
}

# LBNL's region vocabulary, split into the two levels ADR-0001 keeps separate. The seven
# ISOs populate `iso`; the two non-ISO catch-alls populate `non_iso_entity` instead and get
# `iso = NULL`. Any other region string is unreviewed and dropped-with-reason.
ISO_REGIONS: frozenset[str] = frozenset({"CAISO", "ISO-NE", "MISO", "NYISO", "PJM", "SPP", "ERCOT"})
NON_ISO_REGIONS: frozenset[str] = frozenset({"West", "Southeast"})


def canonical_lbnl_status(raw_status: str) -> str | None:
    """Return the canonical token for an LBNL status, or ``None`` if it is unmapped."""
    return LBNL_STATUS_MAP.get(raw_status.strip().lower())


def classify_region(region: str, entity: str | None) -> tuple[str | None, str | None] | None:
    """Split an LBNL region into ``(iso, non_iso_entity)`` per ADR-0001.

    An ISO region returns ``(region, None)``; a non-ISO catch-all (West/Southeast) returns
    ``(None, entity)`` — never storing the catch-all as an ISO. An unrecognized region
    returns ``None`` so the caller can drop it with a reason rather than guess a level.
    """
    if region in ISO_REGIONS:
        return region, None
    if region in NON_ISO_REGIONS:
        return None, entity
    return None


def lbnl_native_id(q_id: object, entity: object) -> str:
    """Build the natural-key id from LBNL's (q_id, entity) pair (``"CAISO / 10"``).

    The codebook says q_id is unique only combined with entity; both are carried through
    verbatim (q_id is free text — ``"Q044a."``, ``"not assigned"``) so the key is stable
    across re-ingests.
    """
    return f"{_text(entity)} / {_text(q_id)}"


def _text(value: object) -> str:
    """Render a key component as its trimmed string; a blank component is the empty string."""
    return "" if value is None else str(value).strip()


_UPSERT = """
    INSERT INTO projects (
        source, native_id, status, q_date, proposed_online_date, actual_online_date,
        withdrawn_date, ia_date, county, state, iso, study_region, non_iso_entity,
        raw_poi, normalized_poi, poi_unmapped, utility
    ) VALUES (
        'lbnl', %(native_id)s, %(status)s, %(q_date)s, %(proposed_online_date)s,
        %(actual_online_date)s, %(withdrawn_date)s, %(ia_date)s, %(county)s, %(state)s,
        %(iso)s, NULL, %(non_iso_entity)s, %(raw_poi)s, NULL, false, %(utility)s
    )
    ON CONFLICT (source, native_id) DO UPDATE SET
        status               = EXCLUDED.status,
        q_date               = EXCLUDED.q_date,
        proposed_online_date = EXCLUDED.proposed_online_date,
        actual_online_date   = EXCLUDED.actual_online_date,
        withdrawn_date       = EXCLUDED.withdrawn_date,
        ia_date              = EXCLUDED.ia_date,
        county               = EXCLUDED.county,
        state                = EXCLUDED.state,
        iso                  = EXCLUDED.iso,
        non_iso_entity       = EXCLUDED.non_iso_entity,
        raw_poi              = EXCLUDED.raw_poi,
        utility              = EXCLUDED.utility
"""

_UPSERT_RESOURCE = """
    INSERT INTO project_resources (source, native_id, type, mw)
    VALUES ('lbnl', %(native_id)s, %(type)s, %(mw)s)
    ON CONFLICT (source, native_id, type) DO UPDATE SET mw = EXCLUDED.mw
"""


def run_lbnl_ingest(
    workbook_path: Path, conn: psycopg.Connection[tuple[object, ...]]
) -> IngestReport:
    """Ingest LBNL's Complete Queue Data sheet into the canonical schema.

    Returns an :class:`IngestReport` with a single :class:`SheetReport` for the one sheet.
    Idempotent on the natural key: re-running upserts every project and resource in place.
    Does not commit — the caller owns the transaction boundary, matching
    :func:`interconnection_agent.ingest.caiso.run_caiso_ingest`.
    """
    workbook = openpyxl.load_workbook(workbook_path, read_only=True, data_only=True)
    try:
        return IngestReport(sheets=(_ingest_complete_queue(workbook, conn),))
    finally:
        workbook.close()


def _ingest_complete_queue(
    workbook: openpyxl.Workbook, conn: psycopg.Connection[tuple[object, ...]]
) -> SheetReport:
    """Ingest the Complete Queue Data sheet into ``projects`` (+ ``project_resources``)."""
    sheet = workbook[COMPLETE_QUEUE_SHEET]
    columns = _cells.header_index(sheet, HEADER_ROW)

    def cell(row: tuple[object, ...], header: str) -> object:
        index = columns.get(header)
        if index is None or index >= len(row):
            return None
        return row[index]

    def resources(row: tuple[object, ...]) -> tuple[dict[str, float | None], int]:
        """Fold the up-to-three type/MW pairs into per-type MW (summing repeats).

        A type with no MW in any of its pairs keeps ``None`` — LBNL blanks are unknown
        capacity (imputed values are excluded from this file), not zero. A pair carrying MW
        but no type label has no child key and is counted skipped.
        """
        by_type: dict[str, float | None] = {}
        skipped = 0
        for type_header, mw_header in zip(TYPE_HEADERS, MW_HEADERS, strict=True):
            fuel = _cells.clean(cell(row, type_header))
            mw = _cells.mw_or_none(cell(row, mw_header))
            if fuel is None and mw is None:
                continue
            if fuel is None:
                skipped += 1
                continue
            if mw is not None:
                by_type[fuel] = (by_type.get(fuel) or 0.0) + mw
            else:
                by_type.setdefault(fuel, None)
        return by_type, skipped

    rows_read = 0
    rows_written = 0
    resources_written = 0
    resources_skipped = 0
    dropped: list[DroppedRow] = []
    seen: set[str] = set()

    for offset, row in enumerate(sheet.iter_rows(min_row=FIRST_DATA_ROW, values_only=True)):
        row_number = FIRST_DATA_ROW + offset
        if all(value is None for value in row):
            continue  # trailing blank rows are not records
        rows_read += 1

        raw_status = _cells.clean(cell(row, Q_STATUS))
        status = canonical_lbnl_status(raw_status) if raw_status else None
        if status is None:
            dropped.append(
                DroppedRow(
                    COMPLETE_QUEUE_SHEET,
                    row_number,
                    f"unrecognized status: {raw_status!r}",
                    category="unrecognized status",
                )
            )
            continue

        region = _cells.clean(cell(row, REGION))
        entity = _cells.clean(cell(row, ENTITY))
        location = classify_region(region, entity) if region else None
        if location is None:
            dropped.append(
                DroppedRow(
                    COMPLETE_QUEUE_SHEET,
                    row_number,
                    f"unrecognized region: {region!r}",
                    category="unrecognized region",
                )
            )
            continue
        iso, non_iso_entity = location
        if iso is None and non_iso_entity is None:
            # A non-ISO catch-all whose entity field is blank: it can populate neither iso
            # nor non_iso_entity, which is the "neither" state ADR-0001 forbids. Drop it with
            # a reason rather than write a row that is neither an ISO nor a named catch-all.
            dropped.append(
                DroppedRow(
                    COMPLETE_QUEUE_SHEET,
                    row_number,
                    f"non-ISO region {region!r} missing entity",
                    category="non-ISO region missing entity",
                )
            )
            continue

        native_id = lbnl_native_id(cell(row, Q_ID), cell(row, ENTITY))
        if native_id in seen:
            # The codebook promises (q_id, entity) is unique; the data holds a few collisions.
            # First-seen wins so a re-ingest is deterministic; the rest are reported, not
            # silently overwritten.
            dropped.append(
                DroppedRow(
                    COMPLETE_QUEUE_SHEET,
                    row_number,
                    f"duplicate natural key: {native_id!r}",
                    category="duplicate natural key",
                )
            )
            continue
        seen.add(native_id)

        conn.execute(
            _UPSERT,
            {
                "native_id": native_id,
                "status": status,
                "q_date": _cells.as_date(cell(row, Q_DATE)),
                "proposed_online_date": _cells.as_date(cell(row, PROP_DATE)),
                "actual_online_date": _cells.as_date(cell(row, ON_DATE)),
                "withdrawn_date": _cells.as_date(cell(row, WD_DATE)),
                "ia_date": _cells.as_date(cell(row, IA_DATE)),
                "county": _cells.clean(cell(row, COUNTY)),
                "state": _cells.clean(cell(row, STATE)),
                "iso": iso,
                "non_iso_entity": non_iso_entity,
                "raw_poi": _cells.verbatim(cell(row, POI_NAME)),
                "utility": _cells.clean(cell(row, UTILITY)),
            },
        )
        rows_written += 1

        by_type, skipped = resources(row)
        resources_skipped += skipped
        for fuel, fuel_mw in by_type.items():
            conn.execute(_UPSERT_RESOURCE, {"native_id": native_id, "type": fuel, "mw": fuel_mw})
            resources_written += 1

    return SheetReport(
        sheet=COMPLETE_QUEUE_SHEET,
        rows_read=rows_read,
        rows_written=rows_written,
        resources_written=resources_written,
        resources_skipped=resources_skipped,
        dropped=tuple(dropped),
    )
