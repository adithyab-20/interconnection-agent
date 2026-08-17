"""Unit tests for the reviewed alias table — deterministic, exact-match resolution.

The table maps a normalized station key to a canonical POI name. Resolution runs the raw
string through :func:`normalize_station` first, so the human who curates the table writes
one representative spelling and every mechanical variant still lands on it. A key with no
entry resolves to ``None`` — the row is unmapped, not guessed. There is no fuzzy fallback.
"""

from __future__ import annotations

import pytest

from interconnection_agent.poi import AliasTable, load_alias_table


def test_resolves_a_reviewed_string_to_its_canonical_name() -> None:
    table = AliasTable.from_rows([("Birds Landing 230 kV", "Birds Landing 230 kV")])
    assert table.resolve("Birds Landing 230 kV") == "Birds Landing 230 kV"


def test_resolution_is_insensitive_to_mechanical_variation() -> None:
    # One reviewed entry catches every typographic variant, because both the entry and the
    # query pass through the normalizer before the exact-match lookup.
    table = AliasTable.from_rows([("Devers Substation 230 kV", "Devers Substation 230 kV")])
    assert table.resolve("DEVERS  SUBSTATION 230kV") == "Devers Substation 230 kV"


def test_groups_two_raw_spellings_onto_one_canonical_name() -> None:
    # The whole point of a curated table over the normalizer: two strings the normalizer
    # keeps apart (a typo, a suffix) are deliberately grouped by a reviewer.
    table = AliasTable.from_rows(
        [
            ("Volta-South 60 kV", "Volta-South 60 kV"),
            ("Vota-South 60 kV", "Volta-South 60 kV"),  # operator typo, reviewed and merged
        ]
    )
    assert table.resolve("Vota-South 60 kV") == table.resolve("Volta-South 60 kV")


def test_an_unreviewed_string_is_unmapped() -> None:
    table = AliasTable.from_rows([("Birds Landing 230 kV", "Birds Landing 230 kV")])
    assert table.resolve("Some Substation Nobody Reviewed 500 kV") is None


def test_blank_and_none_are_unmapped() -> None:
    table = AliasTable.from_rows([("Birds Landing 230 kV", "Birds Landing 230 kV")])
    assert table.resolve(None) is None
    assert table.resolve("   ") is None


def test_rejects_a_key_mapped_to_two_different_canonical_names() -> None:
    # Two rows whose station strings normalize to one key but disagree on the canonical
    # name is a review error, not a silent last-wins — it must fail loudly.
    with pytest.raises(ValueError, match="conflict"):
        AliasTable.from_rows(
            [
                ("Midway 230 kV", "Midway 230 kV"),
                ("MIDWAY 230kV", "Midway Substation 230 kV"),
            ]
        )


def test_the_shipped_table_loads_and_resolves_a_known_poi() -> None:
    # The checked-in, versioned table on disk is what the ETL applies at runtime.
    table = load_alias_table()
    assert table.resolve("Birds Landing 230 kV") == "Birds Landing 230 kV"
