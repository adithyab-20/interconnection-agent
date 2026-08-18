"""POI resolution: deterministic, exact-match, offline-reviewed.

A free-text station string is resolved to a canonical point of interconnection in two
deterministic steps: :func:`normalize_station` collapses mechanical variation into a
lookup key, and the human-reviewed :class:`AliasTable` maps that key to a canonical POI
name by *exact match*. A key with no reviewed entry resolves to ``None`` — flagged as
unmapped, never guessed.

Nothing here does fuzzy matching. Probabilistic grouping belongs only to the offline
proposal script (``scripts/propose_poi_aliases.py``), which is not importable from this
package — a probabilistic join beneath a verified claim would break Tier 1 determinism.
"""

from __future__ import annotations

from interconnection_agent.poi.alias_table import AliasTable, load_alias_table
from interconnection_agent.poi.normalize import normalize_station

__all__ = ["AliasTable", "load_alias_table", "normalize_station"]
