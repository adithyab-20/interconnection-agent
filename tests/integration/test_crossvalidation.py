"""Phase 1 cross-validation: CAISO-raw figures checked against LBNL and Public Advocates.

This is the independent check that justifies loading LBNL at all. CAISO's projects appear in
*both* sources, so a withdrawal or energization figure computed from the hand-rolled CAISO
ETL can be recomputed from LBNL's CAISO rows and the two compared. If the hand-rolled ETL
drifts — a swapped sheet, a dropped status, a miscounted outcome — the two diverge and this
test goes red rather than logging a warning.

It is the single deliberate reader of the base ``projects`` table (ADR-0001): every other
query goes through a per-source view precisely so the two sources cannot be aggregated
together, but cross-validation's whole job is to hold both at once and compare them.

**Figures — matched to Public Advocates' own method.** Two shares over the full per-source
queue, the "cumulative" method: the Public Advocates report states its numbers exactly this
way — its 71% withdrawn + 20% completed + ~9% still active partition every project that ever
entered the queue, so the matching figure is the outcome count over the whole queue, not a
resolved-only rate:

  * *withdrawal* = withdrawn / all rows in the source's queue
  * *energization* = operational / all rows in the source's queue

Both are computed identically for CAISO-raw and for LBNL's CAISO subset, so the CAISO↔LBNL
comparison is method-matched by construction; and both use Public Advocates' cumulative
denominator, so that comparison is method-matched too — the residual against 0.71 / 0.20 is a
snapshot effect, not a raw-vs-cumulative mismatch (ADR-0002's warning). This frozen file runs
through 2025: it carries more late withdrawals than the older Public Advocates snapshot, and
the recent-vintage surge dilutes the completion share, so energization sits below their 20%.

**Tolerances (measured, not rounded).** Each band is set just above the largest difference
actually observed against the frozen snapshots, so "within tolerance" is a specification a
divergence breaks — not a wide catch-all. A genuine ETL drift (a swapped sheet, a dropped
status, a miscounted outcome) moves a share far more than these residuals and fails the suite.
Observed differences:

  * CAISO↔LBNL: withdrawal 0.005, energization 0.027 → inside CROSS_CHECK_TOL = 0.05
  * vs Public Advocates withdrawal: CAISO 0.062, LBNL 0.057 → inside PUB_ADV_WITHDRAWAL_TOL = 0.08
  * vs Public Advocates energization: CAISO 0.091, LBNL 0.118 → inside PUB_ADV_ENERGIZATION_TOL 0.13

The energization band is wider than the withdrawal band because completion share is the more
snapshot-sensitive of the two, exactly as ADR-0002 anticipates — the width is the measured
methodological spread, stated, rather than a warning that would let a divergence slip through.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import psycopg
import pytest

from interconnection_agent.db import connect
from interconnection_agent.ingest import run_caiso_ingest, run_lbnl_ingest

Conn = psycopg.Connection[tuple[object, ...]]

DATA = Path(__file__).resolve().parents[2] / "data"
CAISO_WORKBOOK = DATA / "publicqueuereport.xlsx"
LBNL_WORKBOOK = DATA / "LBNL_Ix_Queue_Data_File_thru2025.xlsx"

pytestmark = pytest.mark.skipif(
    not LBNL_WORKBOOK.exists(),
    reason="LBNL workbook not present (large, uncommitted data file)",
)

# The comparison bands, versioned here so "within tolerance" is a specification. Absolute
# differences in share (a fraction of the queue), not relative. Each is the largest observed
# residual against the frozen snapshots plus a small margin (see the module docstring).
CROSS_CHECK_TOL = 0.05  # CAISO-raw vs LBNL's CAISO subset — identical method, so tight.
PUB_ADV_WITHDRAWAL_TOL = 0.08  # vs Public Advocates' 71% (observed residual ≤0.062).
PUB_ADV_ENERGIZATION_TOL = 0.13  # vs Public Advocates' 20% (observed residual ≤0.118).

# Public Advocates' published CAISO figures (build-spec §2): ~71% withdrawn, ~20% completed.
PUB_ADV_WITHDRAWAL = 0.71
PUB_ADV_ENERGIZATION = 0.20


@dataclass(frozen=True)
class Figures:
    """The two cumulative outcome shares for one source's queue."""

    withdrawal: float
    energization: float


