"""Cross-check the reviewed POI alias groupings against LBNL's ``poi_name``.

LBNL's national file carries its own point-of-interconnection string for each CAISO
project. It is an independent witness: where our reviewed alias table groups two CAISO
projects under one canonical POI, LBNL's ``poi_name`` for those same projects is a check on
whether the grouping is real. This assertion reports every group where the two disagree,
so a wrong merge surfaces for review instead of hiding inside a saturation figure.

LBNL DB ingest is ticket #7, and the full LBNL workbook is 15 MB and stays out of git, so
this check reads a committed frozen slice of its CAISO ``poi_name`` column
(``data/lbnl_caiso_poi.csv``) — keyed by CAISO queue position, since LBNL's ``q_id`` is the
same natural key and ``_native_id`` rebuilds our id from it. It uses the runtime normalizer
and alias table, never fuzzy matching.

A disagreement here is expected and healthy in one direction: our reviewed table
deliberately merges mechanical/spelling variants ("Whirlwind Sub 230kV bus" into
"Whirlwind Substation 230 kV") that LBNL leaves as distinct ``poi_name`` strings. What must
*not* happen is a surprise merge — two projects we group whose LBNL names are genuinely
different substations. The tolerance below bounds the total so a regression that over-merges
many distinct substations fails the suite rather than logging a warning.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import openpyxl

from interconnection_agent.ingest.caiso import (
    ACTIVE_SHEET,
    APPLICATION_STATUS,
    FIRST_DATA_ROW,
    QUEUE_POSITION,
    STATION,
    _header_index,
    _native_id,
)
from interconnection_agent.poi import load_alias_table, normalize_station

DATA = Path(__file__).resolve().parents[2] / "data"
CAISO_WORKBOOK = DATA / "publicqueuereport.xlsx"
LBNL_CAISO_POI = DATA / "lbnl_caiso_poi.csv"

# The reviewed POI groups whose members LBNL spells more than one way in poi_name — i.e.
# the deliberate merges this alias table makes *beyond* mechanical normalization (a "Sub"
# abbreviation, a "bus" suffix, a typo). They are enumerated here so they surface for
# review, and so a *surprise* merge — two projects we group that LBNL treats as genuinely
# different substations — appears as an unexpected canonical name and fails the assertion.
EXPECTED_REVIEWED_MERGES = {
    "Antelope Substation 230 kV",
    "Eldorado Substation 230 kV",
    "Midway-Temblor 115 kV Line",
    "Roadway Substation 115 kV",
    "Volta-South 60 kV",
    "Whirlwind Substation 230 kV",
}


@dataclass(frozen=True)
class Disagreement:
    """One reviewed POI group whose members carry more than one LBNL ``poi_name``."""

    canonical_poi: str
    native_ids: tuple[str, ...]
    lbnl_names: frozenset[str]


def _our_normalized_poi_by_id() -> dict[str, str]:
    """Map each mapped active CAISO project to the canonical POI the alias table assigns."""
    table = load_alias_table()
    result: dict[str, str] = {}
    workbook = openpyxl.load_workbook(CAISO_WORKBOOK, read_only=True, data_only=True)
    try:
        sheet = workbook[ACTIVE_SHEET]
        columns = _header_index(sheet)  # read by header, not bare index, per caiso.py

        def cell(row: tuple[object, ...], header: str) -> object:
            index = columns[header]
            return row[index] if index < len(row) else None

        for row in sheet.iter_rows(min_row=FIRST_DATA_ROW, values_only=True):
            if all(v is None for v in row):
                continue
            queue_position = cell(row, QUEUE_POSITION)
            if queue_position is None or not str(queue_position).strip():
                continue
            status = cell(row, APPLICATION_STATUS)
            if status is None or str(status).strip().upper() != "ACTIVE":
                continue
            station = cell(row, STATION)
            canonical = table.resolve(None if station is None else str(station))
            if canonical is not None:
                result[_native_id(queue_position)] = canonical
        return result
    finally:
        workbook.close()


def _lbnl_poi_name_by_id() -> dict[str, str]:
    """Map each CAISO LBNL row to its normalized ``poi_name``, keyed by our native id."""

    def native_id(q_id: str) -> str:
        # A plain-integer q_id must go in as an int so _native_id zero-pads it exactly as
        # the CAISO ingest does ("22" -> CAISO-0022); revision ids ("643R") stay as text.
        return _native_id(int(q_id) if q_id.isdigit() else q_id)

    with LBNL_CAISO_POI.open("r", encoding="utf-8", newline="") as stream:
        return {
            native_id(row["q_id"]): normalize_station(row["poi_name"])
            for row in csv.DictReader(stream)
        }


def find_disagreements() -> tuple[list[Disagreement], int]:
    """Return (disagreeing groups, overlap size) between our groupings and LBNL's names."""
    ours = _our_normalized_poi_by_id()
    lbnl = _lbnl_poi_name_by_id()
    overlap = [native_id for native_id in ours if native_id in lbnl]

    groups: dict[str, list[str]] = defaultdict(list)
    for native_id in overlap:
        groups[ours[native_id]].append(native_id)

    disagreements = [
        Disagreement(
            canonical_poi=canonical,
            native_ids=tuple(sorted(members)),
            lbnl_names=frozenset(lbnl[n] for n in members),
        )
        for canonical, members in groups.items()
        if len(members) >= 2 and len({lbnl[n] for n in members}) > 1
    ]
    return disagreements, len(overlap)


def test_alias_groupings_are_consistent_with_lbnl_poi_name() -> None:
    disagreements, overlap = find_disagreements()

    # Sanity: the two datasets really do overlap on the active CAISO queue.
    assert overlap > 200

    report = "\n".join(
        f"  {d.canonical_poi!r} {list(d.native_ids)} -> LBNL {sorted(d.lbnl_names)}"
        for d in sorted(disagreements, key=lambda d: d.canonical_poi)
    )
    disagreeing = {d.canonical_poi for d in disagreements}

    # Every disagreement must be one of the reviewed merges we already vetted. A canonical
    # name here that is NOT in that set is a surprise merge — projects we grouped that LBNL
    # calls different substations — and must be reviewed, so the suite fails on it.
    surprises = disagreeing - EXPECTED_REVIEWED_MERGES
    assert not surprises, f"unreviewed POI merges disagree with LBNL poi_name:\n{report}"

    # And a reviewed merge that stops disagreeing means the table changed under us; re-review
    # so the vetted set stays honest rather than silently stale.
    assert disagreeing == EXPECTED_REVIEWED_MERGES, (
        "reviewed merges no longer match LBNL disagreements; update "
        f"EXPECTED_REVIEWED_MERGES:\n{report}"
    )
