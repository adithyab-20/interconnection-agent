"""Unit tests for the POI normalizer — the mechanical canonicalization, case by case.

``normalize_station`` collapses only *mechanical* variation in the operator's free-text
station string: case, whitespace, the ``230kV`` / ``230 kV`` voltage spelling, hyphen
spacing. It deliberately does **not** strip descriptors like "Substation", "Line", or
"Bus", because a substation and the line leaving it are different points of
interconnection — merging them would group two real POIs into one. Genuine synonyms and
typos are the reviewed alias table's job (``test_poi_alias``), not the normalizer's.

The output is a lookup *key*, not a display name; it is compared for exact equality, so
these tests pin the exact string the key normalizes to.
"""

from __future__ import annotations

from interconnection_agent.poi import normalize_station


def test_collapses_case_and_surrounding_whitespace() -> None:
    assert normalize_station("  Birds Landing 230 kV  ") == "birds landing 230 kv"


def test_collapses_internal_whitespace_runs() -> None:
    assert normalize_station("Gates\t\n 230   kV") == "gates 230 kv"


def test_unifies_the_voltage_token_spelling() -> None:
    # The ticket's own example: "230kV" and "230 kV" must land on one key.
    assert normalize_station("Devers Substation 230kV") == normalize_station(
        "Devers Substation 230 kV"
    )
    assert normalize_station("Devers Substation 230kV") == "devers substation 230 kv"


def test_unifies_hyphen_spacing_between_endpoints() -> None:
    # "Midway-Temblor" and "Midway - Temblor" name the same line; spacing must not split.
    assert normalize_station("Midway - Temblor 115 kV Line") == normalize_station(
        "Midway-Temblor 115 kV Line"
    )
    assert normalize_station("Midway-Temblor 115 kV Line") == "midway-temblor 115 kv line"


def test_keeps_descriptors_that_distinguish_real_pois() -> None:
    # A substation is not the line leaving it; the normalizer must keep them apart and
    # leave the semantic call to the reviewed alias table.
    assert normalize_station("Midway 230 kV") != normalize_station("Midway 230 kV Line")


def test_folds_unicode_compatibility_forms_to_plain_ascii() -> None:
    # NFKC folds full-width characters onto their plain forms, so a stray unicode spelling
    # of a station cannot dodge its alias entry.
    assert normalize_station("Ｇａｔｅｓ ２３０ｋＶ") == "gates 230 kv"


def test_blank_and_none_normalize_to_the_empty_key() -> None:
    assert normalize_station(None) == ""
    assert normalize_station("   ") == ""