@pytest.fixture(scope="module")
def conn_module() -> Iterator[Conn]:
    """A module-scoped connection, rolled back after the cross-validation run."""
    c = connect()
    c.autocommit = False
    try:
        yield c
    finally:
        c.rollback()
        c.close()


@pytest.fixture(scope="module", autouse=True)
def _seed_both_sources(conn_module: Conn) -> None:
    """Seed CAISO and LBNL into the base table once, so both sources are present to compare."""
    run_caiso_ingest(CAISO_WORKBOOK, conn_module)
    run_lbnl_ingest(LBNL_WORKBOOK, conn_module)


def _figures(conn: Conn, predicate: str) -> Figures:
    """Compute the withdrawal and energization shares over the base rows matching ``predicate``.

    Reads the base ``projects`` table directly — the one place ADR-0001 sanctions it — because
    the comparison needs both sources' rows, which the per-source views deliberately separate.
    """
    row = conn.execute(
        "SELECT "
        "  count(*) FILTER (WHERE status = 'Withdrawn')::float / count(*), "
        "  count(*) FILTER (WHERE status = 'Operational')::float / count(*) "
        f"FROM projects WHERE {predicate}"
    ).fetchone()
    assert row is not None
    return Figures(withdrawal=cast(float, row[0]), energization=cast(float, row[1]))


@pytest.fixture(scope="module")
def caiso(conn_module: Conn) -> Figures:
    return _figures(conn_module, "source = 'caiso_raw'")


@pytest.fixture(scope="module")
def lbnl_caiso(conn_module: Conn) -> Figures:
    # LBNL's CAISO rows only — the same operator CAISO-raw covers, so the two are comparable.
    return _figures(conn_module, "source = 'lbnl' AND iso = 'CAISO'")


def test_caiso_and_lbnl_agree_on_the_withdrawal_figure(caiso: Figures, lbnl_caiso: Figures) -> None:
    assert caiso.withdrawal == pytest.approx(lbnl_caiso.withdrawal, abs=CROSS_CHECK_TOL)


def test_caiso_and_lbnl_agree_on_the_energization_figure(
    caiso: Figures, lbnl_caiso: Figures
) -> None:
    assert caiso.energization == pytest.approx(lbnl_caiso.energization, abs=CROSS_CHECK_TOL)


def test_caiso_withdrawal_lands_near_the_public_advocates_figure(caiso: Figures) -> None:
    assert caiso.withdrawal == pytest.approx(PUB_ADV_WITHDRAWAL, abs=PUB_ADV_WITHDRAWAL_TOL)


def test_caiso_energization_lands_near_the_public_advocates_figure(caiso: Figures) -> None:
    assert caiso.energization == pytest.approx(PUB_ADV_ENERGIZATION, abs=PUB_ADV_ENERGIZATION_TOL)


def test_lbnl_caiso_subset_lands_near_the_public_advocates_figures(lbnl_caiso: Figures) -> None:
    # The same published values check LBNL's CAISO subset by the same cumulative method — an
    # independent second path to the Public Advocates numbers, each within its measured band.
    assert lbnl_caiso.withdrawal == pytest.approx(PUB_ADV_WITHDRAWAL, abs=PUB_ADV_WITHDRAWAL_TOL)
    assert lbnl_caiso.energization == pytest.approx(
        PUB_ADV_ENERGIZATION, abs=PUB_ADV_ENERGIZATION_TOL
    )


def test_the_two_sources_are_both_actually_present(conn_module: Conn) -> None:
    # Guard the guard: if a source failed to seed, count(*) would be zero and every share
    # above would be a silent 0/0. Assert both sources landed rows before trusting the bands.
    counts: dict[str, int] = {
        cast(str, row[0]): cast(int, row[1])
        for row in conn_module.execute(
            "SELECT source, count(*) FROM projects GROUP BY source"
        ).fetchall()
    }
    assert counts.get("caiso_raw", 0) > 0
    assert counts.get("lbnl", 0) > 0
