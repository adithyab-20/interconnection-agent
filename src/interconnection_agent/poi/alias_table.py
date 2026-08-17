"""The reviewed alias table: exact-match resolution from a checked-in CSV.

The table is a human-reviewed, versioned CSV (:data:`ALIAS_CSV`) shipped inside the
package so the ETL can apply it at runtime with no external data dependency. Each row is
``(station, canonical_poi)``: a representative raw station spelling and the canonical POI
name a reviewer assigned it. On load, every station is run through
:func:`normalize_station` to a lookup key, so a reviewer writes one spelling and every
mechanical variant of it still resolves.

Resolution is exact-match only. A raw string whose key is not in the table resolves to
``None`` — the row is reported as unmapped, never assigned a probabilistic best guess.
Fuzzy grouping lives solely in the offline proposal script, which this module never
imports.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable
from importlib.resources import files

from interconnection_agent.poi.normalize import normalize_station

# The checked-in table, versioned alongside the code and shipped in the wheel.
ALIAS_CSV = "aliases.csv"


class AliasTable:
    """An immutable, normalized-key → canonical-POI lookup with no fuzzy fallback."""

    def __init__(self, by_key: dict[str, str]) -> None:
        # Already-normalized keys; construct via :meth:`from_rows` or :func:`load_alias_table`
        # rather than calling this directly, so keys are normalized and conflicts caught.
        self._by_key = by_key

    @classmethod
    def from_rows(cls, rows: Iterable[tuple[str, str]]) -> AliasTable:
        """Build a table from ``(station, canonical_poi)`` pairs.

        The station is normalized to a key. Two rows whose stations share a key but name
        different canonical POIs are a review error and raise ``ValueError`` — a silent
        last-wins would bury the disagreement the table exists to make explicit.
        """
        by_key: dict[str, str] = {}
        for station, canonical in rows:
            key = normalize_station(station)
            if not key or not canonical:
                continue  # a blank station or canonical name carries no mapping
            existing = by_key.get(key)
            if existing is not None and existing != canonical:
                raise ValueError(
                    f"alias conflict: {station!r} -> {canonical!r} collides with "
                    f"{existing!r} on key {key!r}"
                )
            by_key[key] = canonical
        return cls(by_key)

    def resolve(self, raw: str | None) -> str | None:
        """Return the canonical POI for ``raw``, or ``None`` if it is unmapped."""
        key = normalize_station(raw)
        if not key:
            return None
        return self._by_key.get(key)

    def __len__(self) -> int:
        return len(self._by_key)


def load_alias_table() -> AliasTable:
    """Load the checked-in alias table shipped with the package."""
    text = files("interconnection_agent.poi").joinpath(ALIAS_CSV).read_text(encoding="utf-8")
    reader = csv.DictReader(io.StringIO(text))
    return AliasTable.from_rows((row["station"], row["canonical_poi"]) for row in reader)
