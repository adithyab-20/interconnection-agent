"""Mechanical canonicalization of the operator's free-text station string.

CAISO writes the same substation many ways — "Birds Landing 230 kV", "BIRDS LANDING
230kV", "Midway - Temblor" vs "Midway-Temblor". :func:`normalize_station` collapses the
*mechanical* variation (case, whitespace, the ``kV`` spelling, hyphen spacing) into a
stable lookup key, so the reviewed alias table can be keyed on one form instead of every
typographic variant.

It stops there on purpose. It does **not** drop descriptors like "Substation", "Line", or
"Bus": a substation and the transmission line leaving it are *different* points of
interconnection, and folding them together would silently merge two real POIs. Genuine
synonyms, abbreviations, and typos are resolved by the human-reviewed alias table
(:mod:`interconnection_agent.poi.alias_table`), never guessed here.

The result is a lookup key, not a display name — it is only ever compared for exact
equality against the alias table's keys.
"""

from __future__ import annotations

import re
import unicodedata

# "230kV", "230 kV", "230  KV" -> "230 kv": a single space between the number and unit.
_VOLTAGE = re.compile(r"(\d+)\s*kv\b")

# " - " or "-" between endpoints -> a bare hyphen, so "Midway - Temblor" and
# "Midway-Temblor" name one line. Applied after lower-casing and whitespace collapse.
_HYPHEN = re.compile(r"\s*-\s*")


def normalize_station(raw: str | None) -> str:
    """Return the exact-match lookup key for a raw station string.

    Empty, blank, and ``None`` inputs all normalize to the empty key ``""`` — a row with
    no station string has nothing to resolve and is left unmapped by the alias table.
    """
    if raw is None:
        return ""
    # NFKC folds full-width and compatibility characters onto their plain forms before we
    # reason about the text, so a stray unicode variant cannot dodge an alias entry.
    text = unicodedata.normalize("NFKC", str(raw))
    text = " ".join(text.split()).lower()
    text = _VOLTAGE.sub(r"\1 kv", text)
    text = _HYPHEN.sub("-", text)
    return text
