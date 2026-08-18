"""Unit tests for the LBNL reader's pure classification helpers — no database.

These pin the three decisions that ADR-0001 makes load-bearing, in isolation from the
Postgres seam: the status vocabulary map, the ISO / non-ISO region split (West and
Southeast are *never* stored as ISOs), and the natural key built from LBNL's own
(q_id, entity) identifier. The end-to-end behaviour is asserted against the real workbook
and Postgres in the integration suite.
"""

from __future__ import annotations

import pytest

from interconnection_agent.ingest.lbnl import (
    canonical_lbnl_status,
    classify_region,
    lbnl_native_id,
)


def test_every_documented_status_maps_to_a_canonical_token() -> None:
    # The five statuses the codebook lists, each mapped explicitly. active/withdrawn/
    # operational reuse CAISO's canonical tokens so the cross-check SQL is uniform across
    # sources; suspended/unknown are LBNL-only states given their own tokens.
    assert canonical_lbnl_status("active") == "Active"
    assert canonical_lbnl_status("withdrawn") == "Withdrawn"
    assert canonical_lbnl_status("operational") == "Operational"
    assert canonical_lbnl_status("suspended") == "Suspended"
    assert canonical_lbnl_status("unknown") == "Unknown"


def test_an_unseen_status_is_unmapped_rather_than_guessed() -> None:
    # A status LBNL has not shown before must be reviewed into the map before it can land.
    assert canonical_lbnl_status("retired") is None


def test_iso_regions_populate_iso_and_leave_non_iso_entity_null() -> None:
    # An ISO row: iso is the region name, non_iso_entity stays NULL.
    assert classify_region("CAISO", entity="CAISO") == ("CAISO", None)
    assert classify_region("PJM", entity="PJM") == ("PJM", None)


def test_west_and_southeast_are_non_iso_and_never_stored_as_an_iso() -> None:
    # ADR-0001: West/Southeast are balancing-area catch-alls, not operators. iso is NULL and
    # the entity field supplies non_iso_entity.
    assert classify_region("West", entity="APS") == (None, "APS")
    assert classify_region("Southeast", entity="Duke") == (None, "Duke")


def test_an_unrecognized_region_is_rejected() -> None:
    # A region that is neither one of the seven ISOs nor a known non-ISO catch-all must be
    # reviewed before its rows can land — it is not silently assigned.
    assert classify_region("Atlantis", entity="X") is None


def test_a_non_iso_region_with_no_entity_yields_the_neither_state() -> None:
    # West/Southeast take their non_iso_entity from the entity field; with entity blank, both
    # levels are NULL — the "neither" state ADR-0001 forbids. classify_region surfaces it as
    # (None, None) so the reader can drop the row rather than write a level-less location.
    assert classify_region("West", entity=None) == (None, None)


def test_native_id_combines_entity_and_q_id() -> None:
    # The codebook: q_id is unique only when combined with entity. The natural key encodes
    # exactly that pair.
    assert lbnl_native_id("Q173", "APS") == "APS / Q173"
    assert lbnl_native_id(10, "CAISO") == "CAISO / 10"


def test_native_id_is_stable_for_a_messy_q_id() -> None:
    # LBNL's q_id is free text ("not assigned", "Q044a."); it is carried through verbatim so
    # the key is reproducible across re-ingests.
    assert lbnl_native_id("not assigned", "APS") == "APS / not assigned"


@pytest.mark.parametrize("region", ["CAISO", "ISO-NE", "MISO", "NYISO", "PJM", "SPP", "ERCOT"])
def test_all_seven_isos_classify_as_isos(region: str) -> None:
    result = classify_region(region, entity=region)
    assert result == (region, None)
